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

    // Reads tar1090's own live ColorByAlt config (declared globally by its
    // config.js) rather than keeping a hardcoded copy, so track colors
    // always match whatever the live map is actually drawing -- including
    // if it's customized later.
    var FALLBACK_BREAKPOINTS = [[2000, 20], [10000, 140], [40000, 300]];

    function altitudeColor(altitude, onGround) {
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

    function renderTrack(geojson) {
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
                    geometry: arrowLineString(ol.proj.fromLonLat(mid), brng, 250),
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
    }

    function drawTrack(icao, visit) {
        clearTrack();
        var url = API_BASE + "track/" + icao + (visit ? "?visit=" + visit : "");
        fetch(url)
            .then(function (resp) {
                if (!resp.ok) throw new Error("track fetch failed");
                return resp.json();
            })
            .then(renderTrack)
            .catch(function (e) {
                console.error("adsb-history-logger: failed to draw track", e);
            });
    }

    function renderVisits(icao, visits) {
        var el = ensurePanel();
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
                drawTrack(icao, this.getAttribute("data-visit"));
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
                renderVisits(icao, data.visits);
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

    // Guarded rather than a bare call so this file can also be `require()`d
    // under Node for unit tests (see tests-js/) without needing a real
    // browser `window`.
    if (typeof window !== "undefined") {
        window.setInterval(poll, POLL_MS);
    }

    // Exposes the pure logic functions for tests-js/ under Node; a no-op
    // in the browser, where `module` doesn't exist.
    if (typeof module !== "undefined" && module.exports) {
        module.exports = { altitudeColor: altitudeColor, bearing: bearing, arrowLineString: arrowLineString };
    }
})();
