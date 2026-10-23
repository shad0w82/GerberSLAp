#!/usr/bin/env python3
"""
Dati di prova sintetici per il rendering dei Gerber (nati nella Fase 1, passo 1).

Scrive in data/ file Gerber ed Excellon minimi, uno per ogni funzione da provare,
e in data/reference/ la geometria attesa in WKT (mm), calcolata con shapely in modo
indipendente da gerbonara e pygerber. Servirà da riferimento esatto nei passi 2, 3 e 5.

Unità: mm, formato Gerber 4.6. Tutti i file stanno nel quadrante positivo.
Fonte unica dei dati di prova: i test la usano in memoria (`TESTS`, `DRILLS`, `ROBUSTNESS`, `synth_board()`) o la
scrivono su disco con `write(cartella)`. Da riga di comando:  .venv/bin/python tests/support/testdata.py [cartella]
"""
import json
import math
import os
import sys
import zipfile

from shapely.affinity import rotate, translate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
QS = 128   # segmenti per quarto di cerchio nella geometria di riferimento


# --- scrittura Gerber / Excellon ----------------------------------------------------
def u(v): return int(round(v * 1e6))                        # mm -> intero 4.6
def at(x, y): return f"X{u(x)}Y{u(y)}"
def flash(x, y): return at(x, y) + "D03*"
def move(x, y): return at(x, y) + "D02*"
def draw(x, y): return at(x, y) + "D01*"


def arc(sx, sy, ex, ey, cx, cy, ccw=True):
    return ["G03*" if ccw else "G02*", f"{at(ex, ey)}I{u(cx - sx)}J{u(cy - sy)}D01*", "G01*"]


def region(ops): return ["G36*", *ops, "G37*"]


def gerber(function, body, apertures=(), macros=()):
    head = [f"%TF.FileFunction,{function}*%", "%FSLAX46Y46*%", "%MOMM*%",
            *macros, *apertures, "G75*", "G01*", "%LPD*%"]
    return "\n".join(head + list(body) + ["M02*", ""])


def excellon(function, tools, holes=(), slots=()):
    """tools {n: diametro}; holes [(n, x, y)]; slots [(n, x1, y1, x2, y2)]."""
    L = ["M48", "; DRILL file sintetico GerberSLAp", "; FORMAT={-:-/ absolute / metric / decimal}",
         f"; #@! TF.FileFunction,{function}", "FMAT,2", "METRIC"]
    L += [f"T{n}C{d:.3f}" for n, d in tools.items()]
    L += ["%", "G90", "G05"]
    for n in tools:
        L.append(f"T{n}")
        L += [f"X{x:.3f}Y{y:.3f}" for t, x, y in holes if t == n]
        L += [f"X{x1:.3f}Y{y1:.3f}G85X{x2:.3f}Y{y2:.3f}" for t, x1, y1, x2, y2 in slots if t == n]
    return "\n".join(L + ["T0", "M30", ""])


# --- geometria di riferimento -------------------------------------------------------
def disc(x, y, d): return Point(x, y).buffer(d / 2, quad_segs=QS)
def stroke(pts, w): return LineString(pts).buffer(w / 2, quad_segs=QS)      # tratto con punte tonde
def arc_pts(cx, cy, r, a0, a1, n=2048):
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def obround(x, y, w, h):
    if w >= h:
        return LineString([(x - (w - h) / 2, y), (x + (w - h) / 2, y)]).buffer(h / 2, quad_segs=QS)
    return LineString([(x, y - (h - w) / 2), (x, y + (h - w) / 2)]).buffer(w / 2, quad_segs=QS)


def regular_polygon(x, y, d, n, rot=0.0):
    return Polygon([(x + d / 2 * math.cos(math.radians(rot + 360 * i / n)),
                     y + d / 2 * math.sin(math.radians(rot + 360 * i / n))) for i in range(n)])


# --- macro usate (come le scrivono KiCad ed EAGLE) --------------------------------
M_ROTRECT = ["%AMRotRect*", "21,1,$1,$2,0,0,$3*%"]
M_OCT = ["%AMOct*", "4,1,8,0.5,0.2071,0.2071,0.5,-0.2071,0.5,-0.5,0.2071,-0.5,-0.2071,"
         "-0.2071,-0.5,0.2071,-0.5,0.5,-0.2071,0.5,0.2071,0*%"]
M_ROUNDRECT = [
    "%AMRoundRect*",
    "0 Rectangle with rounded corners*",
    "0 $1 Rounding radius*",
    "0 $2 $3 $4 $5 $6 $7 $8 $9 X,Y pos of 4 corners*",
    "0 Add a 4 corners polygon primitive as box body*",
    "4,1,4,$2,$3,$4,$5,$6,$7,$8,$9,$2,$3,0*",
    "0 Add four circle primitives for the rounded corners*",
    "1,1,$1+$1,$2,$3*", "1,1,$1+$1,$4,$5*", "1,1,$1+$1,$6,$7*", "1,1,$1+$1,$8,$9*",
    "0 Add four rect primitives between the rounded corners*",
    "20,1,$1+$1,$2,$3,$4,$5,0*", "20,1,$1+$1,$4,$5,$6,$7,0*",
    "20,1,$1+$1,$6,$7,$8,$9,0*", "20,1,$1+$1,$8,$9,$2,$3,0*%"]
ROUNDRECT_AP = "%ADD{n}RoundRect,0.250000X-0.800000X-0.400000X0.800000X-0.400000X0.800000X0.400000X-0.800000X0.400000X0*%"


def roundrect(x, y):    # corpo 1,6 x 0,8 con raggio 0,25 -> 2,1 x 1,3
    return translate(box(-0.8, -0.4, 0.8, 0.4).buffer(0.25, quad_segs=QS), x, y)


# --- i file di prova -----------------------------------------------------------------
TESTS = {}    # nome -> (testo Gerber, geometria dark di riferimento)


def add(name, text, geom):
    TESTS[name] = (text, geom)


# f01: regione rettangolare 80 x 50 mm
add("f01_rect_region.gbr",
    gerber("Copper,L1,Top", region([move(10, 10), draw(90, 10), draw(90, 60), draw(10, 60), draw(10, 10)])),
    box(10, 10, 90, 60))

# f02: flash di aperture standard
add("f02_flashes.gbr",
    gerber("Copper,L1,Top",
           ["D10*", flash(10, 10), "D11*", flash(20, 10), "D12*", flash(30, 10), "D13*", flash(40, 10),
            "D14*", flash(50, 10)],
           ["%ADD10C,1.000000*%", "%ADD11R,3.000000X1.500000*%", "%ADD12O,3.000000X1.000000*%",
            "%ADD13P,2.000000X6X0*%", "%ADD14C,0.100000*%"]),
    unary_union([disc(10, 10, 1.0), box(18.5, 9.25, 21.5, 10.75), obround(30, 10, 3.0, 1.0),
                 regular_polygon(40, 10, 2.0, 6), disc(50, 10, 0.1)]))

# f03: linee di larghezza nota (orizzontali) e una diagonale a 45 gradi
_w = [0.05, 0.10, 0.15, 0.20, 0.30, 0.50]
_body, _geo = [], []
for i, w in enumerate(_w):
    _body += [f"D{20 + i}*", move(10, 10 + 5 * i), draw(30, 10 + 5 * i)]
    _geo.append(stroke([(10, 10 + 5 * i), (30, 10 + 5 * i)], w))
_body += ["D23*", move(40, 10), draw(60, 30)]
_geo.append(stroke([(40, 10), (60, 30)], 0.20))
add("f03_lines.gbr",
    gerber("Copper,L1,Top", _body, [f"%ADD{20 + i}C,{w:.6f}*%" for i, w in enumerate(_w)]),
    unary_union(_geo))

# f04: archi (multi-quadrante) con tratto largo: quarto in senso antiorario, cerchio intero, quarto orario
_body = (["D10*", move(20, 10)] + arc(20, 10, 15, 15, 15, 10)
         + [move(40, 15)] + arc(40, 15, 40, 15, 35, 15)
         + [move(55, 15)] + arc(55, 15, 50, 10, 50, 15, ccw=False))
add("f04_arcs.gbr",
    gerber("Copper,L1,Top", _body, ["%ADD10C,0.300000*%"]),
    unary_union([stroke(arc_pts(15, 10, 5, 0, 90), 0.3),
                 stroke(arc_pts(35, 15, 5, 0, 360), 0.3),
                 stroke(arc_pts(50, 15, 5, 0, -90), 0.3)]))

# f05: regione con angoli arrotondati (20 x 10, raggio 2)
x0, y0, x1, y1, r = 10, 10, 30, 20, 2
add("f05_region_arcs.gbr",
    gerber("Copper,L1,Top", region(
        [move(x0 + r, y0), draw(x1 - r, y0)] + arc(x1 - r, y0, x1, y0 + r, x1 - r, y0 + r)
        + [draw(x1, y1 - r)] + arc(x1, y1 - r, x1 - r, y1, x1 - r, y1 - r)
        + [draw(x0 + r, y1)] + arc(x0 + r, y1, x0, y1 - r, x0 + r, y1 - r)
        + [draw(x0, y0 + r)] + arc(x0, y0 + r, x0 + r, y0, x0 + r, y0 + r))),
    box(x0 + r, y0 + r, x1 - r, y1 - r).buffer(r, quad_segs=QS))

# f06: macro (rettangolo ruotato, ottagono, rettangolo arrotondato in stile KiCad)
add("f06_macros.gbr",
    gerber("Copper,L1,Top", ["D10*", flash(15, 15), "D11*", flash(30, 15), "D12*", flash(45, 15)],
           ["%ADD10RotRect,3.000000X1.000000X30.000000*%", "%ADD11Oct,1.000000*%", ROUNDRECT_AP.format(n=12)],
           M_ROTRECT + M_OCT + M_ROUNDRECT),
    unary_union([translate(rotate(box(-1.5, -0.5, 1.5, 0.5), 30, origin=(0, 0)), 15, 15),
                 Polygon([(30.5, 15.2071), (30.2071, 15.5), (29.7929, 15.5), (29.5, 15.2071), (29.5, 14.7929),
                          (29.7929, 14.5), (30.2071, 14.5), (30.5, 14.7929)]),
                 roundrect(45, 15)]))

# f07: polarità clear: quadrato 10x10 con foro clear D4 e disco dark D1 al centro
add("f07_clear.gbr",
    gerber("Copper,L1,Top",
           region([move(10, 10), draw(20, 10), draw(20, 20), draw(10, 20), draw(10, 10)])
           + ["%LPC*%", "D10*", flash(15, 15), "%LPD*%", "D11*", flash(15, 15)],
           ["%ADD10C,4.000000*%", "%ADD11C,1.000000*%"]),
    box(10, 10, 20, 20).difference(disc(15, 15, 4)).union(disc(15, 15, 1)))

# f08: step-and-repeat 3 x 2, passo 5 x 4
add("f08_step_repeat.gbr",
    gerber("Copper,L1,Top", ["%SRX3Y2I5.000000J4.000000*%", "D10*", flash(10, 10), "%SR*%"],
           ["%ADD10C,1.000000*%"]),
    unary_union([disc(10 + 5 * i, 10 + 4 * j, 1.0) for i in range(3) for j in range(2)]))

# f09: contorno aperto (tre lati, con un'interruzione) con tratto 0,1
add("f09_outline_open.gbr",
    gerber("Profile,NP", ["D10*", move(10, 10), draw(50, 10), draw(50, 30), draw(10, 30), draw(10, 15)],
           ["%ADD10C,0.100000*%"]),
    stroke([(10, 10), (50, 10), (50, 30), (10, 30), (10, 15)], 0.1))

# --- fori di prova (Excellon) -----------------------------------------------------
HOLES_PTH = [(1, 12, 12), (2, 20, 12), (3, 30, 12)]
SLOTS_NPTH = [(2, 20, 40, 26, 40)]
HOLES_NPTH = [(1, 60, 40)]
TOOLS_PTH = {1: 0.3, 2: 0.8, 3: 1.0}
TOOLS_NPTH = {1: 3.0, 2: 1.0}
DRILLS = {
    "d01_pth.drl": (excellon("Plated,1,2,PTH", TOOLS_PTH, HOLES_PTH),
                    unary_union([disc(x, y, TOOLS_PTH[t]) for t, x, y in HOLES_PTH])),
    "d02_npth.drl": (excellon("NonPlated,1,2,NPTH", TOOLS_NPTH, HOLES_NPTH, SLOTS_NPTH),
                     unary_union([disc(x, y, TOOLS_NPTH[t]) for t, x, y in HOLES_NPTH]
                                 + [stroke([(a, b), (c, d)], TOOLS_NPTH[t]) for t, a, b, c, d in SLOTS_NPTH])),
}


# f10: Gerber in pollici (formato 2.4, %MOIN*%): disco D 0,04", linea 0,01" lunga 1", quadrato 0,5"
IN = 25.4
add("f10_inch.gbr",
    "\n".join(["%TF.FileFunction,Copper,L1,Top*%", "%FSLAX24Y24*%", "%MOIN*%",
               "%ADD10C,0.040000*%", "%ADD11C,0.010000*%", "G75*", "G01*", "%LPD*%",
               "D10*", "X10000Y10000D03*", "D11*", "X15000Y10000D02*", "X25000Y10000D01*",
               "G36*", "X30000Y10000D02*", "X35000Y10000D01*", "X35000Y15000D01*", "X30000Y15000D01*",
               "X30000Y10000D01*", "G37*", "M02*", ""]),
    unary_union([disc(1 * IN, 1 * IN, 0.04 * IN), stroke([(1.5 * IN, 1 * IN), (2.5 * IN, 1 * IN)], 0.01 * IN),
                 box(3 * IN, 1 * IN, 3.5 * IN, 1.5 * IN)]))

# f11: primitive delle macro: linea vettoriale diagonale (20), poligono (5), anello con primitiva a
#      esposizione spenta (1 + 1). f12: rettangolo da angolo (22), primitiva deprecata ma ancora usata da vecchi CAD
M_VEC = ["%AMVec*", "20,1,0.3,0,0,2,2,0*%"]
M_LL = ["%AMLL*", "22,1,2,1,-1,-0.5,30*%"]
M_POLY = ["%AMPoly*", "5,1,5,0,0,2,15*%"]
M_DONUT = ["%AMDonut*", "1,1,$1,0,0*", "1,0,$2,0,0*%"]
add("f11_macro_prims.gbr",
    gerber("Copper,L1,Top", ["D10*", flash(10, 10), "D11*", flash(20, 10), "D12*", flash(30, 10)],
           ["%ADD10Vec*%", "%ADD11Poly*%", "%ADD12Donut,2.000000X1.000000*%"],
           M_VEC + M_POLY + M_DONUT),
    unary_union([translate(LineString([(0, 0), (2, 2)]).buffer(0.15, cap_style="flat"), 10, 10),
                 translate(regular_polygon(0, 0, 2.0, 5, 15), 20, 10),
                 disc(30, 10, 2.0).difference(disc(30, 10, 1.0))]))
add("f12_macro_22_lower_left.gbr",
    gerber("Copper,L1,Top", ["D10*", flash(10, 10)], ["%ADD10LL*%"], M_LL),
    translate(rotate(box(-1, -0.5, 1, 0.5), 30, origin=(0, 0)), 10, 10))

# f13: zona di rame con isole nei buchi (pad isolati dentro le zone): l'ordine di disegno non deve cancellarle
_c = [(17 + 8 * i, 17 + 8 * j) for i in range(3) for j in range(3)]
add("f13_islands_in_holes.gbr",
    gerber("Copper,L1,Top",
           region([move(10, 10), draw(40, 10), draw(40, 40), draw(10, 40), draw(10, 10)])
           + ["%LPC*%", "D10*"] + [flash(x, y) for x, y in _c] + ["%LPD*%", "D11*"] + [flash(x, y) for x, y in _c],
           ["%ADD10C,6.000000*%", "%ADD11C,2.000000*%"]),
    unary_union([box(10, 10, 40, 40).difference(unary_union([disc(x, y, 6.0) for x, y in _c]))]
                + [disc(x, y, 2.0) for x, y in _c]))

# --- foratura in altri formati (come li scrivono EAGLE e Altium) -------------------
# pollici, zeri finali (TZ) con zeri iniziali soppressi, formato 2:4, utensili T01F00S00C..., coordinate modali
DRILL_INCH_TZ = "\n".join(["M48", ";FILE_FORMAT=2:4", "INCH,TZ", "T01F00S00C0.0315", "T02F00S00C0.0394", "%",
                           "T01", "X5000Y5000", "Y12000", "T02", "X12000Y5000", "M30", ""])
# metrico, zeri iniziali (LZ) con zeri finali soppressi, formato 3:3
DRILL_METRIC_LZ = "\n".join(["M48", ";FILE_FORMAT=3:3", "METRIC,LZ", "T1C0.800", "%", "T1", "X0125Y012", "X030Y030", "M30", ""])
DRILLS["d03_inch_tz.drl"] = (DRILL_INCH_TZ, unary_union([disc(0.5 * IN, 0.5 * IN, 0.0315 * IN),
                                                        disc(0.5 * IN, 1.2 * IN, 0.0315 * IN),
                                                        disc(1.2 * IN, 0.5 * IN, 0.0394 * IN)]))
DRILLS["d04_metric_lz.drl"] = (DRILL_METRIC_LZ, unary_union([disc(12.5, 12.0, 0.8), disc(30.0, 30.0, 0.8)]))

# --- robustezza: macro usata ma mai definita (non ha geometria di riferimento) ----
ROBUSTNESS = {
    # Excellon con coordinate senza punto e senza alcun formato dichiarato (valgono i predefiniti 3:3 / 2:4)
    "r02_excellon_no_format.drl": "\n".join(["M48", "METRIC,LZ", "T1C0.800", "%", "T1", "X0125Y012", "M30", ""]),
    "r01_missing_macro.gbr": gerber("Copper,L1,Top", ["D10*", flash(10, 10), "D11*", flash(20, 10)],
                                    ["%ADD10C,1.000000*%", "%ADD11Foo,1.000000X2.000000*%"]),
}


# --- scheda sintetica 80 x 50 in stile KiCad --------------------------------------
def synth_board():
    pads = [(20 + 2.54 * i, 30) for i in range(10)]               # 10 pad D1,6 a passo 2,54
    vias = [(70 + 2 * i, 30) for i in range(4)]                   # 4 via D0,6 foro 0,3
    sq = (80, 30)                                                  # pad quadrato 2 x 2, foro 1,0
    rr = (60, 50)                                                  # pad rettangolo arrotondato
    trace = [(20, 30), (20, 15), (60, 15)]                         # pista 0,25 con angolo
    thin = [(20, 45), (70, 45)]                                    # pista sottile 0,15 lunga 50
    zone = (65, 40, 75, 48)                                        # zona di rame con foro clear D2
    cu_body = (["D10*"] + [flash(x, y) for x, y in pads] + ["D13*"] + [flash(x, y) for x, y in vias]
               + ["D14*", flash(*sq), "D15*", flash(*rr)]
               + ["D11*", move(*trace[0]), draw(*trace[1]), draw(*trace[2])]
               + ["D12*", move(*thin[0]), draw(*thin[1])]
               + region([move(zone[0], zone[1]), draw(zone[2], zone[1]), draw(zone[2], zone[3]),
                         draw(zone[0], zone[3]), draw(zone[0], zone[1])])
               + ["%LPC*%", "D16*", flash(70, 44), "%LPD*%"])
    cu_geom = unary_union([disc(x, y, 1.6) for x, y in pads] + [disc(x, y, 0.6) for x, y in vias]
                          + [box(79, 29, 81, 31), roundrect(*rr), stroke(trace, 0.25), stroke(thin, 0.15),
                             box(*zone).difference(disc(70, 44, 2.0))])
    cu = gerber("Copper,L1,Top", cu_body,
                ["%ADD10C,1.600000*%", "%ADD11C,0.250000*%", "%ADD12C,0.150000*%", "%ADD13C,0.600000*%",
                 "%ADD14R,2.000000X2.000000*%", ROUNDRECT_AP.format(n=15), "%ADD16C,2.000000*%"], M_ROUNDRECT)
    # contorno 80 x 50 con angoli arrotondati r = 3, tratto 0,1 (come lo scrive KiCad)
    ob = (["D10*", move(13, 10), draw(87, 10)] + arc(87, 10, 90, 13, 87, 13) + [draw(90, 57)]
          + arc(90, 57, 87, 60, 87, 57) + [draw(13, 60)] + arc(13, 60, 10, 57, 13, 57) + [draw(10, 13)]
          + arc(10, 13, 13, 10, 13, 13))
    center = ([(13, 10), (87, 10)] + arc_pts(87, 13, 3, -90, 0, 64) + [(90, 57)] + arc_pts(87, 57, 3, 0, 90, 64)
              + [(13, 60)] + arc_pts(13, 57, 3, 90, 180, 64) + [(10, 13)] + arc_pts(13, 13, 3, 180, 270, 64))
    edge = gerber("Profile,NP", ob, ["%ADD10C,0.100000*%"])
    # maschera: aperture sui pad (via coperte), disegnate come "forme" come fa il CAD
    mk = gerber("Soldermask,Top",
                ["D10*"] + [flash(x, y) for x, y in pads] + ["D11*", flash(*sq)],
                ["%ADD10C,1.700000*%", "%ADD11R,2.100000X2.100000*%"])
    # serigrafia: rettangolo attorno alla fila di pad, tratto 0,15
    sk = gerber("Legend,Top", ["D10*", move(17, 27), draw(46, 27), draw(46, 33), draw(17, 33), draw(17, 27)],
                ["%ADD10C,0.150000*%"])
    pth_holes = [(1, x, y) for x, y in pads] + [(2, x, y) for x, y in vias] + [(3, *sq)]
    pth = excellon("Plated,1,2,PTH", {1: 0.9, 2: 0.3, 3: 1.0}, pth_holes)
    npth_holes = [(1, 15, 15), (1, 85, 15), (1, 15, 55), (1, 85, 55)]
    npth_slot = [(2, 45, 55, 51, 55)]
    npth = excellon("NonPlated,1,2,NPTH", {1: 3.2, 2: 1.0}, npth_holes, npth_slot)
    holes_geom = unary_union([disc(x, y, {1: 0.9, 2: 0.3, 3: 1.0}[t]) for t, x, y in pth_holes]
                             + [disc(x, y, 3.2) for _, x, y in npth_holes]
                             + [stroke([(a, b), (c, d)], 1.0) for _, a, b, c, d in npth_slot])
    files = {"F_Cu.gbr": cu, "Edge_Cuts.gbr": edge, "F_Mask.gbr": mk, "F_Silkscreen.gbr": sk,
             "PTH.drl": pth, "NPTH.drl": npth}
    refs = {"copper": cu_geom, "outline_centerline": LineString(center), "holes": holes_geom}
    return files, refs


def write_zip(path, members):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in members.items():
            z.writestr(name, text)


def write(out, verbose=False):
    """Scrive in `out` tutti i file di prova e in `out/reference` le geometrie attese (WKT)."""
    ref_dir = os.path.join(out, "reference")
    os.makedirs(ref_dir, exist_ok=True)
    expected = {}

    def save(name, text, geom):
        ext = os.path.splitext(name)[1]
        with open(os.path.join(out, name), "w") as f:
            f.write(text)
        with open(os.path.join(ref_dir, os.path.splitext(name)[0] + ".wkt"), "w") as f:
            f.write(geom.wkt)
        b = geom.bounds
        expected[name] = {"bbox_mm": [round(v, 4) for v in b], "area_mm2": round(geom.area, 4)}

    for name, (text, geom) in TESTS.items():
        save(name, text, geom)
    for name, (text, geom) in DRILLS.items():
        save(name, text, geom)

    files, refs = synth_board()
    kicad = {f"synth-{k}": v for k, v in files.items()}
    write_zip(os.path.join(out, "synth_kicad.zip"), kicad)
    # stessa scheda con i nomi di EAGLE: i file hanno contenuto identico
    eagle_names = {"F_Cu.gbr": "synth.cmp", "Edge_Cuts.gbr": "synth.gko", "F_Mask.gbr": "synth.stc",
                   "F_Silkscreen.gbr": "synth.plc", "PTH.drl": "synth.drd"}
    write_zip(os.path.join(out, "synth_eagle.zip"),
              {eagle_names[k]: v for k, v in files.items() if k in eagle_names})
    # stessa scheda KiCad con le voci che macOS aggiunge agli zip (__MACOSX, .DS_Store, file "._")
    junk = {"__MACOSX/._synth-F_Cu.gbr": "\x00\x05\x16\x07\x00\x02\x00\x00Mac OS X        \x00\x02",
            "__MACOSX/._synth-PTH.drl": "\x00\x05\x16\x07\x00\x02\x00\x00Mac OS X        \x00\x02",
            ".DS_Store": "\x00\x00\x00\x01Bud1"}
    write_zip(os.path.join(out, "synth_macos.zip"), {**kicad, **junk})
    for name, text in ROBUSTNESS.items():
        with open(os.path.join(out, name), "w") as f:
            f.write(text)
    for k, g in refs.items():
        with open(os.path.join(ref_dir, f"synth_{k}.wkt"), "w") as f:
            f.write(g.wkt)
        expected[f"synth_{k}"] = {"bbox_mm": [round(v, 4) for v in g.bounds],
                                  "area_mm2": round(g.area, 4) if g.area else None,
                                  "length_mm": round(g.length, 4)}
    with open(os.path.join(out, "expected.json"), "w") as f:
        json.dump(expected, f, indent=1)
    if verbose:
        print(f"scritti {len(os.listdir(out))} elementi in {out}")
        for k, v in expected.items():
            print(f"  {k:28s} bbox {v['bbox_mm']}  area {v.get('area_mm2')}")
    return expected


def main():
    write(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "data"), verbose=True)


if __name__ == "__main__":
    main()
