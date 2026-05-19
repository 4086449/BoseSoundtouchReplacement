# Bose SoundTouch hardware presets via Raspberry Pi UPnP bridge

This project makes Bose SoundTouch hardware preset buttons play web radio again by using a Raspberry Pi as a local bridge.

It was created after the native Bose `LOCAL_INTERNET_RADIO` preset route stored successfully but played as `INVALID_SOURCE`. The working route is UPnP AVTransport:

```text
Bose hardware preset button
  → Bose emits a WebSocket preset event
  → Raspberry Pi bridge detects <preset id="1">
  → Pi sends UPnP SetAVTransportURI + Play to Bose
  → Bose pulls http://PI_IP:8091/radio1.mp3
  → Pi proxy follows broadcaster redirects
  → music plays
```

## Folder layout

```text
BoseSoundtouchReplacement/
├── .env                        ← single source of truth for all IPs/ports
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── README.md
├── nodered/
│   ├── Dockerfile
│   ├── README.md
│   └── data/
│       ├── flows.json
│       ├── package.json
│       └── settings.js
├── soundtouch-radio/           ← application code (copied into Docker image)
│   ├── config.py
│   ├── bridge/
│   │   └── bose-preset-bridge.py
│   ├── proxy/
│   │   ├── radio-proxy.py
│   │   └── logos/
│   │       └── (station logo PNGs)
│   └── soundtouch-api/
│       ├── bose-key.sh
│       ├── bose-radio.sh
│       └── play-bose-upnp.sh
└── systemd/                    ← alternative: bare-metal deployment
    ├── README.md
    ├── install.sh
    ├── bose-preset-bridge.service
    └── soundtouch-radio-proxy.service
```

## Preset mapping

| Hardware preset | Station | Local proxy URL |
|---:|---|---|
| 1 | VRT Radio 1 | `http://PI_IP:8091/radio1.mp3` |
| 2 | VRT Radio 2 Limburg | `http://PI_IP:8091/radio2-limburg.mp3` |
| 3 | VRT Studio Brussel | `http://PI_IP:8091/stubru.mp3` |
| 4 | Joe | `http://PI_IP:8091/joe.mp3` |
| 5 | Nostalgie Vlaanderen | `http://PI_IP:8091/nostalgie.mp3` |
| 6 | JOE Gold | `http://PI_IP:8091/joe-gold.mp3` |

---

## Quick start (Docker — recommended)

### 1. Clone and configure

```bash
ssh pi@PI_IP
git clone https://github.com/4086449/BoseSoundtouchReplacement.git
cd BoseSoundtouchReplacement
cp .env.example .env
nano .env
```

Set your IP addresses:

```env
BOSE_IP=10.0.0.199
PI_IP=10.0.0.241
PROXY_PORT=8091
PROXY_BIND_IP=0.0.0.0
SPEAKER_NAME=Living Room
ACTIVE_ZONE_NAME=
```

Important distinction:

- `PROXY_BIND_IP=0.0.0.0` — where the container listens (always `0.0.0.0` for Docker)
- `PI_IP` — the host IP advertised to the Bose in UPnP URLs

### 2. Build and start

```bash
docker compose up -d --build
```

### 3. Verify

Test the stream proxy:

```bash
curl -I http://PI_IP:8091/radio1.mp3
```

Expected: `HTTP/1.0 200 OK` with `Content-Type: audio/mpeg`.

Press a Bose hardware preset button, then check:

```bash
curl -s "http://BOSE_IP:8090/now_playing"
```

Expected: `<ContentItem source="UPNP" ...>` with `<playStatus>PLAY_STATE</playStatus>`.

### 4. View logs

```bash
docker compose logs -f radio-proxy
docker compose logs -f bose-bridge
docker compose logs -f nodered
```

### 5. Stop / restart

```bash
docker compose down
docker compose up -d
```

---

## Alternative: bare-metal with systemd

If Docker is not available, see [`systemd/README.md`](systemd/README.md) for instructions on running directly with systemd services.

---

## Shell utilities

The `soundtouch-radio/soundtouch-api/` folder has helper scripts that source `.env` automatically:

Play a station by preset number:

```bash
soundtouch-radio/soundtouch-api/bose-radio.sh 1
soundtouch-radio/soundtouch-api/bose-radio.sh 2
soundtouch-radio/soundtouch-api/bose-radio.sh 3
soundtouch-radio/soundtouch-api/bose-radio.sh 4
soundtouch-radio/soundtouch-api/bose-radio.sh 5
soundtouch-radio/soundtouch-api/bose-radio.sh 6
```

Send Bose key commands:

```bash
soundtouch-radio/soundtouch-api/bose-key.sh VOLUME_UP
soundtouch-radio/soundtouch-api/bose-key.sh VOLUME_DOWN
soundtouch-radio/soundtouch-api/bose-key.sh PLAY_PAUSE
soundtouch-radio/soundtouch-api/bose-key.sh MUTE
```

Quick play preset 1:

```bash
soundtouch-radio/soundtouch-api/play-bose-upnp.sh
```

---

## Keep dummy Bose presets stored

The hardware bridge needs the Bose to emit preset selection events. On some firmware versions, this requires something to be stored in each hardware preset slot.

It is okay if the stored Bose preset itself is broken. The bridge only uses the button press event and then overrides playback with UPnP.

Store a dummy preset:

```bash
curl -X POST "http://BOSE_IP:8090/storePreset" \
  -H "Content-Type: application/xml" \
  --data-binary @- <<EOF
<preset id="1">
  <ContentItem source="LOCAL_INTERNET_RADIO" type="stationurl" location="http://PI_IP:8091/radio1.mp3">
    <itemName>VRT Radio 1</itemName>
  </ContentItem>
</preset>
EOF
```

Repeat for preset IDs 2–6. The dummy preset may show `INVALID_SOURCE`; that is expected.

---

## Troubleshooting

### Proxy works but Bose does not play

```bash
curl -I http://PI_IP:8091/radio1.mp3
soundtouch-radio/soundtouch-api/bose-radio.sh 1
curl -s "http://BOSE_IP:8090/now_playing"
```

If `bose-radio.sh 1` works but the hardware button does not, the issue is the bridge or WebSocket event parsing.

### Hardware button event appears but nothing plays

```bash
docker compose logs -f bose-bridge
```

The bridge must show:

```text
PRESET_1: playing VRT Radio 1
Now playing VRT Radio 1
```

### Bose shows INVALID_SOURCE

That is the old native preset path failing. The bridge should override it shortly after the button press. Check that the bose-bridge container is running.

### WebSocket cannot connect

Verify the Bose is reachable:

```bash
curl -s "http://BOSE_IP:8090/info"
```

Update `BOSE_IP` in `.env` and restart: `docker compose restart bose-bridge`.

---

## Node-RED multi-speaker dashboard

The Docker stack includes a Node-RED dashboard in `./nodered/`.

Start the full stack:

```bash
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

Node-RED stores its runtime state in the Docker volume `nodered-data`. To re-seed from project files:

```bash
docker compose down -v
docker compose up -d --build
```

### Multiple Bose speakers and zones

In the Node-RED dashboard, edit the Speakers JSON:

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

Edit Zones JSON:

```json
{
  "downstairs": {
    "name": "Downstairs",
    "master": "living",
    "members": ["kitchen"]
  }
}
```

When a station is played to a zone, Node-RED creates/updates the Bose zone first, then starts UPnP playback on the zone master.

### Custom stream URLs

The radio proxy supports a dynamic proxy endpoint:

```text
http://PI_IP:8091/proxy.mp3?url=ENCODED_HTTP_OR_HTTPS_STREAM_URL
```

The Node-RED dashboard uses this when "proxy custom URL via Pi" is enabled. This is useful for ordinary MP3/AAC internet radio streams. It does not convert web players, DRM services, YouTube, Spotify, AirPlay, or Bluetooth audio.

---

## Display metadata

The Bose middle display line is a prioritized subtitle. Default priority:

1. Fresh live metadata (when ICY parsing is added later)
2. Active zone name
3. Speaker/device name
4. Station owner (e.g. VRT, DPG Media)

The UPnP metadata sent to Bose:

- `dc:title` = station name
- `dc:creator` / `upnp:artist` = chosen subtitle
- `upnp:album` = `Live Radio`
- `upnp:albumArtURI` = station logo URL (if present)

### Logo files

Put optional PNG/JPG files in `soundtouch-radio/proxy/logos/`:

```text
radio1.png
radio2-limburg.png
stubru.png
joe.png
nostalgie.png
joe-gold.png
```

Served at `http://PI_IP:8091/logos/radio1.png`.

### Metadata endpoints

```bash
curl http://PI_IP:8091/metadata/radio1.json
```

Currently returns placeholder metadata. Included so ICY parsing can be added later without changing the bridge or Node-RED logic.

---

## Notes

- `sender="Gabbo"` is required for Bose key commands; `sender="curl"` caused XML parse errors.
- The direct Bose `LOCAL_INTERNET_RADIO` path stored presets successfully but produced `INVALID_SOURCE`.
- UPnP playback works once the stream is proxied through the Pi.
- The hardware preset button is used as a trigger, not as the actual stored playback source.
- This Docker setup does **not** use `network_mode: host`. It publishes only the proxy port (`8091`). This works because the project uses fixed IP addresses and direct TCP/HTTP calls, not UPnP multicast discovery.

