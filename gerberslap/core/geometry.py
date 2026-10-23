"""From parsed Gerber/Excellon files to shapely geometry, and placing that geometry on the plane.

Everything is converted to polygons *before* any transform, so mirroring cannot flip arc directions and any
rotation angle works. Units are millimetres, y up.
"""
import contextlib
import io
import math
from dataclasses import dataclass

import shapely
from shapely.geometry import LineString, LinearRing, Point, Polygon, box
from shapely.affinity import affine_transform

from gerbonara import MM
from gerbonara import graphic_primitives as gp
from gerbonara.utils import approximate_arc

from .gerber_io import LOCK

TOL = 0.0005        # mm: maximum flattening error of circles and arcs (0.5 um, 1/100 of a 51 um pixel)


def _quad_segs(r, tol=TOL):
    r = max(r, 1e-6)
    step = 2 * math.acos(max(0.0, 1 - tol / r)) if tol < r else math.pi / 2
    return max(4, min(256, math.ceil((math.pi / 2) / max(step, 1e-3))))


def _disc(x, y, r, tol=TOL):
    """Regular polygon with the *area* of the circle (radius widened by <= 0.5 tolerance), so hole and pad areas
    carry no bias; an inscribed polygon would lose up to 0.6 % of the area of a 0.3 mm hole."""
    qs = _quad_segs(r, tol)
    n = 4 * qs
    return Point(x, y).buffer(r * math.sqrt(2 * math.pi / (n * math.sin(2 * math.pi / n))), quad_segs=qs)


def _polygons(g):
    """Valid polygon(s) of `g`: self-intersecting regions are repaired instead of failing later."""
    if g is None or g.is_empty:
        return None
    if not g.is_valid:
        g = shapely.make_valid(g)
    parts = [p for p in shapely.get_parts(g) if isinstance(p, Polygon) and not p.is_empty]
    return shapely.union_all(parts) if parts else None


def _stroke(points, width, tol=TOL):
    r = width / 2
    return LineString(points).buffer(r, quad_segs=_quad_segs(r, tol))


def _arc_points(p, tol=TOL):
    return list(approximate_arc(p.cx, p.cy, p.x1, p.y1, p.x2, p.y2, p.clockwise, max_error=tol))


def primitive_to_geometry(p, tol=TOL):
    """Polygon of one gerbonara graphic primitive, or None when it has no area."""
    if isinstance(p, gp.Circle):
        return _disc(p.x, p.y, p.r, tol)
    if isinstance(p, gp.ArcPoly):
        pts = p.approximate_arcs(max_error=tol).outline
        return _polygons(Polygon(pts)) if len(pts) >= 3 else None
    if isinstance(p, gp.Rectangle):
        # Rectangle.to_arc_poly() is the *unrotated bounding box* of the rotated rectangle (meant for extents only)
        c, s, hw, hh = math.cos(p.rotation), math.sin(p.rotation), p.w / 2, p.h / 2
        return Polygon([(p.x + c * dx - s * dy, p.y + s * dx + c * dy)
                        for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))])
    if isinstance(p, gp.Line):
        if math.dist((p.x1, p.y1), (p.x2, p.y2)) < 1e-9:
            return _disc(p.x1, p.y1, p.width / 2, tol)
        return _stroke([(p.x1, p.y1), (p.x2, p.y2)], p.width, tol)
    if isinstance(p, gp.Arc):
        r, rad = p.width / 2, math.dist((p.cx, p.cy), (p.x1, p.y1))
        if p.is_circle:                                             # full circle: an annulus
            outer = _disc(p.cx, p.cy, rad + r, tol)
            return outer.difference(_disc(p.cx, p.cy, max(rad - r, 1e-9), tol)) if rad > r else outer
        return _stroke(_arc_points(p, tol), p.width, tol)
    raise NotImplementedError(f"graphic primitive {type(p).__name__}")


def _primitives(gfile):
    with LOCK, contextlib.redirect_stdout(io.StringIO()):          # gerbonara leaves a debug print in macro code
        return [p for obj in gfile.objects for p in obj.to_primitives(unit=MM)]


def layer_geometry(gfile, tol=TOL):
    """Geometry drawn by a Gerber or Excellon file: objects in file order, dark adds and clear removes."""
    runs, cur, cur_dark = [], [], True
    for p in _primitives(gfile):
        g = primitive_to_geometry(p, tol)
        if g is None or g.is_empty:
            continue
        if p.polarity_dark != cur_dark and cur:
            runs.append((cur_dark, cur))
            cur = []
        cur_dark = p.polarity_dark
        cur.append(g)
    if cur:
        runs.append((cur_dark, cur))
    result = Polygon()
    for dark, geoms in runs:
        u = shapely.union_all(geoms)
        result = result.union(u) if dark else result.difference(u)
    return result


def holes_geometry(excellon_file, tol=TOL):
    """All drilled holes and slots at their exact diameter."""
    return layer_geometry(excellon_file, tol)


def _linework(gfile, tol):
    """(centre line, stroke width or None) for every line, arc and region boundary of an outline file."""
    out = []
    for p in _primitives(gfile):
        if isinstance(p, gp.Line) and math.dist((p.x1, p.y1), (p.x2, p.y2)) > 1e-9:
            out.append((LineString([(p.x1, p.y1), (p.x2, p.y2)]), p.width))
        elif isinstance(p, gp.Arc):
            pts = _arc_points(p, tol) if not p.is_circle else list(
                Point(p.cx, p.cy).buffer(math.dist((p.cx, p.cy), (p.x1, p.y1)), quad_segs=_quad_segs(
                    math.dist((p.cx, p.cy), (p.x1, p.y1)), tol)).exterior.coords)
            out.append((LineString(pts), p.width))
        elif isinstance(p, gp.ArcPoly):
            pts = p.approximate_arcs(max_error=tol).outline
            if len(pts) >= 3:
                out.append((LinearRing(pts), None))
    return out


def outline_lines(gfile, tol=TOL):
    """Centre line of the board outline, with no stroke width: size and centre of the board come from this."""
    lines = [ln for ln, _ in _linework(gfile, tol)]
    return shapely.union_all(lines) if lines else LineString()


def outline_strokes(gfile, min_width, tol=TOL):
    """Outline as copper stroke, centred on the drawn edge. Each stroke is max(its Gerber width, min_width)."""
    strokes = []
    for line, width in _linework(gfile, tol):
        w = max(width or 0.0, min_width)
        strokes.append(line.buffer(w / 2, quad_segs=_quad_segs(w / 2, tol)))
    return shapely.union_all(strokes) if strokes else Polygon()


# --- the area of a board ------------------------------------------------------------------------
AREA_SNAP = 0.001          # mm: outline pieces whose ends are less than twice this apart are taken as joined (files round to 0.1-1 um)
AREA_EXTENT_TOL = 0.01     # mm: the enclosed area must reach the outline's extent this closely, or the outline is not what it seems
AREA_EXTENT_MISMATCH = 0.05  # mm: and the board's extent as the importer fixed it, this closely


@dataclass(frozen=True)
class BoardArea:
    """`geometry` is the region the outline encloses (cut-outs are holes), or None with the `reason` why not:
    "no_outline" (nothing drawn) or "not_closed" (no closed contour, or the closed ones do not reach the whole drawing)."""
    geometry: object
    reason: object = None


def board_area(gfile, snap=AREA_SNAP, tol=TOL):
    """The region enclosed by the outline file: its closed contours filled with the even-odd rule, so a closed contour inside
    another one (a mounting hole, a slot) is a cut-out and two separate ones (a panel) are two boards.

    Contours are taken on the centre line of the drawn edge, as for the board's extent. Pieces whose ends are off by a few
    micrometres (rounded coordinates) are joined; anything wider is open. When the closed contours do not reach the extent of the
    whole drawing (an open contour next to a closed circle, a dimension line outside the board) nothing is guessed: the answer is None."""
    lines = [ln for ln, _ in _linework(gfile, tol)]
    if not lines:
        return BoardArea(None, "no_outline")
    net = shapely.union_all(lines)
    thick = net.buffer(snap)
    region = Polygon()
    for part in shapely.get_parts(thick):
        if isinstance(part, Polygon):
            for ring in part.interiors:
                region = region.symmetric_difference(Polygon(ring).buffer(snap))       # back out to the centre line
    if region.is_empty or any(abs(a - b) > AREA_EXTENT_TOL for a, b in zip(net.bounds, region.bounds)):
        return BoardArea(None, "not_closed")
    return BoardArea(region)


def area_or_rectangle(gfile, *, size, center, tol=TOL):
    """The area of a board for a layer that needs one, always something: the region the outline `gfile` encloses (None if there is
    no outline file) or, when that cannot be had, the rectangle of the board's extent (`size` and `center`, in the file's own
    coordinates). Returns (geometry, reason): `reason` is None when the outline gave it, else why the rectangle is used:
    "no_outline", "not_closed" or "extent_mismatch" (the outline's area is not the extent the board was given)."""
    w, h = size
    rect = box(center[0] - w / 2, center[1] - h / 2, center[0] + w / 2, center[1] + h / 2)
    if gfile is None:
        return rect, "no_outline"
    a = board_area(gfile, tol=tol)
    if a.geometry is None:
        return rect, a.reason
    if any(abs(x - y) > AREA_EXTENT_MISMATCH for x, y in zip(a.geometry.bounds, rect.bounds)):
        return rect, "extent_mismatch"
    return a.geometry, None


def compose_material(shapes, outline=None, holes=None):
    """Where material stays: (union of `shapes` and outline strokes) minus the holes.

    The resist polarity is applied afterwards (raster.exposure_mask), so this works for positive and negative resist.
    """
    parts = [g for g in shapes if g is not None and not g.is_empty]
    if outline is not None and not outline.is_empty:
        parts.append(outline)
    material = shapely.union_all(parts) if parts else Polygon()
    if holes is not None and not holes.is_empty:
        material = material.difference(holes)
    return material


# --- placement on the plane ---------------------------------------------------------------------
def extent_center(geom):
    minx, miny, maxx, maxy = geom.bounds
    return ((minx + maxx) / 2, (miny + maxy) / 2)


def extent_size(geom):
    minx, miny, maxx, maxy = geom.bounds
    return (maxx - minx, maxy - miny)


@dataclass(frozen=True)
class Placement:
    """Where a board sits on the plane, seen from above with the user in front of the printer.

    `center` is the plane position (u, v) in mm of the board's extent centre; `angle` rotates counterclockwise
    (degrees) and `mirror` flips left-right, both about that centre; mirror is applied before the rotation.
    """
    center: tuple
    angle: float = 0.0
    mirror: bool = False

    def matrix(self, source_center):
        """Shapely affine matrix (a, b, d, e, xoff, yoff) taking the board's own coordinates to the plane."""
        t = math.radians(self.angle)
        m = -1.0 if self.mirror else 1.0
        a, b, d, e = math.cos(t) * m, -math.sin(t), math.sin(t) * m, math.cos(t)
        cx, cy = source_center
        return (a, b, d, e, self.center[0] - (a * cx + b * cy), self.center[1] - (d * cx + e * cy))


def place(geom, placement, source_center):
    return affine_transform(geom, placement.matrix(source_center))
