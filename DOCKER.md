# Running soundtouch-radio with Docker

This setup can run without `network_mode: host` because it uses fixed IP addresses and direct HTTP/TCP calls rather than UPnP multicast discovery.

Traffic flow:

```text
Bose -> Pi:8091                  # pulls proxied MP3 stream
bridge container -> Bose:8080    # listens to SoundTouch WebSocket events
bridge container -> Bose:8091    # sends UPnP AVTransport SOAP commands
proxy container -> internet      # follows broadcaster redirects and streams audio
```

## 1. Edit the IP configuration

Edit `.env` in the project root before building/running:

```env
BOSE_IP=10.0.0.199
PI_IP=10.0.0.241
PROXY_BIND_IP=0.0.0.0
PROXY_PORT=8091
```

For Docker bridge networking, keep:

```env
PROXY_BIND_IP=0.0.0.0
```

The Bose must still receive URLs using the Pi's real LAN IP, for example:

```text
http://10.0.0.241:8091/radio1.mp3
```

Do not use `0.0.0.0` in URLs sent to the Bose.

## 2. Stop any existing systemd services

If you previously installed the host services, stop them so they do not conflict with Docker on port 8091:

```bash
sudo systemctl stop soundtouch-radio-proxy.service bose-preset-bridge.service 2>/dev/null || true
sudo systemctl disable soundtouch-radio-proxy.service bose-preset-bridge.service 2>/dev/null || true
```

## 3. Build and start

From the project root:

```bash
cd /home/pi/soundtouch-radio
docker compose up -d --build
```

Check status:

```bash
docker compose ps
```

## 4. Test the proxy

From another machine on the LAN:

```bash
curl -I http://PI_IP:8091/radio1.mp3
```

Expected:

```text
HTTP/1.0 200 OK
Content-Type: audio/mpeg
```

## 5. Test hardware presets

Watch the bridge logs:

```bash
docker compose logs -f bose-bridge
```

Press hardware preset 1 on the Bose. You should see something like:

```text
PRESET_1: playing VRT Radio 1
Now playing VRT Radio 1
```

Watch the proxy logs:

```bash
docker compose logs -f radio-proxy
```

You should see a request for `/radio1.mp3`.

## 6. Check Bose state

```bash
curl -s "http://BOSE_IP:8090/now_playing"
```

Success looks like:

```xml
<ContentItem source="UPNP" location="http://PI_IP:8091/radio1.mp3" ...>
<playStatus>PLAY_STATE</playStatus>
```

## Why not host networking?

Host networking is useful for UPnP/DLNA discovery because SSDP uses multicast UDP. This project no longer needs discovery: the Bose IP and Pi IP are configured directly. Normal Docker bridge networking is enough as long as port 8091 is published.

Use host networking only if you later add automatic SSDP/mDNS discovery or DLNA browsing.

## Node-RED dashboard service

The compose stack includes Node-RED:

```yaml
nodered:
  build: ./nodered
  ports:
    - "1880:1880"
  volumes:
    - nodered-data:/data
```

Open the editor at `http://PI_IP:1880` and the dashboard at `http://PI_IP:1880/ui`.

The dashboard is backed by `node-red-dashboard` and uses Node-RED HTTP endpoints under `/soundtouch/api/*` to manage dynamic speakers, zones, preset playback, keys, and custom streams.

The container does not use host networking. It only needs outbound access to the Bose devices and a published proxy port `8091` on the Pi.

## Metadata/logos in Docker

Docker still publishes only port `8091` for the proxy. Logo and metadata endpoints are served on the same port:

```text
http://PI_IP:8091/logos/radio1.png
http://PI_IP:8091/metadata/radio1.json
```

Keep `PROXY_BIND_IP = "0.0.0.0"` in `config.py` for Docker. Keep `PI_IP` set to the Pi's LAN IP because that is the address Bose devices must use to fetch streams and artwork.
