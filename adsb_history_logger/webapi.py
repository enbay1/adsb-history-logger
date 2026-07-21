#!/usr/bin/env python3
"""Small local, read-only JSON API exposing track history.

Meant to sit behind a reverse proxy (e.g. lighttpd, alongside tar1090) so
the browser-side integration (see webui/history-overlay.js) can fetch
visit history and track GeoJSON for the currently selected aircraft.
Not designed for direct internet exposure -- bind it to 127.0.0.1 and
proxy it, same as this project's systemd unit does.
"""
import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from adsb_history_logger.db import open_db
from adsb_history_logger.query import track_geojson, visits_summary

HEX_RE = re.compile(r"^[0-9a-fA-F]{6}$")


def make_handler(db_path: str):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, obj, status=200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *fmt_args):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            parts = [p for p in parsed.path.split("/") if p]
            qs = parse_qs(parsed.query)

            if len(parts) == 2 and parts[0] == "history":
                icao = parts[1].lower()
                if not HEX_RE.match(icao):
                    self._json({"error": "invalid icao"}, 400)
                    return
                conn = open_db(db_path)
                try:
                    self._json({"icao": icao, "visits": visits_summary(conn, icao)})
                finally:
                    conn.close()
                return

            if len(parts) == 2 and parts[0] == "track":
                icao = parts[1].lower()
                if not HEX_RE.match(icao):
                    self._json({"error": "invalid icao"}, 400)
                    return
                visit_param = qs.get("visit", [None])[0]
                visit = int(visit_param) if visit_param else None
                conn = open_db(db_path)
                try:
                    geojson = track_geojson(conn, icao, visit=visit)
                finally:
                    conn.close()
                if geojson is None:
                    self._json({"error": "visit out of range"}, 400)
                    return
                self._json(geojson)
                return

            self._json({"error": "not found"}, 404)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="/var/lib/adsb-history-logger/history.db")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8091)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.db_path))
    print(f"adsb-history-web listening on {args.host}:{args.port}, db={args.db_path}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
