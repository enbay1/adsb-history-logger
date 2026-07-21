from adsb_history_logger.sbs import parse_sbs

POSITION_LINE = ("MSG,3,1,1,A835AF,1,2026/07/21,10:00:00.000,2026/07/21,10:00:00.000,"
                  "UAL123,35000,,,40.88123,-123.98456,,,0,0,0,0")

VELOCITY_LINE = ("MSG,4,1,1,A835AF,1,2026/07/21,10:00:01.000,2026/07/21,10:00:01.000,"
                  ",,450,270.5,,,-64,,0,0,0,0")

IDENT_LINE = ("MSG,1,1,1,A835AF,1,2026/07/21,10:00:02.000,2026/07/21,10:00:02.000,"
              "UAL123,,,,,,,,0,0,0,0")

ON_GROUND_LINE = ("MSG,3,1,1,A835AF,1,2026/07/21,10:00:03.000,2026/07/21,10:00:03.000,"
                   "UAL123,0,,,40.88123,-123.98456,,,0,0,0,-1")


def test_parse_position_line():
    msg = parse_sbs(POSITION_LINE)
    assert msg is not None
    assert msg["ttype"] == 3
    assert msg["icao"] == "a835af"
    assert msg["callsign"] == "UAL123"
    assert msg["altitude"] == 35000
    assert msg["lat"] == 40.88123
    assert msg["lon"] == -123.98456
    assert msg["ground_speed"] is None
    assert msg["on_ground"] == 0


def test_parse_velocity_line_has_no_position():
    msg = parse_sbs(VELOCITY_LINE)
    assert msg is not None
    assert msg["ttype"] == 4
    assert msg["lat"] is None
    assert msg["ground_speed"] == 450
    assert msg["track"] == 270.5
    assert msg["vertical_rate"] == -64


def test_parse_ident_line():
    msg = parse_sbs(IDENT_LINE)
    assert msg is not None
    assert msg["ttype"] == 1
    assert msg["callsign"] == "UAL123"


def test_on_ground_flag():
    msg = parse_sbs(ON_GROUND_LINE)
    assert msg["on_ground"] == 1


def test_rejects_non_msg_rows():
    assert parse_sbs("STA,1,1,1,A835AF,,,,,,,,,,,,,,,,,") is None


def test_rejects_blank_line():
    assert parse_sbs("") is None
    assert parse_sbs("\n") is None


def test_rejects_short_line():
    assert parse_sbs("MSG,3,1,1,A835AF") is None


def test_rejects_missing_icao():
    line = ("MSG,3,1,1,,1,2026/07/21,10:00:00.000,2026/07/21,10:00:00.000,"
            "UAL123,35000,,,40.88123,-123.98456,,,0,0,0,0")
    assert parse_sbs(line) is None


def test_icao_is_lowercased():
    msg = parse_sbs(POSITION_LINE)
    assert msg["icao"] == msg["icao"].lower()
