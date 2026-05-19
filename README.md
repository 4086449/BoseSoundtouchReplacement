# Bose SoundTouch hardware presets via Raspberry Pi UPnP bridge

This project makes Bose SoundTouch hardware preset buttons play web radio again by using a Raspberry Pi as a local bridge.

It was created after the native Bose `LOCAL_INTERNET_RADIO` preset route stored successfully but played as `INVALID_SOURCE`. The working route is UPnP AVTransport:

```text
Bose hardware preset button
  -> Bose emits a WebSocket preset event
  -> Raspberry Pi bridge detects <preset id="1">
  -> Pi sends UPnP SetAVTransportURI + Play to Bose
  -> Bose pulls http://PI_IP:8091/radio1.mp3
  -> Pi proxy follows broadcaster redirects
  -> music plays
```

## Folder layout

Expected location on the Pi:

```text
/home/pi/soundtouch-radio
├── README.md
├── .env
├── .env.example
├── config.py
├── config.sh
├── install-services.sh
├── bose-bridge
│   ├── bose-preset-bridge.py
│   └── venv
├── bose-key.sh
├── bose-radio.sh
├── joe-gold.json
├── joe.json
├── make-json.sh
├── nostalgie.json
├── play-bose-upnp.sh
├── radio1.json
├── radio2-limburg.json
├── soundtouch-proxy
│   ├── radio-proxy.py
│   └── radio-proxy.py.bak
├── stubru.json
└── systemd
    ├── bose-preset-bridge.service
    └── soundtouch-radio-proxy.service
```

The `.json` files are optional diagnostics for the old Bose local-internet-radio method. The working playback path uses `bose-preset-bridge.py`, `radio-proxy.py`, and UPnP.

## Preset mapping

| Hardware preset | Station | Local proxy URL |
|---:|---|---|
| 1 | VRT Radio 1 | `http://PI_IP:8091/radio1.mp3` |
| 2 | VRT Radio 2 Limburg | `http://PI_IP:8091/radio2-limburg.mp3` |
| 3 | VRT Studio Brussel | `http://PI_IP:8091/stubru.mp3` |
| 4 | Joe | `http://PI_IP:8091/joe.mp3` |
| 5 | Nostalgie Vlaanderen | `http://PI_IP:8091/nostalgie.mp3` |
| 6 | JOE Gold | `http://PI_IP:8091/joe-gold.mp3` |

## 1. Copy project to the new Pi

Copy this folder to the new Pi as:

```bash
/home/pi/soundtouch-radio
```

For example:

```bash
scp -r soundtouch-radio pi@NEW_PI_IP:/home/pi/
```

Then SSH into the Pi:

```bash
ssh pi@NEW_PI_IP
cd /home/pi/soundtouch-radio
```

## 2. Install base packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv curl
```

## 3. Configure IP addresses

Edit the `.env` file in the project root:

```bash
nano /home/pi/soundtouch-radio/.env
```

Set:

```env
BOSE_IP=NEW_BOSE_IP
PI_IP=NEW_PI_IP
PROXY_PORT=8091
PROXY_BIND_IP=0.0.0.0
SPEAKER_NAME=Living Room
ACTIVE_ZONE_NAME=
```

Both `config.py` and `config.sh` read from this file automatically. You no longer need to edit them separately.

## 4. Install Python dependency

```bash
cd /home/pi/soundtouch-radio/bose-bridge
python3 -m venv venv
./venv/bin/pip install websockets
```

## 5. Test the stream proxy manually

Start the proxy in a terminal:

```bash
cd /home/pi/soundtouch-radio
/usr/bin/python3 soundtouch-proxy/radio-proxy.py
```

From another terminal or another computer:

```bash
curl -I http://NEW_PI_IP:8091/radio1.mp3
```

Expected:

```text
HTTP/1.0 200 OK
Content-Type: audio/mpeg
```

Test actual audio bytes:

```bash
curl -v --max-time 5 http://NEW_PI_IP:8091/radio1.mp3 -o /tmp/radio1-test.mp3
```

If you receive data, stop the manual proxy with `Ctrl+C`.

## 6. Test direct UPnP playback

Run:

```bash
cd /home/pi/soundtouch-radio
./bose-radio.sh 1
```

Then check the Bose:

```bash
curl -s "http://NEW_BOSE_IP:8090/now_playing"
```

A successful response should include:

```xml
<ContentItem source="UPNP" location="http://NEW_PI_IP:8091/radio1.mp3"
```

and:

```xml
<playStatus>PLAY_STATE</playStatus>
```

Try all presets:

```bash
./bose-radio.sh 1
./bose-radio.sh 2
./bose-radio.sh 3
./bose-radio.sh 4
./bose-radio.sh 5
./bose-radio.sh 6
```

## 7. Test hardware preset bridge manually

Run:

```bash
cd /home/pi/soundtouch-radio/bose-bridge
./venv/bin/python bose-preset-bridge.py
```

Press hardware preset button 1 on the Bose.

Expected log:

```text
Connecting to ws://NEW_BOSE_IP:8080
Connected. Press a Bose hardware preset button.
Event: <SoundTouchSdkInfo ... />
Event: <updates ...><nowSelectionUpdated><preset id="1">...</preset></nowSelectionUpdated></updates>
PRESET_1: playing VRT Radio 1
Now playing VRT Radio 1
```

Check playback:

```bash
curl -s "http://NEW_BOSE_IP:8090/now_playing"
```

Expected:

```xml
<nowPlaying ... source="UPNP" ...>
...
<playStatus>PLAY_STATE</playStatus>
```

## 8. Install systemd services

From project root:

```bash
cd /home/pi/soundtouch-radio
./install-services.sh
```

Or manually:

```bash
sudo cp systemd/soundtouch-radio-proxy.service /etc/systemd/system/
sudo cp systemd/bose-preset-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable soundtouch-radio-proxy.service
sudo systemctl enable bose-preset-bridge.service
sudo systemctl start soundtouch-radio-proxy.service
sudo systemctl start bose-preset-bridge.service
```

Check services:

```bash
systemctl status soundtouch-radio-proxy.service
systemctl status bose-preset-bridge.service
```

Watch bridge logs:

```bash
journalctl -u bose-preset-bridge.service -f
```

Watch proxy logs:

```bash
journalctl -u soundtouch-radio-proxy.service -f
```

## 9. Keep dummy Bose presets stored

The hardware bridge needs the Bose to emit preset selection events. On some firmware versions, this may require something to be stored in each hardware preset slot.

It is okay if the stored Bose preset itself is broken. The bridge only uses the button press event and then overrides playback with UPnP.

You can store a dummy local preset like this:

```bash
curl -X POST "http://NEW_BOSE_IP:8090/storePreset" \
  -H "Content-Type: application/xml" \
  --data-binary @- <<EOF
<preset id="1">
  <ContentItem source="LOCAL_INTERNET_RADIO" type="stationurl" location="http://NEW_PI_IP:8091/radio1.mp3">
    <itemName>VRT Radio 1</itemName>
  </ContentItem>
</preset>
EOF
```

Repeat for other preset IDs if needed. The dummy preset may still show `INVALID_SOURCE`; that is expected. The bridge should detect `<preset id="1">` and replace it with working UPnP playback.

## 10. Useful commands

Play by command line:

```bash
/home/pi/soundtouch-radio/bose-radio.sh 1
/home/pi/soundtouch-radio/bose-radio.sh 2
/home/pi/soundtouch-radio/bose-radio.sh 3
/home/pi/soundtouch-radio/bose-radio.sh 4
/home/pi/soundtouch-radio/bose-radio.sh 5
/home/pi/soundtouch-radio/bose-radio.sh 6
```

Send Bose key commands:

```bash
/home/pi/soundtouch-radio/bose-key.sh VOLUME_UP
/home/pi/soundtouch-radio/bose-key.sh VOLUME_DOWN
/home/pi/soundtouch-radio/bose-key.sh PLAY_PAUSE
/home/pi/soundtouch-radio/bose-key.sh MUTE
```

Restart services:

```bash
sudo systemctl restart soundtouch-radio-proxy.service
sudo systemctl restart bose-preset-bridge.service
```

Check current playback:

```bash
curl -s "http://NEW_BOSE_IP:8090/now_playing"
```

## 11. Troubleshooting

### Proxy works but Bose does not play

Test:

```bash
curl -I http://NEW_PI_IP:8091/radio1.mp3
/home/pi/soundtouch-radio/bose-radio.sh 1
curl -s "http://NEW_BOSE_IP:8090/now_playing"
```

If `bose-radio.sh 1` works but the hardware button does not, the issue is the bridge service or WebSocket event parsing.

### Hardware button event appears but nothing plays

Watch bridge logs:

```bash
journalctl -u bose-preset-bridge.service -f
```

The bridge must show:

```text
PRESET_1: playing VRT Radio 1
Now playing VRT Radio 1
```

If it only shows the raw event, check that the event contains `<preset id="1">`. The script supports this event shape.

### Bose shows INVALID_SOURCE

That is the old native Bose preset path failing. The bridge should override it shortly after the button press. If it stays as `INVALID_SOURCE`, check that `bose-preset-bridge.service` is running.

### WebSocket cannot connect

Check Bose IP and port:

```bash
curl -s "http://NEW_BOSE_IP:8090/info"
```

Then update `config.py` and restart:

```bash
sudo systemctl restart bose-preset-bridge.service
```

### Service paths are wrong

The included service files assume:

```text
/home/pi/soundtouch-radio
```

If you install elsewhere, update:

```text
systemd/soundtouch-radio-proxy.service
systemd/bose-preset-bridge.service
```

before running `install-services.sh`.

## 12. Files to edit when duplicating

Only this file needs IP updates:

```text
/home/pi/soundtouch-radio/.env
```

Then restart:

```bash
sudo systemctl restart soundtouch-radio-proxy.service
sudo systemctl restart bose-preset-bridge.service
```

## Notes

- `sender="Gabbo"` is required for Bose key commands; `sender="curl"` caused XML parse errors in testing.
- The direct Bose `LOCAL_INTERNET_RADIO` path stored presets successfully but produced `INVALID_SOURCE` in testing.
- UPnP playback worked once the stream was proxied through the Pi.
- The hardware preset button is used as a trigger, not as the actual stored playback source.

---

## 13. Optional: run with Docker instead of systemd

The project now includes Docker support:

```text
Dockerfile
docker-compose.yml
.dockerignore
DOCKER.md
```

This Docker setup does **not** use `network_mode: host`. It publishes only the proxy port:

```yaml
ports:
  - "8091:8091"
```

This works because the project uses fixed IP addresses and direct TCP/HTTP calls. It does not rely on UPnP multicast discovery.

Before running Docker, make sure `.env` is configured:

```env
BOSE_IP=NEW_BOSE_IP
PI_IP=NEW_PI_IP
PROXY_BIND_IP=0.0.0.0
PROXY_PORT=8091
```

Important distinction:

```text
PROXY_BIND_IP = "0.0.0.0"     # where the container listens
PI_IP = "NEW_PI_IP"           # URL advertised to the Bose
```

The Bose should receive URLs like:

```text
http://NEW_PI_IP:8091/radio1.mp3
```

not:

```text
http://0.0.0.0:8091/radio1.mp3
```

If the host systemd services are installed, stop them before using Docker:

```bash
sudo systemctl stop soundtouch-radio-proxy.service bose-preset-bridge.service 2>/dev/null || true
sudo systemctl disable soundtouch-radio-proxy.service bose-preset-bridge.service 2>/dev/null || true
```

Start Docker:

```bash
cd /home/pi/soundtouch-radio
docker compose up -d --build
```

Check logs:

```bash
docker compose logs -f radio-proxy
docker compose logs -f bose-bridge
```

Test the proxy:

```bash
curl -I http://NEW_PI_IP:8091/radio1.mp3
```

Then press a Bose hardware preset button and check:

```bash
curl -s "http://NEW_BOSE_IP:8090/now_playing"
```

More detail is in [`DOCKER.md`](DOCKER.md).

## Node-RED multi-speaker dashboard

This package now includes a Node-RED dashboard in `./nodered`.

Start the full Docker stack:

```bash
cd /home/pi/soundtouch-radio
docker compose up -d --build
```

Open:

```text
http://PI_IP:1880/ui
```

The dashboard lets you dynamically edit:

- the speakers map
- Bose zones/groups
- preset-to-station playback
- volume, mute, play/pause, and power controls
- custom stream URL playback

Node-RED stores its runtime state in the Docker volume `nodered-data`. If you change the bundled flow files and want Docker to re-seed Node-RED from the project files, remove the volume first:

```bash
docker compose down -v
docker compose up -d --build
```

The Node-RED dashboard uses classic `node-red-dashboard` widgets. The dashboard page is available under `/ui`.

### Multiple Bose speakers and zones

In the Node-RED dashboard, edit the Speakers JSON like this:

```json
{
  "living": {
    "name": "Living Room",
    "ip": "10.0.0.199",
    "device_id": "000C8AC19FAA"
  },
  "kitchen": {
    "name": "Kitchen",
    "ip": "10.0.0.200",
    "device_id": "000C8A..."
  }
}
```

Edit Zones JSON like this:

```json
{
  "downstairs": {
    "name": "Downstairs",
    "master": "living",
    "members": ["kitchen"]
  }
}
```

When a station is played to a zone, Node-RED tries to create/update the Bose zone first, then starts UPnP playback on the zone master.

### Custom stream URLs

The radio proxy also supports a dynamic proxy endpoint:

```text
http://PI_IP:8091/proxy.mp3?url=ENCODED_HTTP_OR_HTTPS_STREAM_URL
```

The Node-RED dashboard uses this when "proxy custom URL via Pi" is enabled.

This is useful for ordinary MP3/AAC internet radio streams. It does not magically convert web players, DRM services, YouTube, Spotify, AirPlay, or Bluetooth audio into an HTTP radio stream. For arbitrary live audio input, use an encoder such as `ffmpeg` plus Icecast or a local HTTP MP3/AAC stream, then point the dashboard at that stream URL.

## Display metadata and future live metadata support

The project now treats the Bose middle display line as a prioritized subtitle instead of a fixed artist field.

Default priority:

1. Fresh live metadata, when available later
2. Active zone name
3. Speaker/device name
4. Station owner, such as VRT or DPG Media

The UPnP metadata sent to Bose is built like this:

- `dc:title` = station name, for example `VRT Radio 1`
- `dc:creator` / `upnp:artist` = chosen subtitle
- `upnp:album` = `Live Radio`
- `upnp:albumArtURI` = station logo URL, if a logo file exists

This means today's display is usually:

```text
VRT Radio 1
Living Room
station logo
```

or, when playing to a configured zone:

```text
VRT Radio 1
Downstairs
station logo
```

Later, when ICY metadata parsing is added to the proxy, the same code will prefer fresh metadata automatically:

```text
VRT Radio 1
Artist - Song Title
station logo
```

### Logo files

Put optional PNG/JPG files in:

```text
soundtouch-proxy/logos/
```

Default filenames:

```text
radio1.png
radio2-limburg.png
stubru.png
joe.png
nostalgie.png
joe-gold.png
```

The proxy serves them at:

```text
http://PI_IP:8091/logos/radio1.png
```

### Metadata endpoints

The proxy now exposes placeholder metadata endpoints, for example:

```bash
curl http://PI_IP:8091/metadata/radio1.json
```

At the moment these return empty/stale metadata, by design. They are included so ICY parsing can be added later without changing the bridge or Node-RED display logic.

### Configuration fields

In `config.py`:

```python
DISPLAY_SUBTITLE_PRIORITY = [
    "live_metadata",
    "zone_name",
    "speaker_name",
    "station_owner",
]
LIVE_METADATA_MAX_AGE_SECONDS = 45
```

For the single-speaker Python bridge, `SPEAKER_NAME` and optional `ACTIVE_ZONE_NAME` are used as fallbacks. In Node-RED, the dashboard dynamically derives the subtitle from the selected zone or speaker.
