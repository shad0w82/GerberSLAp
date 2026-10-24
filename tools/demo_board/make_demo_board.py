#!/usr/bin/env python3
"""Writes the demo board of the documentation: an invented 40 x 28 mm board (a small 555-style blinker: one SOIC-8,
three 0805 parts, a two-pin header, a test point), as Gerber X2 + Excellon files in a zip. It is made up for the manual:
it is not a validated design and it was never etched.

    .venv/bin/python tools/demo_board/make_demo_board.py [output.zip]     (default: docs/assets/GerberSLAp-demo.zip)

The zip is deterministic (same bytes every time) and the file names follow the usual CAD pattern, so the app recognises it by itself.
`check()` verifies that copper of different nets never touches and that silkscreen keeps away from the pads."""
import io
import math
import sys
import zipfile
from pathlib import Path

NAME = "GerberSLAp-demo"
OX, OY = 10.0, 10.0                  # the board sits at (10..50, 10..38) mm, like a file from a CAD program
W, H = 40.0, 28.0                    # board size
R = 2.0                              # corner radius
TRACE = 0.30                         # copper trace width (mm)
SILK = 0.15                          # silkscreen line width (mm)

# ---- the design (coordinates relative to the lower-left corner of the board, mm) --------------------------------------
SMD = {                              # name: (x, y, width, height, net)
    "U1-1": (19.3, 15.905, 1.55, 0.6, "GND"), "U1-2": (19.3, 14.635, 1.55, 0.6, "TRIG"),
    "U1-3": (19.3, 13.365, 1.55, 0.6, "OUT"), "U1-4": (19.3, 12.095, 1.55, 0.6, "VCC"),
    "U1-5": (24.7, 12.095, 1.55, 0.6, "CTRL"), "U1-6": (24.7, 13.365, 1.55, 0.6, "THR"),
    "U1-7": (24.7, 14.635, 1.55, 0.6, "DIS"), "U1-8": (24.7, 15.905, 1.55, 0.6, "VCC"),
    "R1-1": (12.0875, 19.0, 1.025, 1.4, "VCC"), "R1-2": (13.9125, 19.0, 1.025, 1.4, "DISR"),
    "R2-1": (12.0875, 9.0, 1.025, 1.4, "DISR"), "R2-2": (13.9125, 9.0, 1.025, 1.4, "THR"),
    "C1-1": (30.0875, 9.0, 1.025, 1.4, "THR"), "C1-2": (31.9125, 9.0, 1.025, 1.4, "GND"),
    "D1-1": (30.0875, 19.0, 1.025, 1.4, "OUT"), "D1-2": (31.9125, 19.0, 1.025, 1.4, "GND"),
}
PTH = {                              # name: (x, y, pad diameter, drill, net)   (plated: copper ring on both sides)
    "J1-1": (4.0, 15.27, 1.7, 1.0, "VCC"), "J1-2": (4.0, 12.73, 1.7, 1.0, "GND"), "TP1": (35.5, 9.0, 1.8, 1.0, "GND"),
}
VIAS = {"V1": (17.2, 15.905, 0.8, 0.4, "GND")}
NPTH = [(3.5, 3.5), (36.5, 3.5), (3.5, 24.5), (36.5, 24.5)]     # mounting holes, 2.2 mm
NPTH_D = 2.2
F_TRACES = [                         # (net, [points])
    ("VCC", [(4.0, 15.27), (8.0, 15.27), (8.0, 22.0), (26.8, 22.0), (26.8, 15.905), (24.7, 15.905)]),
    ("VCC", [(8.0, 19.0), (12.0875, 19.0)]),
    ("VCC", [(19.3, 12.095), (16.2, 12.095), (16.2, 22.0)]),
    ("GND", [(19.3, 15.905), (17.2, 15.905)]),
    ("GND", [(31.9125, 9.0), (35.5, 9.0)]),
    ("GND", [(31.9125, 19.0), (35.5, 19.0), (35.5, 9.0)]),
    ("DISR", [(13.9125, 19.0), (15.0, 19.0)]),
    ("THR", [(13.9125, 9.0), (15.0, 9.0)]),
]
B_TRACES = [("GND", [(4.0, 12.73), (4.0, 6.0), (35.5, 6.0), (35.5, 9.0)]), ("GND", [(17.2, 15.905), (17.2, 6.0)])]

# ---- a small stroke font for the silkscreen (grid 3 x 5, strokes are polylines) --------------------------------------
_P = [(0, 0), (0, 5), (2.3, 5), (3, 4.3), (3, 3.2), (2.3, 2.5), (0, 2.5)]
GLYPHS = {
    "A": [[(0, 0), (0, 3), (1.5, 5), (3, 3), (3, 0)], [(0, 2), (3, 2)]],
    "B": [[(0, 0), (0, 5), (2, 5), (3, 4), (3, 3), (2, 2.5), (0, 2.5)], [(2, 2.5), (3, 1.5), (3, 1), (2, 0), (0, 0)]],
    "C": [[(3, 4.5), (2.3, 5), (0.7, 5), (0, 4.3), (0, 0.7), (0.7, 0), (2.3, 0), (3, 0.5)]],
    "D": [[(0, 0), (0, 5), (1.8, 5), (3, 4), (3, 1), (1.8, 0), (0, 0)]],
    "E": [[(3, 5), (0, 5), (0, 0), (3, 0)], [(0, 2.5), (2.2, 2.5)]],
    "G": [[(3, 4.3), (2.3, 5), (0.7, 5), (0, 4.3), (0, 0.7), (0.7, 0), (2.3, 0), (3, 0.7), (3, 2.3), (1.6, 2.3)]],
    "J": [[(3, 5), (3, 0.7), (2.3, 0), (0.7, 0), (0, 0.7)]],
    "L": [[(0, 5), (0, 0), (3, 0)]],
    "M": [[(0, 0), (0, 5), (1.5, 2.8), (3, 5), (3, 0)]],
    "N": [[(0, 0), (0, 5), (3, 0), (3, 5)]],
    "O": [[(0.7, 0), (0, 0.7), (0, 4.3), (0.7, 5), (2.3, 5), (3, 4.3), (3, 0.7), (2.3, 0), (0.7, 0)]],
    "P": [_P],
    "R": [_P, [(1.5, 2.5), (3, 0)]],
    "S": [[(3, 4.3), (2.3, 5), (0.7, 5), (0, 4.3), (0, 3.4), (0.7, 2.5), (2.3, 2.5), (3, 1.6), (3, 0.7), (2.3, 0), (0.7, 0), (0, 0.7)]],
    "T": [[(0, 5), (3, 5)], [(1.5, 5), (1.5, 0)]],
    "U": [[(0, 5), (0, 0.7), (0.7, 0), (2.3, 0), (3, 0.7), (3, 5)]],
    "V": [[(0, 5), (1.5, 0), (3, 5)]],
    "1": [[(0.5, 4), (1.5, 5), (1.5, 0)], [(0.5, 0), (2.5, 0)]],
    "2": [[(0, 4.3), (0.7, 5), (2.3, 5), (3, 4.3), (3, 3.4), (0, 0), (3, 0)]],
    "+": [[(0.5, 2.5), (2.5, 2.5)], [(1.5, 1.5), (1.5, 3.5)]],
    "-": [[(0.5, 2.5), (2.5, 2.5)]],
}


def text_strokes(text, x, y, size=1.1, spacing=0.9):
    """Polylines (mm, board coordinates) of `text`, lower-left at (x, y); `size` is the height of a letter."""
    s = size / 5.0
    out, cx = [], x
    for ch in text:
        for stroke in GLYPHS.get(ch, []):
            out.append([(cx + px * s, y + py * s) for px, py in stroke])
        cx += (3 + spacing) * s
    return out


def text_width(text, size=1.1, spacing=0.9):
    return len(text) * (3 + spacing) * size / 5.0 - spacing * size / 5.0


def silk_items():
    """Silkscreen: part outlines (kept off the pads), reference texts, pin-1 mark, a label."""
    lines = []
    def rect(x0, y0, x1, y1): return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    lines.append(rect(17.9, 10.9, 26.1, 17.1))                                # U1 body outline (outside the pad columns)
    for cx, cy in ((13.0, 19.0), (13.0, 9.0), (31.0, 9.0), (31.0, 19.0)):    # 0805 outlines above and below the pads
        lines.append([(cx - 1.2, cy + 1.05), (cx + 1.2, cy + 1.05)])
        lines.append([(cx - 1.2, cy - 1.05), (cx + 1.2, cy - 1.05)])
    lines += text_strokes("U1", 21.6, 17.9) + text_strokes("R1", 12.2, 20.6) + text_strokes("R2", 12.2, 6.8)
    lines += text_strokes("C1", 30.2, 6.8) + text_strokes("D1", 30.2, 20.6)
    lines += text_strokes("J1", 6.2, 17.4) + text_strokes("+", 6.0, 14.7, 1.0) + text_strokes("-", 6.0, 12.1, 1.0)
    lines += text_strokes("GERBERSLAP", 11.0, 2.2, 1.6)
    lines += text_strokes("DEMO", 29.0, 24.6, 1.6)
    return lines


PIN1 = (18.35, 16.75)                 # a small dot next to pin 1 of U1 (silkscreen flash, 0.5 mm)


# ---- Gerber / Excellon writing -----------------------------------------------------------------------------------------
def _u(v): return int(round(v * 1e6))
def _at(x, y): return f"X{_u(x + OX)}Y{_u(y + OY)}"


class Aps:
    """Aperture table: `get('C', d)`, `get('R', w, h)` give a D-code and collect the %ADD% lines."""
    def __init__(self): self.codes, self.lines = {}, []
    def get(self, kind, *dims):
        key = (kind,) + dims
        if key not in self.codes:
            n = 10 + len(self.codes)
            self.codes[key] = n
            self.lines.append(f"%ADD{n}{kind},{'X'.join(f'{d:.6f}' for d in dims)}*%")
        return f"D{self.codes[key]}*"


def _gerber(function, polarity, aps, body):
    head = ["%TF.GenerationSoftware,GerberSLAp,demo board generator,1*%", f"%TF.FileFunction,{function}*%",
            f"%TF.FilePolarity,{polarity}*%", "%FSLAX46Y46*%", "%MOMM*%", *aps.lines, "G75*", "G01*", "%LPD*%"]
    return "\n".join(head + body + ["M02*", ""])


def _draw(aps, width, pts):
    out = [aps.get("C", width), f"{_at(*pts[0])}D02*"]
    out += [f"{_at(*p)}D01*" for p in pts[1:]]
    return out


def _flash_c(aps, d, x, y): return [aps.get("C", d), f"{_at(x, y)}D03*"]
def _flash_r(aps, w, h, x, y): return [aps.get("R", w, h), f"{_at(x, y)}D03*"]


def copper(side):
    aps, body = Aps(), []
    traces = F_TRACES if side == "F" else B_TRACES
    for _, pts in traces:
        body += _draw(aps, TRACE, pts)
    if side == "F":
        for x, y, w, h, _ in SMD.values(): body += _flash_r(aps, w, h, x, y)
    for x, y, d, _, _ in PTH.values(): body += _flash_c(aps, d, x, y)
    for x, y, d, _, _ in VIAS.values(): body += _flash_c(aps, d, x, y)
    return _gerber("Copper,L1,Top" if side == "F" else "Copper,L2,Bot", "Positive", aps, body)


def mask():
    aps, body = Aps(), []
    for x, y, w, h, _ in SMD.values(): body += _flash_r(aps, w + 0.1, h + 0.1, x, y)        # 0.05 mm of margin on each side
    for x, y, d, _, _ in PTH.values(): body += _flash_c(aps, d + 0.1, x, y)
    return _gerber("Soldermask,Top", "Negative", aps, body)                               # KiCad writes masks as the openings


def silkscreen():
    aps, body = Aps(), []
    for pts in silk_items():
        body += _draw(aps, SILK, pts)
    body += _flash_c(aps, 0.5, *PIN1)
    return _gerber("Legend,Top", "Positive", aps, body)


def edge():
    aps = Aps()
    d = aps.get("C", 0.1)
    def arc(sx, sy, ex, ey, cx, cy): return ["G03*", f"{_at(ex, ey)}I{_u(cx - sx)}J{_u(cy - sy)}D01*", "G01*"]
    body = [d, f"{_at(R, 0)}D02*", f"{_at(W - R, 0)}D01*", *arc(W - R, 0, W, R, W - R, R), f"{_at(W, H - R)}D01*",
            *arc(W, H - R, W - R, H, W - R, H - R), f"{_at(R, H)}D01*", *arc(R, H, 0, H - R, R, H - R),
            f"{_at(0, R)}D01*", *arc(0, R, R, 0, R, R)]
    return _gerber("Profile,NP", "Positive", aps, body)


def excellon(function, tools, holes):
    lines = ["M48", "; DRILL file {GerberSLAp demo board generator}", "; FORMAT={-:-/ absolute / metric / decimal}",
             f"; #@! TF.FileFunction,{function}", "FMAT,2", "METRIC"]
    lines += [f"T{n}C{d:.3f}" for n, d in tools.items()]
    lines += ["%", "G90", "G05"]
    for n in tools:
        lines.append(f"T{n}")
        lines += [f"X{x + OX:.3f}Y{y + OY:.3f}" for t, x, y in holes if t == n]
    return "\n".join(lines + ["T0", "M30", ""])


def build_files():
    plated = [(1, x, y) for x, y, _, d, _ in PTH.values() if d == 1.0] + [(2, x, y) for x, y, *_ in VIAS.values()]
    return {
        f"{NAME}-F_Cu.gbr": copper("F"), f"{NAME}-B_Cu.gbr": copper("B"), f"{NAME}-F_Mask.gbr": mask(),
        f"{NAME}-F_Silkscreen.gbr": silkscreen(), f"{NAME}-Edge_Cuts.gbr": edge(),
        f"{NAME}-PTH.drl": excellon("Plated,1,2,PTH", {1: 1.0, 2: 0.4}, plated),
        f"{NAME}-NPTH.drl": excellon("NonPlated,1,2,NPTH", {1: NPTH_D}, [(1, x, y) for x, y in NPTH]),
    }


def build_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in sorted(build_files().items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, text.encode("utf-8"))
    return buf.getvalue()


# ---- self-check ---------------------------------------------------------------------------------------------------------
def check(min_clearance=0.2):
    """Raises AssertionError if copper of two nets comes closer than `min_clearance`, or silkscreen touches a pad."""
    from shapely.geometry import LineString, Point, box
    def pad_geoms():
        for n, (x, y, w, h, net) in SMD.items(): yield "F", net, n, box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)
        for n, (x, y, d, _, net) in PTH.items():
            for side in "FB": yield side, net, n, Point(x, y).buffer(d / 2)
        for n, (x, y, d, _, net) in VIAS.items():
            for side in "FB": yield side, net, n, Point(x, y).buffer(d / 2)
    items = list(pad_geoms())
    for side, traces in (("F", F_TRACES), ("B", B_TRACES)):
        for i, (net, pts) in enumerate(traces): items.append((side, net, f"trace {side}{i}", LineString(pts).buffer(TRACE / 2)))
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a[0] == b[0] and a[1] != b[1]:
                assert a[3].distance(b[3]) >= min_clearance, f"{a[2]} ({a[1]}) too close to {b[2]} ({b[1]}): {a[3].distance(b[3]):.2f} mm"
    silk = [LineString(p).buffer(SILK / 2) for p in silk_items()] + [Point(PIN1).buffer(0.25)]
    for s in silk:
        for side, net, name, g in items:
            if side == "F" and name in {**SMD, **PTH, **VIAS}:
                assert s.distance(g) >= 0.15, f"silkscreen touches {name}: {s.distance(g):.2f} mm"
    outline = box(0, 0, W, H)
    for _, _, name, g in items:
        assert outline.buffer(-0.3).contains(g), f"{name} is too close to the board edge"


if __name__ == "__main__":
    check()
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "docs" / "assets" / f"{NAME}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build_zip())
    print(f"wrote {out} ({out.stat().st_size} bytes)")
