#!/usr/bin/env python3
"""
ctbio.py - read / write ChiTuBox CTB (magic 0x12FD0106, "v5") files for the
Creality LD-002H, using a known-good .ctb sliced by ChiTuBox as a template.

Layout, as determined from a ChiTuBox-sliced sample (box.ctb) plus the public
catibo / UVtools documentation:

  0x000  fixed header (112 B)           magic, version, sizes, exposure, offsets...
  0x070  ExtConfig  (60 B)              lift / retract settings, bottom layer count
  0x0AC  ExtConfig2 (76 B)              machine-type string offset, enc. mode, AA level
  0x0F8  ExtConfig3                     [+40] total exposure s (f32), [+44] max layer
                                        blob size, [+52] layer count
  ....   preview headers + RLE15 data, machine name, notice text, resin strings
  LT     layer table, 36 B / layer:     z, exposure, 0 (light_off, unused), data_off,
                                        data_len, 0, 0x54, 0, 0
  then, for every layer, back to back:
         84 B  per-layer record         copy of table entry, +36 total size, +40 lift dist,
                                        +44 lift speed, +56 retract speed, +68/+72/+76 rest
                                        before lift / after lift / after retract, +80 PWM
         N B   RLE7 pixel data, XOR-encrypted with a per-layer keystream
         8 B   trailer                  lit area in mm^2 (f32) + u32 0
  last 4 B: CRC32 (little endian) of everything before it

Pixels: 7 bit (0..127), RLE7: first byte = 0x80|value for a run (else the single
pixel value); a run is followed by a 1..3 byte big-endian length
(0xxxxxxx | 10xxxxxx.. | 110xxxxx....). We never emit the 4-byte form.

Cipher (per layer, IV = layer index):
  c  = key*0x2D83CDAC + 0xD8A83423
  x0 = (IV*0x1E1530CD + 0xEC3D47CD) * c ;  x[n+1] = x[n] + c   (all mod 2^32)
  out32 = in32 XOR x[n]

Only a template with the same structure (ChiTuBox export for the LD-002H) is
supported: the static head of the file is copied from it unchanged.
"""
import struct
import sys
import zlib
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

M32 = 0xFFFFFFFF
RES_X, RES_Y = 1620, 2560
PANEL_MM_X, PANEL_MM_Y = 82.62, 130.56
PITCH_MM = PANEL_MM_X / RES_X  # 0.051 mm
FULL = 127  # fully lit pixel value in a CTB layer

# --- header field offsets (all verified against box.ctb) --------------------
H_LAYER_H, H_EXP, H_BOT_EXP, H_LIGHTOFF = 0x20, 0x24, 0x28, 0x2C
H_BOT_COUNT, H_RES_X, H_RES_Y = 0x30, 0x34, 0x38
H_LAYER_TBL, H_LAYER_CNT, H_PRINT_TIME = 0x40, 0x44, 0x4C
H_EXT_OFF, H_PWM, H_BOT_PWM, H_KEY, H_EXT2_OFF = 0x54, 0x60, 0x62, 0x64, 0x68
EX3_OFF_PTR = 0xEC  # u32 inside ExtConfig2 -> offset of ExtConfig3


# ---------------------------------------------------------------------------
# cipher + RLE
# ---------------------------------------------------------------------------
def crypt(buf: bytes, key: int, iv: int) -> bytes:
    """Symmetric XOR stream cipher used on layer data (key == 0 -> plaintext)."""
    if key == 0:
        return buf
    c = (key * 0x2D83CDAC + 0xD8A83423) & M32
    x = (((iv * 0x1E1530CD + 0xEC3D47CD) & M32) * c) & M32
    pad = buf + b"\0" * ((-len(buf)) % 4)
    words = np.frombuffer(pad, dtype="<u4").astype(np.uint64)
    n = np.arange(len(words), dtype=np.uint64)
    ks = (np.uint64(x) + n * np.uint64(c)) & np.uint64(M32)
    out = (words ^ ks).astype("<u4").tobytes()
    return out[: len(buf)]


def rle7_decode(buf: bytes, total: int = RES_X * RES_Y) -> np.ndarray:
    out = np.zeros(total, np.uint8)
    px = i = 0
    while i < len(buf) and px < total:
        b0 = buf[i]; i += 1
        v = b0 & 0x7F
        if b0 & 0x80:
            b1 = buf[i]
            if b1 & 0x80 == 0:
                n = b1; i += 1
            elif b1 & 0xC0 == 0x80:
                n = ((b1 & 0x3F) << 8) | buf[i + 1]; i += 2
            elif b1 & 0xE0 == 0xC0:
                n = ((b1 & 0x1F) << 16) | (buf[i + 1] << 8) | buf[i + 2]; i += 3
            else:
                n = ((b1 & 0x0F) << 24) | (buf[i + 1] << 16) | (buf[i + 2] << 8) | buf[i + 3]; i += 4
        else:
            n = 1
        out[px:px + n] = v
        px += n
    if px != total:
        raise ValueError(f"RLE7 decoded {px} px, expected {total}")
    return out


MAX_RUN = 0x1FFFFF  # largest run expressible with a 3-byte length


def rle7_encode(flat: np.ndarray) -> bytes:
    f = np.ascontiguousarray(flat, dtype=np.uint8).ravel()
    idx = np.flatnonzero(np.diff(f)) + 1
    starts = np.concatenate(([0], idx))
    ends = np.concatenate((idx, [len(f)]))
    out = bytearray()
    for s, e in zip(starts.tolist(), ends.tolist()):
        v = int(f[s]); n = e - s
        while n > 0:
            m = min(n, MAX_RUN); n -= m
            if m == 1:
                out.append(v)
                continue
            out.append(0x80 | v)
            if m <= 0x7F:
                out.append(m)
            elif m <= 0x3FFF:
                out += bytes([0x80 | (m >> 8), m & 0xFF])
            else:
                out += bytes([0xC0 | (m >> 16), (m >> 8) & 0xFF, m & 0xFF])
    return bytes(out)


# ---------------------------------------------------------------------------
# preview images (RGB555 + repeat flag, run-length, run <= 4095)
# ---------------------------------------------------------------------------
def preview_decode(data: bytes) -> np.ndarray:
    """Preview data -> flat array of 16-bit colours  R5 (15..11) G5 (10..6) 0 (5) B5 (4..0)."""
    out, i = [], 0
    while i + 1 < len(data):
        dot = data[i] | (data[i + 1] << 8); i += 2
        rep = 1
        if dot & 0x20:                                    # repeat flag (bit 5)
            rep += (data[i] | (data[i + 1] << 8)) & 0xFFF; i += 2
        out.extend([dot & ~0x20 & 0xFFFF] * rep)
    return np.array(out, dtype=np.uint16)


def preview_encode(colors: np.ndarray, max_run: int = 4095) -> bytes:
    """Inverse of preview_decode; reproduces ChiTuBox's bytes exactly (checked on 10 previews)."""
    c = np.asarray(colors, np.uint16).ravel()
    idx = np.flatnonzero(np.diff(c)) + 1
    starts = np.concatenate(([0], idx)); ends = np.concatenate((idx, [len(c)]))
    out = bytearray()
    for s, e in zip(starts.tolist(), ends.tolist()):
        v = int(c[s]); n = e - s
        while n > 0:
            m = min(n, max_run); n -= m
            if m == 1:
                out += struct.pack("<H", v)
            else:
                out += struct.pack("<HH", v | 0x20, 0x3000 | (m - 1))
    return bytes(out)


def make_preview(layer: np.ndarray, max_side: int = 500, crop: bool = True,
                 bg: int = 8, fg: int = 255) -> np.ndarray:
    """Layer image (2560 x 1620, bool or 0..127) -> (h x w) array of 16-bit preview colours.

    The preview always shows the view from above, as the object lies on the glass:
      1. the layer is turned into that view (file -> printer is a 90 deg counter-clockwise rotation);
      2. with crop=True it is cut to the lit area plus a margin (the object, not the whole screen);
      3. the long side is scaled to max_side (<= 500, the largest size seen in ChiTuBox files).
    No further rotation: an object deeper (front-back) than wide gives a portrait preview even
    though the printer's preview boxes are landscape.
    Light pixels become white, the rest near-black (like ChiTuBox's preview background)."""
    from PIL import Image
    a = np.asarray(layer)
    lit = np.clip(a.astype(np.float32) / (1.0 if a.dtype == bool else 127.0), 0, 1)
    if crop:
        ys, xs = np.nonzero(lit > 0)
        if len(ys):
            m = max(30, int(0.04 * max(ys.max() - ys.min() + 1, xs.max() - xs.min() + 1)))
            y0, y1 = max(0, ys.min() - m), min(lit.shape[0], ys.max() + 1 + m)
            x0, x1 = max(0, xs.min() - m), min(lit.shape[1], xs.max() + 1 + m)
            lit = lit[y0:y1, x0:x1]
    lit = np.rot90(lit, 1)                                   # view from above, as on the glass
    h, w = lit.shape
    k = max_side / max(h, w)
    out_w, out_h = max(1, round(w * k)), max(1, round(h * k))
    im = Image.fromarray((np.ascontiguousarray(lit) * 255).astype(np.uint8)).resize((out_w, out_h), Image.BOX)
    g = np.asarray(im, np.float32) / 255.0
    v = (bg + g * (fg - bg)).astype(np.uint8) >> 3           # 5 bits per channel, grey
    v = v.astype(np.uint16)
    return (v << 11) | (v << 6) | v


def _replace_previews(head: bytearray, pv: np.ndarray) -> bytearray:
    """Return a new head with both previews replaced by `pv` (h x w colours), fixing every pointer after them."""
    h, w = pv.shape
    ext2 = _u32(head, H_EXT2_OFF); ex3 = _u32(head, ext2 + 0x40)
    p1 = _u32(head, 0x3C); l1 = _u32(head, p1 + 12)
    p2 = _u32(head, 0x48); l2 = _u32(head, p2 + 12)
    old_rest = _u32(head, ext2 + 28)                       # machine-type string = start of what follows
    assert p2 == p1 + 32 + l1 and old_rest == p2 + 32 + l2, "unexpected preview layout in the template"
    data = preview_encode(pv); n = len(data)
    off1 = p1 + 32; p2n = off1 + n; off2 = p2n + 32; new_rest = off2 + n
    delta = new_rest - old_rest
    hdr = lambda off: struct.pack("<8I", w, h, off, n, 0, 0, 0, 0)
    new = bytearray(head[:p1]) + hdr(off1) + data + hdr(off2) + data + bytes(head[old_rest:])
    struct.pack_into("<I", new, 0x48, p2n)
    struct.pack_into("<I", new, ext2 + 28, _u32(head, ext2 + 28) + delta)         # machine string
    struct.pack_into("<I", new, ex3 + 72, _u32(head, ex3 + 72) + delta)           # notice
    resin_old = _u32(head, ex3 + 80); resin_new = resin_old + delta
    struct.pack_into("<I", new, ex3 + 80, resin_new)                              # resin block
    for k in (8, 16, 24):                                                          # its three string pointers
        struct.pack_into("<I", new, resin_new + k, _u32(head, resin_old + k) + delta)
    return new


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def _u32(d, o): return struct.unpack_from("<I", d, o)[0]
def _f32(d, o): return struct.unpack_from("<f", d, o)[0]


@dataclass
class LayerInfo:
    z: float
    exposure: float
    light_off: float
    data_off: int
    data_len: int


class CTB:
    def __init__(self, path: str):
        self.path = path
        self.d = open(path, "rb").read()
        d = self.d
        self.magic, self.version = _u32(d, 0), _u32(d, 4)
        if self.magic != 0x12FD0106:
            raise ValueError(f"unsupported magic {self.magic:#x} (expected 0x12fd0106)")
        self.key = _u32(d, H_KEY)
        self.layer_count = _u32(d, H_LAYER_CNT)
        self.table_off = _u32(d, H_LAYER_TBL)
        self.layers: List[LayerInfo] = []
        for i in range(self.layer_count):
            z, e, lo, off, ln = struct.unpack_from("<fffII", d, self.table_off + 36 * i)
            self.layers.append(LayerInfo(z, e, lo, off, ln))
        crc = zlib.crc32(d[:-4]) & M32
        self.crc_ok = crc == _u32(d, len(d) - 4)

    def layer_image(self, i: int) -> np.ndarray:
        L = self.layers[i]
        raw = crypt(self.d[L.data_off:L.data_off + L.data_len], self.key, i)
        return rle7_decode(raw).reshape(RES_Y, RES_X)

    def preview_image(self, which: int = 0) -> np.ndarray:
        """Decode preview 0 or 1 -> (h, w, 3) uint8 RGB."""
        p = struct.unpack_from("<I", self.d, 0x3C if which == 0 else 0x48)[0]
        w, h, off, ln = struct.unpack_from("<4I", self.d, p)
        c = preview_decode(self.d[off:off + ln]).reshape(h, w).astype(np.uint16)
        rgb = np.stack([(c >> 11) & 0x1F, (c >> 6) & 0x1F, c & 0x1F], axis=-1).astype(np.uint8)
        return rgb * 8

    def info(self) -> str:
        d = self.d
        s = [f"file            {self.path} ({len(d)} bytes, CRC32 {'ok' if self.crc_ok else 'BAD'})",
             f"magic/version   {self.magic:#010x} / {self.version}",
             f"printer volume  {_f32(d,8):.2f} x {_f32(d,12):.2f} x {_f32(d,16):.2f} mm",
             f"layer height    {_f32(d,H_LAYER_H):.3f} mm   layers {self.layer_count}",
             f"exposure        {_f32(d,H_EXP)} s   bottom {_f32(d,H_BOT_EXP)} s x {_u32(d,H_BOT_COUNT)}",
             f"resolution      {_u32(d,H_RES_X)} x {_u32(d,H_RES_Y)}   projection {_u32(d,0x50)}",
             f"pwm             {struct.unpack_from('<H',d,H_PWM)[0]} / bottom {struct.unpack_from('<H',d,H_BOT_PWM)[0]}",
             f"enc key         {self.key:#010x}   print time {_u32(d,H_PRINT_TIME)} s"]
        return "\n".join(s)


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------
@dataclass
class Layer:
    image: object                # (2560, 1620) array (bool, 0/1 or 0..127) or a callable returning one
    exposure_s: float
    z_mm: Optional[float] = None  # None -> auto
    rest_before_lift_s: Optional[float] = None  # None -> use the file-wide value
    lift_mm: Optional[float] = None             # None -> use the file-wide value (per-layer lift distance)


def _norm(img: np.ndarray) -> np.ndarray:
    a = np.asarray(img)
    if a.shape != (RES_Y, RES_X):
        raise ValueError(f"layer image must be {RES_Y}x{RES_X} (rows x cols), got {a.shape}")
    if a.dtype == bool:
        return a.astype(np.uint8) * FULL
    a = a.astype(np.uint8)
    return np.minimum(a, FULL) if a.max() > 1 else a * FULL


def write_ctb(template: str, out: str, layers: List[Layer], *,
              layer_height_mm: float = 0.05,
              lift_mm: float = 0.0, lift_speed: float = 65.0, retract_speed: float = 150.0,
              bottom_lift_mm: Optional[float] = None, bottom_lift_speed: Optional[float] = None,
              rest_before_lift_s: float = 0.0, rest_after_lift_s: float = 0.0,
              rest_after_retract_s: float = 0.0,
              park_z_mm: Optional[float] = None,
              bottom_layers: int = 0,
              header_exposure_s: Optional[float] = None,
              header_bottom_exposure_s: Optional[float] = None,
              motion_from_template: bool = False,
              rest_override_s: Optional[float] = None,
              preview: Optional[np.ndarray] = None,
              preview_crop: bool = True) -> None:
    """Write `out` using the static head of `template` and the given layers.

    park_z_mm: if set, every layer gets this Z (so the carriage never descends);
               otherwise Z = (layer_index+1) * layer_height, like ChiTuBox.
    Rest times are the three ChiTuBox "Rest Time ..." settings; they are stored
    per layer and in three header blocks (verified against boxsmall.ctb).
    bottom_lift_mm applies to the first `bottom_layers` layers (default: = lift_mm).

    preview: a layer image (2560 x 1620) to show as the file's preview instead of the template's
    (landscape, cropped to the lit area unless preview_crop=False); all pointers after the previews
    are recomputed.

    motion_from_template: keep ALL lift/retract distances, speeds (including the second
    "+" stage) and rest times exactly as the template file has them (bottom layers copy the
    template's first layer record, normal layers its last one) instead of writing the
    lift_*/retract_*/rest_* arguments. rest_override_s, if given, replaces only the
    'rest before lift' in that mode. Use it with a file made by ChiTuBox with the motion
    settings you want.
    """
    t = CTB(template)
    head = bytearray(t.d[:t.table_off])
    table_off = t.table_off
    if preview is not None:
        head = _replace_previews(head, make_preview(preview, crop=preview_crop))
        table_off = len(head)
    n = len(layers)
    if n < 1:
        raise ValueError("need at least one layer")
    key = t.key
    blift = lift_mm if bottom_lift_mm is None else bottom_lift_mm
    bspeed = lift_speed if bottom_lift_speed is None else bottom_lift_speed
    rests = (rest_before_lift_s, rest_after_lift_s, rest_after_retract_s)
    if motion_from_template:
        def _rec(i):
            L0 = t.layers[i]
            return bytes(t.d[L0.data_off - 84 + 40:L0.data_off])      # per-layer record bytes +40..+83
        tpl_bot, tpl_nor = _rec(0), _rec(t.layer_count - 1)

    exps = [float(L.exposure_s) for L in layers]
    zs = [L.z_mm if L.z_mm is not None else (park_z_mm if park_z_mm is not None
          else (i + 1) * layer_height_mm) for i, L in enumerate(layers)]

    # layer blobs
    rles, max_len = [], 0
    for L in layers:
        img = _norm(L.image() if callable(L.image) else L.image)
        rle = rle7_encode(img)
        area = float(np.count_nonzero(img)) * PITCH_MM * PITCH_MM
        rles.append((rle, area))
        max_len = max(max_len, len(rle))

    table = bytearray()
    body = bytearray()
    pos = table_off + 36 * n
    travel = 0.0
    layer_rests = []
    for i, (rle, area) in enumerate(rles):
        ex_start = pos
        data_off = ex_start + 84
        entry = struct.pack("<fffIIIIII", zs[i], exps[i], 0.0, data_off, len(rle), 0, 84, 0, 0)
        table += entry
        total = 84 + len(rle) + 8
        if motion_from_template:
            rec = bytearray(tpl_bot if i < bottom_layers else tpl_nor)
            if rest_override_s is not None:
                struct.pack_into("<f", rec, 28, rest_override_s)       # +68 rest before lift
            lrests = struct.unpack_from("<fff", rec, 28)
            d1, s1, d2, s2, rs1, rd2, rs2 = struct.unpack_from("<fffffff", rec, 0)
            travel += (d1 / s1 * 60 if s1 >= 1 else 0) + (d2 / s2 * 60 if s2 >= 1 else 0) \
                      + (d1 / rs1 * 60 if rs1 >= 1 else 0) + (rd2 / rs2 * 60 if rs2 >= 1 else 0)
            layer_rests.append(sum(lrests))
            ex = bytearray(entry) + struct.pack("<I", total) + bytes(rec)
        else:
            lift = layers[i].lift_mm if layers[i].lift_mm is not None else (blift if i < bottom_layers else lift_mm)
            if lift > 0:
                travel += lift / lift_speed * 60 + lift / retract_speed * 60
            rb = layers[i].rest_before_lift_s if layers[i].rest_before_lift_s is not None else rest_before_lift_s
            lrests = (rb, rest_after_lift_s, rest_after_retract_s)
            layer_rests.append(sum(lrests))
            ex = bytearray(entry)
            ex += struct.pack("<I", total)                    # +36
            ex += struct.pack("<ff", lift, bspeed if i < bottom_layers else lift_speed)   # +40 lift dist, +44 lift speed
            ex += struct.pack("<II", 0, 0)                    # +48,+52 (2nd-stage lift)
            ex += struct.pack("<f", retract_speed)            # +56
            ex += struct.pack("<II", 0, 0)                    # +60,+64 (2nd-stage retract)
            ex += struct.pack("<fff", *lrests)                # +68 before lift, +72 after lift, +76 after retract
            ex += struct.pack("<f", 255.0)                    # +80 LED PWM
        assert len(ex) == 84, len(ex)
        body += ex + crypt(rle, key, i) + struct.pack("<fI", area, 0)
        pos += total

    # patch header / ext blocks (offsets verified on box/cube/boxsmall)
    ext = _u32(head, H_EXT_OFF)          # ExtConfig (112)
    ext2 = _u32(head, H_EXT2_OFF)        # ExtConfig2 (172)
    ex3 = _u32(head, ext2 + 0x40)        # ExtConfig3 (248)
    total_time = sum(exps) + sum(layer_rests)
    struct.pack_into("<f", head, H_LAYER_H, layer_height_mm)
    struct.pack_into("<f", head, H_EXP, header_exposure_s if header_exposure_s is not None
                     else (exps[-1] if n > 1 else exps[0]))
    struct.pack_into("<f", head, H_BOT_EXP, header_bottom_exposure_s if header_bottom_exposure_s is not None
                     else exps[0])
    struct.pack_into("<f", head, H_LIGHTOFF, 0.0)
    struct.pack_into("<I", head, H_BOT_COUNT, bottom_layers)
    struct.pack_into("<I", head, H_LAYER_TBL, table_off)
    struct.pack_into("<I", head, H_LAYER_CNT, n)
    struct.pack_into("<I", head, H_PRINT_TIME, int(total_time + travel))
    struct.pack_into("<fff", head, ext + 20, 0.0, 0.0, 0.0)          # resin estimates (zero)
    struct.pack_into("<I", head, ext + 40, bottom_layers)
    if not motion_from_template:
        # ExtConfig: bottom lift, bottom speed, lift, speed, retract speed
        struct.pack_into("<fffff", head, ext, blift, bspeed, lift_mm, lift_speed, retract_speed)
        # ExtConfig2: rest before lift (+24), after retract (+52), after lift (+56)
        struct.pack_into("<f", head, ext2 + 24, rest_before_lift_s)
        struct.pack_into("<f", head, ext2 + 52, rest_after_retract_s)
        struct.pack_into("<f", head, ext2 + 56, rest_after_lift_s)
        # ExtConfig3: retract speed, rests (after retract, after lift, before lift)
        struct.pack_into("<f", head, ex3, retract_speed)
        struct.pack_into("<fff", head, ex3 + 24, rest_after_retract_s, rest_after_lift_s, rest_before_lift_s)
    elif rest_override_s is not None:
        struct.pack_into("<f", head, ext2 + 24, rest_override_s)
        struct.pack_into("<f", head, ex3 + 32, rest_override_s)
    # ExtConfig3: total time (exposure + rests), max blob size, layer count
    struct.pack_into("<f", head, ex3 + 40, float(total_time))
    struct.pack_into("<I", head, ex3 + 44, max_len)
    struct.pack_into("<I", head, ex3 + 52, n)
    # ex3+48 (the odd "6"/"0") is copied from the template unchanged

    blob = bytes(head) + bytes(table) + bytes(body)
    blob += struct.pack("<I", zlib.crc32(blob) & M32)
    with open(out, "wb") as fh:
        fh.write(blob)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "info":
        print(CTB(sys.argv[2]).info())
    elif len(sys.argv) >= 4 and sys.argv[1] == "layer":
        from PIL import Image
        c = CTB(sys.argv[2]); i = int(sys.argv[3])
        out = sys.argv[4] if len(sys.argv) > 4 else f"layer{i}.png"
        Image.fromarray((c.layer_image(i).astype(np.uint16) * 255 // 127).astype(np.uint8)).save(out)
        print("wrote", out)
    else:
        print("usage: ctbio.py info file.ctb | ctbio.py layer file.ctb N [out.png]")
