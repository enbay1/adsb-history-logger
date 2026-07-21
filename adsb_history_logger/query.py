#!/usr/bin/env python3
"""CLI for querying the local ADS-B track-history database."""
import argparse
import csv as csv_module
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Optional

from adsb_history_logger.aircraft_db import import_csv
from adsb_history_logger.db import open_db

HEX_RE = re.compile(r"^[0-9a-fA-F]{6}$")

DEFAULT_VISIT_GAP = 1800  # seconds of silence that separates two visits


def fmt_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def resolve_icaos(conn: sqlite3.Connection, query: str) -> list:
    """Resolve a user-supplied identifier (ICAO hex, callsign, registration,
    typecode, or operator) to a list of matching ICAO24 addresses."""
    if HEX_RE.match(query):
        return [query.lower()]

    like = f"%{query.strip()}%"
    icaos = set()

    cur = conn.execute("SELECT icao FROM aircraft WHERE last_callsign LIKE ?", (like,))
    icaos.update(row[0] for row in cur.fetchall())

    cur = conn.execute(
        """SELECT icao24 FROM aircraft_ref
           WHERE registration LIKE ? OR typecode LIKE ? OR operator LIKE ? OR model LIKE ?""",
        (like, like, like, like),
    )
    icaos.update(row[0] for row in cur.fetchall())

    return sorted(icaos)


def group_visits(positions: list, gap_seconds: float = DEFAULT_VISIT_GAP) -> list:
    """Group a time-ordered list of position dicts into discrete visits,
    splitting wherever the gap between consecutive fixes exceeds gap_seconds."""
    visits = []
    current = []

    def close_visit():
        if not current:
            return
        alts = [p["altitude"] for p in current if p["altitude"] is not None]
        callsigns = sorted({p["callsign"] for p in current if p["callsign"]})
        visits.append({
            "start_ts": current[0]["ts"],
            "end_ts": current[-1]["ts"],
            "count": len(current),
            "min_altitude": min(alts) if alts else None,
            "max_altitude": max(alts) if alts else None,
            "callsigns": callsigns,
        })

    for pos in positions:
        if current and pos["ts"] - current[-1]["ts"] > gap_seconds:
            close_visit()
            current = []
        current.append(pos)
    close_visit()

    return visits


def visits_summary(conn: sqlite3.Connection, icao: str, since: Optional[float] = None,
                    visit_gap: float = DEFAULT_VISIT_GAP) -> list:
    """Grouped visit history for one aircraft, newest data included."""
    positions = fetch_positions(conn, icao, since=since)
    return group_visits(positions, gap_seconds=visit_gap)


def track_geojson(conn: sqlite3.Connection, icao: str, visit: Optional[int] = None,
                   since: Optional[float] = None, visit_gap: float = DEFAULT_VISIT_GAP) -> Optional[dict]:
    """A GeoJSON LineString of an aircraft's track, optionally limited to one visit.

    Returns None if `visit` is out of range for the aircraft's visit history.
    """
    positions = fetch_positions(conn, icao, since=since)
    if visit is not None:
        visits = group_visits(positions, gap_seconds=visit_gap)
        if visit < 1 or visit > len(visits):
            return None
        v = visits[visit - 1]
        positions = [p for p in positions if v["start_ts"] <= p["ts"] <= v["end_ts"]]

    coords = [[p["lon"], p["lat"]] for p in positions if p["lat"] is not None and p["lon"] is not None]
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"icao": icao},
            "geometry": {"type": "LineString", "coordinates": coords},
        }],
    }


def fetch_positions(conn: sqlite3.Connection, icao: str, since: Optional[float] = None) -> list:
    query = "SELECT icao, callsign, altitude, ground_speed, track, lat, lon, vertical_rate, squawk, on_ground, ts FROM positions WHERE icao = ?"
    params = [icao]
    if since is not None:
        query += " AND ts >= ?"
        params.append(since)
    query += " ORDER BY ts"
    cur = conn.execute(query, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def cmd_aircraft(conn: sqlite3.Connection, args) -> None:
    icaos = resolve_icaos(conn, args.query)
    if not icaos:
        print(f"no match for '{args.query}'", file=sys.stderr)
        sys.exit(1)

    for icao in icaos:
        ref = conn.execute(
            "SELECT registration, typecode, manufacturer, model, operator, owner FROM aircraft_ref WHERE icao24 = ?",
            (icao,),
        ).fetchone()
        seen = conn.execute(
            "SELECT first_seen, last_seen, last_callsign, message_count FROM aircraft WHERE icao = ?",
            (icao,),
        ).fetchone()

        print(f"=== {icao.upper()} ===")
        if ref:
            reg, typecode, manufacturer, model, operator, owner = ref
            print(f"  registration: {reg or '?'}   type: {typecode or '?'} ({model or '?'})")
            print(f"  operator: {operator or '?'}   owner: {owner or '?'}")
        else:
            print("  (no reference data -- run 'refresh-db' to import registration/type info)")

        if not seen:
            print("  no positions logged locally for this aircraft")
            continue

        positions = fetch_positions(conn, icao, since=args.since)
        visits = group_visits(positions, gap_seconds=args.visit_gap)
        print(f"  {seen[3]} position fixes logged, {len(visits)} visit(s) in range")
        for i, v in enumerate(visits, 1):
            duration_min = (v["end_ts"] - v["start_ts"]) / 60
            print(f"  visit {i}: {fmt_ts(v['start_ts'])} -> {fmt_ts(v['end_ts'])} "
                  f"({duration_min:.0f} min, {v['count']} fixes, "
                  f"alt {v['min_altitude']}-{v['max_altitude']} ft, "
                  f"callsigns: {', '.join(v['callsigns']) or '?'})")


def cmd_track(conn: sqlite3.Connection, args) -> None:
    icaos = resolve_icaos(conn, args.query)
    if not icaos:
        print(f"no match for '{args.query}'", file=sys.stderr)
        sys.exit(1)
    icao = icaos[0]
    if len(icaos) > 1:
        print(f"multiple matches, using {icao.upper()} (others: {', '.join(i.upper() for i in icaos[1:])})",
              file=sys.stderr)

    if args.format == "geojson":
        geojson = track_geojson(conn, icao, visit=args.visit, since=args.since, visit_gap=args.visit_gap)
        if geojson is None:
            print(f"visit {args.visit} out of range", file=sys.stderr)
            sys.exit(1)
        json.dump(geojson, sys.stdout)
        print()
        return

    positions = fetch_positions(conn, icao, since=args.since)
    if args.visit is not None:
        visits = group_visits(positions, gap_seconds=args.visit_gap)
        if args.visit < 1 or args.visit > len(visits):
            print(f"visit {args.visit} out of range (1-{len(visits)})", file=sys.stderr)
            sys.exit(1)
        v = visits[args.visit - 1]
        positions = [p for p in positions if v["start_ts"] <= p["ts"] <= v["end_ts"]]

    writer = csv_module.writer(sys.stdout)
    writer.writerow(["ts_utc", "callsign", "altitude", "ground_speed", "track", "lat", "lon",
                      "vertical_rate", "squawk", "on_ground"])
    for p in positions:
        writer.writerow([fmt_ts(p["ts"]), p["callsign"], p["altitude"], p["ground_speed"],
                          p["track"], p["lat"], p["lon"], p["vertical_rate"], p["squawk"],
                          p["on_ground"]])


def cmd_search(conn: sqlite3.Connection, args) -> None:
    clauses = []
    params = []
    for field, value in (("registration", args.registration), ("typecode", args.typecode),
                          ("operator", args.operator), ("model", args.model)):
        if value:
            clauses.append(f"{field} LIKE ?")
            params.append(f"%{value}%")
    if not clauses:
        print("specify at least one of --registration/--typecode/--operator/--model", file=sys.stderr)
        sys.exit(1)

    query = f"SELECT icao24, registration, typecode, model, operator FROM aircraft_ref WHERE {' OR '.join(clauses)} LIMIT 200"
    for icao24, reg, typecode, model, operator in conn.execute(query, params):
        seen = conn.execute("SELECT message_count FROM aircraft WHERE icao = ?", (icao24,)).fetchone()
        seen_str = f"{seen[0]} fixes logged" if seen else "not seen locally"
        print(f"{icao24.upper()}  {reg or '?':<10} {typecode or '?':<6} {model or '?':<20} {operator or '?':<20} ({seen_str})")


def cmd_refresh_db(conn: sqlite3.Connection, args) -> None:
    count = import_csv(conn, args.csv_path)
    print(f"imported/updated {count} aircraft reference rows")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="/var/lib/adsb-history-logger/history.db")
    sub = parser.add_subparsers(dest="command", required=True)

    p_aircraft = sub.add_parser("aircraft", help="show visit history for an aircraft")
    p_aircraft.add_argument("query", help="ICAO hex, callsign, registration, typecode, or operator")
    p_aircraft.add_argument("--since", type=float, default=None, help="unix timestamp lower bound")
    p_aircraft.add_argument("--visit-gap", type=float, default=DEFAULT_VISIT_GAP)
    p_aircraft.set_defaults(func=cmd_aircraft)

    p_track = sub.add_parser("track", help="dump raw position fixes for an aircraft")
    p_track.add_argument("query", help="ICAO hex, callsign, registration, typecode, or operator")
    p_track.add_argument("--since", type=float, default=None)
    p_track.add_argument("--visit", type=int, default=None, help="limit to the Nth visit (1-indexed)")
    p_track.add_argument("--visit-gap", type=float, default=DEFAULT_VISIT_GAP)
    p_track.add_argument("--format", choices=["csv", "geojson"], default="csv")
    p_track.set_defaults(func=cmd_track)

    p_search = sub.add_parser("search", help="search the aircraft reference database")
    p_search.add_argument("--registration")
    p_search.add_argument("--typecode")
    p_search.add_argument("--operator")
    p_search.add_argument("--model")
    p_search.set_defaults(func=cmd_search)

    p_refresh = sub.add_parser("refresh-db", help="(re)import the aircraft reference CSV")
    p_refresh.add_argument("csv_path")
    p_refresh.set_defaults(func=cmd_refresh_db)

    args = parser.parse_args()
    conn = open_db(args.db_path)
    try:
        args.func(conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
