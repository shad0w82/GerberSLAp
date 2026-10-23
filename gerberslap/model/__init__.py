"""The data model: immutable, validated values that describe a project, the library of recipes and the problems found.

No geometry and no printer in here: layers are referenced by file hash, and what depends on a printer is data passed in
(`Plane`, `ExposureLimits`) or lives in a driver under printers/.
"""
from .base import SCHEMA_VERSION
from .catalog import (MAX_DOSAGES, MAX_RECIPES, Development, Dosage, DosageName, DosageNote, PrinterConfig, PrinterFile, Recipe, RecipeNotes,
                      RecipeRef, Resist)
from .exposure import ExposureLimits, ExposureValues
from .issues import C, Issue, LC, Severity
from .ladder import LADDER_TESTS, STRIP_GAP_MM, LadderSpec
from .layout import Extent, Margins, Plane, board_extent, is_outside, margins, overlaps
from .project import (DRAWING_ROLES, STACK_ROLES, area_outline, Board, BoardPlacement, FileRef, Layer, LayerStatus, Polarity, Project, Role, Side,
                      Size)

__all__ = ["LADDER_TESTS", "STRIP_GAP_MM", "LadderSpec", "SCHEMA_VERSION", "MAX_DOSAGES", "MAX_RECIPES", "Development", "Dosage", "DosageName", "DosageNote", "PrinterConfig", "PrinterFile",
           "Recipe", "RecipeNotes", "RecipeRef", "Resist", "ExposureLimits",
           "ExposureValues", "C", "LC", "Issue", "Severity", "Extent", "Margins", "Plane", "board_extent", "is_outside",
           "margins", "overlaps", "DRAWING_ROLES", "STACK_ROLES", "area_outline", "Board", "BoardPlacement", "FileRef", "Layer", "LayerStatus",
           "Polarity", "Project", "Role", "Side", "Size"]
