#!/usr/bin/env python3
"""Delete position rows older than a retention window, to keep the local
database bounded on disk. Meant to run periodically (see the packaged
systemd timer), not continuously.
"""
import argparse
import sqlite3
import sys
import time

from adsb_history_logger.db import open_db


def prune(conn: sqlite3.Connection, retention_days: float) -> int:
    cutoff = time.time() - retention_days * 86400
    cur = conn.execute("DELETE FROM positions WHERE ts < ?", (cutoff,))
    conn.commit()
    return cur.rowcount


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="/var/lib/adsb-history-logger/history.db")
    parser.add_argument("--retention-days", type=float, default=1095,
                         help="delete position rows older than this many days (default: 3 years)")
    parser.add_argument("--vacuum", action="store_true", help="reclaim disk space after pruning")
    args = parser.parse_args()

    conn = open_db(args.db_path)
    deleted = prune(conn, args.retention_days)
    if args.vacuum and deleted:
        conn.execute("VACUUM")
    conn.close()
    print(f"pruned {deleted} position rows older than {args.retention_days} days", file=sys.stderr)


if __name__ == "__main__":
    main()
