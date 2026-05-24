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
import json
import logging
import mimetypes
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    PROXY_BIND_IP,
    PROXY_PORT,
    STATUS_FILE,
    load_speakers,
    reconcile_device_ids,
    save_speakers,
    validate_speakers,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("radio-proxy")

BASE_DIR = Path(__file__).resolve().parent
LOGO_DIR = BASE_DIR / "logos"
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

    def _send_json(self, code, payload):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
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
        self._send_json(200, cfg)

    def _serve_put_config(self):
        payload, err = self._read_json_body()
        if err:
            return self._send_json(400, {"ok": False, "errors": [err]})
        errors = validate_speakers(payload)
        if errors:
            return self._send_json(422, {"ok": False, "errors": errors})
        try:
            with _CFG_LOCK:
                save_speakers(payload)
                _refresh_runtime(payload)
        except OSError as e:
            log.error("save_speakers failed: %s", e)
            return self._send_json(500, {"ok": False, "errors": [str(e)]})
        log.info("speakers.json updated via PUT /config")
        self._send_json(200, {"ok": True, "config": payload})

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
            )
        try:
            with STATUS_FILE.open() as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            return self._send_json(500, {"ok": False, "errors": [str(e)]})
        try:
            updated_at = float(data.get("updated_at") or 0)
        except (TypeError, ValueError):
            updated_at = 0.0
        age = time.time() - updated_at if updated_at else None
        data["age_seconds"] = age
        data["stale"] = age is None or age > STATUS_STALE_SECONDS
        data.setdefault("ok", True)
        self._send_json(200, data)

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
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/config/discover":
            return self._serve_post_discover()
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)


def main():
    print(f"Starting SoundTouch radio proxy on {PROXY_BIND_IP}:{PROXY_PORT}", flush=True)
    print(f"Configured streams: {', '.join(sorted(STREAMS))}", flush=True)
    threading.Thread(target=_startup_reconcile, name="startup-reconcile", daemon=True).start()
    ThreadingHTTPServer((PROXY_BIND_IP, PROXY_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
