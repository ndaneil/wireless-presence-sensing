#!/bin/sh
# Used during development to force a re-build of the docker container
set -eu
PRESENCE_APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
export APP_HOME="$PRESENCE_APP_DIR"
if [ ! -f "$PRESENCE_APP_DIR/.cache/app-compose.yaml" ]; then
    echo 'Run this app in App Lab once to generate its Compose configuration.' >&2
    exit 1
fi
if [ ! -f "$PRESENCE_APP_DIR/bricks/lan_presence/service/app/discovery/mdns.py" ]; then
    echo 'The new mDNS source is missing. Update this app folder first.' >&2
    exit 1
fi
set -- -f "$PRESENCE_APP_DIR/.cache/app-compose.yaml"
if [ -f "$PRESENCE_APP_DIR/.cache/app-compose-overrides.yaml" ]; then
    set -- "$@" -f "$PRESENCE_APP_DIR/.cache/app-compose-overrides.yaml"
fi
docker compose "$@" up -d --no-deps --build --force-recreate lan-presence
docker compose "$@" exec -T lan-presence python -c 'import app.discovery.mdns, zeroconf; print("Running Python Zeroconf mDNS:", app.discovery.mdns.__file__)'
