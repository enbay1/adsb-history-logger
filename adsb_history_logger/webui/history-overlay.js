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

    var API_BASE = "history-api/";
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

    function drawTrack(icao, visit) {
        clearTrack();
        var url = API_BASE + "track/" + icao + (visit ? "?visit=" + visit : "");
        trackLayer = new ol.layer.Vector({
            name: "adsbHistoryTrack",
            title: "ADS-B history track",
            zIndex: 250,
            source: new ol.source.Vector({
                url: url,
                format: new ol.format.GeoJSON({
                    defaultDataProjection: "EPSG:4326",
                    projection: "EPSG:3857",
                }),
            }),
            style: new ol.style.Style({
                stroke: new ol.style.Stroke({
                    color: "rgba(255, 80, 220, 0.9)",
                    width: 3,
                }),
            }),
        });
        OLMap.addLayer(trackLayer);
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
            .catch(function () {
                el.innerHTML = '<div class="adsb-history-empty">history unavailable</div>';
            });
    }

    function poll() {
        var plane = typeof SelectedPlane !== "undefined" ? SelectedPlane : null;
        var icao = plane ? plane.icao : null;

        if (icao !== lastIcao) {
            lastIcao = icao;
            clearTrack();
            if (icao) {
                loadHistory(icao);
            } else {
                var el = ensurePanel();
                if (el) el.innerHTML = "";
            }
        }
    }

    window.setInterval(poll, POLL_MS);
})();
