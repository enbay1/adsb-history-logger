// adsb-history-logger integration for tar1090.
//
// This file is loaded as a plain <script> tag alongside tar1090's own
// script.js (see install-tar1090-integration for how it gets wired in).
// It does not modify or depend on tar1090's internals beyond the globals
// tar1090 itself declares at the top level of script.js: `OLMap` (the
// OpenLayers map instance) and `SelectedPlane` (the currently selected
// aircraft, or null). Everything here is original code, MIT licensed,
// kept deliberately separate from tar1090's own GPLv2 codebase.
(function () {
    "use strict";

    // Root-anchored on purpose: tar1090 can be mounted at a subpath (e.g.
    // /tar1090/), and a relative path here would resolve underneath that
    // subpath instead of matching the lighttpd proxy rule, which is
    // anchored at the site root.
    var API_BASE = "/history-api/";
    var POLL_MS = 700;

    var panel = null;
    var trackLayer = null;
    var lastIcao = null;

    // Everything shown via innerHTML that came from the database (callsigns,
    // registrations, owner names from the reference CSV) goes through this.
    function escapeHtml(value) {
        return String(value === null || value === undefined ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    // One-line label for a /lookup result, e.g. "N709DS · GLF6 · A97659".
    function describeAircraft(r) {
        var parts = [];
        if (r.registration) parts.push(r.registration);
        else if (r.last_callsign) parts.push(r.last_callsign);
        if (r.typecode) parts.push(r.typecode);
        parts.push(String(r.icao).toUpperCase());
        return parts.join(" \u00b7 ");
    }

    function ensurePanel() {
        if (panel) return panel;
        panel = document.getElementById("adsb_history_panel");
        return panel;
    }

    function clearTrack() {
        if (trackLayer && typeof OLMap !== "undefined" && OLMap) {
            OLMap.removeLayer(trackLayer);
        }
        trackLayer = null;
    }

    // tar1090 (planeObject_*.js) exposes its own global altitudeColor(alt)
    // -> [h, s, l], the exact function it uses to color the live plane
    // markers/trails -- including baro-altitude adjustment, quantized
    // rounding, and h/s/l range clamping that our own fallback below
    // doesn't replicate. Delegating to it when present guarantees history
    // tracks are colored identically to the live map, rather than merely
    // similarly via a hand-rolled reimplementation kept in sync by hand.
    function altitudeColor(altitude, onGround) {
        if (typeof window !== "undefined" && typeof window.altitudeColor === "function") {
            var hsl = window.altitudeColor(onGround ? "ground" : altitude);
            return "hsla(" + hsl[0] + ", " + hsl[1] + "%, " + hsl[2] + "%, 0.9)";
        }
        return altitudeColorFallback(altitude, onGround);
    }

    // Used under Node (tests-js/, no `window`/tar1090 globals) and as a
    // defensive fallback if tar1090's own function is ever unavailable.
    var FALLBACK_BREAKPOINTS = [[2000, 20], [10000, 140], [40000, 300]];

    function altitudeColorFallback(altitude, onGround) {
        var cfg = (typeof ColorByAlt !== "undefined" && ColorByAlt) ? ColorByAlt : null;

        if (onGround) {
            if (cfg && cfg.ground) return "hsla(" + cfg.ground.h + ", " + cfg.ground.s + "%, " + cfg.ground.l + "%, 0.9)";
            return "hsla(15, 80%, 20%, 0.9)";
        }
        if (altitude === null || altitude === undefined) {
            if (cfg && cfg.unknown) return "hsla(" + cfg.unknown.h + ", " + cfg.unknown.s + "%, " + cfg.unknown.l + "%, 0.9)";
            return "hsla(0, 0%, 40%, 0.9)";
        }

        var breakpoints = (cfg && cfg.air && cfg.air.h) ? cfg.air.h.map(function (b) { return [b.alt, b.val]; }) : FALLBACK_BREAKPOINTS;
        var s = (cfg && cfg.air) ? cfg.air.s : 85;
        var l = (cfg && cfg.air) ? cfg.air.l : 50;

        var h;
        if (altitude <= breakpoints[0][0]) {
            h = breakpoints[0][1];
        } else if (altitude >= breakpoints[breakpoints.length - 1][0]) {
            h = breakpoints[breakpoints.length - 1][1];
        } else {
            h = breakpoints[breakpoints.length - 1][1];
            for (var i = 0; i < breakpoints.length - 1; i++) {
                var a0 = breakpoints[i][0], h0 = breakpoints[i][1];
                var a1 = breakpoints[i + 1][0], h1 = breakpoints[i + 1][1];
                if (altitude >= a0 && altitude <= a1) {
                    h = h0 + ((altitude - a0) / (a1 - a0)) * (h1 - h0);
                    break;
                }
            }
        }
        return "hsla(" + h + ", " + s + "%, " + l + "%, 0.9)";
    }

    // Initial compass bearing (radians, 0 = north, clockwise) from point 1 to point 2.
    function bearing(lon1, lat1, lon2, lat2) {
        var toRad = Math.PI / 180;
        var phi1 = lat1 * toRad, phi2 = lat2 * toRad;
        var dLambda = (lon2 - lon1) * toRad;
        var y = Math.sin(dLambda) * Math.cos(phi2);
        var x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLambda);
        return Math.atan2(y, x);
    }

    // A small open chevron (left arm -> tip -> right arm), in projected map
    // units, pointing along `bearingRad`. Built from LineString rather than
    // Polygon deliberately: LineString is confirmed used directly by
    // tar1090's own code against this bundle, Polygon isn't, and this
    // bundle is a trimmed custom build that may not include it.
    function arrowLineString(centerProjected, bearingRad, sizeMeters) {
        var pts = [[-0.5, -0.4], [0, 0.6], [0.5, -0.4]];
        var cos = Math.cos(bearingRad), sin = Math.sin(bearingRad);
        var points = pts.map(function (p) {
            var x = p[0] * sizeMeters, y = p[1] * sizeMeters;
            return [
                centerProjected[0] + (x * cos + y * sin),
                centerProjected[1] + (-x * sin + y * cos),
            ];
        });
        return new ol.geom.LineString(points);
    }

    // Arrows are sized in screen pixels, not fixed map meters: a fixed
    // meter size is sub-pixel (invisible) at the zoom level you'd normally
    // view a whole track at, and oversized when zoomed in on one segment.
    var ARROW_PIXELS = 14;

    function arrowSizeMeters() {
        var view = (typeof OLMap !== "undefined" && OLMap && OLMap.getView) ? OLMap.getView() : null;
        var resolution = view ? view.getResolution() : null;
        return resolution ? ARROW_PIXELS * resolution : 250;
    }

    function renderTrack(geojson, fit) {
        var segments = geojson.features;
        var features = [];

        segments.forEach(function (seg) {
            var coords = seg.geometry.coordinates;
            var color = altitudeColor(seg.properties.altitude, seg.properties.on_ground);
            var line = new ol.Feature({
                geometry: new ol.geom.LineString([
                    ol.proj.fromLonLat(coords[0]),
                    ol.proj.fromLonLat(coords[1]),
                ]),
            });
            line.setStyle(new ol.style.Style({
                stroke: new ol.style.Stroke({ color: color, width: 3 }),
            }));
            features.push(line);
        });

        // Arrow failures must never take the line segments down with them.
        try {
            var arrowEvery = Math.max(1, Math.ceil(segments.length / 15));
            for (var i = 0; i < segments.length; i += arrowEvery) {
                var seg = segments[i];
                var coords = seg.geometry.coordinates;
                var brng = bearing(coords[0][0], coords[0][1], coords[1][0], coords[1][1]);
                var mid = [(coords[0][0] + coords[1][0]) / 2, (coords[0][1] + coords[1][1]) / 2];
                var color = altitudeColor(seg.properties.altitude, seg.properties.on_ground);
                var arrow = new ol.Feature({
                    geometry: arrowLineString(ol.proj.fromLonLat(mid), brng, arrowSizeMeters()),
                });
                arrow.setStyle(new ol.style.Style({
                    stroke: new ol.style.Stroke({ color: color, width: 2 }),
                }));
                features.push(arrow);
            }
        } catch (e) {
            console.error("adsb-history-logger: direction arrows failed, showing line only", e);
        }

        trackLayer = new ol.layer.Vector({
            name: "adsbHistoryTrack",
            title: "ADS-B history track",
            zIndex: 250,
            source: new ol.source.Vector({ features: features }),
        });
        OLMap.addLayer(trackLayer);

        // Tracks drawn from the history search are usually of aircraft long
        // gone from the live map, so their track may well be off-screen.
        if (fit && features.length) {
            try {
                OLMap.getView().fit(trackLayer.getSource().getExtent(), {
                    padding: [60, 60, 60, 60],
                    maxZoom: 12,
                });
            } catch (e) {
                console.error("adsb-history-logger: couldn't zoom to track", e);
            }
        }
    }

    function drawTrack(icao, visit, fit) {
        clearTrack();
        var url = API_BASE + "track/" + icao + (visit ? "?visit=" + visit : "");
        fetch(url)
            .then(function (resp) {
                if (!resp.ok) throw new Error("track fetch failed");
                return resp.json();
            })
            .then(function (geojson) { renderTrack(geojson, fit); })
            .catch(function (e) {
                console.error("adsb-history-logger: failed to draw track", e);
            });
    }

    // `fit`: zoom the map to a track when one of these visits is clicked.
    function renderVisits(icao, visits, el, fit) {
        if (!el) return;

        if (!visits.length) {
            el.innerHTML = '<div class="adsb-history-empty">no local history for this aircraft yet</div>';
            return;
        }

        var html = '<div class="adsb-history-title">History (' + visits.length + " visit" +
            (visits.length === 1 ? "" : "s") + ")</div>";
        for (var i = 0; i < visits.length; i++) {
            var v = visits[i];
            var start = new Date(v.start_ts * 1000);
            var mins = Math.round((v.end_ts - v.start_ts) / 60);
            var altRange = (v.min_altitude || "?") + "-" + (v.max_altitude || "?") + " ft";
            html += '<div class="adsb-history-visit" data-visit="' + (i + 1) + '">' +
                '<span class="adsb-history-visit-date">' + start.toLocaleString() + "</span>" +
                '<span class="adsb-history-visit-meta">' + mins + " min, " + altRange + "</span>" +
                "</div>";
        }
        html += '<div class="adsb-history-clear">clear track</div>';
        el.innerHTML = html;

        var visitEls = el.getElementsByClassName("adsb-history-visit");
        for (var j = 0; j < visitEls.length; j++) {
            visitEls[j].addEventListener("click", function () {
                drawTrack(icao, this.getAttribute("data-visit"), fit);
            });
        }
        el.getElementsByClassName("adsb-history-clear")[0].addEventListener("click", clearTrack);
    }

    var RETRY_MS = 2000;

    function loadHistory(icao) {
        var el = ensurePanel();
        if (!el) return;
        el.innerHTML = '<div class="adsb-history-loading">loading history...</div>';

        fetch(API_BASE + "history/" + icao)
            .then(function (resp) {
                if (!resp.ok) throw new Error("history fetch failed");
                return resp.json();
            })
            .then(function (data) {
                renderVisits(icao, data.visits, el, false);
            })
            .catch(function (e) {
                console.error("adsb-history-logger: failed to load history, will retry", e);
                el.innerHTML = '<div class="adsb-history-empty">history unavailable, retrying...</div>';
                // Keep retrying while this aircraft is still selected, rather
                // than getting permanently stuck after one transient failure
                // (e.g. right after page load, before tar1090 has settled).
                window.setTimeout(function () {
                    if (lastIcao === icao) loadHistory(icao);
                }, RETRY_MS);
            });
    }

    function poll() {
        var plane = typeof SelectedPlane !== "undefined" ? SelectedPlane : null;
        var icao = plane ? plane.icao : null;

        if (icao !== lastIcao) {
            clearTrack();
            lastIcao = icao;
            if (icao) {
                loadHistory(icao);
            } else {
                var el = ensurePanel();
                if (el) el.innerHTML = "";
            }
        }
    }

    // History search: looks aircraft up in our own database rather than
    // tar1090's live plane list, so it still works for aircraft tar1090 has
    // already dropped (it forgets a plane ~15 minutes after last contact,
    // and the selected-plane panel above can only follow what tar1090 has).
    var searchEl = null;

    function renderSearchResults(results) {
        var list = searchEl.querySelector(".adsb-history-search-results");
        var visitsEl = searchEl.querySelector(".adsb-history-search-visits");
        visitsEl.innerHTML = "";

        if (!results.length) {
            list.innerHTML = '<div class="adsb-history-empty">no logged aircraft match</div>';
            return;
        }

        var html = "";
        for (var i = 0; i < results.length; i++) {
            var r = results[i];
            var seen = new Date(r.last_seen * 1000).toLocaleString();
            html += '<div class="adsb-history-visit adsb-history-result" data-icao="' + escapeHtml(r.icao) + '"' +
                ' title="' + escapeHtml(r.owner || r.operator || "") + '">' +
                '<span class="adsb-history-visit-date">' + escapeHtml(describeAircraft(r)) + "</span>" +
                '<span class="adsb-history-visit-meta">' + escapeHtml(seen) + "</span>" +
                "</div>";
        }
        list.innerHTML = html;

        var rows = list.getElementsByClassName("adsb-history-result");
        for (var j = 0; j < rows.length; j++) {
            rows[j].addEventListener("click", function () {
                for (var k = 0; k < rows.length; k++) rows[k].classList.remove("adsb-history-active");
                this.classList.add("adsb-history-active");
                showSearchVisits(this.getAttribute("data-icao"));
            });
        }
    }

    function showSearchVisits(icao) {
        var visitsEl = searchEl.querySelector(".adsb-history-search-visits");
        visitsEl.innerHTML = '<div class="adsb-history-loading">loading history...</div>';
        fetch(API_BASE + "history/" + icao)
            .then(function (resp) {
                if (!resp.ok) throw new Error("history fetch failed");
                return resp.json();
            })
            .then(function (data) {
                renderVisits(icao, data.visits, visitsEl, true);
            })
            .catch(function (e) {
                console.error("adsb-history-logger: history search failed", e);
                visitsEl.innerHTML = '<div class="adsb-history-empty">history unavailable, try again</div>';
            });
    }

    function runSearch(query) {
        var list = searchEl.querySelector(".adsb-history-search-results");
        searchEl.querySelector(".adsb-history-search-visits").innerHTML = "";
        query = query.trim();
        if (query.length < 2) {
            list.innerHTML = '<div class="adsb-history-empty">type at least 2 characters</div>';
            return;
        }
        list.innerHTML = '<div class="adsb-history-loading">searching...</div>';
        fetch(API_BASE + "lookup?q=" + encodeURIComponent(query))
            .then(function (resp) {
                if (!resp.ok) throw new Error("lookup failed");
                return resp.json();
            })
            .then(function (data) { renderSearchResults(data.results); })
            .catch(function (e) {
                console.error("adsb-history-logger: lookup failed", e);
                list.innerHTML = '<div class="adsb-history-empty">search unavailable, try again</div>';
            });
    }

    function initSearch() {
        searchEl = document.getElementById("adsb_history_search");
        if (!searchEl) return;
        searchEl.innerHTML =
            '<form class="adsb-history-search-form">' +
            '<div class="infoBlockTitleText">History search (all logged aircraft):</div>' +
            '<input type="text" class="searchInput adsb-history-search-input" maxlength="64"' +
            ' title="Hex ID, callsign, registration, type, operator, or owner -- includes aircraft no longer on the map">' +
            '<button class="formButton" type="submit">Search</button>' +
            '<button class="formButton adsb-history-search-clear" type="button">Clear</button>' +
            "</form>" +
            '<div class="adsb-history-search-results"></div>' +
            '<div class="adsb-history-search-visits"></div>';

        var form = searchEl.querySelector("form");
        var input = searchEl.querySelector("input");
        form.addEventListener("submit", function (ev) {
            ev.preventDefault();
            runSearch(input.value);
        });
        searchEl.querySelector(".adsb-history-search-clear").addEventListener("click", function () {
            input.value = "";
            searchEl.querySelector(".adsb-history-search-results").innerHTML = "";
            searchEl.querySelector(".adsb-history-search-visits").innerHTML = "";
            clearTrack();
        });
    }

    // Guarded rather than a bare call so this file can also be `require()`d
    // under Node for unit tests (see tests-js/) without needing a real
    // browser `window`.
    if (typeof window !== "undefined") {
        window.setInterval(poll, POLL_MS);
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", initSearch);
        } else {
            initSearch();
        }
    }

    // Exposes the pure logic functions for tests-js/ under Node; a no-op
    // in the browser, where `module` doesn't exist.
    if (typeof module !== "undefined" && module.exports) {
        module.exports = {
            altitudeColor: altitudeColor,
            bearing: bearing,
            arrowLineString: arrowLineString,
            escapeHtml: escapeHtml,
            describeAircraft: describeAircraft,
        };
    }
})();
