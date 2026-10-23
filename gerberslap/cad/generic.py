"""The conventions all programs share: X2 attributes first, then names and extensions.

A file is classified by what it says about itself (X2 `FileFunction`), then by its name, then by the layer name written
inside it. Names are compared token by token ("Flight_Controller_PCB_Copper_Signal_Top.gbr" is flight, controller, pcb,
copper, signal, top, gbr), so a project called "tophat" is not read as a top layer. The first rule that matches wins,
and the specific rules come before the general ones.
"""
import re
from typing import Optional

from ..model import Role, Side
from .base import Assignment, Probe, Recognizer

TOP, BOTTOM, INNER = Side.TOP, Side.BOTTOM, Side.INNER


def normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _tok(pattern: str):
    return re.compile(rf"(?:^|_)(?:{pattern})(?:_|$)")


# (pattern over the normalised name, role, side, confidence)
_RULES = [(_tok(p), role, side, conf) for p, role, side, conf in (
    # not layers of the board: drawings, assembly, reports and job files written next to the layers
    (r"f_fab|b_fab|f_crtyd|b_crtyd|f_adhes|b_adhes|dwgs_user|cmts_user|eco\d_user|margin|assembly|courtyard|fabrication"
     r"|pnp|bom|centroid|gbrjob|gpi|dri|rep|extrep|apr|apr_lib|drr|rul|lgr|gd1|gg1|drill_map|drillmap", Role.IGNORE, TOP, .9),
    # paste is for assembly, not for exposing a board
    (r"f_paste|b_paste|paste_top|paste_bot|paste_bottom|solderpaste_top|solderpaste_bot|solderpaste_bottom|top_paste"
     r"|bottom_paste|gtp|gbp|crc|crs", Role.IGNORE, TOP, .9),
    # outline
    (r"edge_cuts", Role.OUTLINE, TOP, .95),
    (r"board_?outline|outline|profile|dimensions?", Role.OUTLINE, TOP, .9),
    (r"gko|gml|dim|mill|milling", Role.OUTLINE, TOP, .7),
    (r"gm1", Role.OUTLINE, TOP, .6),
    # copper
    (r"f_cu", Role.COPPER, TOP, .95),
    (r"copper_signal_top|copper_top|top_copper(_layer)?|top_layer|toplayer", Role.COPPER, TOP, .9),
    (r"gtl|cmp", Role.COPPER, TOP, .85),
    (r"b_cu", Role.COPPER, BOTTOM, .95),
    (r"copper_signal_bot(tom)?|copper_bot(tom)?|bottom_copper(_layer)?|bottom_layer|bottomlayer|bot_layer", Role.COPPER, BOTTOM, .9),
    (r"gbl|sol", Role.COPPER, BOTTOM, .85),
    (r"in\d+_cu", Role.COPPER, INNER, .95),
    (r"copper_(signal|plane)_\d+|inner_?layer_?\d*", Role.COPPER, INNER, .85),
    (r"g\d{1,2}|gp\d{1,2}|ly\d+", Role.COPPER, INNER, .7),
    # solder mask: drawn in the files as the openings
    (r"f_mask", Role.MASK, TOP, .95),
    (r"soldermask_top|solder_?mask_top|top_solder_?mask|top_solder|topsoldermask", Role.MASK, TOP, .9),
    (r"gts|stc", Role.MASK, TOP, .85),
    (r"b_mask", Role.MASK, BOTTOM, .95),
    (r"soldermask_bot(tom)?|solder_?mask_bot(tom)?|bottom_solder_?mask|bottom_solder|bot_solder|bottomsoldermask", Role.MASK, BOTTOM, .9),
    (r"gbs|sts", Role.MASK, BOTTOM, .85),
    # silkscreen
    (r"f_silkscreen|f_silks|f_silk", Role.SILK, TOP, .95),
    (r"silkscreen_top|legend_top|top_overlay|top_silkscreen|top_silk|topsilk|top_legend", Role.SILK, TOP, .9),
    (r"gto|plc", Role.SILK, TOP, .85),
    (r"b_silkscreen|b_silks|b_silk", Role.SILK, BOTTOM, .95),
    (r"silkscreen_bot(tom)?|legend_bot(tom)?|bottom_overlay|bottom_silkscreen|bottom_silk|botsilk|bottom_legend", Role.SILK, BOTTOM, .9),
    (r"gbo|pls", Role.SILK, BOTTOM, .85),
)]

_NON_PLATED = _tok(r"npth|non_?plated|np")
_PLATED = _tok(r"pth|plated")
_X2_SIDE = {"top": TOP, "t": TOP, "front": TOP, "bot": BOTTOM, "bottom": BOTTOM, "b": BOTTOM, "back": BOTTOM,
            "inr": INNER, "inner": INNER}
# X2 file functions that are not a layer of the board for our purposes
_X2_IGNORED = {"paste", "keep-out", "other", "drillmap", "fab", "assembly", "component", "glue", "carbonmask",
               "goldmask", "peelmask", "viafill", "drawing", "vcut", "array", "depthrout", "solderpaste"}


def _x2_side(values) -> Side:
    for v in values[1:]:
        if v.lower() in _X2_SIDE:
            return _X2_SIDE[v.lower()]
    return TOP


def _from_x2(p: Probe) -> Optional[tuple]:
    ff = p.attributes.get("FileFunction")
    if not ff or not ff[0]:
        return None
    f = ff[0].lower()
    if f == "copper":
        return Role.COPPER, _x2_side(ff)
    if f == "soldermask":
        return Role.MASK, _x2_side(ff)
    if f == "legend":
        return Role.SILK, _x2_side(ff)
    if f == "profile":
        return Role.OUTLINE, TOP
    if f in ("plated", "nonplated"):
        return Role.DRILL, TOP
    if f in _X2_IGNORED:
        return Role.IGNORE, TOP
    return None


def _match_name(text: str):
    n = normalise(text)
    for rx, role, side, conf in _RULES:
        m = rx.search(n)
        if m:
            return role, side, conf, m.group(0).strip("_")
    return None


def _plated(p: Probe, n: str) -> Optional[bool]:
    ff = p.attributes.get("FileFunction")
    if ff and ff[0].lower() == "plated":
        return True
    if ff and ff[0].lower() == "nonplated":
        return False
    if _NON_PLATED.search(n):
        return False
    if _PLATED.search(n):
        return True
    return None


def classify(p: Probe) -> Assignment:
    base = dict(name=p.name, kind=p.kind, negative=p.negative)
    n = normalise(p.basename)
    if p.kind == "excellon":
        return Assignment(role=Role.DRILL, side=TOP, confidence=1.0, reason="content:excellon",
                          plated=_plated(p, n), **{**base, "negative": False})
    if p.kind == "other":
        return Assignment(role=Role.IGNORE, side=TOP, confidence=1.0, reason="not_gerber", **{**base, "negative": False})
    x2 = _from_x2(p)
    if x2:
        return Assignment(role=x2[0], side=x2[1], confidence=1.0, reason="x2", **base)
    hit = _match_name(p.basename)
    if hit:
        role, side, conf, token = hit
        return Assignment(role=role, side=side, confidence=conf, reason=f"name:{token}", **base)
    if p.inline_name:
        hit = _match_name(p.inline_name)
        if hit:
            role, side, conf, token = hit
            return Assignment(role=role, side=side, confidence=round(conf - .05, 2), reason=f"inline:{token}", **base)
    return Assignment(role=Role.IGNORE, side=TOP, confidence=0.0, reason="unknown", **base)


class GenericRecognizer(Recognizer):
    """Always applicable, never the first choice."""
    name = "generic"

    def score(self, probes) -> float:
        return 0.1
