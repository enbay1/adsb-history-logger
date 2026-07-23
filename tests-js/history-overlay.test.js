// Unit tests for the pure logic in history-overlay.js: altitude->color
// mapping and direction bearing. All three real-world bugs in this file
// so far (Polygon crash, stuck-on-error panel, color mismatch) were in
// code this file exercises or adjacent to it -- this exists so the next
// one gets caught before it ships.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { altitudeColor, bearing, arrowLineString } = require("../adsb_history_logger/webui/history-overlay.js");

function withColorByAlt(cfg, fn) {
    const prev = global.ColorByAlt;
    global.ColorByAlt = cfg;
    try {
        fn();
    } finally {
        global.ColorByAlt = prev;
    }
}

test("altitudeColor: ground uses ColorByAlt.ground when available", () => {
    withColorByAlt({ ground: { h: 0, s: 0, l: 45 }, unknown: {}, air: { h: [], s: 0, l: 0 } }, () => {
        assert.equal(altitudeColor(0, true), "hsla(0, 0%, 45%, 0.9)");
    });
});

test("altitudeColor: ground falls back to a fixed color when ColorByAlt is unavailable", () => {
    withColorByAlt(undefined, () => {
        assert.equal(altitudeColor(0, true), "hsla(15, 80%, 20%, 0.9)");
    });
});

test("altitudeColor: null/undefined altitude uses ColorByAlt.unknown", () => {
    withColorByAlt({ ground: {}, unknown: { h: 10, s: 20, l: 30 }, air: { h: [], s: 0, l: 0 } }, () => {
        assert.equal(altitudeColor(null, false), "hsla(10, 20%, 30%, 0.9)");
        assert.equal(altitudeColor(undefined, false), "hsla(10, 20%, 30%, 0.9)");
    });
});

test("altitudeColor: unknown altitude falls back when ColorByAlt is unavailable", () => {
    withColorByAlt(undefined, () => {
        assert.equal(altitudeColor(null, false), "hsla(0, 0%, 40%, 0.9)");
    });
});

test("altitudeColor: altitude at or below the first breakpoint uses its hue", () => {
    const cfg = { ground: {}, unknown: {}, air: { h: [{ alt: 2000, val: 20 }, { alt: 10000, val: 140 }], s: 85, l: 50 } };
    withColorByAlt(cfg, () => {
        assert.equal(altitudeColor(0, false), "hsla(20, 85%, 50%, 0.9)");
        assert.equal(altitudeColor(2000, false), "hsla(20, 85%, 50%, 0.9)");
    });
});

test("altitudeColor: altitude at or above the last breakpoint uses its hue", () => {
    const cfg = { ground: {}, unknown: {}, air: { h: [{ alt: 2000, val: 20 }, { alt: 10000, val: 140 }], s: 85, l: 50 } };
    withColorByAlt(cfg, () => {
        assert.equal(altitudeColor(50000, false), "hsla(140, 85%, 50%, 0.9)");
    });
});

test("altitudeColor: interpolates hue linearly between breakpoints", () => {
    const cfg = { ground: {}, unknown: {}, air: { h: [{ alt: 2000, val: 20 }, { alt: 10000, val: 140 }], s: 85, l: 50 } };
    withColorByAlt(cfg, () => {
        // halfway between 2000 (hue 20) and 10000 (hue 140) -> hue 80
        assert.equal(altitudeColor(6000, false), "hsla(80, 85%, 50%, 0.9)");
    });
});

test("altitudeColor: uses tar1090's live saturation/lightness, not hardcoded ones", () => {
    // This is the exact bug reported against v0.3.1: a hardcoded copy of
    // stock SkyAware's s/l values didn't match this install's actual
    // (customized) tar1090 config.
    const cfg = { ground: {}, unknown: {}, air: { h: [{ alt: 2000, val: 20 }, { alt: 10000, val: 140 }], s: 88, l: 44 } };
    withColorByAlt(cfg, () => {
        assert.equal(altitudeColor(2000, false), "hsla(20, 88%, 44%, 0.9)");
    });
});

test("altitudeColor: falls back to built-in breakpoints when ColorByAlt is unavailable", () => {
    withColorByAlt(undefined, () => {
        assert.equal(altitudeColor(2000, false), "hsla(20, 85%, 50%, 0.9)");
        assert.equal(altitudeColor(40000, false), "hsla(300, 85%, 50%, 0.9)");
    });
});

test("altitudeColor: delegates to tar1090's own window.altitudeColor when present, for byte-identical live-track colors", () => {
    // tar1090 (planeObject_*.js) does baro adjustment, quantized rounding,
    // and h/s/l clamping our own fallback math doesn't replicate -- when
    // embedded in tar1090, we must defer to its function rather than a
    // parallel reimplementation that can silently drift out of sync.
    const prevWindow = global.window;
    global.window = {
        altitudeColor: function (alt) {
            assert.equal(alt, 6000);
            return [99, 77, 33];
        },
    };
    try {
        assert.equal(altitudeColor(6000, false), "hsla(99, 77%, 33%, 0.9)");
    } finally {
        global.window = prevWindow;
    }
});

test("altitudeColor: passes the 'ground' sentinel string to window.altitudeColor when onGround is true", () => {
    const prevWindow = global.window;
    global.window = {
        altitudeColor: function (alt) {
            assert.equal(alt, "ground");
            return [0, 0, 45];
        },
    };
    try {
        assert.equal(altitudeColor(0, true), "hsla(0, 0%, 45%, 0.9)");
    } finally {
        global.window = prevWindow;
    }
});

test("bearing: due north is ~0 radians", () => {
    assert.ok(Math.abs(bearing(0, 0, 0, 1)) < 1e-9);
});

test("bearing: due east is ~pi/2 radians", () => {
    assert.ok(Math.abs(bearing(0, 0, 1, 0) - Math.PI / 2) < 1e-9);
});

test("bearing: due west is ~-pi/2 radians", () => {
    assert.ok(Math.abs(bearing(0, 0, -1, 0) + Math.PI / 2) < 1e-9);
});

test("bearing: due south is ~pi or -pi radians", () => {
    const b = bearing(0, 0, 0, -1);
    assert.ok(Math.abs(Math.abs(b) - Math.PI) < 1e-9);
});

test("arrowLineString: rotates a north-pointing tip toward the given bearing", () => {
    // Fake just enough of the OL API surface: capture the coordinates
    // instead of depending on the real library.
    global.ol = { geom: { LineString: function (points) { return { points: points }; } } };
    try {
        const size = 100;
        const geom = arrowLineString([0, 0], Math.PI / 2, size); // pointing east
        const tip = geom.points[1]; // [left, tip, right]
        assert.ok(Math.abs(tip[0] - size * 0.6) < 1e-6, "tip x should move east");
        assert.ok(Math.abs(tip[1]) < 1e-6, "tip y should stay ~0 when pointing due east");
    } finally {
        delete global.ol;
    }
});
