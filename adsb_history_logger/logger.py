#!/usr/bin/env python3
"""
Local ADS-B track history logger.

Connects to dump1090-fa's (or readsb's) SBS output and records position
history for every aircraft seen, independent of any external aggregator --
so aircraft hidden from public sites via FAA LADD/PIA are captured too.

This is a read-only client of an already-published local feed: it does not
touch dump1090-fa, piaware, fr24feed, or any other feeder in any way.
"""
import argparse
import os
import signal
import socket
import time
from typing import Optional

from adsb_history_logger.db import flush, open_db
from adsb_history_logger.sbs import parse_sbs

FIELDS = ("callsign", "altitude", "ground_speed", "track", "lat", "lon",
          "vertical_rate", "squawk", "on_ground")


def process_line(line: str, state: dict, last_logged: dict, now: float,
                  min_interval: float) -> Optional[tuple]:
    """Update per-aircraft state from one SBS line; return a position row to
    log if this line represents a fresh-enough position fix, else None."""
    msg = parse_sbs(line)
    if msg is None:
        return None

    icao = msg["icao"]
    st = state.setdefault(icao, {})
    for k in FIELDS:
        if msg[k] is not None:
            st[k] = msg[k]

    if msg["ttype"] != 3 or st.get("lat") is None or st.get("lon") is None:
        return None
    if now - last_logged.get(icao, 0) < min_interval:
        return None

    last_logged[icao] = now
    return (
        icao, st.get("callsign"), st.get("altitude"), st.get("ground_speed"),
        st.get("track"), st.get("lat"), st.get("lon"), st.get("vertical_rate"),
        st.get("squawk"), st.get("on_ground"), now,
    )


def run(host: str, port: int, db_path: str, min_interval: float, flush_interval: float,
        stop_flag) -> None:
    conn = open_db(db_path)
    pending = []
    last_logged: dict = {}
    state: dict = {}
    last_flush = time.time()
    backoff = 1

    print(f"adsb-history-logger starting, feed={host}:{port} db={db_path} "
          f"min_interval={min_interval}s", flush=True)

    try:
        while not stop_flag():
            sock = None
            try:
                sock = socket.create_connection((host, port), timeout=10)
                sock.settimeout(1.0)
                buf = b""
                backoff = 1
                print(f"connected to {host}:{port}", flush=True)

                while not stop_flag():
                    try:
                        chunk = sock.recv(4096)
                        if not chunk:
                            raise ConnectionError("feed closed connection")
                        buf += chunk
                    except socket.timeout:
                        pass

                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        row = process_line(
                            line.decode("ascii", errors="replace"),
                            state, last_logged, time.time(), min_interval,
                        )
                        if row is not None:
                            pending.append(row)

                    now = time.time()
                    if now - last_flush >= flush_interval and pending:
                        flush(conn, pending)
                        pending = []
                        last_flush = now

            except (ConnectionError, OSError) as e:
                print(f"feed connection lost ({e}), retrying in {backoff}s", flush=True)
                if pending:
                    flush(conn, pending)
                    pending = []
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
            finally:
                if sock is not None:
                    sock.close()
    finally:
        if pending:
            flush(conn, pending)
        conn.close()
        print("adsb-history-logger stopped", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("ADSB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ADSB_PORT", "30003")))
    parser.add_argument("--db-path", default=os.environ.get("ADSB_DB_PATH", "/var/lib/adsb-history-logger/history.db"))
    parser.add_argument("--min-interval", type=float,
                         default=float(os.environ.get("ADSB_MIN_INTERVAL", "10")),
                         help="minimum seconds between logged positions, per aircraft")
    parser.add_argument("--flush-interval", type=float,
                         default=float(os.environ.get("ADSB_FLUSH_INTERVAL", "5")),
                         help="seconds between database writes")
    args = parser.parse_args()

    stop = {"flag": False}

    def handle_signal(signum, frame):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    run(args.host, args.port, args.db_path, args.min_interval, args.flush_interval,
        lambda: stop["flag"])


if __name__ == "__main__":
    main()
