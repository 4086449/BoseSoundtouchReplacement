#!/bin/sh
# Backwards-compatible helper: play VRT Radio 1 via UPnP.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$SCRIPT_DIR/bose-radio.sh" 1
