"""The calibration ladder as geometry on the exposure plane: where the strips go, the tests that every strip holds and how they are laid out, the time written on a
strip, and the mask of every step of the file. Printer-independent: coordinates are millimetres on the plane seen from above, x from the left and y from the BACK (the top
of the picture, as the page draws it), and the pixel grid is a parameter.

THIS IS THE LAYOUT OF `js/ladder.js`, number for number (the strips, the tests, how they are packed into rows, the size and place of the time): a test runs both with Node and
compares them. What the two do not share is the shape of the letters of the time (the page draws it with the font of the browser, the file with the font that Pillow carries inside itself).

A ladder is a set of strips side by side, the first on the left; the strip k is lit for k times the time of the first one: step i of the file opens the strips from i on
(see `ladder_step_masks`). A strip holds, under its time, the tests the person switched on: blocks of copper that are laid out in rows (see `strip_drawing`).
"""
import math
from functools import lru_cache

import numpy as np
import shapely
from PIL import Image, ImageDraw, ImageFont, features
from shapely.geometry import Point, box

from .raster import Grid, binarize, coverage

TESTS = ("lines_v", "lines_h", "gaps", "soic8", "fine", "passives", "rings")       # in the order they are laid out
STRIP_GAP = 1.0                                                                       # mm of dark between two strips
HEAD, FOOT, MARGIN, GAP_X, GAP_Y = 9.0, 0.8, 0.3, 0.8, (1.2, 3.5)
LABEL_Y = 6.2                                                                         # mm from the back: the baseline of the time
LABEL_MAX_MM = 4.4
LABEL_STROKE = 0.022                                                                  # of the height of the letters, on each side: the font Pillow carries is a light one, and a letter on a board has to be a good thick line


# ---- the tests: pieces of copper, each drawn from its own corner (0, 0), x to the right and y down. A shape is {"r": [x, y, w, h]} (a rectangle),
# {"ring": [cx, cy, outer, inner]} (a pad with a hole: the two diameters) or {"dot": [cx, cy, r]} (a round pad).
def _r(x, y, w, h):
    return {"r": [x, y, w, h]}


def _fine():
    out = []
    for n, pitch, w, y in ((8, 0.65, 0.35, 0), (12, 0.5, 0.28, 2.5), (14, 0.4, 0.2, 5)):
        x0 = (5.78 - ((n - 1) * pitch + w)) / 2
        out.extend(_r(x0 + k * pitch, y, w, 1.3) for k in range(n))
    return out


_DEFS = {
    "lines_v": (0.35, [{"s": [_r(k * 2 * w, 0, w, 8.5) for k in range(5)]} for w in (0.10, 0.15, 0.20, 0.30, 0.40)]),
    "lines_h": (0.25, [{"s": [_r(0, k * 2 * w, 2.2, w) for k in range(5)]} for w in (0.10, 0.15, 0.20, 0.30, 0.40)]),
    "gaps": (0.8, [{"s": [_r(0, 0, 1.1, 3.6), _r(1.1 + g, 0, 1.1, 3.6)]} for g in (0.10, 0.15, 0.20, 0.30)]),
    "soic8": (0.8, [{"s": [s for k in range(4) for s in (_r(0, k * 1.27, 1.5, 0.6), _r(5.4, k * 1.27, 1.5, 0.6))]}]),
    "fine": (0.8, [{"s": _fine()}]),
    "passives": (0.8, [{"s": [_r(0, 0, 1.2, 1.4), _r(2.2, 0, 1.2, 1.4)]}, {"s": [_r(0, 0, 0.9, 0.95), _r(1.7, 0, 0.9, 0.95)]},
                       {"s": [_r(0, 0, 0.6, 0.6), _r(1.1, 0, 0.6, 0.6)]}]),
    "rings": (0.8, [{"s": [{"ring": [1, 1, 2.0, 0.8]}], "h": 2}, {"s": [{"ring": [0.8, 1, 1.6, 0.6]}], "h": 2}, {"s": [{"ring": [0.6, 1, 1.2, 0.5]}], "h": 2},
                    {"s": [{"dot": [0.4, 1, 0.4]}], "h": 2}]),
}


def _bounds(s):
    if "r" in s:
        x, y, w, h = s["r"]
        return [x, y, x + w, y + h]
    if "ring" in s:
        cx, cy, o, _ = s["ring"]
        return [cx - o / 2, cy - o / 2, cx + o / 2, cy + o / 2]
    cx, cy, r = s["dot"]
    return [cx - r, cy - r, cx + r, cy + r]


def _moved(s, dx, dy):
    if "r" in s:
        x, y, w, h = s["r"]
        return {"r": [x + dx, y + dy, w, h]}
    if "ring" in s:
        cx, cy, o, i = s["ring"]
        return {"ring": [cx + dx, cy + dy, o, i]}
    cx, cy, r = s["dot"]
    return {"dot": [cx + dx, cy + dy, r]}


# each test with its pieces and their sizes (the box of their shapes, from (0, 0))
BLOCK = {}
for _id in TESTS:
    _gx, _pieces = _DEFS[_id]
    BLOCK[_id] = {"id": _id, "gx": _gx, "pieces": [
        {"shapes": p["s"], "w": max(_bounds(s)[2] for s in p["s"]), "h": p["h"] if "h" in p else max(_bounds(s)[3] for s in p["s"])} for p in _pieces]}


def strip_drawing(width, height, tests):
    """How the tests of a strip are laid out. The time takes the top (`HEAD` mm from the back); under it the tests go in the order of TESTS. A test is put at the end of the last
    row if all of it fits there (`GAP_X` mm after the one before); if not, on a new row, and its pieces wrap onto more rows when they do not fit the width (`MARGIN` mm are kept
    free at each side). A piece wider than the strip has no room; rows that do not fit the height (with at least `GAP_Y[0]` between them) are left out from the last one on; the
    tests that lost a piece are reported. Every row is centred, with its pieces at the top, and the rows are spread over the height with the gap between them growing to `GAP_Y[1]`.
    Returns {"shapes", "dropped", "rows"}."""
    inner, avail, rows, dropped, eps = width - 2 * MARGIN, height - HEAD - FOOT, [], set(), 1e-9
    for tid in [t for t in TESTS if t in tests]:
        b, pieces = BLOCK[tid], []
        for p in b["pieces"]:
            if p["w"] > inner + eps:
                dropped.add(tid)
            else:
                pieces.append(p)
        if not pieces:
            continue
        total = sum(p["w"] for p in pieces) + (len(pieces) - 1) * b["gx"]
        row = rows[-1] if rows else None
        if not (row and row["w"] + GAP_X + total <= inner + eps):             # all of it at the end of the last row, or on a new one
            row = None
        for p in pieces:
            if row and row["w"] + (b["gx"] if row["last"] == tid else GAP_X) + p["w"] > inner + eps:     # (this piece does not fit the row any more)
                row = None
            if row is None:
                row = {"items": [], "w": 0, "h": 0, "last": None}
                rows.append(row)
            gap = (b["gx"] if row["last"] == tid else GAP_X) if row["items"] else 0
            row["items"].append({"id": tid, "p": p, "dx": row["w"] + gap})
            row["w"] += gap + p["w"]
            row["h"] = max(row["h"], p["h"])
            row["last"] = tid

    def taken(n):
        return sum(r["h"] for r in rows[:n]) + max(0, n - 1) * GAP_Y[0]

    while rows and taken(len(rows)) > avail + eps:
        for it in rows.pop()["items"]:
            dropped.add(it["id"])
    total_h = sum(r["h"] for r in rows)
    gap = min(GAP_Y[1], max(GAP_Y[0], (avail - total_h) / (len(rows) - 1))) if len(rows) > 1 else 0
    shapes, placed, y = [], [], HEAD
    for row in rows:
        x0 = (width - row["w"]) / 2
        for it in row["items"]:
            for sh in it["p"]["shapes"]:
                shapes.append(_moved(sh, x0 + it["dx"], y))
        ids = []
        for it in row["items"]:
            if it["id"] not in ids:
                ids.append(it["id"])
        placed.append({"y": y, "h": row["h"], "ids": ids})
        y += row["h"] + gap
    return {"shapes": shapes, "dropped": [t for t in TESTS if t in dropped], "rows": placed}


def label_size(text, width=13.0):
    """The size (mm) of the time written at the top of a strip: it shrinks with the number of characters (and with a narrow strip) so that it stays inside it."""
    return min(LABEL_MAX_MM, (width - 0.5) / (len(text) * 0.6))


def label_font_available():
    """Whether the time of a strip can be written. The font is the one Pillow carries inside itself (Aileron Regular: there is no file to install); cutting it to a size needs
    FreeType, which the wheels of Pillow have, and without it Pillow would give a small fixed font that is not the size asked for."""
    return features.check("freetype2")


@lru_cache(maxsize=64)
def _label_font(px):
    return ImageFont.load_default(size=px)


def _write_label(img, xy, text, px):
    """The text, centred on x and with the baseline on y, in white; thickened (`LABEL_STROKE`) so that it comes out as bold as the DejaVu it replaced."""
    ImageDraw.Draw(img).text(xy, text, fill=255, font=_label_font(px), anchor="ms", stroke_width=max(1, round(px * LABEL_STROKE)), stroke_fill=255)


def seconds_text(n):
    """A time as it is written on a strip: no decimals for a whole number, else one (the point, whatever the language of the page: the file is not translated)."""
    return f"{n:.0f}" if float(n).is_integer() else f"{n:.1f}"


def strip_label(total_s):
    return f"{seconds_text(total_s)} s"


def ladder_layout(bands, width, height, step, plane_w, plane_h, tests):
    """Where the strips are on the plane: centred both ways. `fits` says whether all of it is inside the plane (a ladder is a piece of copper: it has to fit the board)."""
    pitch = width + STRIP_GAP
    total_w = (bands - 1) * pitch + width
    x0, y0 = (plane_w - total_w) / 2, (plane_h - height) / 2
    strips = [{"i": i, "x": x0 + i * pitch, "y": y0, "w": width, "h": height, "total_s": (i + 1) * step} for i in range(bands)]
    return {"x0": x0, "y0": y0, "width": total_w, "height": height, "pitch": pitch, "strips": strips, "fits": x0 >= -1e-9 and y0 >= -1e-9,
            "drawing": strip_drawing(width, height, tests)}


# ---- the pixels --------------------------------------------------------------------------------------------------------------
def _polygon(s):
    if "r" in s:
        x, y, w, h = s["r"]
        return box(x, y, x + w, y + h)
    if "ring" in s:
        cx, cy, o, i = s["ring"]
        return Point(cx, cy).buffer(o / 2, quad_segs=32).difference(Point(cx, cy).buffer(i / 2, quad_segs=32))
    cx, cy, r = s["dot"]
    return Point(cx, cy).buffer(r, quad_segs=32)


def _window(grid, x_mm, y_mm, w_mm, h_mm, pad=2):
    """The part of the grid that holds a box (picture mm: x from the left, y from the back), a little larger, aligned to the pixels, so that what is drawn in it has exactly the
    pixels it would have on the whole grid. Returns (the sub-grid, (row0, row1, col0, col1))."""
    p = grid.pitch
    c0, c1 = max(0, math.floor(x_mm / p) - pad), min(grid.width, math.ceil((x_mm + w_mm) / p) + pad)
    r0, r1 = max(0, math.floor(y_mm / p) - pad), min(grid.height, math.ceil((y_mm + h_mm) / p) + pad)
    if c1 <= c0 or r1 <= r0:
        return None, None
    top = grid.oy + grid.height * p
    return Grid(c1 - c0, r1 - r0, p, ox=grid.ox + c0 * p, oy=top - r1 * p), (r0, r1, c0, c1)


def _to_plane(geom, grid):
    top = grid.oy + grid.height * grid.pitch
    return shapely.transform(geom, lambda c: np.column_stack([grid.ox + c[:, 0], top - c[:, 1]]))        # y from the back -> y up


def ladder_step_masks(layout, grid, *, polarity, mirror, supersample=16):
    """The mask of every step of the file: step i lights the strips from i on, so that the strip k is lit by k + 1 steps (k + 1 times the time of one). `layout` is `ladder_layout`'s.
    Positive resist: the strip is lit except where the copper stays (the tests and the time); negative: only the copper is lit. The ladder turned over (`mirror`) is
    flipped left to right as a whole, the time too. Every mask is a bool array (grid.height, grid.width), row 0 at the back."""
    font_px = lambda text, w: label_size(text, w) / grid.pitch
    drawing = shapely.union_all([_polygon(s) for s in layout["drawing"]["shapes"]]) if layout["drawing"]["shapes"] else None
    lit = []
    for strip in layout["strips"]:
        sub, at = _window(grid, strip["x"], strip["y"], strip["w"], strip["h"])
        if sub is None:                                                                  # all of it is outside the plane
            lit.append(None)
            continue
        r0, r1, c0, c1 = at
        material = np.zeros((r1 - r0, c1 - c0), bool)
        if drawing is not None:
            material |= binarize(coverage(_to_plane(shapely.affinity.translate(drawing, strip["x"], strip["y"]), grid), sub, supersample))
        text = strip_label(strip["total_s"])
        img = Image.new("L", (c1 - c0, r1 - r0), 0)
        _write_label(img, ((strip["x"] + strip["w"] / 2 - c0 * grid.pitch) / grid.pitch, (strip["y"] + LABEL_Y - r0 * grid.pitch) / grid.pitch), text, font_px(text, strip["w"]))
        material |= np.asarray(img) >= 128
        if polarity == "negative":
            lit.append((at, material))
        else:
            field = binarize(coverage(_to_plane(box(strip["x"], strip["y"], strip["x"] + strip["w"], strip["y"] + strip["h"]), grid), sub, supersample))
            lit.append((at, field & ~material))
    masks, acc = [None] * len(lit), np.zeros((grid.height, grid.width), bool)
    for j in reversed(range(len(lit))):                                                # step j lights the strips j.., so the masks are built from the last strip back
        if lit[j] is not None:
            (r0, r1, c0, c1), part = lit[j]
            acc[r0:r1, c0:c1] |= part
        masks[j] = np.ascontiguousarray(acc[:, ::-1]) if mirror else acc.copy()               # (a copy: the next step adds to `acc`)
    return masks
