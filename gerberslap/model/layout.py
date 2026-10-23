"""Where boards sit on the plane: extents, margins, overlaps. Plain geometry on the numbers the model holds.

A board's extent here is the bounding box of its own box after mirror and rotation. For a board that is not a rectangle
that is a little larger than the true outline, which is right for warnings; the exact shape is used by the pipeline.
"""
import math
from dataclasses import dataclass

from pydantic import Field

from .base import Model
from .project import Board

OVERLAP_TOLERANCE_MM = 0.01       # two extents closer than this on either axis do not count as overlapping
OUTSIDE_TOLERANCE_MM = 1e-6


class Plane(Model):
    """The exposure plane: the LCD seen from above with the user in front of the printer (mm)."""
    width_mm: float = Field(gt=0)      # u, left to right
    height_mm: float = Field(gt=0)     # v, front to back


@dataclass(frozen=True)
class Extent:
    minx: float
    maxx: float
    miny: float
    maxy: float

    @property
    def width(self) -> float:
        return self.maxx - self.minx

    @property
    def height(self) -> float:
        return self.maxy - self.miny

    @property
    def center(self) -> tuple:
        return ((self.minx + self.maxx) / 2, (self.miny + self.maxy) / 2)


@dataclass(frozen=True)
class Margins:
    """Distances from the board's extent to the four edges of the plane; negative means it goes past the edge."""
    left: float
    right: float
    front: float
    back: float


def board_extent(board: Board) -> Extent:
    p = board.placement
    hw, hh = board.size.width_mm / 2, board.size.height_mm / 2
    t = math.radians(p.angle)
    c, s = math.cos(t), math.sin(t)
    m = -1.0 if p.mirror else 1.0
    xs, ys = [], []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        x, y = sx * hw * m, sy * hh                      # mirror first, then rotate, both about the centre
        xs.append(p.x + x * c - y * s)
        ys.append(p.y + x * s + y * c)
    return Extent(min(xs), max(xs), min(ys), max(ys))


def margins(extent: Extent, plane: Plane) -> Margins:
    return Margins(left=extent.minx, right=plane.width_mm - extent.maxx,
                   front=extent.miny, back=plane.height_mm - extent.maxy)


def is_outside(extent: Extent, plane: Plane) -> bool:
    m = margins(extent, plane)
    return min(m.left, m.right, m.front, m.back) < -OUTSIDE_TOLERANCE_MM


def overlaps(a: Extent, b: Extent) -> bool:
    return (min(a.maxx, b.maxx) - max(a.minx, b.minx) > OVERLAP_TOLERANCE_MM
            and min(a.maxy, b.maxy) - max(a.miny, b.miny) > OVERLAP_TOLERANCE_MM)
