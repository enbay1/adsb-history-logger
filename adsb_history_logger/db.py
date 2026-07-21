"""SQLite schema and storage helpers for the local track-history database."""
import os
import sqlite3
from typing import Iterable, Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    icao TEXT NOT NULL,
    callsign TEXT,
    altitude INTEGER,
    ground_speed REAL,
    track REAL,
    lat REAL,
    lon REAL,
    vertical_rate INTEGER,
    squawk TEXT,
    on_ground INTEGER,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_positions_icao_ts ON positions(icao, ts);
CREATE INDEX IF NOT EXISTS idx_positions_ts ON positions(ts);

CREATE TABLE IF NOT EXISTS aircraft (
    icao TEXT PRIMARY KEY,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    last_callsign TEXT,
    message_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS aircraft_ref (
    icao24 TEXT PRIMARY KEY,
    registration TEXT,
    typecode TEXT,
    manufacturer TEXT,
    model TEXT,
    operator TEXT,
    owner TEXT,
    updated_at REAL NOT NULL
);
"""


def open_db(path: str) -> sqlite3.Connection:
    dirname = os.path.dirname(path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# A position row tuple, matching the column order of the INSERT below.
PositionRow = Sequence  # (icao, callsign, altitude, ground_speed, track, lat, lon, vertical_rate, squawk, on_ground, ts)


def insert_positions(conn: sqlite3.Connection, rows: Iterable[PositionRow]) -> None:
    conn.executemany(
        """INSERT INTO positions
           (icao, callsign, altitude, ground_speed, track, lat, lon, vertical_rate, squawk, on_ground, ts)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )


def upsert_aircraft_seen(conn: sqlite3.Connection, rows: Iterable[PositionRow]) -> None:
    """Update the aircraft summary table from a batch of position rows.

    Only the latest (icao, callsign, ts) per aircraft in the batch is applied,
    and message_count is bumped once per row seen (not just once per aircraft),
    so it reflects total position fixes logged.
    """
    latest: dict = {}
    counts: dict = {}
    for row in rows:
        icao, callsign, ts = row[0], row[1], row[10]
        counts[icao] = counts.get(icao, 0) + 1
        prev = latest.get(icao)
        if prev is None or ts > prev[1]:
            latest[icao] = (callsign, ts)

    for icao, (callsign, ts) in latest.items():
        conn.execute(
            """INSERT INTO aircraft (icao, first_seen, last_seen, last_callsign, message_count)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(icao) DO UPDATE SET
                 last_seen=excluded.last_seen,
                 last_callsign=COALESCE(excluded.last_callsign, aircraft.last_callsign),
                 message_count=aircraft.message_count + excluded.message_count""",
            (icao, ts, ts, callsign, counts[icao]),
        )


def flush(conn: sqlite3.Connection, rows: Sequence[PositionRow]) -> None:
    if not rows:
        return
    insert_positions(conn, rows)
    upsert_aircraft_seen(conn, rows)
    conn.commit()
