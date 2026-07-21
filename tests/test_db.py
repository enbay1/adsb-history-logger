import sqlite3

import pytest

from adsb_history_logger.db import flush, open_db


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "history.db"
    c = open_db(str(db_path))
    yield c
    c.close()


def row(icao, callsign, ts, altitude=1000):
    return (icao, callsign, altitude, 200.0, 90.0, 40.0, -123.0, 0, "1200", 0, ts)


def test_schema_creates_expected_tables(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"positions", "aircraft", "aircraft_ref"} <= tables


def test_flush_inserts_positions(conn):
    flush(conn, [row("a835af", "UAL123", 1000.0), row("a835af", "UAL123", 1010.0)])
    count = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    assert count == 2


def test_flush_upserts_aircraft_summary(conn):
    flush(conn, [row("a835af", "UAL123", 1000.0)])
    flush(conn, [row("a835af", "UAL123", 1010.0)])

    rec = conn.execute(
        "SELECT first_seen, last_seen, last_callsign, message_count FROM aircraft WHERE icao='a835af'"
    ).fetchone()
    assert rec == (1000.0, 1010.0, "UAL123", 2)


def test_flush_tracks_multiple_aircraft_independently(conn):
    flush(conn, [row("a835af", "UAL123", 1000.0), row("aabbcc", "DAL456", 1000.0)])
    icaos = {r[0] for r in conn.execute("SELECT icao FROM aircraft")}
    assert icaos == {"a835af", "aabbcc"}


def test_flush_keeps_last_callsign_when_later_batch_has_none(conn):
    flush(conn, [row("a835af", "UAL123", 1000.0)])
    flush(conn, [row("a835af", None, 1010.0)])
    last_callsign = conn.execute("SELECT last_callsign FROM aircraft WHERE icao='a835af'").fetchone()[0]
    assert last_callsign == "UAL123"


def test_flush_with_empty_rows_is_a_noop(conn):
    flush(conn, [])
    assert conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 0
