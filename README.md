# Bose SoundTouch Replacement

I need an alternative for the Bose SoundTouch app now that it is deprecated.
I want to keep basic control, internet radio/presets and full multi-room behavior.
The phone is only a controller, not the audio source. The radio plays directly
on the speakers, just like before, including from the physical IR remote.

## Goal

Recreate this experience:

- Press preset 1 -> Bose starts Radio 1 in living room + kitchen
- Press preset 2 -> Bose starts station 2 in selected rooms
- Phone is only a controller, not the audio source
- Radio keeps playing directly on the Bose speakers
- The physical IR remote keeps working with the same presets

Built on:

- Home Assistant
- Node-RED
- Mosquitto MQTT
- Gerbera (DLNA radio relay) - the only viable source path on this device
- Radio Browser (station catalog, build-time only)

## Why Gerbera (and not TuneIn / direct stream URLs)

Probing the speaker (`curl http://<bose>:8090/sources`) on this firmware shows:

- TUNEIN source is **gone** - removed by Bose. Existing presets return
  `INVALID_SOURCE`. The IR remote presets are currently dead too.
- INTERNET_RADIO source is **not accepted** - `UNKNOWN_SOURCE_ERROR (1005)`.
- UPNP is available when a DLNA server is on the LAN, and it is
  `multiroomallowed="true"`.

So the only working path for internet radio is: Gerbera on the Pi advertises
the streams as DLNA items, the speaker plays them via UPNP, multi-room works,
and `/setPresetButton` writes the same UPNP `ContentItem`s into slots 1-6 so
the IR remote works again.

## Stack

| Service | Purpose | Default URL |
| --- | --- | --- |
| `homeassistant` | Control surface, dashboard, entities | http://pi:8123 |
| `nodered` | Orchestration: presets, multi-room, policy, polling, library build | http://pi:1880 |
| `mosquitto` | MQTT broker between HA and Node-RED | tcp://pi:1883 |
| `mqtt-explorer-web` | Live MQTT topic inspector for debugging | http://pi:4000 |
| `gerbera` | DLNA server exposing the 6 radio streams (host networking) | http://pi:49152 |
| `wiremock` (profile `mock`) | Fake SoundTouch API for offline flow dev | http://pi:8090 |

## Bring-up on the Pi

1. Clone this repo onto the Pi.
2. `cp .env.example .env` and edit `BOSE_HOST` if your speaker IP differs.
   `GERBERA_URL` is preset to `http://10.0.0.241:49152` (the Pi's LAN IP).
3. `docker compose up -d` (Portainer can adopt the stack via "Add stack ->
   Web editor" pointing at the same `docker-compose.yml`, or via Git).
4. First-run Node-RED setup: open http://pi:1880, then **Menu -> Import**,
   pick **Clipboard**, paste the contents of `node-red/data/flows.json`,
   and deploy. (Or copy that file into the `nodered_data` volume directly.)
5. Open Home Assistant at http://pi:8123, complete the onboarding, then
   reload YAML (Developer Tools -> YAML -> All).
6. In HA, run `script.st_rebuild_library` once. This:
   - Resolves all 6 stations via Radio Browser (Hasselt-biased ranking).
   - Publishes them as DLNA items into Gerbera.
   - Writes `node-red/data/presets.json` with the UPNP `ContentItem` for
     each preset.
7. Verify `curl http://<bose>:8090/sources | grep UPNP` now shows
   `status="READY"`.
8. Try `script.st_preset_1` from the dashboard with one room toggled on.
9. Once `now_playing` polling has run once per device (10s tick), every
   room in `node-red/data/rooms.json` will have its MAC auto-filled and
   multi-room (`/setZone`) is ready.
10. Run `script.st_push_presets` to write the UPNP `ContentItem`s into the
    speakers' preset slots 1-6. The physical IR remote works again.

## Adding more rooms

Edit `node-red/data/rooms.json`, add the device's IP, redeploy. State polling
will fill in `mac` automatically on the next tick.

## Editing the station catalog

Edit `config/gerbera/radio-stations.json`, then run `script.st_rebuild_library`
in HA (or publish to `soundtouch/cmd/rebuild_library`). After a successful
resolve, copy `stationuuid` and the resolved URL back into the entry as
`pinned_uuid` / `pinned_url` to skip the search next time.

## MQTT topic contract

| Topic | Direction | Payload |
| --- | --- | --- |
| `soundtouch/cmd/preset` | HA -> Node-RED | `{preset:1..6, rooms:[ids], policy:"continue"\|"strict"}` |
| `soundtouch/cmd/rebuild_library` | HA -> Node-RED | `{trigger:"ha"}` |
| `soundtouch/cmd/push_presets` | HA -> Node-RED | `{trigger:"ha"}` |
| `soundtouch/state/<room>` | Node-RED -> HA | per-preset result, retained |
| `soundtouch/state/<room>/now_playing` | Node-RED -> HA | source, item, mac, ts |
| `soundtouch/state/last_command` | Node-RED -> HA | summary of last preset trigger |
| `soundtouch/state/library` | Node-RED -> HA | `{ok, count}` after rebuild |
| `soundtouch/status/nodered` | Node-RED LWT | `online` / `offline`, retained |

## Verified original presets (backup)

`curl http://10.0.0.199:8090/presets` (before any `setPresetButton` writes):

```xml
<?xml version="1.0" encoding="UTF-8" ?><presets><preset id="1" createdOn="1730052777" updatedOn="1730052777"><ContentItem source="TUNEIN" type="stationurl" location="/v1/playback/station/s18555" sourceAccount="" isPresetable="true"><itemName>VRT Radio 1</itemName><containerArt>http://cdn-radiotime-logos.tunein.com/s18555g.png</containerArt></ContentItem></preset><preset id="2" createdOn="1569612656" updatedOn="1600153136"><ContentItem source="TUNEIN" type="stationurl" location="/v1/playback/station/s25706" sourceAccount="" isPresetable="true"><itemName>VRT Radio 2 Limburg</itemName><containerArt>http://cdn-profiles.tunein.com/s25706/images/logoq.png?t=159075</containerArt></ContentItem></preset><preset id="3" createdOn="1541268447" updatedOn="1587886736"><ContentItem source="TUNEIN" type="stationurl" location="/v1/playback/station/s2611" sourceAccount="" isPresetable="true"><itemName>VRT Studio Brussel</itemName><containerArt>http://cdn-profiles.tunein.com/s2611/images/logoq.jpg</containerArt></ContentItem></preset><preset id="4" createdOn="1569612715" updatedOn="1613287045"><ContentItem source="TUNEIN" type="stationurl" location="/v1/playback/station/s69293" sourceAccount="" isPresetable="true"><itemName>Joe</itemName><containerArt>http://cdn-profiles.tunein.com/s25741/images/logoq.png</containerArt></ContentItem></preset><preset id="5" createdOn="1541278576" updatedOn="1598508677"><ContentItem source="TUNEIN" type="stationurl" location="/v1/playback/station/s48080" sourceAccount="" isPresetable="true"><itemName>Nostalgie Vlaanderen</itemName><containerArt>http://cdn-profiles.tunein.com/s115194/images/logoq.png?t=154885</containerArt></ContentItem></preset><preset id="6" createdOn="1729967874" updatedOn="1749730210"><ContentItem source="TUNEIN" type="stationurl" location="/v1/playback/station/s308755" sourceAccount="" isPresetable="true"><itemName>JOE Gold</itemName><containerArt>http://cdn-profiles.tunein.com/s308755/images/logog.jpg?t=638449028770000000</containerArt></ContentItem></preset></presets>
```

The Node-RED "push presets" flow also writes a fresh backup
(`/data/presets-backup-<room>-<ts>.xml`) the first time it runs per room.

## Known constraints

- **Portable speaker** as zone master can drop the multi-room zone when it
  sleeps. The expansion logic prefers a mains-powered device as master when
  any are present in the selection.
- Gerbera DLNA item URIs may change across full library rebuilds; treat
  `presets.json` as generated and re-run "rebuild library" + "push presets"
  in that order after edits.
- `mqtt-explorer-web` and Mosquitto run anonymous and are intended for the
  local LAN only. Do not expose to WAN.
- Spotify and AirPlay sources are still `READY` on the device but are out
  of v1 scope.

See `PLAN.md` for the full design rationale.
