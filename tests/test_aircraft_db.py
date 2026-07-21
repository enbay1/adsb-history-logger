from adsb_history_logger.aircraft_db import import_csv
from adsb_history_logger.db import open_db

SAMPLE_CSV = """'icao24','registration','typecode','manufacturerName','model','operator','owner'
'a835af','N12345','B738','Boeing','737-800','United Airlines','United Airlines'
'aabbcc','N67890','C172','Cessna','172 Skyhawk','','Private Owner'
"""


def test_import_csv_loads_rows(tmp_path):
    csv_path = tmp_path / "aircraft.csv"
    csv_path.write_text(SAMPLE_CSV, encoding="utf-8")

    conn = open_db(str(tmp_path / "history.db"))
    count = import_csv(conn, str(csv_path))
    assert count == 2

    rec = conn.execute(
        "SELECT registration, typecode, manufacturer, model, operator, owner FROM aircraft_ref WHERE icao24='a835af'"
    ).fetchone()
    assert rec == ("N12345", "B738", "Boeing", "737-800", "United Airlines", "United Airlines")

    rec2 = conn.execute("SELECT owner FROM aircraft_ref WHERE icao24='aabbcc'").fetchone()
    assert rec2 == ("Private Owner",)
    conn.close()


def test_import_csv_is_idempotent_and_updates_existing_rows(tmp_path):
    csv_path = tmp_path / "aircraft.csv"
    csv_path.write_text(SAMPLE_CSV, encoding="utf-8")
    conn = open_db(str(tmp_path / "history.db"))

    import_csv(conn, str(csv_path))
    import_csv(conn, str(csv_path))

    count = conn.execute("SELECT COUNT(*) FROM aircraft_ref").fetchone()[0]
    assert count == 2
    conn.close()


def test_import_csv_skips_rows_without_icao24(tmp_path):
    csv_path = tmp_path / "aircraft.csv"
    csv_path.write_text(
        "'icao24','registration','typecode','manufacturerName','model','operator','owner'\n"
        "'','N00000','C172','Cessna','172','','' \n",
        encoding="utf-8",
    )
    conn = open_db(str(tmp_path / "history.db"))
    count = import_csv(conn, str(csv_path))
    assert count == 0
    conn.close()
