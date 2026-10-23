"""Geometry -> per-pixel coverage on a regular grid, then the exposure mask.

Coverage is supersampled: each pixel is sampled at `supersample` x `supersample` points (sub-pixel centres).
At 51 um pixels, 8x8 and 16x16 give no wrong pixel against the exact area on any test shape and at any
rotation; 4x4 does, so lower values are refused. The sampling is done with
numpy on the polygon edges (no intermediate image), so memory stays small whatever the supersampling.

Pixel (row r, column c) covers x in [ox + c*pitch, ox + (c+1)*pitch] and y in [oy + (H-1-r)*pitch, oy + (H-r)*pitch];
row 0 is the top (largest y), as in an image.
"""
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import Polygon

MIN_SUPERSAMPLE = 8


@dataclass(frozen=True)
class Grid:
    width: int                 # pixels
    height: int
    pitch: float = 0.051       # mm per pixel
    ox: float = 0.0            # mm, lower-left corner of the grid
    oy: float = 0.0

    @property
    def extent(self):
        """(xmin, ymin, xmax, ymax) in mm."""
        return (self.ox, self.oy, self.ox + self.width * self.pitch, self.oy + self.height * self.pitch)

    def to_pixel(self, x, y):
        """Plane position in mm -> (column, row) as floats; pixel (r, c) spans [c, c+1] x [r, r+1]."""
        return ((x - self.ox) / self.pitch, (self.oy + self.height * self.pitch - y) / self.pitch)

    def to_mm(self, col, row):
        return (self.ox + col * self.pitch, self.oy + (self.height - row) * self.pitch)


def _parts(geom):
    return [g for g in shapely.get_parts(geom) if isinstance(g, Polygon) and not g.is_empty]


def _edges(geom, grid, S):
    """All ring edges in sample coordinates (X right, Y down, one unit per sub-pixel), oriented so ya < yb."""
    top, p = grid.oy + grid.height * grid.pitch, grid.pitch
    segs = []
    for poly in _parts(geom):
        for ring in (poly.exterior, *poly.interiors):
            c = np.asarray(ring.coords, dtype=np.float64)
            x, y = (c[:, 0] - grid.ox) / p * S, (top - c[:, 1]) / p * S
            segs.append(np.column_stack([x[:-1], y[:-1], x[1:], y[1:]]))
    if not segs:
        return None
    e = np.concatenate(segs)
    keep = e[:, 1] != e[:, 3]                                    # horizontal edges never cross a sample row
    e = e[keep]
    swap = e[:, 1] > e[:, 3]
    e[swap] = e[swap][:, [2, 3, 0, 1]]
    return e


def coverage(geom, grid, supersample=16, band=256):
    """Fraction (0..1, float32) of every pixel covered by `geom`; shape (height, width).

    Every pixel is sampled at supersample x supersample sub-pixel centres and a sample counts when it lies inside
    the geometry (even-odd rule over all rings at once). The geometry must be what layer_geometry and
    compose_material return: valid polygons whose parts do not overlap. No sample is added or lost at the edges, so
    sizes and positions carry no bias beyond the 1/supersample pixel quantisation.
    """
    if supersample < MIN_SUPERSAMPLE:
        raise ValueError(f"supersample must be at least {MIN_SUPERSAMPLE}: 4x4 gives wrong pixels on thin lines")
    S, W, H = int(supersample), grid.width, grid.height
    out = np.zeros((H, W), dtype=np.float32)
    edges = _edges(geom, grid, S)
    if edges is None:
        return out
    xa, ya, xb, yb = edges.T
    slope = (xb - xa) / (yb - ya)
    jmin, jmax = np.ceil(ya - 0.5).astype(np.int64), np.ceil(yb - 0.5).astype(np.int64)    # rows y in [ya, yb)
    stride = W + 1
    for r0 in range(0, H, band):
        r1 = min(H, r0 + band)
        js, je = r0 * S, r1 * S
        lo, hi = np.maximum(jmin, js), np.minimum(jmax, je)
        n = np.maximum(hi - lo, 0)
        total = int(n.sum())
        if not total:
            continue
        sel = np.flatnonzero(n)
        rep = np.repeat(sel, n[sel])
        offs = np.arange(total) - np.repeat(np.cumsum(n[sel]) - n[sel], n[sel])
        rows = lo[rep] + offs
        x = xa[rep] + (rows + 0.5 - ya[rep]) * slope[rep]
        order = np.lexsort((x, rows))
        rows, x = rows[order], x[order]
        if (np.bincount(rows - js, minlength=je - js) & 1).any():
            raise ValueError("unbalanced crossings: the geometry is not a set of closed, non-overlapping rings")
        i0 = np.clip(np.ceil(x[0::2] - 0.5), 0, W * S).astype(np.int64)         # first sample inside the span
        i1 = np.clip(np.ceil(x[1::2] - 0.5), 0, W * S).astype(np.int64)         # first sample after it
        pr = rows[0::2] // S - r0
        ok = i1 > i0
        i0, i1, pr = i0[ok], i1[ok], pr[ok]
        c0, c1 = i0 // S, (i1 - 1) // S
        same = c0 == c1
        size = (r1 - r0) * stride
        direct = np.bincount(np.concatenate([pr[same] * stride + c0[same], pr[~same] * stride + c0[~same],
                                             pr[~same] * stride + c1[~same]]),
                             weights=np.concatenate([(i1 - i0)[same], (S - i0 % S)[~same], (i1 - c1 * S)[~same]]),
                             minlength=size)
        wide = ~same & (c1 > c0 + 1)                                            # whole pixels between the ends
        diff = (np.bincount(pr[wide] * stride + c0[wide] + 1, minlength=size) * S
                - np.bincount(pr[wide] * stride + c1[wide], minlength=size) * S)
        total_counts = direct.reshape(-1, stride) + np.cumsum(diff.reshape(-1, stride), axis=1)
        out[r0:r1] = (total_counts[:, :W] / (S * S)).astype(np.float32)
    return np.clip(out, 0.0, 1.0)


def binarize(cov, threshold=0.5):
    """Pixels where at least half is covered."""
    return cov >= threshold


def exposure_mask(material_cov, resist, threshold=0.5):
    """True where UV light must pass.

    Positive resist: light removes the resist, so it must pass where the copper is to be etched away, that is
    everywhere except the material. Negative resist: light passes where the material stays.
    """
    mat = binarize(material_cov, threshold)
    if resist == "positive":
        return ~mat
    if resist == "negative":
        return mat
    raise ValueError("resist must be 'positive' or 'negative'")
