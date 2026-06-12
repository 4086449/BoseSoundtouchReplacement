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
│   ├── speakers.json           ← runtime state (gitignored, created from .example)
│   ├── speakers.json.example
│   ├── bridge/
│   │   └── bose-preset-bridge.py
│   ├── proxy/
│   │   ├── radio-proxy.py
│   │   ├── openapi.yaml
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
FOLDER=/home/pi/BoseSoundtouchReplacement
PI_IP=10.0.0.241
PROXY_PORT=8091
PROXY_BIND_IP=0.0.0.0

# Fallback values used only when soundtouch-radio/speakers.json is absent:
BOSE_IP=10.0.0.199
SPEAKER_NAME=Living Room
ACTIVE_ZONE_NAME=
```

Important distinctions:

- `PROXY_BIND_IP=0.0.0.0` — where the container listens (always `0.0.0.0` for Docker)
- `PI_IP` — the host IP advertised to the Bose in UPnP URLs
- `BOSE_IP` / `SPEAKER_NAME` / `ACTIVE_ZONE_NAME` are a **single-speaker fallback**. As soon as `soundtouch-radio/speakers.json` exists they are ignored by the bridge and proxy. See [Multiple Bose speakers, zones and stations](#multiple-bose-speakers-zones-and-stations) below.

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

Play a station by preset number (defaults to the speaker at `$BOSE_IP`):

```bash
soundtouch-radio/soundtouch-api/bose-radio.sh 1
soundtouch-radio/soundtouch-api/bose-radio.sh 2
soundtouch-radio/soundtouch-api/bose-radio.sh 3
soundtouch-radio/soundtouch-api/bose-radio.sh 4
soundtouch-radio/soundtouch-api/bose-radio.sh 5
soundtouch-radio/soundtouch-api/bose-radio.sh 6
```

Target a specific speaker from `speakers.json` by passing its id as a second
argument; the IP is resolved by querying the proxy `/config` endpoint with
`jq` and falls back to `$BOSE_IP` if `jq` is missing or the proxy is
unreachable:

```bash
soundtouch-radio/soundtouch-api/bose-radio.sh radio1 kitchen
soundtouch-radio/soundtouch-api/bose-radio.sh stubru living
```

Send Bose key commands (optional speaker id works the same way):

```bash
soundtouch-radio/soundtouch-api/bose-key.sh VOLUME_UP
soundtouch-radio/soundtouch-api/bose-key.sh VOLUME_DOWN kitchen
soundtouch-radio/soundtouch-api/bose-key.sh PLAY_PAUSE living
soundtouch-radio/soundtouch-api/bose-key.sh MUTE
```

Quick play preset 1:

```bash
soundtouch-radio/soundtouch-api/play-bose-upnp.sh
```

---

## Bose SoundTouch local API commands

Bose SoundTouch speakers expose a local HTTP API on port `8090`. Bose's
official 2026 SoundTouch Web API documentation is here:
<https://assets.bosecreative.com/m/496577402d128874/original/SoundTouch-Web-API.pdf>

This project currently uses the `/key`, `/setZone`, `/info`, `/now_playing`,
and `/presets` endpoints directly, plus UPnP AVTransport on port `8091` for
reliable custom stream playback.

### Key values for `POST /key`

Send keys as a press followed by a release:

```bash
curl -s -X POST "http://BOSE_IP:8090/key" \
  -H "Content-Type: application/xml" \
  --data-binary '<key state="press" sender="Gabbo">PLAY_PAUSE</key>'

curl -s -X POST "http://BOSE_IP:8090/key" \
  -H "Content-Type: application/xml" \
  --data-binary '<key state="release" sender="Gabbo">PLAY_PAUSE</key>'
```

Known key values:

| Key | Meaning |
|---|---|
| `PLAY` | Start playback |
| `PAUSE` | Pause playback |
| `STOP` | Stop playback |
| `PREV_TRACK` | Previous track |
| `NEXT_TRACK` | Next track |
| `THUMBS_UP` | Like/rate up, source-dependent |
| `THUMBS_DOWN` | Dislike/rate down, source-dependent |
| `BOOKMARK` | Bookmark, source-dependent |
| `POWER` | Toggle power/standby |
| `MUTE` | Toggle mute |
| `VOLUME_UP` | Raise volume one step |
| `VOLUME_DOWN` | Lower volume one step |
| `PRESET_1` | Select hardware preset 1 |
| `PRESET_2` | Select hardware preset 2 |
| `PRESET_3` | Select hardware preset 3 |
| `PRESET_4` | Select hardware preset 4 |
| `PRESET_5` | Select hardware preset 5 |
| `PRESET_6` | Select hardware preset 6 |
| `AUX_INPUT` | Select AUX input |
| `SHUFFLE_OFF` | Disable shuffle |
| `SHUFFLE_ON` | Enable shuffle |
| `REPEAT_OFF` | Disable repeat |
| `REPEAT_ONE` | Repeat one |
| `REPEAT_ALL` | Repeat all |
| `PLAY_PAUSE` | Toggle play/pause |
| `ADD_FAVORITE` | Add favorite, source-dependent |
| `REMOVE_FAVORITE` | Remove favorite, source-dependent |
| `INVALID_KEY` | Documented sentinel, not useful as a command |

### Set volume to a numeric value

Yes. Absolute volume is supported, but it is not a `/key` value. Use
`POST /volume` with an integer from `0` through `100`:

```bash
curl -s -X POST "http://10.0.0.216:8090/volume" \
  -H "Content-Type: application/xml" \
  --data-binary '<volume>50</volume>'
```

Read the current target/actual volume and mute state:

```bash
curl -s "http://10.0.0.216:8090/volume"
```

Set mute explicitly:

```bash
curl -s -X POST "http://10.0.0.216:8090/volume" \
  -H "Content-Type: application/xml" \
  --data-binary '<volume><muteenabled>true</muteenabled></volume>'
```

The native speaker API is XML over HTTP, so a JSON shape like
`{"volume": 50}` or `volume: 50` would need to be translated by our proxy or
Node-RED before sending it to the Bose.

### Other local SoundTouch API endpoints

| Endpoint | Methods | Purpose |
|---|---|---|
| `/key` | `POST` | Send one of the key values above |
| `/select` | `POST` | Select a source such as `AUX`, `BLUETOOTH`, or product inputs |
| `/sources` | `GET` | List available sources for this product/account |
| `/bassCapabilities` | `GET` | Report whether bass control is supported and its range |
| `/bass` | `GET`, `POST` | Read or set bass |
| `/getZone` | `GET` | Read current multi-room zone membership |
| `/setZone` | `POST` | Create or replace a multi-room zone |
| `/addZoneSlave` | `POST` | Add a speaker to a zone |
| `/removeZoneSlave` | `POST` | Remove a speaker from a zone |
| `/now_playing` | `GET` | Read current source, metadata and play state; firmware also accepts `/nowPlaying` |
| `/trackInfo` | `GET` | Read current track metadata |
| `/volume` | `GET`, `POST` | Read or set absolute volume and mute |
| `/presets` | `GET` | List stored presets |
| `/info` | `GET` | Read device name, ID, type, network and version info |
| `/name` | `POST` | Set the device name |
| `/capabilities` | `GET` | List optional product-specific API capabilities |
| `/audiodspcontrols` | `GET`, `POST` | Optional audio mode / video sync controls |
| `/audioproducttonecontrols` | `GET`, `POST` | Optional bass and treble controls |
| `/audioproductlevelcontrols` | `GET`, `POST` | Optional center/surround level controls |

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

### Multiple Bose speakers, zones and stations

All runtime state lives in **`soundtouch-radio/speakers.json`** (gitignored).
The proxy is the sole writer; the bridge watches the file's mtime and reloads
automatically when it changes. Both the dashboard and the shell helpers go
through the proxy's HTTP API.

Create it once from the example:

```bash
cp soundtouch-radio/speakers.json.example soundtouch-radio/speakers.json
```

or open the dashboard at `http://PI_IP:1880/ui` and use the form editor to
add speakers, zones, stations and presets. Saving from the dashboard does a
`PUT /config` against the proxy, which validates the payload and writes a
`.bak` of the previous version once per process.

A minimal multi-speaker file looks like this:

```json
{
  "version": 1,
  "speakers": {
    "living":  { "name": "Living",  "ip": "192.168.168.117" },
    "kitchen": { "name": "Kitchen", "ip": "192.168.168.253", "default_zone": "downstairs" }
  },
  "zones": {
    "downstairs": { "name": "Downstairs", "master": "kitchen", "members": ["living"] }
  },
  "stations": {
    "radio1": { "name": "VRT Radio 1", "owner": "VRT", "path": "/radio1.mp3", "upstream": "https://..." }
  },
  "presets": { "PRESET_1": "radio1" }
}
```

Fields:

- **`speakers[id].default_zone`** — when set, pressing a preset on this
  speaker grouples the listed zone first (the master + members are joined
  via `/setZone`) and then plays on the master.
- **`speakers[id].device_id`** — the Bose `deviceID`. Required for zone
  grouping. Leave it blank and click **Discover device IDs** in the
  dashboard (or `POST /config/discover` on the proxy) to fetch it from
  `http://IP:8090/info` automatically.
- **`speakers[id].enabled`** — set to `false` to disable the per-speaker
  WebSocket task without removing the entry.

The proxy exposes a few additional endpoints on port `PROXY_PORT`:

| Endpoint | Purpose |
|---|---|
| `GET  /config` | current `speakers.json` |
| `PUT  /config` | replace `speakers.json` (422 on validation errors) |
| `POST /config/discover` | fill in missing `device_id`s from each Bose |
| `GET  /status` | bridge state (per-speaker WebSocket status, last event, `stale` flag if older than 60s) |
| `GET  /openapi.yaml` | full OpenAPI 3.1 specification |
| `GET  /docs` | interactive Swagger UI for the API |

The dashboard's status card polls `/status` every 10 seconds and shows a
colored dot per speaker (`ok` / `warn` / `err` / `dim`). Use the **API docs**
button in the dashboard to open `/docs` in a new tab.

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

## Verified original presets (backup)

`curl http://10.0.0.199:8090/presets` (before any `setPresetButton` writes):

```xml
<?xml version="1.0" encoding="UTF-8" ?><presets><preset id="1" createdOn="1730052777" updatedOn="1730052777"><ContentItem source="TUNEIN" type="stationurl" location="/v1/playback/station/s18555" sourceAccount="" isPresetable="true"><itemName>VRT Radio 1</itemName><containerArt>http://cdn-radiotime-logos.tunein.com/s18555g.png</containerArt></ContentItem></preset><preset id="2" createdOn="1569612656" updatedOn="1600153136"><ContentItem source="TUNEIN" type="stationurl" location="/v1/playback/station/s25706" sourceAccount="" isPresetable="true"><itemName>VRT Radio 2 Limburg</itemName><containerArt>http://cdn-profiles.tunein.com/s25706/images/logoq.png?t=159075</containerArt></ContentItem></preset><preset id="3" createdOn="1541268447" updatedOn="1587886736"><ContentItem source="TUNEIN" type="stationurl" location="/v1/playback/station/s2611" sourceAccount="" isPresetable="true"><itemName>VRT Studio Brussel</itemName><containerArt>http://cdn-profiles.tunein.com/s2611/images/logoq.jpg</containerArt></ContentItem></preset><preset id="4" createdOn="1569612715" updatedOn="1613287045"><ContentItem source="TUNEIN" type="stationurl" location="/v1/playback/station/s69293" sourceAccount="" isPresetable="true"><itemName>Joe</itemName><containerArt>http://cdn-profiles.tunein.com/s25741/images/logoq.png</containerArt></ContentItem></preset><preset id="5" createdOn="1541278576" updatedOn="1598508677"><ContentItem source="TUNEIN" type="stationurl" location="/v1/playback/station/s48080" sourceAccount="" isPresetable="true"><itemName>Nostalgie Vlaanderen</itemName><containerArt>http://cdn-profiles.tunein.com/s115194/images/logoq.png?t=154885</containerArt></ContentItem></preset><preset id="6" createdOn="1729967874" updatedOn="1749730210"><ContentItem source="TUNEIN" type="stationurl" location="/v1/playback/station/s308755" sourceAccount="" isPresetable="true"><itemName>JOE Gold</itemName><containerArt>http://cdn-profiles.tunein.com/s308755/images/logog.jpg?t=638449028770000000</containerArt></ContentItem></preset></presets>
```
