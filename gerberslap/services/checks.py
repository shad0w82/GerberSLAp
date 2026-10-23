"""The checks of the interface, as code: given a project and what it refers to, list what is wrong.

Only a few things stop the generation of a file (`blocking`); everything else
informs. The result is a list of `Issue` with codes and parameters, in a fixed order: the layers of each board, then
the overlaps, then what the project refers to (printer, recipe, polarity), then the exposure.
"""
from typing import Iterable, Optional, Union

from ..model import (C, Board, ExposureLimits, ExposureValues, Issue, Plane, PrinterConfig, Project, Recipe, RecipeRef, Role,
                     Severity, board_extent, is_outside, overlaps)

ChosenRecipe = Union[Recipe, RecipeRef]             # all a check reads of a recipe is its id and its polarity


def blocking(issues: Iterable[Issue]) -> list[Issue]:
    return [i for i in issues if i.blocking]


def _kinds(board: Board) -> set:
    """The kinds of drawing layer that are on: the outline counts as copper, the holes draw nothing."""
    return {Role.COPPER if layer.role is Role.OUTLINE else layer.role for layer in board.drawing_layers_on}


def board_issues(board: Board, plane: Plane) -> list[Issue]:
    out: list[Issue] = []
    if is_outside(board_extent(board), plane):
        out.append(Issue(code=C.BOARD_OUTSIDE_PLANE, severity=Severity.WARNING, board_id=board.id))
    for layer in board.layers:
        if layer.status.level != "ok":
            level = Severity.ERROR if layer.status.level == "error" else Severity.WARNING
            out.append(Issue(code=C.LAYER_ISSUE, severity=level, board_id=board.id, layer_id=layer.id,
                             params={"status_code": layer.status.code, **layer.status.params}))
        if layer.on and layer.status.level == "error":
            out.append(Issue(code=C.LAYER_ERROR_ON, severity=Severity.ERROR, blocking=True,
                             board_id=board.id, layer_id=layer.id))
    if not board.drawing_layers_on:
        out.append(Issue(code=C.BOARD_NO_LAYER_ON, severity=Severity.ERROR, blocking=True, board_id=board.id))
    if len(_kinds(board)) > 1:
        out.append(Issue(code=C.BOARD_LAYER_SUM, severity=Severity.WARNING, board_id=board.id))
    return out


def layout_issues(project: Project, plane: Plane) -> list[Issue]:
    out: list[Issue] = []
    if not any(board.drawing_layers_on for board in project.boards):
        out.append(Issue(code=C.NO_LAYER_ON, severity=Severity.ERROR, blocking=True))
    for board in project.boards:
        out.extend(board_issues(board, plane))
    extents = [(board, board_extent(board)) for board in project.boards]
    for i, (a, ea) in enumerate(extents):
        for b, eb in extents[i + 1:]:
            if overlaps(ea, eb):
                out.append(Issue(code=C.BOARDS_OVERLAP, severity=Severity.WARNING, board_id=a.id,
                                 params={"board_a": a.id, "board_b": b.id}))
    kinds = [_kinds(board) for board in project.boards]
    if len(set().union(*kinds)) > 1 and not any(len(k) > 1 for k in kinds):
        out.append(Issue(code=C.LAYER_TYPES_MIXED, severity=Severity.WARNING))
    return out


def reference_issues(project: Project, printer: Optional[PrinterConfig], recipe: Optional[ChosenRecipe]) -> list[Issue]:
    """The printer must exist. A recipe is not needed (the values and the polarity can be set by hand), but one the project refers to
    must be found; and the polarity saved with the project must be the one the recipe has now."""
    out: list[Issue] = []
    if printer is None:
        out.append(Issue(code=C.PRINTER_MISSING, severity=Severity.ERROR, blocking=True,
                         params={"printer_id": project.printer_id}))
    if recipe is None:
        if project.recipe_id is not None:
            out.append(Issue(code=C.RECIPE_MISSING, severity=Severity.ERROR, blocking=True,
                             params={"recipe_id": project.recipe_id}))
    elif project.polarity is not None and project.polarity != recipe.polarity:
        out.append(Issue(code=C.POLARITY_MISMATCH, severity=Severity.WARNING,
                         params={"project": project.polarity.value, "recipe": recipe.polarity.value}))
    return out


def exposure_issues(exposure: Optional[ExposureValues], limits: ExposureLimits, *,
                    printer: Optional[PrinterConfig], recipe: Optional[ChosenRecipe]) -> list[Issue]:
    """`exposure` is None when the recipe has no dosage for the printer and no values were entered by hand: the dosages of another
    printer are never used in silence."""
    out: list[Issue] = []
    if exposure is None:
        if printer is not None and recipe is not None:
            out.append(Issue(code=C.DOSAGE_MISSING, severity=Severity.WARNING,
                             params={"printer_id": printer.id, "recipe_id": recipe.id}))
        out.append(Issue(code=C.EXPOSURE_INVALID, severity=Severity.ERROR, blocking=True, params={"reason": "missing"}))
        return out
    flash = exposure.flash_s
    if limits.min_flash_s is not None and flash < limits.min_flash_s:
        out.append(Issue(code=C.FLASH_BELOW_MINIMUM, severity=Severity.ERROR, blocking=True,
                         params={"flash_s": flash, "min_s": limits.min_flash_s}))
    if limits.max_proven_flash_s is not None and flash > limits.max_proven_flash_s:
        out.append(Issue(code=C.FLASH_BEYOND_PROVEN, severity=Severity.WARNING,
                         params={"flash_s": flash, "max_s": limits.max_proven_flash_s}))
    return out


def check_project(project: Project, *, plane: Plane, printer: Optional[PrinterConfig] = None,
                  recipe: Optional[ChosenRecipe] = None, exposure: Optional[ExposureValues] = None,
                  limits: ExposureLimits = ExposureLimits()) -> list[Issue]:
    return (layout_issues(project, plane) + reference_issues(project, printer, recipe)
            + exposure_issues(exposure, limits, printer=printer, recipe=recipe))
