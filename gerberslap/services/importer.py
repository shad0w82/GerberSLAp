"""Opening a zip: recognise the files, read them, fix the board's size and centre, and say what is wrong with each layer.

The result is a `Board` (layers by file hash, no geometry) plus the files themselves, to put in the cache that the
pipeline reads from. Nothing is guessed in silence: a file that cannot be read, a layer drawn as a negative, a mask that
draws most of the board, holes that do not fall on the board are all marked on the layer with a code, and a layer with an
error starts switched off. A zip with a mask whose board area cannot be had from the outline says so (`board_area_estimated`).
"""
import hashlib
import re
from dataclasses import dataclass
from typing import Optional

from ..cad import ImportRefused, Recognition, recognize
from ..core import GerberError, area_or_rectangle, holes_geometry, layer_geometry, outline_lines, read_file, zip_members
from ..model import (Board, BoardPlacement, C, FileRef, Issue, LC, Layer, LayerStatus, Plane, Role, STACK_ROLES, Severity, Side,
                     Size, area_outline)

DRILL_MARGIN_MM = 2.0                # holes may lie this far outside the board's extent (a hole at the very edge)
JOB_SIZE_TOLERANCE_MM = 1.0
MASK_COVERS_LIMIT = 0.5              # a mask file draws the openings (5-12% of the board in real exports): more than this is suspect
_DRAWN = (Role.COPPER, Role.OUTLINE, Role.SILK)          # read to check they can be, and refused when drawn as a negative
_READ = (*_DRAWN, Role.MASK)                              # the mask is read too, but its declared polarity says nothing (see below)
# The order a board's layers start in, from the top of the stack to the bottom: silkscreen, solder mask and copper of the top side,
# the inner copper layers, then copper, solder mask and silkscreen of the bottom side. The outline and the holes come after, apart
# from the stack (in that order), and the files the exposure does not use last.
_STACK_RANK = {(Role.SILK, Side.TOP): 0, (Role.MASK, Side.TOP): 1, (Role.COPPER, Side.TOP): 2, (Role.COPPER, Side.INNER): 3,
               (Role.COPPER, Side.BOTTOM): 4, (Role.MASK, Side.BOTTOM): 5, (Role.SILK, Side.BOTTOM): 6}
_APART_RANK = {Role.OUTLINE: 8, Role.DRILL: 9, Role.IGNORE: 10}


def _order_key(role: Role, side: Side, name: str):
    """Inner layers and layers of the same kind go by name with the numbers read as numbers (In2 before In10)."""
    rank = _STACK_RANK.get((role, side), 7 if role in STACK_ROLES else _APART_RANK[role])
    return rank, tuple(int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", name))


@dataclass(frozen=True)
class Imported:
    board: Board
    files: dict                  # sha256 -> bytes, for the cache the pipeline reads from
    cad: str
    issues: tuple                # findings about the zip as a whole (no outline, no drill file...)
    skipped: tuple               # names of files that are not layers (reports, job files) or were hidden


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _base(name: str) -> str:
    return name.replace("\\", "/").rsplit("/", 1)[-1]


def _clean(text: str) -> str:
    return re.sub(r"[\x00-\x1f\x7f/\\]", "_", text).strip() or "layer"


def _slug(text: str, taken: set) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]", "_", text).lstrip("_.-")[:56] or "layer"
    out, i = base, 2
    while out in taken:
        out, i = f"{base}_{i}", i + 1
    taken.add(out)
    return out


def _union(boxes):
    boxes = [b for b in boxes if b is not None]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _read(name, data):
    """The parsed file, or the reason it could not be."""
    try:
        return read_file(name, data), None
    except GerberError as exc:
        return None, str(exc.reason)[:200]


def _extent(parsed, rec: Recognition):
    """The board's extent (minx, miny, maxx, maxy) mm: the outline's centre line if there is one, else the copper."""
    outlines = sorted((a for a in rec.assignments if a.role is Role.OUTLINE and not a.negative and parsed.get(a.name)),
                      key=lambda a: -a.confidence)
    for a in outlines:
        lines = outline_lines(parsed[a.name].file)
        if not lines.is_empty:
            return lines.bounds, True, a.name
    boxes = []
    for a in rec.assignments:
        if a.role is Role.COPPER and a.side is not Side.INNER and not a.negative and parsed.get(a.name):
            g = layer_geometry(parsed[a.name].file)
            boxes.append(None if g.is_empty else g.bounds)
    return _union(boxes), False, None


def import_zip(source, *, board_id: str, source_name: Optional[str] = None, name: Optional[str] = None,
               plane: Optional[Plane] = None, mirror: bool = False) -> Imported:
    """`source`: a path or the bytes of a zip. Raises ImportRefused (and its subclass Incompatible) when the zip cannot be
    used at all, GerberError for a zip that is not valid; everything else is reported on the board."""
    contents = zip_members(source)
    members = contents.members
    rec = recognize(members)
    if not any(a.role is Role.COPPER for a in rec.assignments):
        raise ImportRefused("no copper layer found", code="no_copper", params={"cad": rec.cad})

    # read what the exposure can use
    parsed, problems = {}, {}
    for a in rec.assignments:
        if a.role in _READ and a.kind == "gerber":
            parsed[a.name], problems[a.name] = _read(a.name, members[a.name])
    drills = [a for a in rec.assignments if a.role is Role.DRILL and a.kind == "excellon"]
    drill_parsed = {a.name: _read(a.name, members[a.name]) for a in drills}

    extent, from_outline, outline_name = _extent(parsed, rec)
    if extent is None:
        raise ImportRefused("no geometry to size the board from", code="no_geometry", params={"cad": rec.cad})
    w, h = extent[2] - extent[0], extent[3] - extent[1]
    if not (0 < w <= 2000 and 0 < h <= 2000):
        raise ImportRefused("the board's size is not plausible", code="bad_extent", params={"width_mm": w, "height_mm": h})
    centre = ((extent[0] + extent[2]) / 2, (extent[1] + extent[3]) / 2)

    taken: set = set()
    layers = []
    files: dict = {}
    source: dict = {}                # layer id -> the name of the file it was read from

    def ref(a):
        data = members[a.name]
        files[_sha(data)] = data
        return FileRef(name=_clean(_base(a.name)), sha256=_sha(data))

    for a in sorted((a for a in rec.assignments if a.kind == "gerber"), key=lambda a: _order_key(a.role, a.side, a.name)):
        status = LayerStatus()
        if a.role in _READ:
            if problems.get(a.name):
                status = LayerStatus(level="error", code=LC.UNREADABLE, params={"reason": problems[a.name]})
            elif a.negative and a.role is not Role.MASK:
                # a mask is declared negative by some programs (Altium, KiCad) and not by others (EAGLE), and draws its openings in
                # all of them: what the file says about its polarity is not used for it
                status = LayerStatus(level="error", code=LC.NEGATIVE_IMAGE)
        r = ref(a)
        layer = Layer(id=_slug(r.name.rsplit(".", 1)[0], taken), role=a.role, name=r.name, files=(r,),
                      side=a.side, on=False, status=status)
        source[layer.id] = a.name
        layers.append(layer)

    if drills:
        refs = tuple(ref(a) for a in drills)
        status = LayerStatus()
        for a, r in zip(drills, refs):
            res, reason = drill_parsed[a.name]
            if res is None:
                status = LayerStatus(level="error", code=LC.UNREADABLE, params={"reason": reason})
                break
            holes = holes_geometry(res.file)
            if not holes.is_empty:
                b = holes.bounds
                if (b[0] < extent[0] - DRILL_MARGIN_MM or b[1] < extent[1] - DRILL_MARGIN_MM
                        or b[2] > extent[2] + DRILL_MARGIN_MM or b[3] > extent[3] + DRILL_MARGIN_MM):
                    status = LayerStatus(level="error", code=LC.DRILL_OUTSIDE_BOARD,
                                         params={"file": r.name, "margin_mm": DRILL_MARGIN_MM})
                    break
        layers.append(Layer(id=_slug("drill", taken), role=Role.DRILL, name=" + ".join(r.name for r in refs)[:200],
                            files=refs, status=status, on=False))
        layers.sort(key=lambda l: _order_key(l.role, l.side, l.name))

    layers = _switch_on(layers, outline_name)
    layers, area_reason = _check_masks(layers, parsed, source, size=(w, h), centre=centre)

    issues = []
    if not from_outline:
        issues.append(Issue(code=C.NO_OUTLINE, severity=Severity.WARNING, board_id=board_id))
    if area_reason:
        issues.append(Issue(code=C.BOARD_AREA_ESTIMATED, severity=Severity.WARNING, board_id=board_id, params={"reason": area_reason}))
    if not drills:
        issues.append(Issue(code=C.NO_DRILL, severity=Severity.WARNING, board_id=board_id))
    job = rec.info.get("job_size_mm")
    if job and (abs(job[0] - w) > JOB_SIZE_TOLERANCE_MM or abs(job[1] - h) > JOB_SIZE_TOLERANCE_MM):
        issues.append(Issue(code=C.JOB_SIZE_MISMATCH, severity=Severity.WARNING, board_id=board_id,
                            params={"job_mm": list(job), "outline_mm": [round(w, 3), round(h, 3)]}))
    unknown = sorted(_clean(_base(a.name)) for a in rec.assignments if a.kind in ("gerber", "excellon") and a.reason == "unknown")
    if unknown:
        issues.append(Issue(code=C.FILES_UNRECOGNISED, severity=Severity.WARNING, board_id=board_id, params={"names": unknown}))

    placement = BoardPlacement(x=plane.width_mm / 2 if plane else 0.0, y=plane.height_mm / 2 if plane else 0.0, mirror=mirror)
    stem = _base(source_name or "board")
    stem = stem[:-4] if stem.lower().endswith(".zip") else stem
    board = Board(id=board_id, name=_clean(name or stem)[:200], source=_clean(_base(source_name))[:255] if source_name else None,
                  size=Size(width_mm=w, height_mm=h), source_center=centre, placement=placement, layers=tuple(layers))
    skipped = tuple(sorted({*contents.skipped, *(a.name for a in rec.assignments if a.kind == "other")}))
    return Imported(board=board, files=files, cad=rec.cad, issues=tuple(issues), skipped=skipped)


def _check_masks(layers, parsed, source, *, size, centre):
    """What a mask needs to be exposed: the board's area. Returns the layers (a mask that draws more than MASK_COVERS_LIMIT of the
    board gets a warning) and why the area is only the extent rectangle, or None (also None when there is no mask to use)."""
    masks = {l.id for l in layers if l.role is Role.MASK and l.status.level != "error"}
    if not masks:
        return layers, None
    outline = area_outline(layers)
    gfile = parsed[source[outline.id]].file if outline and parsed.get(source[outline.id]) else None
    area, reason = area_or_rectangle(gfile, size=size, center=centre)
    out = []
    for l in layers:
        if l.id in masks:
            drawn = layer_geometry(parsed[source[l.id]].file).intersection(area).area
            ratio = drawn / area.area if area.area > 0 else 0.0
            if ratio > MASK_COVERS_LIMIT:
                l = l.model_copy(update={"status": LayerStatus(level="warning", code=LC.MASK_COVERS_BOARD, params={"percent": round(100 * ratio)})})
        out.append(l)
    return out, reason


def _switch_on(layers, outline_name):
    """On opening: the copper (the top one, or the bottom one if there is no top), the outline and the holes are on; the
    mask, the silkscreen and everything else are off. A layer with an error stays off."""
    ok = lambda l: l.status.level != "error"                                            # noqa: E731
    copper = [l for l in layers if l.role is Role.COPPER and l.side is not Side.INNER and ok(l)]
    primary = next((l for l in copper if l.side is Side.TOP), None) or next(iter(copper), None)
    outlines = [l for l in layers if l.role is Role.OUTLINE and ok(l)]
    best = next((l for l in outlines if outline_name and l.name == _clean(_base(outline_name))), None) or next(iter(outlines), None)
    chosen = {id(x) for x in (primary, best) if x is not None}
    return [l.model_copy(update={"on": ok(l) and (id(l) in chosen or l.role is Role.DRILL)}) for l in layers]
