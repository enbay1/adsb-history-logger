#!/usr/bin/env python3
"""Wire the adsb-history-logger "History" panel into an existing tar1090
install.

This copies our own history-overlay.js/css (original, MIT licensed) into
tar1090's html directory and adds three small, idempotent insertions to
its index.html: a stylesheet link, an empty container div for the History
panel, and a script tag. tar1090's own files are otherwise untouched --
we never modify or redistribute tar1090's GPLv2 code itself.

Also drops a lighttpd reverse-proxy snippet so the browser can reach the
adsb-history-web API same-origin, at /history-api/.

Safe to re-run (e.g. after a tar1090 update resets index.html): re-running
just re-applies the same three insertions.
"""
import argparse
import importlib.resources
import shutil
import subprocess
import sys
from pathlib import Path

from adsb_history_logger import __version__

BEGIN_MARKER = "<!-- adsb-history-logger:begin -->"
END_MARKER = "<!-- adsb-history-logger:end -->"

LIGHTTPD_CONF_TEMPLATE = """\
# {marker}
$HTTP["url"] =~ "^/history-api/" {{
    proxy.server = ( "" => ( ( "host" => "{host}", "port" => {port} ) ) )
    proxy.header = ( "map-urlpath" => ( "/history-api/" => "/" ) )
}}
"""


def _strip_previous(html: str) -> str:
    while BEGIN_MARKER in html and END_MARKER in html:
        start = html.index(BEGIN_MARKER)
        end = html.index(END_MARKER) + len(END_MARKER)
        html = html[:start] + html[end:]
    return html


def patch_index_html(tar1090_dir: Path) -> None:
    index_path = tar1090_dir / "index.html"
    html = index_path.read_text(encoding="utf-8")
    html = _strip_previous(html)

    # The ?v= query string is a cache-buster: tar1090's lighttpd config
    # caches *.js/*.css under its path for 14 days, and a stale copy has
    # caused real confusion more than once. Browsers key their cache by
    # the full URL including the query string, so bumping this on every
    # release forces a fresh fetch regardless of that Cache-Control header.
    css_tag = (f'{BEGIN_MARKER}\n<link rel="stylesheet" href="history-overlay.css?v={__version__}">\n'
               f'{END_MARKER}\n')
    if "</head>" not in html:
        raise RuntimeError(f"couldn't find </head> in {index_path}")
    html = html.replace("</head>", css_tag + "</head>", 1)

    anchor = 'id="selected_icao"'
    idx = html.find(anchor)
    if idx == -1:
        raise RuntimeError(f"couldn't find aircraft info panel anchor ({anchor}) in {index_path}")
    close_div = html.find("</div>", idx)
    if close_div == -1:
        raise RuntimeError(f"couldn't find closing </div> after {anchor} in {index_path}")
    close_div += len("</div>")
    panel_html = f'\n{BEGIN_MARKER}\n<div id="adsb_history_panel"></div>\n{END_MARKER}\n'
    html = html[:close_div] + panel_html + html[close_div:]

    script_tag = (f'{BEGIN_MARKER}\n<script src="history-overlay.js?v={__version__}"></script>\n'
                  f'{END_MARKER}\n')
    if "</body>" not in html:
        raise RuntimeError(f"couldn't find </body> in {index_path}")
    html = html.replace("</body>", script_tag + "</body>", 1)

    index_path.write_text(html, encoding="utf-8")


def copy_assets(tar1090_dir: Path) -> None:
    webui = importlib.resources.files("adsb_history_logger") / "webui"
    for name in ("history-overlay.js", "history-overlay.css"):
        shutil.copyfile(str(webui / name), str(tar1090_dir / name))


def write_lighttpd_conf(conf_dir: Path, host: str, port: int) -> Path:
    conf_path = conf_dir / "adsb-history-logger.conf"
    conf_path.write_text(
        LIGHTTPD_CONF_TEMPLATE.format(marker="managed by adsb-history-logger", host=host, port=port),
        encoding="utf-8",
    )
    return conf_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tar1090-dir", default="/usr/local/share/tar1090/html")
    parser.add_argument("--lighttpd-conf-dir", default="/etc/lighttpd/conf-enabled")
    parser.add_argument("--api-host", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, default=8091)
    parser.add_argument("--no-reload", action="store_true", help="don't reload lighttpd afterward")
    args = parser.parse_args()

    tar1090_dir = Path(args.tar1090_dir)
    if not (tar1090_dir / "index.html").is_file():
        print(f"error: {tar1090_dir}/index.html not found -- is tar1090 installed there?", file=sys.stderr)
        sys.exit(1)

    copy_assets(tar1090_dir)
    patch_index_html(tar1090_dir)
    print(f"patched {tar1090_dir}/index.html")

    conf_dir = Path(args.lighttpd_conf_dir)
    if conf_dir.is_dir():
        subprocess.run(["lighttpd-enable-mod", "proxy"], check=False)
        conf_path = write_lighttpd_conf(conf_dir, args.api_host, args.api_port)
        print(f"wrote {conf_path}")
        if not args.no_reload:
            result = subprocess.run(["systemctl", "reload", "lighttpd"], check=False)
            if result.returncode != 0:
                print("warning: 'systemctl reload lighttpd' failed -- reload it manually", file=sys.stderr)
    else:
        print(f"note: {conf_dir} not found, skipped lighttpd proxy config -- set it up manually", file=sys.stderr)

    print("done. Make sure the adsb-history-web service is enabled and running:")
    print("  sudo systemctl enable --now adsb-history-web.service")


if __name__ == "__main__":
    main()
