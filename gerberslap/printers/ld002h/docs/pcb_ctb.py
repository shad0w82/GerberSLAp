#!/usr/bin/env python3
"""
pcb_ctb.py - make .ctb files for the Creality LD-002H to use it as a UV
exposure unit for pre-sensitized PCB blanks. A trial tool: the app does not use it
(its driver, gerberslap/printers/ld002h/driver.py, writes the same files; a test
compares the two). It lives next to the format document and finds the writer,
ctbio.py, in the package, so it can be run from anywhere:

  python gerberslap/printers/ld002h/docs/pcb_ctb.py ...

The commands:

  pcb_ctb.py test   -t box.ctb -o test_pattern.ctb  [--exposure 4]
  pcb_ctb.py ladder -t box.ctb -o ladder.ctb        [--step 10 --bands 8]
  pcb_ctb.py probe  -t box.ctb -o lift_probe.ctb   (does the plate move when lift = 0?)
  pcb_ctb.py png board.png -t box.ctb -o board.ctb  --dpi 1200 --exposure 60
                        [--invert] [--mirror-x] [--mirror-y] [--rotate 90] [--center]
                        (--mirror-x/-y, --start-delay, --pulses/--rest work on every command)

-t/--template must be a .ctb sliced for your printer by ChiTuBox (any model).
Only its static header is reused; geometry/exposure come from here.

Coordinates in this file: image column x runs along the panel's SHORT axis
(82.62 mm, 1620 px), image row y along the LONG axis (130.56 mm, 2560 px),
pixel pitch 51 um. "Lit" (value 127) = UV passes through.

WHAT THE PRINTER DOES (verified on an LD-002H with ChiTuBox files and probes):
 - exposure, bottom exposure, bottom-layer count and rest times come from the file
   HEADER and apply to every layer; per-layer table values for these are ignored, so all
   exposure layers share one time (ladder / pulses / png all satisfy this)
 - the per-layer Z and image are used as written
 - lift/retract distances and speeds ARE honoured, down to 0.001 mm (speedCube.ctb); a
   distance of exactly 0 makes the printer fall back to a 5 mm cycle, so never write 0.
   Best practice: make a file in ChiTuBox with the motion you want and use it as the
   template with --motion-from-template (copies distances, speeds, 2nd stages, rests).
 - Z0 homing at the start and the final rise are fixed; the first rise to the layer Z is
   slow (~60 mm/min), hence --park-z defaults to 1 mm. With the build plate removed there
   is >= 30 mm between carriage and LCD at Z0; keep board + weight under ~25 mm.

Timing: after each layer the printer waits the rest time with everything off (Spento),
then does the lift/retract cycle (negligible with a 0.001 mm lift).

Orientation (from the F test and one corner of the mirrored test): file -> printer is a
pure 90 deg counter-clockwise rotation seen from above with you at the front: file top
edge = printer left, file right edge = back, file bottom edge = right, file left edge =
front. The file's top-left pixel is the front-left corner of the screen; the 130.56 mm
axis (file rows) runs left-right, the 82.62 mm axis (file columns) runs front-back.

Terms: Nero = LCD and UV on, black image; Mask = pattern; Spento = LCD and UV off.

The file format itself (header, per-layer records, rest-time fields, cipher,
CRC) was verified byte-for-byte against four ChiTuBox files for this printer.
"""
import argparse
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 4)))   # the root of the repository, where the package is
from gerberslap.printers.ld002h import ctbio
from gerberslap.printers.ld002h.ctbio import RES_X, RES_Y, PITCH_MM, Layer, write_ctb

PX_PER_MM = 1.0 / PITCH_MM


def mm(v): return v * PX_PER_MM


def font(size_mm):
    px = max(6, int(round(mm(size_mm))))
    return ImageFont.load_default(size=px)   # the font Pillow carries inside itself (vector, Pillow >= 10.1)


def to_mask(im: Image.Image) -> np.ndarray:
    return np.asarray(im.convert("L")) > 127


# ---------------------------------------------------------------- test pattern
def test_pattern() -> np.ndarray:
    """Asymmetric pattern: lit = drawn. Shows orientation, scale and usable area."""
    im = Image.new("L", (RES_X, RES_Y), 0)
    dr = ImageDraw.Draw(im)
    W, H = ctbio.PANEL_MM_X, ctbio.PANEL_MM_Y
    # frame, 1 mm wide, inset 1 mm
    dr.rectangle([mm(1), mm(1), mm(W - 1), mm(H - 1)], outline=255, width=int(mm(1)))
    # rulers: ticks every 5 mm along the top edge (x) and left edge (y); labels every 10 mm
    for k in range(0, int(W) + 1, 5):
        L = 6 if k % 10 == 0 else 3
        dr.rectangle([mm(k), mm(3), mm(k) + 2, mm(3 + L)], fill=255)
        if k % 10 == 0 and 20 <= k <= W - 15:
            dr.text((mm(k) - mm(2), mm(10)), str(k), fill=255, font=font(3.5))
    for k in range(0, int(H) + 1, 5):
        L = 6 if k % 10 == 0 else 3
        dr.rectangle([mm(3), mm(k), mm(3 + L), mm(k) + 2], fill=255)
        if k % 10 == 0 and 20 <= k <= H - 8:
            dr.text((mm(11), mm(k) - mm(1.8)), str(k), fill=255, font=font(3.5))
    # corner markers: filled square top-left, filled circle top-right
    dr.rectangle([mm(5), mm(5), mm(12), mm(12)], fill=255)
    dr.ellipse([mm(W - 12), mm(5), mm(W - 5), mm(12)], fill=255)
    dr.text((mm(24), mm(15.5)), "TOP", fill=255, font=font(6))
    # 50 x 50 mm square for a caliper scale check (outline 0.5 mm)
    dr.rectangle([mm(20), mm(30), mm(70), mm(80)], outline=255, width=int(mm(0.5)))
    dr.text((mm(23), mm(32)), "50 mm", fill=255, font=font(5))
    # big asymmetric "F"
    dr.text((mm(22), mm(84)), "F", fill=255, font=font(28))
    # line / space groups: widths 2,3,4,5,6,8 px (~4..16 mil), 5 bars each
    y = mm(88)
    x0 = mm(46)
    for wpx in (2, 3, 4, 5, 6, 8):
        for k in range(5):
            xx = x0 + k * 2 * wpx
            dr.rectangle([xx, y, xx + wpx - 1, y + mm(4)], fill=255)
        dr.text((x0 + 10 * wpx + 8, y - mm(0.5)), f"{wpx}px", fill=255, font=font(3))
        y += mm(5.5)
    return to_mask(im)


# ---------------------------------------------------------------- ladder
def ladder_layers(bands: int, band_mm: float, width_mm: float, y0_mm: float):
    """Layer i exposes bands j >= i, so band j gets (j+1) x step. Features are
    dark on a lit field (positive resist: lit area is what gets removed)."""
    x0 = (ctbio.PANEL_MM_X - width_mm) / 2
    base = []
    for j in range(bands):
        im = Image.new("L", (RES_X, RES_Y), 0)
        dr = ImageDraw.Draw(im)
        ya = y0_mm + j * band_mm
        dr.rectangle([mm(x0), mm(ya), mm(x0 + width_mm), mm(ya + band_mm - 1)], fill=255)
        # dark test features inside the band
        yy = ya + 2
        xx = mm(x0 + 3)
        for wpx in (2, 3, 4, 5, 6, 8):
            for k in range(6):
                dr.rectangle([xx + k * 2 * wpx, mm(yy), xx + k * 2 * wpx + wpx - 1, mm(yy + 6)], fill=0)
            xx += 12 * wpx + mm(2.5)
        base.append(im)
    return base, x0


def label_on(im: Image.Image, text: str, x_mm: float, y_mm: float):
    ImageDraw.Draw(im).text((mm(x_mm), mm(y_mm)), text, fill=0, font=font(3.5))


# ---------------------------------------------------------------- png -> layer
def png_layer(path, dpi, invert, mirror_x, mirror_y, rotate, center, off_x, off_y) -> np.ndarray:
    src = Image.open(path).convert("L")
    if rotate:
        src = src.rotate(-rotate, expand=True)
    scale = (25.4 / dpi) / PITCH_MM  # source px -> panel px
    new = (max(1, round(src.width * scale)), max(1, round(src.height * scale)))
    src = src.resize(new, Image.NEAREST if scale > 1 else Image.BOX)
    m = np.asarray(src) > 127
    if invert:
        m = ~m
    if mirror_x: m = m[:, ::-1]
    if mirror_y: m = m[::-1, :]
    h, w = m.shape
    if w > RES_X or h > RES_Y:
        sys.exit(f"board raster is {w}x{h} px after scaling, panel is {RES_X}x{RES_Y}. "
                 f"Try --rotate 90 or a smaller board.")
    out = np.zeros((RES_Y, RES_X), bool)
    ox = (RES_X - w) // 2 if center else int(mm(off_x))
    oy = (RES_Y - h) // 2 if center else int(mm(off_y))
    ox = min(max(ox, 0), RES_X - w); oy = min(max(oy, 0), RES_Y - h)
    out[oy:oy + h, ox:ox + w] = m
    # outside the board image the screen stays dark (no exposure outside the board)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("-t", "--template", required=True, help="ChiTuBox .ctb sliced for the LD-002H")
        p.add_argument("-o", "--out", required=True)
        p.add_argument("--park-z", type=float, default=1.0,
                       help="constant Z for all layers, mm above Z0 (default 1; the printer rises to it at ~60 mm/min)")
        p.add_argument("--chitubox-motion", action="store_true",
                       help="use normal ChiTuBox motion instead (Z = layer*0.05, 5 mm lift)")
        p.add_argument("--preview-png", help="also save the first layer as PNG")
        p.add_argument("--preview-full-panel", action="store_true",
                       help="preview shows the whole screen area instead of being cropped to the lit area")
        p.add_argument("--keep-template-preview", action="store_true",
                       help="keep the template's preview image instead of showing the first exposure layer")
        p.add_argument("--mirror-x", action="store_true", help="flip left/right (board exposed copper-side down)")
        p.add_argument("--mirror-y", action="store_true", help="flip top/bottom")
        p.add_argument("--start-delay", type=float, default=0.0,
                       help="approximate seconds before the real exposure starts, so you can place the board "
                            "after the Z0 homing; built from 'bottom' layers (1 s black, then the rest, then "
                            "the printer's 5 mm cycle each)")
        p.add_argument("--motion-from-template", action="store_true",
                       help="copy ALL lift/retract distances, speeds (incl. the second stage) and rest times from the "
                            "template file (make it in ChiTuBox with the motion settings you want); --rest, if given, "
                            "still overrides 'rest before lift'")
        p.add_argument("--lift-mm", type=float, default=0.001, help="lift distance in mm (NEVER 0: the printer then does its default 5 mm cycle)")
        p.add_argument("--lift-speed", type=float, default=500.0, help="lift speed, mm/min (header)")
        p.add_argument("--retract-speed", type=float, default=500.0, help="return speed, mm/min (header)")
        p.add_argument("--rest-after-lift", type=float, default=0.0, help="s, ChiTuBox 'Rest Time After Lift'")
        p.add_argument("--rest-after-retract", type=float, default=0.0, help="s, ChiTuBox 'Rest Time After Retract'")
        p.add_argument("--delay-layers", type=int, default=None, help="exact number of delay layers (overrides --start-delay)")
        p.add_argument("--cycle-s", type=float, default=8.0,
                       help="ESTIMATE of the printer's 5 mm lift/return cycle, s (used only to size --start-delay)")
        p.add_argument("--pulses", type=int, default=1,
                       help="split each exposure into N equal flashes (same total dose, less heating)")
        p.add_argument("--rest", type=float, default=None,
                       help="seconds of rest after each flash, stored as ChiTuBox 'Rest Time Before Lift' "
                            "(UV off, before any lift; default 5 if --pulses>1, else 0)")

    p = sub.add_parser("test"); common(p); p.add_argument("--exposure", type=float, default=4.0)
    p = sub.add_parser("ladder"); common(p)
    p.add_argument("--step", type=float, default=10.0, help="seconds per step (band k gets k x step)")
    p.add_argument("--bands", type=int, default=8); p.add_argument("--band-mm", type=float, default=14)
    p.add_argument("--width-mm", type=float, default=76); p.add_argument("--y0-mm", type=float, default=8)
    p = sub.add_parser("probe", help="lift-distance probe: black layers with different lift distances, no board needed")
    common(p)
    p.add_argument("--lifts", default="0,0.5,1,2,4,8", help="comma list of lift distances in mm (default 0,0.5,1,2,4,8)")
    p.add_argument("--repeat", type=int, default=2, help="layers per distance")
    p.add_argument("--probe-rest", type=float, default=4.0, help="rest before lift, s (so the start of each move is obvious)")
    p = sub.add_parser("expprobe", help="is the exposure read from each layer or from the file header?")
    common(p)
    p.add_argument("--exposures", default="3,6,9", help="per-layer exposures written in the layer table, s")
    p.add_argument("--header-exposure", type=float, default=20.0, help="exposure written in the file header, s")
    p.add_argument("--probe-rest", type=float, default=10.0)
    p = sub.add_parser("bottomprobe", help="are bottom-layer count/exposure and the rest time read from the header?")
    common(p)
    p.add_argument("--layers", type=int, default=4)
    p.add_argument("--bottom-layers", type=int, default=2)
    p.add_argument("--bottom-exposure", type=float, default=3.0)
    p.add_argument("--exposure", type=float, default=8.0)
    p.add_argument("--header-rest", type=float, default=6.0)
    p.add_argument("--table-rest", type=float, default=2.0, help="decoy rest written in each layer record")
    p = sub.add_parser("speedprobe", help="does the printer use the lift/retract speeds from the header? (time the 5 mm cycle)")
    common(p)
    p.add_argument("--layers", type=int, default=3)
    p = sub.add_parser("headerlift", help="lift distance/speed written in the HEADER (bottom vs normal layers)")
    common(p)
    p.add_argument("--bottom-layers", type=int, default=2)
    p.add_argument("--layers", type=int, default=6)
    p.add_argument("--bottom-lift", type=float, default=12.0)
    p.add_argument("--bottom-speed", type=float, default=300.0)
    p.add_argument("--probe-lift", type=float, default=2.0, help="lift distance of the normal layers")
    p.add_argument("--probe-speed", type=float, default=600.0, help="lift speed of the normal layers")
    p.add_argument("--probe-retract", type=float, default=300.0)
    p = sub.add_parser("png"); common(p); p.add_argument("png")
    p.add_argument("--dpi", type=float, required=True); p.add_argument("--exposure", type=float, required=True)
    p.add_argument("--invert", action="store_true")
    p.add_argument("--rotate", type=int, default=0, choices=(0, 90, 180, 270))
    p.add_argument("--center", action="store_true"); p.add_argument("--off-x", type=float, default=0.0)
    p.add_argument("--off-y", type=float, default=0.0)
    a = ap.parse_args()

    if a.cmd == "probe":
        lifts = [float(x) for x in a.lifts.split(",")]
        black = np.zeros((RES_Y, RES_X), bool)
        out_layers = []
        for lf in lifts:
            for _ in range(a.repeat):
                out_layers.append(Layer(black, 1.0, rest_before_lift_s=a.probe_rest, lift_mm=lf))
        write_ctb(a.template, a.out, out_layers, rest_before_lift_s=a.probe_rest, lift_mm=0.0, park_z_mm=a.park_z)
        c = ctbio.CTB(a.out)
        print(c.info()); print()
        print("layer  lift(mm)   (each layer: 1 s black, %g s dark rest, then the lift/retract cycle)" % a.probe_rest)
        for i, L in enumerate(out_layers): print(f"  {i+1:2d}    {L.lift_mm:g}")
        return
    if a.cmd == "headerlift":
        black = np.zeros((RES_Y, RES_X), bool)
        out_layers = [Layer(black, 1.0) for _ in range(a.layers)]
        write_ctb(a.template, a.out, out_layers, rest_before_lift_s=2.0, park_z_mm=a.park_z,
                  lift_mm=a.probe_lift, bottom_lift_mm=a.bottom_lift,
                  lift_speed=a.probe_speed, bottom_lift_speed=a.bottom_speed, retract_speed=a.probe_retract,
                  header_exposure_s=1.0, header_bottom_exposure_s=1.0, bottom_layers=a.bottom_layers)
        c = ctbio.CTB(a.out); print(c.info()); print()
        print(f"{a.layers} layers: [Nero 1 s, Spento 2 s, cycle]; header says:")
        print(f"  first {a.bottom_layers} (bottom): lift {a.bottom_lift:g} mm at {a.bottom_speed:g} mm/min, back at {a.probe_retract:g} mm/min")
        print(f"  next {a.layers - a.bottom_layers} (normal): lift {a.probe_lift:g} mm at {a.probe_speed:g} mm/min, back at {a.probe_retract:g} mm/min")
        print("if the header is honoured: bottom rise %.1f s to %.0f mm above 30, return %.1f s; normal rise %.1f s to %g mm, return %.1f s" % (
            a.bottom_lift/a.bottom_speed*60, a.bottom_lift, a.bottom_lift/a.probe_retract*60,
            a.probe_lift/a.probe_speed*60, a.probe_lift, a.probe_lift/a.probe_retract*60))
        print("if the printer keeps its fixed 5 mm cycle: every layer rises 5 mm")
        return
    if a.cmd == "speedprobe":
        black = np.zeros((RES_Y, RES_X), bool)
        out_layers = [Layer(black, 1.0) for _ in range(a.layers)]
        write_ctb(a.template, a.out, out_layers, rest_before_lift_s=2.0, lift_mm=0.0, park_z_mm=a.park_z,
                  lift_speed=a.lift_speed, retract_speed=a.retract_speed,
                  header_exposure_s=1.0, header_bottom_exposure_s=1.0, bottom_layers=0)
        c = ctbio.CTB(a.out); print(c.info()); print()
        print(f"{a.layers} x [Nero 1 s, Spento 2 s, 5 mm cycle]; header speeds: lift {a.lift_speed:g}, retract {a.retract_speed:g} mm/min")
        print("if the file speeds are used, 5 mm up takes %.1f s and 5 mm down %.1f s" % (5/a.lift_speed*60, 5/a.retract_speed*60))
        return
    if a.cmd == "bottomprobe":
        pat = test_pattern()
        if a.mirror_x: pat = pat[:, ::-1]
        if a.mirror_y: pat = pat[::-1, :]
        out_layers = [Layer(pat, 1.0, rest_before_lift_s=a.table_rest) for _ in range(a.layers)]   # decoy table values
        write_ctb(a.template, a.out, out_layers, rest_before_lift_s=a.header_rest, lift_mm=0.0, park_z_mm=a.park_z,
                  header_exposure_s=a.exposure, header_bottom_exposure_s=a.bottom_exposure, bottom_layers=a.bottom_layers)
        c = ctbio.CTB(a.out); print(c.info()); print()
        print(f"header: {a.bottom_layers} bottom layer(s) at {a.bottom_exposure:g} s, then {a.exposure:g} s; rest {a.header_rest:g} s")
        print(f"layer table/record (decoys): exposure 1 s, rest {a.table_rest:g} s on every layer")
        print("expected if the header rules:  " + " | ".join(
            f"Mask {a.bottom_exposure if i < a.bottom_layers else a.exposure:g}s, Spento {a.header_rest:g}s" for i in range(a.layers)))
        print(f"expected if the layer table rules: every Mask 1s, Spento {a.table_rest:g}s")
        return
    if a.cmd == "expprobe":
        pat = test_pattern()
        if a.mirror_x: pat = pat[:, ::-1]
        if a.mirror_y: pat = pat[::-1, :]
        ex = [float(x) for x in a.exposures.split(",")]
        out_layers = [Layer(pat, e, rest_before_lift_s=a.probe_rest) for e in ex]
        write_ctb(a.template, a.out, out_layers, rest_before_lift_s=a.probe_rest, lift_mm=0.0,
                  park_z_mm=a.park_z, header_exposure_s=a.header_exposure,
                  header_bottom_exposure_s=a.header_exposure, bottom_layers=0)
        c = ctbio.CTB(a.out); print(c.info()); print()
        print(f"layer table says {ex} s per layer; header says {a.header_exposure:g} s; rest {a.probe_rest:g} s after each")
        print(f"-> if each flash lasts {ex} s the per-layer value is used; if all last {a.header_exposure:g} s the header is used")
        return
    if a.cmd == "test":
        imgs = [test_pattern()]; exps = [a.exposure]
    elif a.cmd == "ladder":
        base, x0 = ladder_layers(a.bands, a.band_mm, a.width_mm, a.y0_mm)
        for j, im in enumerate(base):
            label_on(im, f"{(j + 1) * a.step:g}s", x0 + a.width_mm - 14, a.y0_mm + j * a.band_mm + 4)
        masks = [to_mask(im) for im in base]
        imgs = []
        for i in range(a.bands):
            m = np.zeros((RES_Y, RES_X), bool)
            for j in range(i, a.bands):
                m |= masks[j]
            imgs.append(m)
        exps = [a.step] * a.bands
    else:
        imgs = [png_layer(a.png, a.dpi, a.invert, a.mirror_x, a.mirror_y, a.rotate, a.center, a.off_x, a.off_y)]
        exps = [a.exposure]

    if a.cmd in ("test", "ladder"):
        imgs = [(m[:, ::-1] if a.mirror_x else m) for m in imgs]
        imgs = [(m[::-1, :] if a.mirror_y else m) for m in imgs]
    if a.pulses < 1:
        sys.exit("--pulses must be >= 1")
    rest = a.rest if a.rest is not None else (5.0 if a.pulses > 1 else 0.0)
    if a.pulses > 1:
        if min(exps) / a.pulses < 1.0:
            sys.exit(f"{min(exps)} s / {a.pulses} pulses = {min(exps)/a.pulses:.2f} s per flash; "
                     f"keep flashes >= 1 s (reduce --pulses)")
        imgs = [m for m in imgs for _ in range(a.pulses)]      # arrays are shared, not copied
        exps = [e / a.pulses for e in exps for _ in range(a.pulses)]
    # The firmware reads exposure / bottom count / bottom exposure / rest from the file HEADER and applies
    # them to every layer (verified on an LD-002H), so all real layers must share one exposure.
    if len(set(round(e, 6) for e in exps)) != 1:
        sys.exit("all exposure layers must have the same exposure time: the printer uses one value for all of them")
    e_main = exps[0]
    if a.delay_layers is not None:
        K = max(0, a.delay_layers)
    elif a.start_delay > 0:
        K = max(1, int(np.ceil(a.start_delay / (1.0 + rest + a.cycle_s))))
    else:
        K = 0
    motion = dict(lift_mm=a.lift_mm, lift_speed=a.lift_speed, retract_speed=a.retract_speed,
                  rest_after_lift_s=a.rest_after_lift, rest_after_retract_s=a.rest_after_retract, park_z_mm=a.park_z)
    black = np.zeros((RES_Y, RES_X), bool)
    out_layers = [Layer(black, 1.0) for _ in range(K)] + [Layer(m, e) for m, e in zip(imgs, exps)]
    if a.motion_from_template:
        motion = dict(motion_from_template=True, rest_override_s=a.rest, park_z_mm=a.park_z)
    write_ctb(a.template, a.out, out_layers, rest_before_lift_s=rest, bottom_layers=K,
              header_exposure_s=e_main, header_bottom_exposure_s=(1.0 if K else e_main),
              preview=(None if a.keep_template_preview else imgs[0]),
              preview_crop=not a.preview_full_panel, **motion)
    if a.preview_png:
        Image.fromarray(imgs[0].astype(np.uint8) * 255).save(a.preview_png)
    c = ctbio.CTB(a.out)
    print(c.info())
    for i, L in enumerate(out_layers):
        assert np.array_equal(c.layer_image(i) > 0, L.image), f"layer {i} failed round trip"
    print(f"self-check ok: {len(out_layers)} layer(s) decode back identically")
    print("expected on the printer (after Z0 homing and the rise to %g mm):" % a.park_z)
    if a.motion_from_template:
        print("  (lift/retract distances, speeds and rest times copied from the template%s)" % (
            f"; rest before lift overridden to {a.rest:g} s" if a.rest is not None else ""))
    if K:
        print(f"  {K} x [Nero 1 s, Spento {rest:g} s, lift cycle]   (about {K*(1+rest+a.cycle_s):.0f} s to place the board; cycle time is an estimate)")
    n = len(exps)
    print(f"  {n} x [Mask {e_main:g} s, Spento {rest:g} s, lift cycle]   (UV on with the pattern: {sum(exps):g} s total)")


if __name__ == "__main__":
    main()
