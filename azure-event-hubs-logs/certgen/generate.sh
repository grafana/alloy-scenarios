#!/usr/bin/env bash
# Generates a throwaway CA + server certificate for the "eventhub" broker and a
# PKCS12 truststore for clients, then writes a ready-to-use client.properties.
#
# loki.source.azure_event_hubs hardcodes TLS on its Kafka connection (see
# README "Why a self-hosted broker"), so the broker needs a real TLS listener
# -- these certs exist purely to satisfy that, not for any security purpose.
set -euo pipefail
cd /certs

openssl genrsa -out ca.key 2048 2>/dev/null
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt -subj "/CN=alloy-demo-ca"

openssl genrsa -out broker.key 2048 2>/dev/null
openssl req -new -key broker.key -out broker.csr -subj "/CN=eventhub" \
  -addext "subjectAltName=DNS:eventhub,DNS:localhost"
openssl x509 -req -in broker.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out broker.crt -days 3650 -sha256 \
  -extfile <(printf "subjectAltName=DNS:eventhub,DNS:localhost")

cat broker.crt ca.crt > broker-chain.crt
openssl pkcs12 -export -in broker-chain.crt -inkey broker.key \
  -out broker.p12 -name eventhub -passout pass:brokerpass

keytool -importcert -alias ca -keystore truststore.p12 -storetype PKCS12 \
  -storepass trustpass -file ca.crt -noprompt

printf "brokerpass" > keystore_creds
printf "brokerpass" > key_creds

cat > client.properties << 'EOF'
security.protocol=SASL_SSL
sasl.mechanism=PLAIN
sasl.jaas.config=org.apache.kafka.common.security.plain.PlainLoginModule required username="$ConnectionString" password="SAS_KEY_VALUE";
ssl.truststore.location=/etc/kafka/secrets/truststore.p12
ssl.truststore.password=trustpass
ssl.truststore.type=PKCS12
EOF

chmod 644 /certs/*
echo "certificates generated"
