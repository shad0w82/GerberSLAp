"""From a project to the mask of the exposure plane.

For every board, the layers that are on give the material (copper and silkscreen as drawn, the outline as a copper line
at least `min_outline_mm` wide, the solder mask as the board's area minus the openings the file draws, minus the holes if
the holes layer is on); the material is placed on the plane with the
board's position, rotation and mirror; all boards are merged (where layers overlap the result is the sum); the coverage of
every pixel is computed once from the vector geometry (never by resampling a picture); and the resist polarity is applied
last. The grid, the polarity and the supersampling are parameters: nothing here knows a printer.

Reading Gerber files and building a board's material are the slow part, so they are kept in a cache keyed by file hash
and by what is switched on: moving a board costs a raster, not a re-read.
"""
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional

import numpy as np
import shapely

from ..cad.sniff import probe
from ..core import (GerberError, Grid, area_or_rectangle, coverage, compose_material, exposure_mask, holes_geometry,
                    layer_geometry, outline_strokes, place, read_file)
from ..model import Board, C, FileRef, Issue, Polarity, Project, Role, Severity

EDGE_TOLERANCE_MM = 1e-6
_NEGATIVE_CHECKED = (Role.COPPER, Role.SILK, Role.OUTLINE)


class PipelineError(Exception):
    """The project cannot be turned into a mask. `code` and `params` are for the interface, which owns the wording."""

    def __init__(self, code: str, detail: str = "", **params):
        super().__init__(detail or code)
        self.code, self.detail, self.params = code, detail, params


class PipelineCache:
    """A small thread-safe least-recently-used memo for parsed files and boards' materials."""

    def __init__(self, max_entries: int = 128):
        self.max_entries = max_entries
        self._items: OrderedDict = OrderedDict()
        self._lock = threading.RLock()
        self.hits = self.misses = 0

    def get(self, key, make: Callable):
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                self.hits += 1
                return self._items[key]
            self.misses += 1
            value = make()
            self._items[key] = value
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)
            return value

    def __len__(self):
        return len(self._items)


@dataclass(frozen=True, eq=False)
class Render:
    grid: Grid
    material: np.ndarray          # float32 coverage 0..1 of the material, shape (height, width), row 0 at the back
    mask: np.ndarray              # bool, True where UV light must pass (the polarity applied)
    polarity: Polarity
    supersample: int
    issues: tuple = field(default=())

    @property
    def lit_pixels(self) -> int:
        return int(np.count_nonzero(self.mask))


class Reader:
    """Reads the files of a project by hash, parsing each once (through the cache)."""

    def __init__(self, files: Mapping, cache: PipelineCache):
        self.files, self.cache = files, cache

    def data(self, ref: FileRef) -> bytes:
        try:
            return self.files[ref.sha256]
        except KeyError:
            raise PipelineError("file_missing", f"{ref.name} is not in the cache", file=ref.name, sha256=ref.sha256) from None

    def read(self, ref: FileRef):
        data = self.data(ref)

        def make():
            try:
                return read_file(ref.name, data)
            except GerberError as exc:
                raise PipelineError("unreadable", str(exc), file=ref.name, reason=str(exc.reason)[:200]) from exc
        return self.cache.get(("read", ref.sha256), make)

    def area(self, outline: Optional[FileRef], size, center):
        """(geometry, reason) of a board's area, in the coordinates of its files: what the outline file encloses, or the rectangle of
        its extent when it cannot be had (`reason` says why; None when the outline gave it). See `core.area_or_rectangle`."""
        key = ("area", outline.sha256 if outline else None, round(size[0], 6), round(size[1], 6), round(center[0], 6), round(center[1], 6))
        return self.cache.get(key, lambda: area_or_rectangle(self.read(outline).file if outline else None, size=size, center=center))

    def board_area(self, board: Board):
        layer = board.area_outline
        return self.area(layer.files[0] if layer else None, (board.size.width_mm, board.size.height_mm), board.source_center)


def _material_key(board: Board, min_outline_mm: float):
    on = tuple(sorted((layer.role.value, tuple(f.sha256 for f in layer.files)) for layer in board.layers if layer.on))   # not the order
    area = None                                          # the mask's material depends on the area, which depends on the outline file
    if any(layer.on and layer.role is Role.MASK for layer in board.layers):
        outline = board.area_outline
        area = (outline.files[0].sha256 if outline else None, round(board.size.width_mm, 6), round(board.size.height_mm, 6),
                tuple(round(c, 6) for c in board.source_center))
    return ("material", on, round(min_outline_mm, 6), area)


def file_geometry(role: Role, parsed, min_outline_mm: float, area=None):
    """What one parsed file of a layer contributes, in the coordinates of its own files: the holes as holes, the outline as a copper
    line at least `min_outline_mm` wide centred on the drawn edge, copper and silkscreen as drawn. A solder mask file draws its
    openings, not the mask, so the material is the board's `area` minus them."""
    if role is Role.DRILL:
        return holes_geometry(parsed)
    if role is Role.OUTLINE:
        return outline_strokes(parsed, min_outline_mm)
    if role is Role.MASK:
        if area is None:
            raise ValueError("a mask needs the area of the board")
        return area.difference(layer_geometry(parsed))
    return layer_geometry(parsed)


def validate_board(board: Board, reader: Reader) -> None:
    """Every render checks this, cached material or not: a layer that may not be used must never be drawn."""
    drawing = False
    for layer in board.layers:
        if not layer.on:
            continue
        if layer.status.level == "error":
            raise PipelineError("layer_has_error", f"{layer.name} cannot be used: {layer.status.code}",
                                board_id=board.id, layer_id=layer.id, status_code=layer.status.code)
        if layer.role is Role.IGNORE:
            raise PipelineError("layer_unsupported", f"{layer.name} is ignored and cannot be exposed", board_id=board.id, layer_id=layer.id)
        if layer.role in _NEGATIVE_CHECKED:
            for ref in layer.files:
                if probe(ref.name, reader.data(ref)).negative:
                    # the importer marks these; this is for a project that arrives without the mark. A negative image drawn
                    # as positive would expose the opposite of what the board needs.
                    raise PipelineError("negative_layer", f"{ref.name} is a negative image", board_id=board.id,
                                        layer_id=layer.id, file=ref.name)
        drawing = drawing or layer.draws
    if not drawing:
        raise PipelineError("board_no_layer_on", f"{board.name} has no drawing layer on", board_id=board.id)


def board_material(board: Board, reader: Reader, min_outline_mm: float):
    """Where material stays on this board, in the coordinates of its own files (not yet placed). `validate_board` first."""
    shapes, outlines, holes = [], [], []
    area = None
    for layer in sorted(board.layers, key=lambda layer: (layer.role.value, layer.id)):         # the same whatever order the user keeps them in
        if not layer.on:
            continue
        if layer.role is Role.MASK and area is None:
            area = reader.board_area(board)[0]
        for ref in layer.files:
            g = file_geometry(layer.role, reader.read(ref).file, min_outline_mm, area)
            (holes if layer.role is Role.DRILL else outlines if layer.role is Role.OUTLINE else shapes).append(g)
    return compose_material(shapes, shapely.union_all(outlines) if outlines else None,
                            shapely.union_all(holes) if holes else None)


def render(project: Project, files: Mapping, grid: Grid, polarity: Polarity, *, supersample: int = 16,
           cache: Optional[PipelineCache] = None) -> Render:
    """The exposure mask of the whole project on `grid`. `files` maps sha256 to bytes (what the importer returned).
    Raises PipelineError when something cannot be rendered; never returns a mask with a layer silently missing."""
    cache = cache if cache is not None else PipelineCache()
    reader = Reader(files, cache)
    if not any(board.drawing_layers_on for board in project.boards):
        raise PipelineError("no_layer_on", "no drawing layer is on")
    gx0, gy0, gx1, gy1 = grid.extent
    placed, issues = [], []
    for board in project.boards:
        validate_board(board, reader)
        material = cache.get(_material_key(board, project.min_outline_mm),
                             lambda b=board: board_material(b, reader, project.min_outline_mm))
        geom = place(material, board.placement.to_core(), board.source_center)
        if any(layer.on and layer.role is Role.MASK for layer in board.layers):
            reason = reader.board_area(board)[1]
            if reason:
                issues.append(Issue(code=C.BOARD_AREA_ESTIMATED, severity=Severity.WARNING, board_id=board.id, params={"reason": reason}))
        if not geom.is_empty:
            b = geom.bounds
            if (b[0] < gx0 - EDGE_TOLERANCE_MM or b[1] < gy0 - EDGE_TOLERANCE_MM
                    or b[2] > gx1 + EDGE_TOLERANCE_MM or b[3] > gy1 + EDGE_TOLERANCE_MM):
                issues.append(Issue(code=C.BOARD_CLIPPED, severity=Severity.WARNING, board_id=board.id, params={
                    "extent_mm": [round(v, 3) for v in b], "plane_mm": [round(v, 3) for v in (gx0, gy0, gx1, gy1)]}))
        placed.append(geom)
    cov = coverage(shapely.union_all(placed), grid, supersample)
    return Render(grid=grid, material=cov, mask=exposure_mask(cov, polarity.value), polarity=polarity,
                  supersample=supersample, issues=tuple(issues))
