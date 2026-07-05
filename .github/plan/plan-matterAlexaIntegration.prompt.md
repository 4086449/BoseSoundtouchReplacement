# Plan: F01 Matter → Alexa Voice Control for Bose SoundTouch

## Summary
Fix the Node-RED Matter Bridge flow (HTTP request bug + payload bug), fix Docker networking so the Matter bridge is discoverable, commission it to Home Assistant (not Apple Home), then expand to all 5 preset devices. Alexa discovers devices from HA via the existing HA↔Alexa link.

## Status Legend
- `[ ]` — To do
- `[~]` — In progress  
- `[x]` — Done
- `[!]` — Blocked

---

## Bugs Identified

### ~~Bug 1: HTTP Request node — wrong URL~~ ✗ Done 
- Current: `http://10.0.0.241:8091/speaker/portable/preset/1`
- "portable" is a typo; port 8091 is the radio-proxy, not Node-RED; this URL doesn't exist in the API
- Fix: `http://${PI_IP}:1880/soundtouch/api/play`

### ~~Bug 2: Function node — msg.payload missing~~ ✗ Done
- Current: `const msg1 = { "target":"speaker:portable","station":"radio1" }` returned as the message
- The HTTP Request node reads `msg.payload` as the POST body; without it, the body is empty
- Fix: `const msg1 = { payload: { "target":"speaker:portable","station":"radio1" } }`

### Bug 3: Wrong commissioning target (Apple Home vs HA)
- "Home couldn't connect to this accessory" = Apple Home (iOS app), NOT Home Assistant
- Must commission via HA: Settings → Devices & Services → Matter → Add Device But have the iOS Home app installed on the iPhone for QR code scanning during HA commissioning (HA will link to Apple Home automatically if the app is installed)
- Fix: Clear old pairing state, then commission to HA instead of Apple Home

### ~~Bug 4: Docker networking blocks Matter mDNS advertisement~~ ✗ Done
- nodered uses bridge networking; mDNS from inside the container doesn't reach the LAN
- Matter commissioning also needs port 5540 (UDP/TCP) exposed
- Fix: switch nodered to `network_mode: host` in docker-compose.yml (same as matter-server)

### ~~Bug 5: matterbridge networkInterface = wlan0~~ ✗ Done
- wlan0 is not accessible from inside Docker bridge; with host mode this becomes valid again
- With host networking: `wlan0` is correct and matches the Pi's wireless interface
- Alternatively: leave empty for auto-detect

### ~~Bug 6: Old commissioning state in matterStorage~~ ✗ Done
- The bridge was previously paired with Apple Home; that state must be cleared
- Delete contents of `nodered/matter/matterStorage/` before re-commissioning to HA

### ~~Bug 7: Speaker target mismatch~~ — RESOLVED
- `speaker:portable` is a real Bose SoundTouch at IP 10.0.0.216
- User has already renamed `speaker:living` → `speaker:portable` in configs (on feature/matter branch)
- `.env` BOSE_IP=10.0.0.216 matches

### Bug 8: Matter Bridge flow not in flows.json
- The flow from BACKLOG.md notes is not yet in flows.json
- All flows must be in flows.json to persist across Node-RED restarts and be included in the repo
- Fix: Add the Matter Bridge flow to flows.json on the feature/matter branch, then commit and push to GitHub so it's part of the branch for future work and reference.

### Bug 9: python-matter-server in docker-compose may conflict with HA
- HA has its own built-in python-matter-server
- If HA is on a different machine: no conflict, but the service is redundant
- Recommend: remove matter-server from docker-compose.yml, let HA manage its own

---

## Phase 1: Branch Setup
1. Check out `feature/matter` branch
2. Review what's already in `nodered/data/flows.json` on this branch (look for Matter Bridge tab)
3. Identify if the flow already exists, and if so, which bugs are present

## Phase 2: Fix Docker Networking (docker-compose.yml)
4. Change nodered service from bridge networking + port mapping to `network_mode: host`
   - Remove `ports: - "1880:1880"` (host mode makes this automatic)
   - Add `network_mode: host`
5. Remove `matter-server` service from docker-compose.yml (let HA use its own)
   - OR: verify it's already removed on feature/matter branch

## Phase 3: Fix the Matter Bridge flow (nodered/data/flows.json)
6. Fix function node — set payload correctly on msg1:
   `const msg1 = { payload: { "target": "speaker:portable", "station": "radio1" } };`
7. Fix URL in http request node: `http://127.0.0.1:1880/soundtouch/api/play`
8. Fix matterbridge config: change networkInterface from `wlan0` to `""` (auto) or keep `wlan0` with host networking
9. Clarify + fix speaker target (portable vs living) — depends on hardware

## Phase 4: Clear Old Commissioning State
10. Delete all files in `nodered/matter/matterStorage/` (NOT the directory, just contents)
    - This clears the Apple Home pairing so HA can commission fresh

## Phase 5: Commission to Home Assistant
11. Restart docker-compose (`docker compose down && docker compose up -d`)
12. Open Node-RED UI, find the Matter Bridge flow
13. The matteronoffsocket node will show a QR code / pairing code in the debug sidebar
14. In HA: Settings → Devices & Services → + Add Integration → Matter → Add Device
15. Scan QR code or enter pairing code
16. Verify "Portable preset 1" appears in HA as a device

## Phase 6: Alexa Discovery
17. In Alexa app or say: "Alexa, discover devices"
18. HA exposes Matter devices to Alexa via the existing HA↔Alexa Smart Home link
19. Test: "Alexa, turn on Portable preset 1"
20. Verify radio1 plays on the Portable speaker

## Phase 7: Expand to All 5 Preset Devices
21. Add 4 more matteronoffsocket nodes + function nodes + http request nodes for:
    - Portable Radio 2 → {target: "speaker:portable", station: "radio2-limburg"}
    - Portable Studio Brussel → {target: "speaker:portable", station: "stubru"}
    - Portable Joe → {target: "speaker:portable", station: "joe"}
    - Portable Nostalgie → {target: "speaker:portable", station: "nostalgie"}
22. Each follows the same pattern as "Portable preset 1"
23. Use a shared function template with station-specific changes

---

## Relevant Files
- `nodered/data/flows.json` — add/fix Matter Bridge tab + all 5 device flows
- `docker-compose.yml` — switch nodered to host networking, remove matter-server
- `nodered/matter/matterStorage/` — clear contents before re-commissioning

## Verification
1. `docker compose logs nodered` — verify Matter bridge starts without errors, shows pairing code
2. HA Matter integration shows device as "available"
3. Node-RED debug panel shows matteronoffsocket as "connected"
4. "Alexa, discover devices" adds the 5 preset devices
5. Each Alexa command results in correct station playing on the speaker

## Decisions / Scope
- 5 static Matter devices (Radio 1–5 for Portable speaker); Joe Gold as optional 6th
- Using HA as the intermediary for Alexa (not direct Echo 4 commissioning) since HA↔Alexa is already linked
- Removing python-matter-server from our docker-compose — let HA manage its own
- All 5 devices are momentary switches (auto-reset OFF after 500ms) — Alexa ON = play, OFF does nothing

## Confirmed Context
- speaker:portable = Bose SoundTouch at 10.0.0.216
- User has already renamed living → portable in code (feature/matter branch)
- Pi at 10.0.0.241, proxy port 8091, Node-RED port 1880
- 5 Matter devices targeting speaker:portable
