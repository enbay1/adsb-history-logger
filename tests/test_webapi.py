import json
import threading
import urllib.error
import urllib.request

import pytest

from adsb_history_logger.db import flush, open_db
from adsb_history_logger.webapi import make_handler
from http.server import ThreadingHTTPServer


def row(icao, ts, callsign="UAL123", altitude=1000, lat=40.0, lon=-123.0):
    return (icao, callsign, altitude, 200.0, 90.0, lat, lon, 0, "1200", 0, ts)


@pytest.fixture
def server(tmp_path):
    db_path = str(tmp_path / "history.db")
    conn = open_db(db_path)
    flush(conn, [row("a835af", 1000.0), row("a835af", 1010.0, lat=40.01, lon=-123.01)])
    conn.close()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(db_path))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def get_json(url):
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, json.loads(resp.read())


def test_history_endpoint_returns_visits(server):
    status, body = get_json(f"{server}/history/a835af")
    assert status == 200
    assert body["icao"] == "a835af"
    assert len(body["visits"]) == 1
    assert body["visits"][0]["count"] == 2


def test_history_endpoint_rejects_bad_icao(server):
    try:
        urllib.request.urlopen(f"{server}/history/not-hex", timeout=5)
        assert False, "expected HTTPError"
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_track_endpoint_returns_geojson(server):
    status, body = get_json(f"{server}/track/a835af")
    assert status == 200
    assert body["type"] == "FeatureCollection"
    coords = body["features"][0]["geometry"]["coordinates"]
    assert coords == [[-123.0, 40.0], [-123.01, 40.01]]


def test_track_endpoint_visit_out_of_range(server):
    try:
        urllib.request.urlopen(f"{server}/track/a835af?visit=5", timeout=5)
        assert False, "expected HTTPError"
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_unknown_path_is_404(server):
    try:
        urllib.request.urlopen(f"{server}/nope", timeout=5)
        assert False, "expected HTTPError"
    except urllib.error.HTTPError as e:
        assert e.code == 404
