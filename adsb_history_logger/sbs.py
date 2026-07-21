"""Parsing for SBS (BaseStation) format, as emitted by dump1090-fa / readsb on port 30003.

Field layout (0-indexed), per the long-standing BaseStation CSV convention:
  0  message_type       always "MSG" for the rows we care about
  1  transmission_type  1-8, identifies which fields are populated
  2  session_id
  3  aircraft_id
  4  hex_ident          ICAO24 address, our aircraft key
  5  flight_id
  6  date_msg_generated
  7  time_msg_generated
  8  date_msg_logged
  9  time_msg_logged
  10 callsign
  11 altitude
  12 ground_speed
  13 track
  14 latitude
  15 longitude
  16 vertical_rate
  17 squawk
  18 alert
  19 emergency
  20 spi
  21 is_on_ground       "-1" true, "0" false
"""
from typing import Optional, TypedDict


class SbsMessage(TypedDict):
    ttype: int
    icao: str
    callsign: Optional[str]
    altitude: Optional[int]
    ground_speed: Optional[float]
    track: Optional[float]
    lat: Optional[float]
    lon: Optional[float]
    vertical_rate: Optional[int]
    squawk: Optional[str]
    on_ground: Optional[int]


def _num(s: str, cast):
    s = s.strip()
    if not s:
        return None
    try:
        return cast(s)
    except ValueError:
        return None


def parse_sbs(line: str) -> Optional[SbsMessage]:
    """Parse one SBS CSV line. Returns None for blank, malformed, or non-MSG rows."""
    if not line:
        return None
    fields = line.rstrip("\r\n").split(",")
    if len(fields) < 22 or fields[0] != "MSG":
        return None

    ttype = _num(fields[1], int)
    if ttype is None:
        return None

    icao = fields[4].strip().lower()
    if not icao:
        return None

    ground_flag = fields[21].strip()
    on_ground = 1 if ground_flag == "-1" else (0 if ground_flag == "0" else None)

    return {
        "ttype": ttype,
        "icao": icao,
        "callsign": fields[10].strip() or None,
        "altitude": _num(fields[11], int),
        "ground_speed": _num(fields[12], float),
        "track": _num(fields[13], float),
        "lat": _num(fields[14], float),
        "lon": _num(fields[15], float),
        "vertical_rate": _num(fields[16], int),
        "squawk": fields[17].strip() or None,
        "on_ground": on_ground,
    }
