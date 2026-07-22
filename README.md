# adsb-history-logger

A small, local, unfiltered position-history logger for [dump1090-fa](https://github.com/flightaware/dump1090)
/ [readsb](https://github.com/wiedehopf/readsb) style ADS-B decoders.

## Why

Public aggregators (FlightAware, ADS-B Exchange, FlightRadar24, ...) hide
aircraft enrolled in the FAA's LADD or PIA privacy programs from their
displays and APIs. Your own receiver still hears their raw ADS-B broadcasts
just fine -- the filtering happens downstream, not at the antenna. This
tool records every position fix your receiver decodes, straight from your
decoder's local network feed, into a small SQLite database on disk, so you
have a complete, permanent, locally-owned history regardless of what any
external service chooses to show.

## How it works

Your decoder (dump1090-fa, readsb, etc.) already publishes a BaseStation/SBS
format feed on TCP port 30003, which any number of local clients can connect
to at once (this is exactly how tools like tar1090, fr24feed, and Planefence
already consume it). `adsb-history-logger` is just one more read-only client
of that feed. It does not touch, configure, restart, or depend on your
decoder, piaware, fr24feed, or anything else in your stack.

For each aircraft, it throttles writes to at most one position fix every
`--min-interval` seconds (default 10s) -- plenty of resolution for track
playback, while keeping database growth and SD-card write wear manageable
on something like a Raspberry Pi.

## Components

- `adsb-history-logger` -- the daemon. Connects to the SBS feed, decodes
  messages, writes throttled position fixes to SQLite.
- `adsb-history-query` -- CLI for querying history: per-aircraft visit
  history, raw track dumps (CSV or GeoJSON), and reference-database search
  by registration/type/operator.
- `adsb-history-prune` -- deletes position rows older than a retention
  window (default 3 years), meant to be run periodically (e.g. via the
  packaged systemd timer).

## Database schema

- `positions` -- one row per logged position fix (icao, callsign, altitude,
  speed, track, lat/lon, vertical rate, squawk, on_ground, timestamp).
- `aircraft` -- one row per ICAO24 address seen, with first/last-seen times
  and a running fix count.
- `aircraft_ref` -- optional static reference data (registration, type,
  manufacturer, operator, owner) keyed by ICAO24, populated via
  `adsb-history-query refresh-db <csv>`. If you're running
  [Planefence](https://github.com/sdr-enthusiasts/docker-planefence), it
  already downloads a compatible OpenSky-format aircraft database CSV you
  can point this at directly (typically under
  `.../planefence/config/.internal/aircraft-database-complete-*.csv`); any
  OpenSky-format aircraft database export works.

## Install

### From a .deb (recommended on Debian/Raspberry Pi OS)

Download the latest `.deb` from the
[Releases](../../releases) page and install it:

```sh
sudo apt install ./adsb-history-logger_<version>_all.deb
```

This installs the daemon, CLI tools, a systemd service
(`adsb-history-logger.service`), and a weekly pruning timer
(`adsb-history-prune.timer`), and starts the service immediately. The
database defaults to `/var/lib/adsb-history-logger/history.db`.

### From source

```sh
pip install .
adsb-history-logger --host 127.0.0.1 --port 30003 --db-path ./history.db
```

## Configuration

The daemon reads either command-line flags or environment variables (flags
win): `ADSB_HOST`, `ADSB_PORT`, `ADSB_DB_PATH`, `ADSB_MIN_INTERVAL`,
`ADSB_FLUSH_INTERVAL`. When installed from the `.deb`, these are set in
`/etc/default/adsb-history-logger`.

## Usage

```sh
# Import/refresh aircraft reference data (registration, type, operator)
adsb-history-query refresh-db /path/to/aircraft-database.csv

# Show visit history for an aircraft, by ICAO hex, callsign, registration, or type
adsb-history-query aircraft a835af
adsb-history-query aircraft N12345
adsb-history-query aircraft UAL123

# Dump the raw track for an aircraft's most recent visit
adsb-history-query track a835af --visit 1

# Export a track as GeoJSON for mapping
adsb-history-query track a835af --format geojson > track.geojson

# Search the reference database
adsb-history-query search --operator "United Airlines"
adsb-history-query search --typecode B738

# Manually prune old history (normally handled by the packaged timer)
adsb-history-prune --retention-days 1095
```

## tar1090 integration

If you run [tar1090](https://github.com/wiedehopf/tar1090), `adsb-history-logger`
can add a "History" panel to its aircraft info sidebar: select any aircraft
on the map, see its past visits, and click one to draw that track as an
overlay on the live map.

This works as a thin add-on, not a fork: `adsb-history-web` serves a small
read-only JSON API (`/history/<icao>`, `/track/<icao>`), and
`history-overlay.js`/`.css` (original code, bundled with this package) are
copied alongside tar1090's own files and referenced with three small,
idempotent insertions into its `index.html` -- tar1090's own GPLv2 code is
never modified or redistributed. The overlay talks to `OLMap` and
`SelectedPlane`, the globals tar1090 itself exposes; it doesn't touch
tar1090's internals otherwise.

To wire it up (after installing the `.deb`, with tar1090 already installed):

```sh
sudo systemctl enable --now adsb-history-web.service
sudo adsb-history-integrate-tar1090 --tar1090-dir /usr/local/share/tar1090/html
```

Safe to re-run `adsb-history-integrate-tar1090` any time, including after a
tar1090 update resets `index.html` -- it detects and cleanly reapplies its
own insertions. By default it also drops a lighttpd reverse-proxy snippet
routing `/history-api/` to the `adsb-history-web` service (127.0.0.1:8091)
so the browser can reach it same-origin; pass `--lighttpd-conf-dir` if
yours lives somewhere else, or `--no-reload` to apply the config without
reloading lighttpd immediately.

tar1090's lighttpd config typically caches `*.js`/`*.css` files under its
own path for two weeks (`Cache-Control: max-age=1209600`). The integration
script appends a `?v=<version>` query string to the injected `<script>`/
`<link>` tags specifically to defeat this -- each release forces a fresh
fetch regardless of that header, so a plain reload after re-running
`adsb-history-integrate-tar1090` is normally enough (a hard-refresh only
matters if you're re-testing the *same* version again).

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/pip install pytest
.venv/bin/python -m pytest

# browser-side logic (adsb_history_logger/webui/history-overlay.js)
node --test tests-js/
```

## Building the .deb

```sh
dpkg-buildpackage -us -uc -b
```

Produces `../adsb-history-logger_<version>_all.deb`. CI does this
automatically on tagged releases (see `.github/workflows/`).

## License

MIT
