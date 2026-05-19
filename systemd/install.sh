#!/bin/sh
# Install and enable the two systemd services.
# This is a fallback for running without Docker.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)

if [ ! -f "$PROJECT_DIR/.env" ]; then
  echo "Error: $PROJECT_DIR/.env not found. Copy .env.example to .env and configure it."
  exit 1
fi

BRIDGE_DIR="$PROJECT_DIR/soundtouch-radio/bridge"

if [ ! -x "$BRIDGE_DIR/venv/bin/python" ]; then
  echo "Creating Python venv for bridge..."
  python3 -m venv "$BRIDGE_DIR/venv"
  "$BRIDGE_DIR/venv/bin/pip" install websockets
fi

sudo cp "$SCRIPT_DIR/soundtouch-radio-proxy.service" /etc/systemd/system/soundtouch-radio-proxy.service
sudo cp "$SCRIPT_DIR/bose-preset-bridge.service" /etc/systemd/system/bose-preset-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable soundtouch-radio-proxy.service
sudo systemctl enable bose-preset-bridge.service
sudo systemctl restart soundtouch-radio-proxy.service
sudo systemctl restart bose-preset-bridge.service

echo "Installed and started services."
echo "Check with: systemctl status soundtouch-radio-proxy.service bose-preset-bridge.service"
