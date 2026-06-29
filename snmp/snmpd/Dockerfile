# Minimal SNMP agent used as a local demo target for Alloy's SNMP exporter.
# Built from the official Debian image with net-snmp installed.
ARG DEBIAN_VERSION=bookworm-slim@sha256:60eac759739651111db372c07be67863818726f754804b8707c90979bda511df
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
