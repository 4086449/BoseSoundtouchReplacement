# Systemd fallback (no Docker)

Use this if you cannot or prefer not to run Docker on the Pi.

## Prerequisites

```bash
sudo apt update
sudo apt install -y python3 python3-venv curl
```

## Install

1. Configure `.env` in the project root (one level up from this folder).
2. Run:

```bash
cd /home/pi/BoseSoundtouchReplacement/systemd
chmod +x install.sh
./install.sh
```

This creates a Python venv, installs `websockets`, copies the service files, and starts both services.

## Switch from Docker to systemd

```bash
cd /home/pi/BoseSoundtouchReplacement
docker compose down
cd systemd
./install.sh
```

## Switch from systemd to Docker

```bash
sudo systemctl stop soundtouch-radio-proxy.service bose-preset-bridge.service
sudo systemctl disable soundtouch-radio-proxy.service bose-preset-bridge.service
cd /home/pi/BoseSoundtouchReplacement
docker compose up -d --build
```

## Logs

```bash
journalctl -u soundtouch-radio-proxy.service -f
journalctl -u bose-preset-bridge.service -f
```

## Notes

The service files assume the repo is cloned at `/home/pi/BoseSoundtouchReplacement`. If you clone elsewhere, edit the paths in the `.service` files before running `install.sh`.

### Multi-speaker

Both services pick up `soundtouch-radio/speakers.json` automatically; there
is no per-speaker systemd unit. The bridge runs a single process that opens
one WebSocket per enabled speaker and watches the file's mtime (polled every
~2s) so changes saved from the Node-RED dashboard or written by hand take
effect without restarting the service. If `speakers.json` is missing the
bridge and proxy fall back to the single-speaker `.env` variables
(`BOSE_IP`, `SPEAKER_NAME`, `ACTIVE_ZONE_NAME`).

The bridge writes `soundtouch-radio/status.json` after every meaningful
event and the proxy serves it (with computed `age_seconds` and a `stale`
flag) at `GET /status`. `journalctl -u bose-preset-bridge.service -f` and
`curl http://localhost:$PROXY_PORT/status` are two views of the same data.
