from adsb_history_logger.logger import process_line

POSITION_LINE = ("MSG,3,1,1,A835AF,1,2026/07/21,10:00:00.000,2026/07/21,10:00:00.000,"
                  "UAL123,35000,,,40.88123,-123.98456,,,0,0,0,0")

VELOCITY_LINE = ("MSG,4,1,1,A835AF,1,2026/07/21,10:00:01.000,2026/07/21,10:00:01.000,"
                  ",,450,270.5,,,-64,,0,0,0,0")


def test_position_line_without_prior_state_is_logged():
    state, last_logged = {}, {}
    result = process_line(POSITION_LINE, state, last_logged, now=1000.0, min_interval=10)
    assert result is not None
    icao, callsign, altitude, gs, track, lat, lon, vr, squawk, on_ground, ts = result
    assert icao == "a835af"
    assert callsign == "UAL123"
    assert altitude == 35000
    assert lat == 40.88123
    assert ts == 1000.0


def test_velocity_line_alone_does_not_log_a_position():
    state, last_logged = {}, {}
    result = process_line(VELOCITY_LINE, state, last_logged, now=1000.0, min_interval=10)
    assert result is None
    assert state["a835af"]["ground_speed"] == 450


def test_velocity_then_position_merges_state():
    state, last_logged = {}, {}
    process_line(VELOCITY_LINE, state, last_logged, now=999.0, min_interval=10)
    result = process_line(POSITION_LINE, state, last_logged, now=1000.0, min_interval=10)
    assert result is not None
    # ground_speed (index 3) carried over from the earlier velocity message
    assert result[3] == 450


def test_min_interval_throttles_repeated_positions():
    state, last_logged = {}, {}
    first = process_line(POSITION_LINE, state, last_logged, now=1000.0, min_interval=10)
    second = process_line(POSITION_LINE, state, last_logged, now=1005.0, min_interval=10)
    third = process_line(POSITION_LINE, state, last_logged, now=1011.0, min_interval=10)
    assert first is not None
    assert second is None
    assert third is not None


def test_malformed_line_is_ignored():
    state, last_logged = {}, {}
    result = process_line("garbage,not,sbs", state, last_logged, now=1000.0, min_interval=10)
    assert result is None
    assert state == {}
