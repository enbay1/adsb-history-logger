from adsb_history_logger.db import flush, open_db
from adsb_history_logger.query import group_visits, resolve_icaos, track_geojson, visits_summary


def pos(ts, altitude=1000, callsign="UAL123"):
    return {"ts": ts, "altitude": altitude, "callsign": callsign}


def test_group_visits_single_contiguous_visit():
    positions = [pos(0), pos(60), pos(120)]
    visits = group_visits(positions, gap_seconds=1800)
    assert len(visits) == 1
    assert visits[0]["count"] == 3
    assert visits[0]["start_ts"] == 0
    assert visits[0]["end_ts"] == 120


def test_group_visits_splits_on_large_gap():
    positions = [pos(0), pos(60), pos(10000), pos(10060)]
    visits = group_visits(positions, gap_seconds=1800)
    assert len(visits) == 2
    assert visits[0]["count"] == 2
    assert visits[1]["count"] == 2


def test_group_visits_tracks_altitude_range():
    positions = [pos(0, altitude=1000), pos(60, altitude=5000), pos(120, altitude=3000)]
    visits = group_visits(positions, gap_seconds=1800)
    assert visits[0]["min_altitude"] == 1000
    assert visits[0]["max_altitude"] == 5000


def test_group_visits_empty_input():
    assert group_visits([], gap_seconds=1800) == []


def test_group_visits_collects_distinct_callsigns():
    positions = [pos(0, callsign="UAL123"), pos(60, callsign="UAL123"), pos(120, callsign=None)]
    visits = group_visits(positions, gap_seconds=1800)
    assert visits[0]["callsigns"] == ["UAL123"]


def test_resolve_icaos_hex_passthrough(tmp_path):
    conn = open_db(str(tmp_path / "history.db"))
    assert resolve_icaos(conn, "A835AF") == ["a835af"]
    conn.close()


def test_resolve_icaos_by_callsign(tmp_path):
    conn = open_db(str(tmp_path / "history.db"))
    flush(conn, [("a835af", "UAL123", 1000, 200.0, 90.0, 40.0, -123.0, 0, "1200", 0, 1000.0)])
    assert resolve_icaos(conn, "UAL123") == ["a835af"]
    conn.close()


def test_resolve_icaos_by_registration(tmp_path):
    conn = open_db(str(tmp_path / "history.db"))
    conn.execute(
        """INSERT INTO aircraft_ref (icao24, registration, typecode, manufacturer, model, operator, owner, updated_at)
           VALUES ('a835af', 'N12345', 'B738', 'Boeing', '737-800', 'United', 'United', 0)"""
    )
    conn.commit()
    assert resolve_icaos(conn, "N12345") == ["a835af"]
    conn.close()


def test_resolve_icaos_no_match(tmp_path):
    conn = open_db(str(tmp_path / "history.db"))
    assert resolve_icaos(conn, "nonexistent") == []
    conn.close()


def flushrow(icao, ts, lat=40.0, lon=-123.0, altitude=1000, on_ground=0):
    return (icao, "UAL123", altitude, 200.0, 90.0, lat, lon, 0, "1200", on_ground, ts)


def test_visits_summary_matches_group_visits(tmp_path):
    conn = open_db(str(tmp_path / "history.db"))
    flush(conn, [flushrow("a835af", 0), flushrow("a835af", 60)])
    visits = visits_summary(conn, "a835af")
    assert len(visits) == 1
    assert visits[0]["count"] == 2
    conn.close()


def test_track_geojson_emits_one_segment_per_consecutive_pair(tmp_path):
    conn = open_db(str(tmp_path / "history.db"))
    flush(conn, [
        flushrow("a835af", 0, lat=40.0, lon=-123.0, altitude=1000),
        flushrow("a835af", 60, lat=40.1, lon=-123.1, altitude=2000),
        flushrow("a835af", 120, lat=40.2, lon=-123.2, altitude=3000),
    ])
    geojson = track_geojson(conn, "a835af")
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == 2

    seg0 = geojson["features"][0]
    assert seg0["geometry"]["coordinates"] == [[-123.0, 40.0], [-123.1, 40.1]]
    assert seg0["properties"]["altitude"] == 2000  # trailing point's altitude
    assert seg0["properties"]["seq"] == 0

    seg1 = geojson["features"][1]
    assert seg1["geometry"]["coordinates"] == [[-123.1, 40.1], [-123.2, 40.2]]
    assert seg1["properties"]["seq"] == 1
    conn.close()


def test_track_geojson_single_point_has_no_segments(tmp_path):
    conn = open_db(str(tmp_path / "history.db"))
    flush(conn, [flushrow("a835af", 0)])
    geojson = track_geojson(conn, "a835af")
    assert geojson["features"] == []
    conn.close()


def test_track_geojson_marks_on_ground_if_either_endpoint_is(tmp_path):
    conn = open_db(str(tmp_path / "history.db"))
    flush(conn, [flushrow("a835af", 0, on_ground=1), flushrow("a835af", 60, on_ground=0)])
    geojson = track_geojson(conn, "a835af")
    assert geojson["features"][0]["properties"]["on_ground"] is True
    conn.close()


def test_track_geojson_limited_to_visit(tmp_path):
    conn = open_db(str(tmp_path / "history.db"))
    flush(conn, [flushrow("a835af", 0), flushrow("a835af", 60), flushrow("a835af", 10000)])
    geojson = track_geojson(conn, "a835af", visit=1, visit_gap=1800)
    assert len(geojson["features"]) == 1


def test_track_geojson_out_of_range_visit_returns_none(tmp_path):
    conn = open_db(str(tmp_path / "history.db"))
    flush(conn, [flushrow("a835af", 0)])
    assert track_geojson(conn, "a835af", visit=5) is None
    conn.close()
