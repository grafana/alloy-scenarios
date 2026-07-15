# Minimal SNMP agent used as a local demo target for Alloy's SNMP exporter.
# Built from the official Debian image with net-snmp installed.
ARG DEBIAN_VERSION=bookworm-slim@sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818
FROM debian:${DEBIAN_VERSION}

RUN apt-get update \
    && apt-get install -y --no-install-recommends snmpd \
    && rm -rf /var/lib/apt/lists/*

COPY snmpd.conf /etc/snmp/snmpd.conf

EXPOSE 161/udp

# -f foreground (so the container stays up), -Lo log to stdout,
# -C ignore the packaged default config files, -c use ours only.
# The listen address comes from agentaddress in snmpd.conf — passing it
# again here would make snmpd try to bind the same endpoint twice.
CMD ["/usr/sbin/snmpd", "-f", "-Lo", "-C", "-c", "/etc/snmp/snmpd.conf"]
