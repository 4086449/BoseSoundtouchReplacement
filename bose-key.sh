#!/bin/sh
# Send a key command to Bose SoundTouch REST API.

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/config.sh"

KEY="$1"

if [ -z "$KEY" ]; then
  echo "Usage: $0 KEY"
  echo
  echo "Examples:"
  echo "  $0 PLAY_PAUSE"
  echo "  $0 VOLUME_UP"
  echo "  $0 VOLUME_DOWN"
  echo "  $0 MUTE"
  exit 1
fi

curl -s -X POST "http://$BOSE_IP:8090/key" \
  -H "Content-Type: application/xml" \
  --data-binary "<key state=\"press\" sender=\"Gabbo\">$KEY</key>"

echo
sleep 0.2

curl -s -X POST "http://$BOSE_IP:8090/key" \
  -H "Content-Type: application/xml" \
  --data-binary "<key state=\"release\" sender=\"Gabbo\">$KEY</key>"

echo
