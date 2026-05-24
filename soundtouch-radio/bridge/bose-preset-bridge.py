#!/usr/bin/env python3
"""Map Bose SoundTouch hardware preset buttons to UPnP radio streams.

For every enabled speaker in speakers.json we open a WebSocket to
ws://IP:8080 (gabbo subprotocol). When a hardware preset button is
pressed the bridge pushes a working UPnP AVTransport URI back to that
speaker. If the speaker has a `default_zone` and is its master, the
bridge also asks Bose to group the zone's members together before play.

Bridge responsibilities:
  * Per-speaker listener task with exponential backoff (5..60s).
  * mtime-poll on speakers.json so reconfigures take effect without
    restart: changed/disabled/added speakers are cancelled/started in
    place.
  * status.json writes after every meaningful event (atomic).
  * Subtitle priority unchanged: live_metadata, zone_name, speaker name,
    station owner.
"""

import asyncio
import html
import json
import logging
import re
import sys
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    BRIDGE_INTERNAL_PORT,
    DISPLAY_SUBTITLE_PRIORITY,
    LIVE_METADATA_MAX_AGE_SECONDS,
    OVERRIDES_FILE,
    PI_IP,
    PROXY_PORT,
    SPEAKERS_FILE,
    load_overrides,
    load_speakers,
    save_overrides,
    save_status,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("bridge")

BACKOFF_SCHEDULE = [5, 10, 20, 40, 60]
RELOAD_POLL_SECONDS = 2.0

# Verification: poll /now_playing this many times with these gaps (seconds)
# until the on-screen subtitle matches what we asked the speaker to display.
VERIFY_BACKOFF_SECONDS = [0.10, 0.15, 0.25, 0.40, 0.60, 0.80]


# ---------------------------------------------------------------------------
# Shared state.
# ---------------------------------------------------------------------------

class State:
    """Hot-reloadable bridge state shared by all tasks."""

    def __init__(self):
        self.cfg = load_speakers()
        self.tasks = {}        # speaker_id -> asyncio.Task
        self.cancels = {}      # speaker_id -> asyncio.Event
        self.status = {}       # speaker_id -> {state, last_event, ...}
        self.status_lock = asyncio.Lock()
        self.now_playing = {}  # speaker_id -> {station_key, station, subtitle}
        self.refresh_locks = {}  # speaker_id -> asyncio.Lock (single-flight)
        self.overrides = load_overrides()  # cached snapshot
        self.loop = None       # captured in main()

    def speakers(self):
        return self.cfg.get("speakers") or {}

    def zones(self):
        return self.cfg.get("zones") or {}

    def stations(self):
        return self.cfg.get("stations") or {}

    def presets(self):
        return self.cfg.get("presets") or {}

    def speaker_signature(self, sid):
        """Fields that, when changed, require a listener restart."""
        sp = self.speakers().get(sid) or {}
        return (sp.get("ip"), bool(sp.get("enabled", True)))

    def refresh_lock(self, sid):
        lock = self.refresh_locks.get(sid)
        if lock is None:
            lock = asyncio.Lock()
            self.refresh_locks[sid] = lock
        return lock

    def override_text(self, sid):
        entry = (self.overrides or {}).get(sid) or {}
        text = entry.get("text") or ""
        return text if isinstance(text, str) else ""


# ---------------------------------------------------------------------------
# Status reporting.
# ---------------------------------------------------------------------------

async def write_status(st, sid, **fields):
    async with st.status_lock:
        entry = st.status.setdefault(sid, {})
        entry.update(fields)
        entry["last_event_at"] = time.time()
        # Per-speaker playback context for the dashboard.
        np = st.now_playing.get(sid) or {}
        entry["current_station"] = np.get("station_key") or ""
        entry["current_subtitle"] = np.get("subtitle") or ""
        entry["current_override"] = st.override_text(sid)
        payload = {
            "updated_at": time.time(),
            "speakers": st.status,
        }
        try:
            save_status(payload)
        except OSError as e:
            log.warning("Could not write status.json: %s", e)


# ---------------------------------------------------------------------------
# UPnP helpers (one set per speaker, since AVTransport URL is per-IP).
# ---------------------------------------------------------------------------

def av_url(ip):
    return f"http://{ip}:8091/AVTransport/Control"


def soap_post(ip, action, body):
    req = urllib.request.Request(
        av_url(ip),
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPACTION": f'"urn:schemas-upnp-org:service:AVTransport:1#{action}"',
        },
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        return response.read().decode("utf-8", errors="replace")


def station_stream_url(station):
    return f"http://{PI_IP}:{PROXY_PORT}{station['path']}"


def station_logo_url(station):
    logo = station.get("logo") or ""
    if not logo:
        return ""
    if logo.startswith(("http://", "https://")):
        return logo
    return f"http://{PI_IP}:{PROXY_PORT}{logo}"


def fetch_live_metadata(station_key, station):
    meta = station.get("live_metadata") or {}
    if not meta.get("enabled"):
        return None
    endpoint = meta.get("endpoint")
    if not endpoint:
        return None
    url = f"http://{PI_IP}:{PROXY_PORT}{endpoint}"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        return None
    payload.setdefault("station", station_key)
    return payload


def format_live_metadata(metadata):
    if not metadata:
        return ""
    updated_at = metadata.get("updated_at") or 0
    try:
        age = time.time() - float(updated_at)
    except Exception:
        age = LIVE_METADATA_MAX_AGE_SECONDS + 1
    if age > LIVE_METADATA_MAX_AGE_SECONDS:
        return ""
    artist = str(metadata.get("artist") or "").strip()
    title = str(metadata.get("title") or "").strip()
    raw = str(metadata.get("raw") or "").strip()
    if artist and title:
        return f"{artist} - {title}"
    return raw


def choose_subtitle(state, sid, station, live_metadata):
    # Live override preempts the priority list (transient, not persisted in
    # speakers.json — held in overrides.json instead).
    override = state.override_text(sid)
    if override:
        return override, "override"
    sp = state.speakers().get(sid) or {}
    zone_id = sp.get("default_zone") or ""
    zone_name = ""
    if zone_id:
        z = state.zones().get(zone_id) or {}
        zone_name = (z.get("name") or zone_id).strip()
    candidates = {
        "live_metadata": format_live_metadata(live_metadata),
        "zone_name": zone_name,
        "speaker_name": (sp.get("name") or "").strip(),
        "station_owner": str(station.get("owner") or "").strip(),
    }
    for source in DISPLAY_SUBTITLE_PRIORITY:
        value = candidates.get(source, "")
        if value:
            return value, source
    return "", "empty"


def set_av_transport_uri(ip, name, stream_url, subtitle="", album="Live Radio", logo_url=""):
    creator_xml = f"<dc:creator>{html.escape(subtitle)}</dc:creator>" if subtitle else ""
    artist_xml = f"<upnp:artist>{html.escape(subtitle)}</upnp:artist>" if subtitle else ""
    album_xml = f"<upnp:album>{html.escape(album)}</upnp:album>" if album else ""
    art_xml = f"<upnp:albumArtURI>{html.escape(logo_url)}</upnp:albumArtURI>" if logo_url else ""

    didl = f"""<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
           xmlns:dc="http://purl.org/dc/elements/1.1/"
           xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"
           xmlns:dlna="urn:schemas-dlna-org:metadata-1-0/">
  <item id="{html.escape(name)}" parentID="0" restricted="1">
    <dc:title>{html.escape(name)}</dc:title>
    {creator_xml}
    {artist_xml}
    {album_xml}
    {art_xml}
    <upnp:class>object.item.audioItem.audioBroadcast</upnp:class>
    <res protocolInfo="http-get:*:audio/mpeg:DLNA.ORG_PN=MP3">{html.escape(stream_url)}</res>
  </item>
</DIDL-Lite>"""

    envelope = f"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:SetAVTransportURI xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <InstanceID>0</InstanceID>
      <CurrentURI>{html.escape(stream_url)}</CurrentURI>
      <CurrentURIMetaData>{html.escape(didl)}</CurrentURIMetaData>
    </u:SetAVTransportURI>
  </s:Body>
</s:Envelope>"""

    return soap_post(ip, "SetAVTransportURI", envelope)


def play(ip):
    envelope = """<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:Play xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <InstanceID>0</InstanceID>
      <Speed>1</Speed>
    </u:Play>
  </s:Body>
</s:Envelope>"""
    return soap_post(ip, "Play", envelope)


# ---------------------------------------------------------------------------
# Zone helpers (Bose /setZone API).
# ---------------------------------------------------------------------------

def apply_bose_zone(master_speaker, member_speakers):
    """POST /setZone on the master so it groups the listed members.

    Both arguments are speaker dicts with `ip` and `device_id`. Members
    without a device_id are skipped (with a warning) so the master still
    plays alone instead of failing the whole call."""
    master_ip = master_speaker.get("ip")
    master_did = master_speaker.get("device_id") or ""
    if not master_ip or not master_did:
        log.warning("apply_bose_zone: master missing ip/device_id")
        return
    members_xml = []
    for m in member_speakers:
        m_ip = m.get("ip")
        m_did = m.get("device_id") or ""
        if not m_ip or not m_did:
            log.warning("apply_bose_zone: skipping member without device_id (%s)", m.get("name"))
            continue
        members_xml.append(f'<member ipaddress="{html.escape(m_ip)}">{html.escape(m_did)}</member>')
    body = (
        f'<zone master="{html.escape(master_did)}">' + "".join(members_xml) + "</zone>"
    )
    url = f"http://{master_ip}:8090/setZone"
    req = urllib.request.Request(
        url, data=body.encode("utf-8"), method="POST",
        headers={"Content-Type": "application/xml"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
    except Exception as e:
        log.warning("apply_bose_zone(%s) failed: %s", master_ip, e)


# ---------------------------------------------------------------------------
# Preset-event playback.
# ---------------------------------------------------------------------------

def extract_preset_event(message):
    m = re.search(r"PRESET_[1-6]", message)
    if m:
        return m.group(0)
    m = re.search(r'<preset\s+id=["\']([1-6])["\']', message, re.IGNORECASE)
    if m:
        return f"PRESET_{m.group(1)}"
    m = re.search(r'preset(?:ID|Id|id)=["\']([1-6])["\']', message, re.IGNORECASE)
    if m:
        return f"PRESET_{m.group(1)}"
    return None


def is_standby_event(message):
    """Crude detector: a nowPlaying frame whose source is STANDBY."""
    if "<nowPlaying" not in message:
        return False
    return bool(re.search(r'source\s*=\s*["\']STANDBY["\']', message))


# ---------------------------------------------------------------------------
# Read-back verification: ask the speaker what it is showing.
# ---------------------------------------------------------------------------

def fetch_now_playing(ip, timeout=2.5):
    """GET http://IP:8090/now_playing and return the parsed XML element,
    or None on any error."""
    url = f"http://{ip}:8090/now_playing"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read()
    except Exception as e:
        log.debug("now_playing(%s) fetch error: %s", ip, e)
        return None
    try:
        return ET.fromstring(body)
    except ET.ParseError as e:
        log.debug("now_playing(%s) parse error: %s", ip, e)
        return None


def now_playing_subtitle(root):
    """The Bose surfaces our DIDL <dc:creator>/<upnp:artist> as <artist>.
    Returns the string (possibly empty) or None if unavailable."""
    if root is None:
        return None
    el = root.find("artist")
    if el is None or el.text is None:
        return ""
    return el.text.strip()


async def verify_subtitle(ip, expected):
    """Poll /now_playing until <artist> equals `expected` or the schedule
    is exhausted. Returns (matched: bool, shown: str|None)."""
    shown = None
    for delay in VERIFY_BACKOFF_SECONDS:
        await asyncio.sleep(delay)
        root = await asyncio.to_thread(fetch_now_playing, ip)
        shown = now_playing_subtitle(root)
        if shown == expected:
            return True, shown
    return False, shown


async def refresh_subtitle(state, sid):
    """Re-send the current station's DIDL to the speaker so a changed
    subtitle (override or default) takes effect, then verify the speaker
    shows what we sent. Single-flight per speaker; latest-wins coalescing.

    Returns a dict with `state` in {applied, mismatch, timeout, idle, error}
    plus `shown` (the value the speaker reports back)."""
    lock = state.refresh_lock(sid)
    async with lock:
        sp = state.speakers().get(sid) or {}
        ip = sp.get("ip")
        if not ip:
            return {"state": "error", "shown": None, "detail": "no ip"}
        np = state.now_playing.get(sid)
        if not np:
            return {"state": "idle", "shown": None}
        station = np.get("station") or {}
        live_metadata = await asyncio.to_thread(
            fetch_live_metadata, np.get("station_key") or "", station
        )
        subtitle, _source = choose_subtitle(state, sid, station, live_metadata)
        np["subtitle"] = subtitle
        try:
            await asyncio.to_thread(
                set_av_transport_uri,
                ip, station.get("name") or "",
                np.get("stream_url") or "",
                subtitle,
                "Live Radio",
                np.get("logo_url") or "",
            )
        except Exception as e:
            log.warning("[%s] refresh_subtitle SetAVTransportURI failed: %s", sid, e)
            return {"state": "error", "shown": None, "detail": str(e)}
        matched, shown = await verify_subtitle(ip, subtitle)
        await write_status(state, sid)  # picks up new current_subtitle/override
        if matched:
            return {"state": "applied", "shown": shown, "sent": subtitle}
        if shown is None:
            return {"state": "timeout", "shown": None, "sent": subtitle}
        return {"state": "mismatch", "shown": shown, "sent": subtitle}


async def play_station(state, sid, preset_key, station_key, station):
    sp = state.speakers().get(sid) or {}
    speaker_ip = sp.get("ip")
    if not speaker_ip:
        return
    log.info("[%s] %s -> %s", sid, preset_key, station.get("name"))

    # New station/preset wipes any live override from the previous one.
    if sid in (state.overrides or {}):
        state.overrides.pop(sid, None)
        try:
            await asyncio.to_thread(save_overrides, state.overrides)
        except OSError as e:
            log.debug("save_overrides on station change: %s", e)

    # Let the Bose finish its own failed preset selection first.
    await asyncio.sleep(0.7)

    # If this speaker is master of its default zone, group the members first.
    zone_id = sp.get("default_zone") or ""
    if zone_id:
        zone = state.zones().get(zone_id) or {}
        if zone.get("master") == sid:
            members = [state.speakers().get(m) for m in (zone.get("members") or [])]
            members = [m for m in members if m]
            await asyncio.to_thread(apply_bose_zone, sp, members)

    live_metadata = await asyncio.to_thread(fetch_live_metadata, station_key, station)
    subtitle, subtitle_source = choose_subtitle(state, sid, station, live_metadata)
    stream_url = station_stream_url(station)
    logo_url = station_logo_url(station)

    log.info("[%s] title=%r subtitle=%r [%s]", sid, station["name"], subtitle, subtitle_source)
    state.now_playing[sid] = {
        "station_key": station_key,
        "station": station,
        "subtitle": subtitle,
        "stream_url": stream_url,
        "logo_url": logo_url,
    }
    await asyncio.to_thread(
        set_av_transport_uri,
        speaker_ip,
        station["name"],
        stream_url,
        subtitle,
        "Live Radio",
        logo_url,
    )
    await asyncio.sleep(0.3)
    await asyncio.to_thread(play, speaker_ip)
    await write_status(
        state, sid,
        state="connected",
        last_event=f"play {station_key} via {preset_key}",
        last_error="",
        backoff_seconds=0,
    )


# ---------------------------------------------------------------------------
# Per-speaker listener task.
# ---------------------------------------------------------------------------

async def listen_to_speaker(state, sid, cancel_event):
    backoff_idx = 0
    while not cancel_event.is_set():
        sp = state.speakers().get(sid)
        if not sp or not sp.get("enabled", True):
            await write_status(state, sid, state="disabled", last_error="", backoff_seconds=0)
            return
        ip = sp.get("ip") or ""
        if not ip:
            await write_status(state, sid, state="error", last_error="missing ip", backoff_seconds=0)
            return

        ws_url = f"ws://{ip}:8080"
        try:
            await write_status(state, sid, state="connecting", last_error="", backoff_seconds=0)
            log.info("[%s] connecting to %s", sid, ws_url)
            async with websockets.connect(
                ws_url, subprotocols=["gabbo"], ping_interval=20, ping_timeout=10
            ) as ws:
                backoff_idx = 0
                await write_status(state, sid, state="connected", last_error="", backoff_seconds=0)
                log.info("[%s] connected", sid)

                # Race the websocket reader against the cancel event so we
                # can tear down promptly on reconfigure.
                ws_iter = ws.__aiter__()
                while not cancel_event.is_set():
                    next_msg = asyncio.ensure_future(ws_iter.__anext__())
                    cancel_wait = asyncio.ensure_future(cancel_event.wait())
                    done, pending = await asyncio.wait(
                        {next_msg, cancel_wait}, return_when=asyncio.FIRST_COMPLETED
                    )
                    for p in pending:
                        p.cancel()
                    if cancel_wait in done:
                        try:
                            await ws.close()
                        except Exception:
                            pass
                        return
                    try:
                        message = next_msg.result()
                    except StopAsyncIteration:
                        break
                    log.debug("[%s] event: %s", sid, message)
                    if is_standby_event(message):
                        if sid in state.now_playing or sid in (state.overrides or {}):
                            log.info("[%s] STANDBY -> clearing now_playing/override", sid)
                            state.now_playing.pop(sid, None)
                            if state.overrides.pop(sid, None) is not None:
                                try:
                                    await asyncio.to_thread(save_overrides, state.overrides)
                                except OSError as e:
                                    log.debug("save_overrides on standby: %s", e)
                            await write_status(state, sid, last_event="standby")
                        continue
                    preset_key = extract_preset_event(message)
                    if not preset_key:
                        continue
                    station_key = state.presets().get(preset_key)
                    station = state.stations().get(station_key or "")
                    if not station:
                        log.info("[%s] no station for %s", sid, preset_key)
                        continue
                    try:
                        await play_station(state, sid, preset_key, station_key, station)
                    except Exception as e:
                        log.warning("[%s] playback error: %s", sid, e)
                        await write_status(state, sid, state="error", last_error=str(e))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            backoff = BACKOFF_SCHEDULE[min(backoff_idx, len(BACKOFF_SCHEDULE) - 1)]
            backoff_idx += 1
            log.warning("[%s] websocket error: %s; retry in %ds", sid, e, backoff)
            await write_status(
                state, sid, state="error", last_error=str(e), backoff_seconds=backoff
            )
            try:
                await asyncio.wait_for(cancel_event.wait(), timeout=backoff)
                return
            except asyncio.TimeoutError:
                continue


# ---------------------------------------------------------------------------
# Supervisor: spawn/cancel listener tasks based on current config.
# ---------------------------------------------------------------------------

async def reconcile_tasks(state, prev_signatures):
    """Start tasks for new/changed enabled speakers, cancel removed ones."""
    speakers = state.speakers()
    new_signatures = {sid: state.speaker_signature(sid) for sid in speakers}

    # Cancel removed or changed speakers.
    for sid in list(state.tasks):
        if sid not in new_signatures or new_signatures[sid] != prev_signatures.get(sid):
            log.info("[%s] stopping listener (removed or changed)", sid)
            state.cancels[sid].set()
            try:
                await state.tasks[sid]
            except Exception:
                pass
            state.tasks.pop(sid, None)
            state.cancels.pop(sid, None)

    # Start tasks for enabled speakers we don't have yet.
    for sid, sp in speakers.items():
        if not sp.get("enabled", True):
            if sid not in state.tasks:
                await write_status(state, sid, state="disabled", last_error="", backoff_seconds=0)
            continue
        if sid in state.tasks:
            continue
        cancel = asyncio.Event()
        state.cancels[sid] = cancel
        state.tasks[sid] = asyncio.create_task(
            listen_to_speaker(state, sid, cancel), name=f"listen-{sid}"
        )

    return new_signatures


async def reload_watcher(state):
    """Poll speakers.json and overrides.json mtime; reload on change."""
    last_mtime = SPEAKERS_FILE.stat().st_mtime if SPEAKERS_FILE.exists() else 0
    last_overrides_mtime = OVERRIDES_FILE.stat().st_mtime if OVERRIDES_FILE.exists() else 0
    # First reconcile to start initial tasks.
    signatures = await reconcile_tasks(state, {})
    while True:
        await asyncio.sleep(RELOAD_POLL_SECONDS)
        try:
            mtime = SPEAKERS_FILE.stat().st_mtime if SPEAKERS_FILE.exists() else 0
        except OSError:
            mtime = last_mtime
        if mtime != last_mtime:
            last_mtime = mtime
            log.info("speakers.json changed, reloading")
            state.cfg = load_speakers()
            signatures = await reconcile_tasks(state, signatures)
        # Overrides fallback path: the proxy's wake call is the primary
        # signal; this catches the case where that POST was missed.
        try:
            ov_mtime = OVERRIDES_FILE.stat().st_mtime if OVERRIDES_FILE.exists() else 0
        except OSError:
            ov_mtime = last_overrides_mtime
        if ov_mtime != last_overrides_mtime:
            last_overrides_mtime = ov_mtime
            new_ov = await asyncio.to_thread(load_overrides)
            # Diff against cached snapshot; refresh affected speakers.
            old_keys = set((state.overrides or {}).keys())
            new_keys = set(new_ov.keys())
            changed = set()
            for k in old_keys | new_keys:
                if (state.overrides.get(k) or {}).get("text", "") != (new_ov.get(k) or {}).get("text", ""):
                    changed.add(k)
            state.overrides = new_ov
            for sid in changed:
                if sid in state.now_playing:
                    asyncio.create_task(refresh_subtitle(state, sid))


# ---------------------------------------------------------------------------
# Internal HTTP server: proxy posts here on every override change for
# sub-second latency. Loopback-only by default.
# ---------------------------------------------------------------------------

def _start_internal_server(state):
    loop = state.loop

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def _send(self, code, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/internal/refresh":
                return self._send(404, {"state": "error", "detail": "not found"})
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, ValueError) as e:
                return self._send(400, {"state": "error", "detail": str(e)})
            sid = str(payload.get("speaker_id") or "")
            if not sid:
                return self._send(400, {"state": "error", "detail": "missing speaker_id"})
            # Re-read overrides.json so we have the value the proxy just wrote.
            try:
                state.overrides = load_overrides()
            except Exception as e:
                log.debug("internal/refresh load_overrides: %s", e)
            future = asyncio.run_coroutine_threadsafe(refresh_subtitle(state, sid), loop)
            try:
                result = future.result(timeout=6.0)
            except Exception as e:
                return self._send(500, {"state": "error", "detail": str(e)})
            self._send(200, result)

        def log_message(self, fmt, *args):
            log.debug("internal: " + fmt, *args)

    server = ThreadingHTTPServer(("127.0.0.1", BRIDGE_INTERNAL_PORT), _Handler)
    log.info("Internal HTTP server on 127.0.0.1:%d", BRIDGE_INTERNAL_PORT)
    threading.Thread(target=server.serve_forever, name="bridge-internal", daemon=True).start()


async def main():
    state = State()
    state.loop = asyncio.get_running_loop()
    _start_internal_server(state)
    await reload_watcher(state)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
