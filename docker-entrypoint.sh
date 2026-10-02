#!/bin/sh
# Run as PUID:PGID when they are given (handy on a NAS, so that the files in
# /data belong to your user), as root otherwise.
set -e

mkdir -p "${DATA_DIR:-/data}"

if [ -n "${PUID:-}" ] && [ "$(id -u)" = "0" ]; then
    PGID="${PGID:-$PUID}"
    chown -R "$PUID:$PGID" "${DATA_DIR:-/data}"
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
fi

exec "$@"
