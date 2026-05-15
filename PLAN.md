# Plan: SoundTouch Replacement (Pi target, UPnP/DLNA path)

Single host = a dedicated Raspberry Pi running Docker + Docker Compose + Portainer.
The deprecated TuneIn path is dead on this device (`INVALID_SOURCE` confirmed) and
`INTERNET_RADIO` source is not accepted (`UNKNOWN_SOURCE_ERROR 1005`), so the only
viable playback path is **UPNP backed by a DLNA server (Gerbera) on the Pi LAN**,
with Radio Browser feeding the station catalog at build time.

Device confirmed at `10.0.0.199:8090`. Locale: Hasselt, BE (lat 50.9307, lon 5.3325).

## Critical constraints discovered

- TUNEIN source removed from device firmware (not in `/sources`). Existing presets
  return `INVALID_SOURCE`. IR remote presets currently broken.
- INTERNET_RADIO source not accepted (`UNKNOWN_SOURCE_ERROR 1005`).
- READY/usable sources today: AUX, AIRPLAY, SPOTIFY, ALEXA.
- Available-when-server-present (multiroom-allowed): UPNP,
  STORED_MUSIC_MEDIA_RENDERER, LOCAL_MUSIC.
- Path forward: stream internet radio into the speaker via the UPNP source backed
  by a DLNA server (Gerbera) on the Pi LAN. Multicast SSDP works natively on Pi
  Linux with host networking.

## Phases

### Phase 1 - Stack scaffolding

1. `docker-compose.yml`: `homeassistant`, `nodered`, `mosquitto`,
   `mqtt-explorer-web`, `gerbera` (default profile); `wiremock` under
   `profile: mock`. **Gerbera uses `network_mode: host`** (SSDP requirement);
   others on bridge with port maps. Named volumes throughout.
2. `.env.example`: `TZ=Europe/Brussels`, `BOSE_HOST=10.0.0.199`,
   `BOSE_PORT=8090`, `GEO_LAT=50.9307`, `GEO_LON=5.3325`,
   `RB_USER_AGENT=SoundTouchReplacement/0.1`.
3. `config/mosquitto.conf`: anonymous LAN listener 1883 + websocket 9001.
4. `README.md`: Pi bring-up, Portainer-import note, service URLs.

### Phase 2 - DLNA radio relay (Gerbera)

5. `config/gerbera/config.xml`: minimal, friendly name "SoundTouch Radio Relay",
   external-URL items enabled.
6. `config/gerbera/radio-stations.json`: 6 stations seeded (VRT Radio 1,
   VRT Radio 2 Limburg, Studio Brussel, Joe, Nostalgie Vlaanderen, JOE Gold)
   with Radio Browser search criteria + optional pinned uuid/url + geo defaults.
7. Node-RED helper flow "rebuild gerbera library": resolves each station via
   Radio Browser, publishes 6 external-URL items to Gerbera. Idempotent.
8. Verify: `curl /sources` on speaker now shows `UPNP status="READY"`.

### Phase 3 - Home Assistant control surface

9. `homeassistant/config/configuration.yaml`: MQTT broker pointer, packages
   include.
10. `homeassistant/config/packages/soundtouch_presets.yaml`: 3-room booleans,
    `failure_policy` selector (continue|strict), 6 preset scripts publishing to
    `soundtouch/cmd/preset`.
11. Lovelace dashboard: room toggles, 6 preset buttons, policy selector,
    "rebuild library" button.

### Phase 4 - Node-RED orchestration

12. `node-red/flows.json` skeleton: MQTT-in -> validate -> resolve preset to
    UPNP ContentItem -> expand rooms -> `/select` master + `/setZone` slaves ->
    aggregate -> `soundtouch/state/<room>`.
13. Resolver subflow: maps preset id -> Gerbera DLNA item URI from
    `node-red/data/presets.json`. All SoundTouch HTTP encapsulated in one
    `st-api` subflow.
14. Failure policy subflow: `continue` (log & keep) vs `strict` (rollback
    succeeded rooms).
15. State polling: 10s `/now_playing` per room -> MQTT state topics.
16. Radio Browser resolver subflow (used at library-build time only):
    server bootstrap via `/json/servers` cached 24h, UA header,
    `rb_uuid` + `rb_search` (`countrycode=BE`, `hidebroken=true`,
    geo-rank to Hasselt), `/json/url/{uuid}` for click + final stream URL,
    promote successful searches to pinned uuid+url.

### Phase 4b - Preset sync to device (restores IR remote)

17. Manual flow "import current presets": `GET /presets` -> backup XML to disk
    before any overwrite.
18. Manual flow "push presets to device": `POST /setPresetButton` for slots 1-6
    with the UPNP ContentItem so the **physical IR remote works again**.

### Phase 5 - Verification

19. Compose up on Pi, all services healthy, Portainer adopts the stack,
    web UIs reachable on LAN.
20. Mosquitto round-trip from another LAN host.
21. `curl http://10.0.0.199:8090/sources | grep UPNP` shows `READY`.
22. Trigger "rebuild library" -> 6 items visible in Gerbera UI / DLNA browser.
23. HA preset 1 single-room -> `/now_playing` shows `source="UPNP"` + correct
    `itemName`; audio plays.
24. HA preset 1 multi-room (after 2nd device added) -> `/getZone` shows
    master+slaves in sync.
25. Force one room offline -> `continue` keeps others playing; `strict` rolls
    back.
26. After "push presets" -> IR remote PRESET_1..6 plays correct stations;
    no more `INVALID_SOURCE`.
27. Document portable-model quirks and final ContentItem shape in README.

## Decisions

- Pi-only target; iMac fully removed from scope.
- DLNA server: **Gerbera** (web UI, dynamic items). MiniDLNA rejected.
- Gerbera runs `network_mode: host` (SSDP). All other services on bridge.
- Playback path: **UPNP only**. TUNEIN and INTERNET_RADIO ruled out by device probing.
- Radio Browser used at **library-build time**, not at every preset press.
- Portainer not added to compose - already installed on Pi.
- Spotify and AirPlay remain on the device but are out of V1 scope.

## Further considerations

1. Pin Gerbera item IDs in `radio-stations.json` after first publish to detect
   drift across restarts.
2. Pick a mains-powered device as zone master when available (portable can sleep
   and drop the zone).
3. All SoundTouch HTTP in one `st-api` subflow -> single patch point for
   firmware quirks.
4. v1.1 idea: Spotify-takeover HA button (Spotify source is `READY` on the
   device).
