from adsb_history_logger import __version__
from adsb_history_logger.integrate_tar1090 import copy_assets, patch_index_html

FAKE_INDEX = """<!doctype html>
<html>
<head>
<title>tar1090</title>
</head>
<body>
<div id="selected_infoblock">
  <div id="selected_icao" title="ICAO">
  </div>
  <div>other stuff</div>
</div>
<div id="tab-search">
  <form id="search_form">
    <input id="search_input" type="text">
  </form>
  <form id="jump_form"></form>
</div>
<script src="script.js"></script>
</body>
</html>
"""


def write_fake_tar1090(tmp_path, html=FAKE_INDEX):
    (tmp_path / "index.html").write_text(html, encoding="utf-8")
    return tmp_path


def test_patch_inserts_css_panel_and_script(tmp_path):
    tar1090_dir = write_fake_tar1090(tmp_path)
    patch_index_html(tar1090_dir)
    html = (tar1090_dir / "index.html").read_text(encoding="utf-8")

    assert f'href="history-overlay.css?v={__version__}"' in html
    assert 'id="adsb_history_panel"' in html
    assert f'src="history-overlay.js?v={__version__}"' in html
    # panel div lands inside the info block, after the icao anchor
    assert html.index('id="selected_icao"') < html.index('id="adsb_history_panel"')


def test_patch_is_idempotent(tmp_path):
    tar1090_dir = write_fake_tar1090(tmp_path)
    patch_index_html(tar1090_dir)
    patch_index_html(tar1090_dir)
    html = (tar1090_dir / "index.html").read_text(encoding="utf-8")

    assert html.count('id="adsb_history_panel"') == 1
    assert html.count('id="adsb_history_search"') == 1
    assert html.count(f'src="history-overlay.js?v={__version__}"') == 1
    assert html.count(f'href="history-overlay.css?v={__version__}"') == 1


def test_patch_reapplies_cleanly_on_reset_tar1090_update(tmp_path):
    # Simulates a tar1090 update overwriting index.html back to stock.
    tar1090_dir = write_fake_tar1090(tmp_path)
    patch_index_html(tar1090_dir)
    write_fake_tar1090(tmp_path)  # reset to stock, unpatched
    patch_index_html(tar1090_dir)
    html = (tar1090_dir / "index.html").read_text(encoding="utf-8")

    assert html.count('id="adsb_history_panel"') == 1


def test_patch_missing_anchor_raises(tmp_path):
    html = FAKE_INDEX.replace('id="selected_icao"', "")
    tar1090_dir = write_fake_tar1090(tmp_path, html=html)
    try:
        patch_index_html(tar1090_dir)
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_patch_tags_are_versioned_for_cache_busting(tmp_path, monkeypatch):
    # tar1090's lighttpd config caches *.js/*.css for 14 days; the ?v=
    # query string must change across releases so browsers can't keep
    # serving a stale copy after an upgrade (this bit us in practice).
    import adsb_history_logger.integrate_tar1090 as mod

    monkeypatch.setattr(mod, "__version__", "1.2.3")
    tar1090_dir = write_fake_tar1090(tmp_path)
    patch_index_html(tar1090_dir)
    html = (tar1090_dir / "index.html").read_text(encoding="utf-8")

    assert 'src="history-overlay.js?v=1.2.3"' in html
    assert 'href="history-overlay.css?v=1.2.3"' in html


def test_copy_assets_places_files(tmp_path):
    write_fake_tar1090(tmp_path)
    copy_assets(tmp_path)
    assert (tmp_path / "history-overlay.js").is_file()
    assert (tmp_path / "history-overlay.css").is_file()
    assert "OLMap" in (tmp_path / "history-overlay.js").read_text(encoding="utf-8")


def test_patch_inserts_search_box_after_tar1090_search_form(tmp_path):
    tar1090_dir = write_fake_tar1090(tmp_path)
    patch_index_html(tar1090_dir)
    html = (tar1090_dir / "index.html").read_text(encoding="utf-8")

    search_end = html.index("</form>", html.index('id="search_form"'))
    assert search_end < html.index('id="adsb_history_search"') < html.index('id="jump_form"')


def test_patch_without_search_form_still_patches_panel(tmp_path, capsys):
    stock = FAKE_INDEX.replace('id="search_form"', 'id="something_else"')
    tar1090_dir = write_fake_tar1090(tmp_path, stock)
    patch_index_html(tar1090_dir)
    html = (tar1090_dir / "index.html").read_text(encoding="utf-8")

    assert 'id="adsb_history_panel"' in html
    assert 'id="adsb_history_search"' not in html
    assert "skipping the history search box" in capsys.readouterr().err
