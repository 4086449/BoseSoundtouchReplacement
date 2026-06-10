# Plan: F01 Matter → Alexa Voice Control for Bose SoundTouch

## Summary
Fix the Node-RED Matter Bridge flow (HTTP request bug + payload bug), fix Docker networking so the Matter bridge is discoverable, commission it to Home Assistant via a one-click dashboard helper, then expand to all 5 preset devices. Alexa discovers devices from HA via the existing HA↔Alexa link.

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
- Must commission via HA: point HA at the standalone python-matter-server, then use the dashboard commissioning helper (see Phase 5 + 5.5)
- Fix: Clear old pairing state, then commission via dashboard helper

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

### ~~Bug 9: python-matter-server in docker-compose may conflict with HA~~ — RESOLVED (keep standalone)
- HA has its own built-in python-matter-server but standalone is preferred (user decision)
- **Fix**: Keep `matter-server` in docker-compose.yml as-is; configure HA to point at it via Settings → Devices & Services → Matter → Configure → "Use existing Matter server" → `ws://10.0.0.241:5580/ws`
- Commissioning is triggered from a new "Matter Setup" section in the SoundTouch dashboard — see Phase 5.5

---

## ~~Phase 1: Branch Setup~~ ✗ Done
1. Check out `feature/matter` branch
2. Add flow added to the notes on BACKLOG.md to `nodered/data/flows.json`

## ~~Phase 2: Fix Docker Networking (docker-compose.yml)~~ ✗ Done
4. Change nodered service from bridge networking + port mapping to `network_mode: host`
   - Remove `ports: - "1880:1880"` (host mode makes this automatic)
   - Add `network_mode: host`
5. Keep `matter-server` service in docker-compose.yml as-is
   - One-time HA setup: point HA's Matter integration at `ws://10.0.0.241:5580/ws` instead of its built-in server (Settings → Devices & Services → Matter → Configure → Use existing Matter server)

## ~~Phase 3: Fix the Matter Bridge flow (nodered/data/flows.json)~~ ✗ Done
6. Fix function node — set payload correctly on msg1:
   `const msg1 = { payload: { "target": "speaker:portable", "station": "radio1" } };`
7. Fix URL in http request node: `http://127.0.0.1:1880/soundtouch/api/play`
8. Fix matterbridge config: change networkInterface from `wlan0` to `""` (auto) or keep `wlan0` with host networking
9. Clarify + fix speaker target (portable vs living) — depends on hardware

## ~~Phase 4: Clear Old Commissioning State~~ ✗ Done
10. Delete all files in `nodered/matter/matterStorage/` (NOT the directory, just contents)
    - This clears the Apple Home pairing so HA can commission fresh

## Phase 5: Commission via Dashboard Helper
11. Restart docker-compose (`docker compose down && docker compose up -d`)
12. Open the SoundTouch dashboard → scroll to the new **"Matter Setup"** section (built in Phase 5.5)
13. Click **"Commission Bridge"** — the helper flow:
    a. Calls `GET /_matterbridge/commissioning/{bridgeId}` internally → retrieves live `manualPairingCode` from node-red-matter-bridge
    b. Sends `commission_with_code` command over WebSocket to python-matter-server at `ws://localhost:5580/ws`
    c. Dashboard status indicator updates: "Not commissioned" → "Commissioning…" → "Commissioned ✓" or error
14. Verify "Portable preset 1" appears in HA as a Matter device

## Phase 5.5: Build Dashboard Commissioning Helper (nodered/data/flows.json)
Add a **"Matter Setup"** card to the existing SoundTouch Radio Dashboard tab:

**UI elements** (inside the existing `ui_template_dashboard` HTML):
- Button: **"Commission Bridge"** — POSTs to `/soundtouch/api/matter/commission`
- Status text: "Not commissioned" / "Commissioning…" / "Commissioned ✓" / error
- Read-only pairing code field — shows `manualPairingCode` as fallback for manual entry

**New Node-RED nodes** (added to `SoundTouch Radio Dashboard` tab):
- `[HTTP In POST /soundtouch/api/matter/commission]`
  → `[Function: build internal request to /_matterbridge/commissioning/{bridgeId}]`
  → `[HTTP Request GET /_matterbridge/commissioning/{bridgeId}]`
  → `[Function: extract manualPairingCode, build commission_with_code WS message]`
  → `[WebSocket Out → ws://localhost:5580/ws]`
  → `[WebSocket In ← result from python-matter-server]`
  → `[HTTP Response: { success, nodeId } or { error }]`

**Key behaviour notes**:
- `/_matterbridge/commissioning/{id}` returns `{ state: "ready", manualPairingCode }` when not yet commissioned, or `{ state: "commissioned" }` when already done — use `state` to drive the status indicator and short-circuit if already commissioned
- `passcode` and `discriminator` are randomly generated by node-red-matter-bridge on each restart; they stabilize once commissioned (stored in matterStorage). The commission helper therefore only needs to run once after a fresh matterStorage clear.

## Phase 6: Alexa Discovery
15. In Alexa app or say: "Alexa, discover devices"
16. HA exposes Matter devices to Alexa via the existing HA↔Alexa Smart Home link
17. Test: "Alexa, turn on Portable preset 1"
18. Verify radio1 plays on the Portable speaker

## Phase 7: Expand to All 5 Preset Devices
19. Add 4 more matteronoffsocket nodes + function nodes + http request nodes for:
    - Portable Radio 2 → {target: "speaker:portable", station: "radio2-limburg"}
    - Portable Studio Brussel → {target: "speaker:portable", station: "stubru"}
    - Portable Joe → {target: "speaker:portable", station: "joe"}
    - Portable Nostalgie → {target: "speaker:portable", station: "nostalgie"}
20. Each follows the same pattern as "Portable preset 1"
21. Use a shared function template with station-specific changes

---

## Relevant Files
- `nodered/data/flows.json` — add/fix Matter Bridge tab + all 5 device flows + commissioning helper nodes
- `docker-compose.yml` — switch nodered to host networking; matter-server stays
- `nodered/matter/matterStorage/` — clear contents before re-commissioning

## Verification
1. `docker compose logs nodered` — verify Matter bridge starts without errors
2. SoundTouch dashboard "Matter Setup" section shows "Not commissioned"; click "Commission Bridge" → status changes to "Commissioned ✓"
3. HA Matter integration shows device as "available"
4. Node-RED debug panel shows matteronoffsocket as "connected"
5. "Alexa, discover devices" adds the 5 preset devices
6. Each Alexa command results in correct station playing on the speaker

## Decisions / Scope
- 5 static Matter devices (Radio 1–5 for Portable speaker); Joe Gold as optional 6th
- Using HA as the intermediary for Alexa (not direct Echo 4 commissioning) since HA↔Alexa is already linked
- Keeping standalone `python-matter-server` in docker-compose; HA points at it via `ws://10.0.0.241:5580/ws`
- Commissioning helper = new "Matter Setup" section in existing SoundTouch dashboard (not a separate Node-RED tab)
- Dynamic per-speaker Matter provisioning → F03 (out of scope for F01)
- All 5 devices are momentary switches (auto-reset OFF after 500ms) — Alexa ON = play, OFF does nothing

## Confirmed Context
- speaker:portable = Bose SoundTouch at 10.0.0.216
- User has already renamed living → portable in code (feature/matter branch)
- Pi at 10.0.0.241, proxy port 8091, Node-RED port 1880
- 5 Matter devices targeting speaker:portable