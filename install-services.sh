#!/bin/sh
# Install and enable the two systemd services. Run from project root on the Pi.
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ "$PROJECT_DIR" != "/home/pi/soundtouch-radio" ]; then
  echo "Warning: project is at $PROJECT_DIR"
  echo "The included service files assume /home/pi/soundtouch-radio."
  echo "Move the folder there or edit files in systemd/ before installing."
fi

if [ ! -x "$PROJECT_DIR/bose-bridge/venv/bin/python" ]; then
  echo "Creating Python venv for bridge..."
  python3 -m venv "$PROJECT_DIR/bose-bridge/venv"
  "$PROJECT_DIR/bose-bridge/venv/bin/pip" install websockets
fi

sudo cp "$PROJECT_DIR/systemd/soundtouch-radio-proxy.service" /etc/systemd/system/soundtouch-radio-proxy.service
sudo cp "$PROJECT_DIR/systemd/bose-preset-bridge.service" /etc/systemd/system/bose-preset-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable soundtouch-radio-proxy.service
sudo systemctl enable bose-preset-bridge.service
sudo systemctl restart soundtouch-radio-proxy.service
sudo systemctl restart bose-preset-bridge.service

echo "Installed and started services."
echo "Check with: systemctl status soundtouch-radio-proxy.service bose-preset-bridge.service"
