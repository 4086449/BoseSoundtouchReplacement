#!/usr/bin/env python3
"""Stable local HTTP stream proxy for Bose SoundTouch.

The Bose pulls local URLs such as http://PI_IP:8091/radio1.mp3.
This proxy follows broadcaster redirects/tokens and streams audio back to Bose.

It also serves station logos and placeholder metadata endpoints so live ICY
metadata can be added later without changing Node-RED/bridge display logic.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import mimetypes
import socket
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import PROXY_BIND_IP, PROXY_PORT, STATIONS  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
LOGO_DIR = BASE_DIR / "logos"

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


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

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
        # /metadata/radio1.json -> station key radio1
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

    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/logos/"):
            filename = parsed.path.removeprefix("/logos/")
            safe_path = (LOGO_DIR / filename).resolve()
            if safe_path.is_file():
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(str(safe_path))[0] or "application/octet-stream")
                self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()
            return
        if parsed.path.startswith("/metadata/"):
            self.send_response(200 if parsed.path.removeprefix("/metadata/").removesuffix(".json") in METADATA else 404)
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

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
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

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)


def main():
    print(f"Starting SoundTouch radio proxy on {PROXY_BIND_IP}:{PROXY_PORT}", flush=True)
    print(f"Configured streams: {', '.join(sorted(STREAMS))}", flush=True)
    ThreadingHTTPServer((PROXY_BIND_IP, PROXY_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
