#!/usr/bin/env python3
"""Stable local HTTP stream proxy for Bose SoundTouch.

The Bose pulls local URLs such as http://PI_IP:8091/radio1.mp3.
This proxy follows broadcaster redirects/tokens and streams audio back to Bose.

It also serves station logos and placeholder metadata endpoints so live ICY
metadata can be added later without changing Node-RED/bridge display logic.

The proxy additionally owns speakers.json: it exposes /config (GET/PUT),
/config/discover (POST) and /status (GET) so Node-RED and other clients
never touch the file directly.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import cgi
import json
import logging
import mimetypes
import queue
import re
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    BRIDGE_INTERNAL_URL,
    LOGO_ALLOWED_MIME,
    LOGO_DIR,
    LOGO_MAX_BYTES,
    LOGO_MIME_EXT,
    PROXY_BIND_IP,
    PROXY_PORT,
    SSE_KEEPALIVE_SECONDS,
    STATUS_FILE,
    load_overrides,
    load_speakers,
    reconcile_device_ids,
    save_overrides,
    save_speakers,
    validate_speakers,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("radio-proxy")

BASE_DIR = Path(__file__).resolve().parent
OPENAPI_FILE = BASE_DIR / "openapi.yaml"

STATUS_STALE_SECONDS = 60

SWAGGER_HTML = b"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <title>SoundTouch Radio Proxy API</title>
  <link rel=\"stylesheet\" href=\"https://unpkg.com/swagger-ui-dist@5/swagger-ui.css\">
  <style>body{margin:0}</style>
</head>
<body>
  <div id=\"swagger-ui\"></div>
  <script src=\"https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js\"></script>
  <script>
    window.ui = SwaggerUIBundle({
      url: '/openapi.yaml',
      dom_id: '#swagger-ui',
      deepLinking: true,
      tryItOutEnabled: true
    });
  </script>
</body>
</html>
"""

# Runtime config state — guarded by _CFG_LOCK because PUT/discover handlers
# replace these dicts atomically while GET handlers read them.
_CFG_LOCK = threading.Lock()
_CFG = load_speakers()
STATIONS = dict(_CFG.get("stations") or {})
STREAMS = {station["path"]: station["upstream"] for station in STATIONS.values()}
METADATA = {
    station_key: {
        "station": station_key,
        "artist": "",
        "title": "",
        "raw": "",
        "updated_at": 0,
        "enabled": bool((station.get("live_metadata") or {}).get("enabled")),
    }
    for station_key, station in STATIONS.items()
}


def _refresh_runtime(new_cfg):
    """Replace STATIONS/STREAMS/METADATA after a config change."""
    global STATIONS, STREAMS, METADATA
    new_stations = dict(new_cfg.get("stations") or {})
    new_streams = {st["path"]: st["upstream"] for st in new_stations.values()}
    new_metadata = {}
    for station_key, station in new_stations.items():
        prev = METADATA.get(station_key) or {}
        new_metadata[station_key] = {
            "station": station_key,
            "artist": prev.get("artist", ""),
            "title": prev.get("title", ""),
            "raw": prev.get("raw", ""),
            "updated_at": prev.get("updated_at", 0),
            "enabled": bool((station.get("live_metadata") or {}).get("enabled")),
        }
    STATIONS = new_stations
    STREAMS = new_streams
    METADATA = new_metadata


# ---------------------------------------------------------------------------
# Live-subtitle overrides (per-speaker, ephemeral).
# ---------------------------------------------------------------------------

_OVERRIDES_LOCK = threading.Lock()
_OVERRIDES = load_overrides()


def _persist_overrides_locked():
    try:
        save_overrides(_OVERRIDES)
    except OSError as e:
        log.warning("Could not write overrides.json: %s", e)


def _notify_bridge(speaker_id, text, timeout=4.0):
    """Hit the bridge wake endpoint and return its parsed JSON response.

    On any failure returns a synthetic dict so the caller can still answer
    the dashboard with a sensible state."""
    body = json.dumps({"speaker_id": speaker_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        BRIDGE_INTERNAL_URL.rstrip("/") + "/internal/refresh",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            try:
                return json.loads(raw)
            except ValueError:
                return {"state": "error", "shown": None, "detail": raw[:200]}
    except Exception as e:
        return {"state": "error", "shown": None, "detail": str(e)}


def _notify_bridge_now_playing(speaker_id, timeout=4.0):
    """Ask the bridge to pull /now_playing from the speaker right now."""
    body = json.dumps({"speaker_id": speaker_id}).encode("utf-8")
    req = urllib.request.Request(
        BRIDGE_INTERNAL_URL.rstrip("/") + "/internal/now_playing",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            try:
                return json.loads(raw)
            except ValueError:
                return {"ok": False, "detail": raw[:200]}
    except Exception as e:
        return {"ok": False, "detail": str(e)}


# ---------------------------------------------------------------------------
# Server-Sent Events broadcaster.
# ---------------------------------------------------------------------------

class _SSEBroker:
    """In-process pub/sub for SSE clients. One queue per subscriber."""

    def __init__(self):
        self._lock = threading.Lock()
        self._clients = []  # list[queue.Queue]

    def subscribe(self):
        q = queue.Queue(maxsize=64)
        with self._lock:
            self._clients.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            try:
                self._clients.remove(q)
            except ValueError:
                pass

    def publish(self, event, data):
        payload = (event, data)
        with self._lock:
            dead = []
            for q in self._clients:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                try:
                    self._clients.remove(q)
                except ValueError:
                    pass


_SSE = _SSEBroker()


def _status_watcher_loop():
    """Watch status.json mtime; publish a `status` event whenever it changes."""
    last_mtime = 0.0
    while True:
        try:
            mtime = STATUS_FILE.stat().st_mtime if STATUS_FILE.exists() else 0.0
            if mtime != last_mtime:
                last_mtime = mtime
                try:
                    with STATUS_FILE.open() as f:
                        data = json.load(f)
                except (OSError, ValueError):
                    data = {}
                _SSE.publish("status", data)
        except Exception as e:
            log.debug("status watcher: %s", e)
        time.sleep(1.0)


def _startup_reconcile():
    """Run device-id discovery for any enabled speaker missing one, off the
    request path so the proxy starts serving immediately."""
    try:
        with _CFG_LOCK:
            cfg = load_speakers()
            changed = reconcile_device_ids(cfg)
            if changed:
                errs = validate_speakers(cfg)
                if errs:
                    log.warning("Startup reconcile produced invalid config: %s", errs)
                    return
                save_speakers(cfg)
                _refresh_runtime(cfg)
                log.info("Startup reconcile updated speakers.json")
            else:
                log.info("Startup reconcile: nothing to discover")
    except Exception as e:
        log.warning("Startup reconcile failed: %s", e)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    # ---- helpers ----------------------------------------------------------

    def _send_cors(self):
        """Permissive CORS so the Node-RED dashboard (different port) can
        talk to the new endpoints directly. Only used on the new endpoints
        — the existing config/play/status flow already goes through
        Node-RED so it doesn't need CORS."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")

    def _send_json(self, code, payload, cors=False):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        if cors:
            self._send_cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > 1_000_000:
            return None, "missing or oversize body"
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8")), None
        except (ValueError, UnicodeDecodeError) as e:
            return None, f"invalid JSON: {e}"

    def _resolve_upstream(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/proxy.mp3":
            params = urllib.parse.parse_qs(parsed.query)
            raw_url = params.get("url", [None])[0]
            if not raw_url:
                return None
            upstream = urllib.parse.unquote(raw_url)
            if not upstream.startswith(("http://", "https://")):
                return None
            return upstream

        return STREAMS.get(parsed.path)

    def _serve_logo(self, parsed_path):
        filename = parsed_path.removeprefix("/logos/")
        safe_path = (LOGO_DIR / filename).resolve()
        logo_root = LOGO_DIR.resolve()

        if not str(safe_path).startswith(str(logo_root)) or not safe_path.is_file():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Logo not found\n")
            return

        content_type = mimetypes.guess_type(str(safe_path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        with safe_path.open("rb") as f:
            self.wfile.write(f.read())

    def _serve_metadata(self, parsed_path):
        name = parsed_path.removeprefix("/metadata/")
        if not name.endswith(".json"):
            self.send_response(404)
            self.end_headers()
            return
        station_key = name[:-5]
        payload = METADATA.get(station_key)
        if payload is None:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Metadata not found\n")
            return

        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- config endpoints -------------------------------------------------

    def _serve_get_config(self):
        with _CFG_LOCK:
            cfg = load_speakers()
        self._send_json(200, cfg, cors=True)

    def _serve_put_config(self):
        payload, err = self._read_json_body()
        if err:
            return self._send_json(400, {"ok": False, "errors": [err]}, cors=True)
        errors = validate_speakers(payload)
        if errors:
            return self._send_json(422, {"ok": False, "errors": errors}, cors=True)
        try:
            with _CFG_LOCK:
                save_speakers(payload)
                _refresh_runtime(payload)
        except OSError as e:
            log.error("save_speakers failed: %s", e)
            return self._send_json(500, {"ok": False, "errors": [str(e)]}, cors=True)
        log.info("speakers.json updated via PUT /config")
        _SSE.publish("config", payload)
        self._send_json(200, {"ok": True, "config": payload}, cors=True)

    def _serve_post_discover(self):
        try:
            with _CFG_LOCK:
                cfg = load_speakers()
                changed = reconcile_device_ids(cfg)
                if changed:
                    errors = validate_speakers(cfg)
                    if errors:
                        return self._send_json(
                            422, {"ok": False, "errors": errors, "config": cfg}
                        )
                    save_speakers(cfg)
                    _refresh_runtime(cfg)
        except Exception as e:
            log.error("discover failed: %s", e)
            return self._send_json(500, {"ok": False, "errors": [str(e)]})
        self._send_json(200, {"ok": True, "changed": bool(changed), "config": cfg})

    def _serve_get_status(self):
        if not STATUS_FILE.exists():
            return self._send_json(
                200,
                {
                    "ok": True,
                    "stale": True,
                    "reason": "no status.json yet",
                    "updated_at": 0,
                    "speakers": {},
                },
                cors=True,
            )
        try:
            with STATUS_FILE.open() as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            return self._send_json(500, {"ok": False, "errors": [str(e)]}, cors=True)
        try:
            updated_at = float(data.get("updated_at") or 0)
        except (TypeError, ValueError):
            updated_at = 0.0
        age = time.time() - updated_at if updated_at else None
        data["age_seconds"] = age
        data["stale"] = age is None or age > STATUS_STALE_SECONDS
        data.setdefault("ok", True)
        self._send_json(200, data, cors=True)

    # ---- overrides endpoints ---------------------------------------------

    def _serve_get_overrides(self):
        with _OVERRIDES_LOCK:
            self._send_json(200, dict(_OVERRIDES), cors=True)

    def _serve_put_override(self, speaker_id):
        payload, err = self._read_json_body()
        if err:
            return self._send_json(400, {"ok": False, "errors": [err]}, cors=True)
        text = ""
        if isinstance(payload, dict):
            text = str(payload.get("text") or "")
        # Stash the desired value before notifying the bridge so the bridge
        # reads it back via load_overrides().
        with _OVERRIDES_LOCK:
            if text:
                _OVERRIDES[speaker_id] = {
                    "text": text, "ts": time.time(), "state": "pending", "shown": None,
                }
            else:
                _OVERRIDES.pop(speaker_id, None)
            _persist_overrides_locked()
            snapshot = dict(_OVERRIDES)
        _SSE.publish("override", snapshot)

        result = _notify_bridge(speaker_id, text)
        state = str(result.get("state") or "error")
        shown = result.get("shown")

        with _OVERRIDES_LOCK:
            entry = _OVERRIDES.get(speaker_id)
            if entry is not None:
                entry["state"] = state
                entry["shown"] = shown
            _persist_overrides_locked()
            snapshot = dict(_OVERRIDES)
        _SSE.publish("override", snapshot)

        status_map = {
            "applied": 200, "cleared": 200, "idle": 200,
            "timeout": 504, "mismatch": 409, "error": 502,
        }
        code = status_map.get(state, 200)
        self._send_json(code, {"ok": code < 400, **result}, cors=True)

    def _serve_delete_override(self, speaker_id):
        with _OVERRIDES_LOCK:
            had = _OVERRIDES.pop(speaker_id, None) is not None
            _persist_overrides_locked()
            snapshot = dict(_OVERRIDES)
        _SSE.publish("override", snapshot)

        if not had:
            return self._send_json(200, {"ok": True, "state": "noop"}, cors=True)

        result = _notify_bridge(speaker_id, "")
        self._send_json(200, {"ok": True, **result}, cors=True)

    # ---- logo endpoints --------------------------------------------------

    def _serve_get_logos(self):
        try:
            files = sorted(
                f.name for f in LOGO_DIR.iterdir()
                if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
            )
        except OSError:
            files = []
        self._send_json(
            200,
            {"logos": [f"/logos/{name}" for name in files]},
            cors=True,
        )

    def _serve_post_logo(self):
        ctype = self.headers.get("Content-Type") or ""
        if not ctype.lower().startswith("multipart/form-data"):
            return self._send_json(
                415, {"ok": False, "errors": ["expected multipart/form-data"]}, cors=True,
            )
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > LOGO_MAX_BYTES + 8192:
            return self._send_json(
                413,
                {"ok": False, "errors": [f"upload too large (max {LOGO_MAX_BYTES} bytes)"]},
                cors=True,
            )
        env = {"REQUEST_METHOD": "POST", "CONTENT_TYPE": ctype, "CONTENT_LENGTH": str(length)}
        try:
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ=env)
        except Exception as e:
            return self._send_json(400, {"ok": False, "errors": [f"parse error: {e}"]}, cors=True)
        if "file" not in form:
            return self._send_json(400, {"ok": False, "errors": ["missing 'file' field"]}, cors=True)
        item = form["file"]
        if not getattr(item, "file", None) or not item.filename:
            return self._send_json(400, {"ok": False, "errors": ["empty file"]}, cors=True)
        data = item.file.read(LOGO_MAX_BYTES + 1)
        if len(data) > LOGO_MAX_BYTES:
            return self._send_json(
                413,
                {"ok": False, "errors": [f"file exceeds {LOGO_MAX_BYTES} bytes"]},
                cors=True,
            )
        mime = (item.type or mimetypes.guess_type(item.filename)[0] or "").lower()
        if mime not in LOGO_ALLOWED_MIME:
            return self._send_json(
                415,
                {"ok": False, "errors": [f"unsupported type {mime!r}"]},
                cors=True,
            )
        # Sanitize name: use the 'name' field if provided, otherwise the
        # uploaded filename. Strip path components, normalize, force the
        # extension to match the verified MIME.
        raw_name = ""
        if "name" in form:
            raw_name = str(form.getfirst("name") or "")
        if not raw_name:
            raw_name = Path(item.filename).name
        stem = Path(raw_name).stem
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
        if not stem:
            stem = f"logo-{int(time.time())}"
        ext = LOGO_MIME_EXT.get(mime, ".bin")
        target = LOGO_DIR / f"{stem}{ext}"
        # Avoid clobbering an existing file by suffixing -N.
        if target.exists():
            i = 2
            while (LOGO_DIR / f"{stem}-{i}{ext}").exists():
                i += 1
            target = LOGO_DIR / f"{stem}-{i}{ext}"
        try:
            LOGO_DIR.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(target)
        except OSError as e:
            return self._send_json(500, {"ok": False, "errors": [str(e)]}, cors=True)
        log.info("Stored logo %s (%d bytes, %s)", target.name, len(data), mime)
        self._send_json(
            201,
            {"ok": True, "path": f"/logos/{target.name}", "size": len(data), "mime": mime},
            cors=True,
        )

    # ---- SSE -------------------------------------------------------------

    def _serve_events(self):
        # Send initial snapshot so a fresh client doesn't have to wait for
        # the next event to render.
        try:
            with STATUS_FILE.open() as f:
                initial_status = json.load(f)
        except Exception:
            initial_status = {}
        with _OVERRIDES_LOCK:
            initial_overrides = dict(_OVERRIDES)

        q = _SSE.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self._send_cors()
            self.end_headers()
            self._write_sse("status", initial_status)
            self._write_sse("override", initial_overrides)
            last_ping = time.time()
            while True:
                try:
                    event, data = q.get(timeout=SSE_KEEPALIVE_SECONDS)
                except queue.Empty:
                    event = None
                if event is not None:
                    self._write_sse(event, data)
                now = time.time()
                if now - last_ping >= SSE_KEEPALIVE_SECONDS:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    last_ping = now
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log.debug("SSE client gone: %s", e)
        finally:
            _SSE.unsubscribe(q)

    def _write_sse(self, event, data):
        body = json.dumps(data, default=str)
        chunk = f"event: {event}\ndata: {body}\n\n".encode("utf-8")
        self.wfile.write(chunk)
        self.wfile.flush()

    # ---- HTTP verbs -------------------------------------------------------

    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/logos/"):
            filename = parsed.path.removeprefix("/logos/")
            safe_path = (LOGO_DIR / filename).resolve()
            if safe_path.is_file():
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    mimetypes.guess_type(str(safe_path))[0] or "application/octet-stream",
                )
                self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()
            return
        if parsed.path.startswith("/metadata/"):
            self.send_response(
                200 if parsed.path.removeprefix("/metadata/").removesuffix(".json") in METADATA else 404
            )
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            return
        if parsed.path in ("/config", "/status"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            return

        upstream = self._resolve_upstream()
        if not upstream:
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

    def _serve_openapi(self):
        if not OPENAPI_FILE.is_file():
            self.send_response(404)
            self.end_headers()
            return
        body = OPENAPI_FILE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/yaml")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_docs(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(SWAGGER_HTML)))
        self.end_headers()
        self.wfile.write(SWAGGER_HTML)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/config":
            return self._serve_get_config()
        if parsed.path == "/status":
            return self._serve_get_status()
        if parsed.path == "/events":
            return self._serve_events()
        if parsed.path == "/overrides":
            return self._serve_get_overrides()
        if parsed.path == "/logos":
            return self._serve_get_logos()
        if parsed.path == "/openapi.yaml":
            return self._serve_openapi()
        if parsed.path in ("/docs", "/docs/"):
            return self._serve_docs()
        if parsed.path.startswith("/logos/"):
            return self._serve_logo(parsed.path)
        if parsed.path.startswith("/metadata/"):
            return self._serve_metadata(parsed.path)

        upstream = self._resolve_upstream()

        if not upstream:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found\n")
            return

        print(f"Client requested {self.path}; proxying {upstream}", flush=True)

        req = urllib.request.Request(
            upstream,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Icy-MetaData": "0",
                "Accept": "*/*",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                print(f"Upstream final URL: {r.geturl()}", flush=True)
                print(f"Upstream status: {r.status}", flush=True)
                print(f"Upstream content-type: {r.headers.get('Content-Type')}", flush=True)

                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()

                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()

        except BrokenPipeError:
            print("Client disconnected", flush=True)

        except socket.timeout:
            self.send_response(504)
            self.end_headers()
            self.wfile.write(b"Upstream timeout\n")

        except Exception as e:
            print(f"Proxy error: {e}", flush=True)
            self.send_response(502)
            self.end_headers()
            self.wfile.write(("Upstream error: %s\n" % e).encode("utf-8"))

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/config":
            return self._serve_put_config()
        if parsed.path.startswith("/overrides/"):
            sid = parsed.path[len("/overrides/"):]
            if sid:
                return self._serve_put_override(urllib.parse.unquote(sid))
        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/overrides/"):
            sid = parsed.path[len("/overrides/"):]
            if sid:
                return self._serve_delete_override(urllib.parse.unquote(sid))
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/config/discover":
            return self._serve_post_discover()
        if parsed.path == "/logos":
            return self._serve_post_logo()
        if parsed.path.startswith("/now_playing/") and parsed.path.endswith("/refresh"):
            sid = parsed.path[len("/now_playing/"):-len("/refresh")]
            if sid:
                return self._serve_post_now_playing_refresh(urllib.parse.unquote(sid))
        self.send_response(404)
        self.end_headers()

    def _serve_post_now_playing_refresh(self, speaker_id):
        result = _notify_bridge_now_playing(speaker_id)
        code = 200 if result.get("ok") else 502
        self._send_json(code, result, cors=True)

    def do_OPTIONS(self):
        # CORS preflight for the dashboard-facing endpoints.
        self.send_response(204)
        self._send_cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)


def main():
    print(f"Starting SoundTouch radio proxy on {PROXY_BIND_IP}:{PROXY_PORT}", flush=True)
    print(f"Configured streams: {', '.join(sorted(STREAMS))}", flush=True)
    threading.Thread(target=_startup_reconcile, name="startup-reconcile", daemon=True).start()
    threading.Thread(target=_status_watcher_loop, name="status-watcher", daemon=True).start()
    ThreadingHTTPServer((PROXY_BIND_IP, PROXY_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
