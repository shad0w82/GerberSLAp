"""Independent reference for the raster tests: exact area coverage per pixel.

Deliberately shares no code with gerberslap.core.raster. Edge pixels are those touched by the polygon boundary
(densified to a quarter pixel, plus one pixel of margin); they get the exact intersection area from shapely. All
other pixels are fully inside or fully outside, told apart by a coarse pass. Components of a unioned geometry are
disjoint, so their coverages simply add.
"""
import math

import numpy as np
import shapely
from PIL import Image, ImageDraw
from shapely.geometry import MultiPolygon, Polygon

from gerberslap.core import Grid


def make_grid(geom, margin=1.0, pitch=0.051):
    """Grid at integer-mm origin covering `geom` plus a margin."""
    x0, y0, x1, y1 = geom.bounds
    ox, oy = math.floor(x0 - margin), math.floor(y0 - margin)
    return Grid(math.ceil((x1 - ox + margin) / pitch), math.ceil((y1 - oy + margin) / pitch), pitch, ox, oy)


def _coarse(poly, x_left, y_top, w, h, p, S):
    im = Image.new("L", (w * S, h * S), 0)
    d = ImageDraw.Draw(im)

    def tr(coords):
        return [((x - x_left) / p * S - 0.5, (y_top - y) / p * S - 0.5) for x, y in coords]

    d.polygon(tr(poly.exterior.coords), fill=255)
    for ring in poly.interiors:
        d.polygon(tr(ring.coords), fill=0)
    return np.asarray(im.resize((w, h), Image.BOX), dtype=np.float32) / 255.0


def _dilate(m):
    q = np.pad(m, 1)
    out = np.zeros_like(m)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            out |= q[dy:dy + m.shape[0], dx:dx + m.shape[1]]
    return out


def exact_coverage(geom, grid, S0=8):
    W, H, p, ox, oy = grid.width, grid.height, grid.pitch, grid.ox, grid.oy
    out = np.zeros((H, W), dtype=np.float32)
    parts = [g for g in shapely.get_parts(geom) if isinstance(g, Polygon) and not g.is_empty]
    for poly in parts:
        minx, miny, maxx, maxy = poly.bounds
        c0, c1 = max(0, math.floor((minx - ox) / p)), min(W, math.ceil((maxx - ox) / p))
        r0, r1 = max(0, math.floor((oy + H * p - maxy) / p)), min(H, math.ceil((oy + H * p - miny) / p))
        if r1 <= r0 or c1 <= c0:
            continue
        w, h = c1 - c0, r1 - r0
        cov = _coarse(poly, ox + c0 * p, oy + (H - r0) * p, w, h, p, S0)
        edge = np.zeros((h, w), dtype=bool)
        for ring in (poly.exterior, *poly.interiors):
            pts = np.asarray(shapely.segmentize(ring, p / 4).coords)
            cc_ = np.floor((pts[:, 0] - ox) / p).astype(int) - c0
            rr_ = np.floor((oy + H * p - pts[:, 1]) / p).astype(int) - r0
            inside = (cc_ >= 0) & (cc_ < w) & (rr_ >= 0) & (rr_ < h)
            edge[rr_[inside], cc_[inside]] = True
        edge = _dilate(edge)
        sub = np.where(edge, 0.0, np.round(cov)).astype(np.float32)
        rr, cc = np.nonzero(edge)
        if len(rr):
            x0 = ox + (c0 + cc) * p
            y1 = oy + (H - (r0 + rr)) * p
            shapely.prepare(poly)
            sub[rr, cc] = shapely.area(shapely.intersection(poly, shapely.box(x0, y1 - p, x0 + p, y1))) / (p * p)
        out[r0:r1, c0:c1] += sub
    return np.clip(out, 0, 1)


def far_errors(cov, ref):
    """Pixels that, binarized at 0.5, differ from the reference where the reference is clearly inside or outside
    (coverage < 0.25 or > 0.75): real errors, not edge rounding."""
    return int((((cov >= 0.5) != (ref >= 0.5)) & ((ref < 0.25) | (ref > 0.75))).sum())


def max_error(cov, ref):
    return float(np.abs(cov - ref).max())
