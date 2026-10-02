# dcpcheck-web: a web UI for the DCP verifier of DCP-o-matic.
#
# DCP-o-matic (https://dcpomatic.com) is written by Carl Hetherington and is
# licensed under the GPL. This image downloads the official command-line
# package from dcpomatic.com at build time.

FROM ubuntu:24.04

# Version of DCP-o-matic to install.
ARG DCPOMATIC_VERSION=2.18.50
# Package to download from dcpomatic.com ("ubuntu-24.04-x86-cli", ...).
# Picked from the target architecture when empty.
ARG DCPOMATIC_DL_ID=
# Full URL of the .deb, to override the download altogether.
ARG DCPOMATIC_DEB_URL=
# Set by BuildKit (amd64, arm64...).
ARG TARGETARCH

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl python3 tini \
 && rm -rf /var/lib/apt/lists/*

# A .deb dropped in deb/ is used instead of downloading one (see deb/README.md).
COPY deb/ /tmp/deb/

RUN set -eu; \
    deb="$(find /tmp/deb -maxdepth 1 -name '*.deb' | sort | tail -n 1)"; \
    if [ -n "$deb" ]; then \
        echo "Installing DCP-o-matic from $deb"; \
    else \
        id="$DCPOMATIC_DL_ID"; \
        if [ -z "$id" ]; then \
            case "${TARGETARCH:-$(dpkg --print-architecture)}" in \
                amd64) id=ubuntu-24.04-x86-cli ;; \
                arm64) id=ubuntu-24.04-arm-cli ;; \
                *) echo "No DCP-o-matic package known for ${TARGETARCH}; put a .deb in deb/" >&2; exit 1 ;; \
            esac; \
        fi; \
        url="${DCPOMATIC_DEB_URL:-https://dcpomatic.com/dl?id=${id}&version=${DCPOMATIC_VERSION}}"; \
        echo "Downloading DCP-o-matic from $url"; \
        deb=/tmp/dcpomatic.deb; \
        curl -fSL --retry 3 -o "$deb" "$url"; \
    fi; \
    if ! dpkg-deb --info "$deb" >/dev/null 2>&1; then \
        echo "The downloaded file is not a Debian package. Download the Ubuntu 24.04 CLI" >&2; \
        echo "package from https://dcpomatic.com/download, put it in deb/ and build again." >&2; \
        exit 1; \
    fi; \
    dpkg-deb -f "$deb" Version | sed 's/-[^-]*$//' > /etc/dcpomatic-version; \
    apt-get update; \
    apt-get install -y --no-install-recommends "$deb"; \
    rm -rf /var/lib/apt/lists/* /tmp/deb /tmp/dcpomatic.deb; \
    command -v dcpomatic2_verify_cli; \
    echo "DCP-o-matic $(cat /etc/dcpomatic-version) installed"

COPY app/ /opt/dcpcheck/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

WORKDIR /opt/dcpcheck
ENV DCP_ROOT=/dcp \
    DATA_DIR=/data \
    PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python3 -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8080'), timeout=4)"

ENTRYPOINT ["/usr/bin/tini", "--", "sh", "/usr/local/bin/docker-entrypoint.sh"]
CMD ["python3", "-m", "dcpcheck"]
