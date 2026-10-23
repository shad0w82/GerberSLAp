"""A layer as vector shapes for the browser: polygons in millimetres, relative to the board's centre, with the holes cut out.

The browser draws these with its own placement (position, rotation, mirror), so one request per layer is enough however many
times the board is moved. The shapes are the same ones the pipeline rasterises (`file_geometry`), only lightly simplified (2 um:
far below a pixel); the exact preview and the file always come from the full geometry on the server.
"""
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
import shapely
from shapely.affinity import translate

from ..cad.sniff import probe
from ..core import holes_geometry
from ..model import FileRef, Role
from .pipeline import PipelineError, Reader, file_geometry

SIMPLIFY_MM = 0.002
VECTOR_ROLES = (Role.COPPER, Role.SILK, Role.OUTLINE, Role.DRILL, Role.MASK)
_NEGATIVE_CHECKED = (Role.COPPER, Role.SILK, Role.OUTLINE)


@dataclass(frozen=True)
class AreaSpec:
    """What a mask needs to know about its board: the outline file the area comes from (None if there is none) and the size of the
    board's extent, for the rectangle used when the outline does not give an area."""
    outline: Optional[FileRef]
    width_mm: float
    height_mm: float


def _flat(ring) -> list:
    """A ring as [x0, y0, x1, y1, ...] in micrometre precision, without the repeated closing point."""
    return np.round(np.asarray(ring.coords, dtype=float)[:-1], 3).ravel().tolist()


def encode(geom) -> dict:
    polys = []
    for part in shapely.get_parts(geom):
        if part.geom_type != "Polygon" or part.is_empty:
            continue
        rings = [_flat(part.exterior), *(_flat(r) for r in part.interiors)]
        if len(rings[0]) >= 6:
            polys.append(rings)
    bounds = [round(v, 3) for v in geom.bounds] if not geom.is_empty else None
    return {"polygons": polys, "bounds": bounds, "vertices": sum(len(r) // 2 for p in polys for r in p)}


def layer_vectors(reader: Reader, role: Role, refs: Sequence[FileRef], *, center, min_outline_mm: float = 0.3,
                  holes: Optional[Sequence[FileRef]] = None, area: Optional[AreaSpec] = None) -> dict:
    """The shapes of the files of one layer. `holes`, if given, are drill files whose holes are cut out of the result (so the
    browser draws a drilled pad as a ring without any compositing). A mask is the board's area minus what its file draws, so it needs
    `area`. Raises PipelineError for what the pipeline refuses too."""
    if role not in VECTOR_ROLES:
        raise PipelineError("layer_unsupported", f"a {role.value} layer has no shapes to draw", role=role.value)
    board_area = None
    if role is Role.MASK:
        if area is None:
            raise PipelineError("area_missing", "a mask is drawn on the board's area, which was not given")
        board_area = reader.area(area.outline, (area.width_mm, area.height_mm), center)[0]
    parts = []
    for ref in refs:
        if role in _NEGATIVE_CHECKED and probe(ref.name, reader.data(ref)).negative:
            raise PipelineError("negative_layer", f"{ref.name} is a negative image", file=ref.name)
        parts.append(file_geometry(role, reader.read(ref).file, min_outline_mm, board_area))
    geom = shapely.union_all(parts) if parts else shapely.Polygon()
    if holes and role is not Role.DRILL:
        cut = shapely.union_all([holes_geometry(reader.read(h).file) for h in holes])
        if not cut.is_empty:
            geom = geom.difference(cut)
    geom = translate(geom, -center[0], -center[1])
    if not geom.is_empty:
        geom = geom.simplify(SIMPLIFY_MM, preserve_topology=True)
    return encode(geom)
