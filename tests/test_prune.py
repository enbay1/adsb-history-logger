import time

from adsb_history_logger.db import flush, open_db
from adsb_history_logger.prune import prune


def row(icao, ts):
    return (icao, "UAL123", 1000, 200.0, 90.0, 40.0, -123.0, 0, "1200", 0, ts)


def test_prune_deletes_only_old_rows(tmp_path):
    conn = open_db(str(tmp_path / "history.db"))
    now = time.time()
    flush(conn, [row("a835af", now - 400 * 86400)])   # old, should be pruned
    flush(conn, [row("a835af", now - 10 * 86400)])     # recent, should survive

    deleted = prune(conn, retention_days=365)
    assert deleted == 1
    remaining = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    assert remaining == 1
    conn.close()


def test_prune_nothing_to_delete(tmp_path):
    conn = open_db(str(tmp_path / "history.db"))
    flush(conn, [row("a835af", time.time())])
    deleted = prune(conn, retention_days=365)
    assert deleted == 0
    conn.close()
