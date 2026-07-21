"""Import/refresh the static aircraft reference table (registration, type,
manufacturer, operator) from an OpenSky-format aircraft database CSV.

This is the same reference data Planefence downloads for its own use
(commonly found at /home/pi/planefence/config/.internal/aircraft-database-complete-*.csv
on boxes running sdr-enthusiasts/docker-planefence); we just read it too,
so aircraft type/registration lookups work without a second download.
"""
import argparse
import csv
import sqlite3
import sys
import time

from adsb_history_logger.db import open_db

# Column names as they appear in the OpenSky aircraft database export.
CSV_COLUMNS = {
    "icao24": "icao24",
    "registration": "registration",
    "typecode": "typecode",
    "manufacturername": "manufacturer",
    "model": "model",
    "operator": "operator",
    "owner": "owner",
}


def import_csv(conn: sqlite3.Connection, csv_path: str) -> int:
    """Load rows from an OpenSky-format CSV into aircraft_ref. Returns row count."""
    now = time.time()
    count = 0
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, quotechar="'")
        if reader.fieldnames is None:
            return 0
        lower_fields = {name.lower(): name for name in reader.fieldnames}

        rows = []
        for record in reader:
            icao24 = (record.get(lower_fields.get("icao24", "icao24")) or "").strip().lower()
            if not icao24:
                continue
            rows.append((
                icao24,
                (record.get(lower_fields.get("registration", "registration")) or "").strip() or None,
                (record.get(lower_fields.get("typecode", "typecode")) or "").strip() or None,
                (record.get(lower_fields.get("manufacturername", "manufacturername")) or "").strip() or None,
                (record.get(lower_fields.get("model", "model")) or "").strip() or None,
                (record.get(lower_fields.get("operator", "operator")) or "").strip() or None,
                (record.get(lower_fields.get("owner", "owner")) or "").strip() or None,
                now,
            ))
            count += 1

    conn.executemany(
        """INSERT INTO aircraft_ref
           (icao24, registration, typecode, manufacturer, model, operator, owner, updated_at)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(icao24) DO UPDATE SET
             registration=excluded.registration,
             typecode=excluded.typecode,
             manufacturer=excluded.manufacturer,
             model=excluded.model,
             operator=excluded.operator,
             owner=excluded.owner,
             updated_at=excluded.updated_at""",
        rows,
    )
    conn.commit()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", help="path to an OpenSky-format aircraft database CSV")
    parser.add_argument("--db-path", default="/var/lib/adsb-history-logger/history.db")
    args = parser.parse_args()

    conn = open_db(args.db_path)
    count = import_csv(conn, args.csv_path)
    conn.close()
    print(f"imported/updated {count} aircraft reference rows", file=sys.stderr)


if __name__ == "__main__":
    main()
