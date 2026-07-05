#!/bin/sh
# Send a key command to Bose SoundTouch REST API.
#
# Usage: bose-key.sh <KEY> [<speaker-id>]
#   <speaker-id> optional id from speakers.json; resolved via the proxy at
#                http://$PI_IP:$PROXY_PORT/config. Defaults to $BOSE_IP.

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ENV_FILE="$SCRIPT_DIR/../../.env"
if [ -f "$ENV_FILE" ]; then set -a; . "$ENV_FILE"; set +a; fi
BOSE_IP="${BOSE_IP:-10.0.0.216}"
PI_IP="${PI_IP:-10.0.0.241}"
PROXY_PORT="${PROXY_PORT:-8091}"

resolve_speaker_ip() {
  sid="$1"
  if [ -z "$sid" ]; then echo "$BOSE_IP"; return 0; fi
  if ! command -v jq >/dev/null 2>&1; then
    echo "warn: jq not installed; using \$BOSE_IP=$BOSE_IP" >&2
    echo "$BOSE_IP"; return 0
  fi
  ip=$(curl -sS --max-time 2 "http://$PI_IP:$PROXY_PORT/config" 2>/dev/null \
         | jq -r --arg s "$sid" '.speakers[$s].ip // empty' 2>/dev/null)
  if [ -n "$ip" ]; then echo "$ip"; return 0; fi
  echo "warn: speaker '$sid' not in proxy /config; using \$BOSE_IP=$BOSE_IP" >&2
  echo "$BOSE_IP"
}

KEY="$1"
TARGET_IP=$(resolve_speaker_ip "$2")

if [ -z "$KEY" ]; then
  echo "Usage: $0 KEY [<speaker-id>]"
  echo
  echo "Examples:"
  echo "  $0 PLAY_PAUSE"
  echo "  $0 VOLUME_UP kitchen"
  echo "  $0 VOLUME_DOWN"
  echo "  $0 MUTE"
  exit 1
fi

curl -s -X POST "http://$TARGET_IP:8090/key" \
  -H "Content-Type: application/xml" \
  --data-binary "<key state=\"press\" sender=\"Gabbo\">$KEY</key>"

echo
sleep 0.2

curl -s -X POST "http://$TARGET_IP:8090/key" \
  -H "Content-Type: application/xml" \
  --data-binary "<key state=\"release\" sender=\"Gabbo\">$KEY</key>"
