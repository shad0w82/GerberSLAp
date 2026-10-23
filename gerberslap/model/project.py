"""Project, boards and layers: what the user lays out on the exposure plane.

Nothing here knows a printer or a CAD program. A board keeps only the size of its extent (width and height in its own
frame, centred on the origin), never geometry: the Gerber files are referenced by hash and read by the pipeline.
"""
from enum import Enum
from typing import Literal, Optional

from pydantic import Field, field_validator, model_validator

from ..core import Placement
from .base import PROJECT_SCHEMA_VERSION, Code, Color, FileName, Id, JsonValue, Model, Name, Sha256


class Role(str, Enum):
    COPPER = "copper"
    OUTLINE = "outline"
    MASK = "mask"
    SILK = "silk"
    DRILL = "drill"        # draws nothing: switched on, it subtracts its holes from every drawing layer
    IGNORE = "ignore"      # a file of the zip that the exposure does not use (paste, fabrication, drawings)


# the layers that draw something; a board needs at least one of them on
DRAWING_ROLES = frozenset({Role.COPPER, Role.OUTLINE, Role.MASK, Role.SILK})
# the layers of the stack: they lie one over the other, and their order in a board's list (the first is the top one) is the order they
# are drawn in. The outline and the holes are kept apart from it: the outline is always drawn over the stack, the holes draw nothing.
STACK_ROLES = frozenset({Role.COPPER, Role.MASK, Role.SILK})


class Side(str, Enum):
    TOP = "top"
    BOTTOM = "bottom"
    INNER = "inner"        # an inner copper layer: recognised and listed, but a single-sided exposure never uses it


class Polarity(str, Enum):
    POSITIVE = "positive"   # light where there is no copper
    NEGATIVE = "negative"   # light where there is copper


class FileRef(Model):
    name: FileName
    sha256: Sha256


class LayerStatus(Model):
    """`ok`, or a warning or error with a code (and parameters) that the interface turns into text.

    A layer with an error cannot be switched on; a layer with a warning can.
    """
    level: Literal["ok", "warning", "error"] = "ok"
    code: Optional[Code] = None
    params: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _code_matches_level(self):
        if self.level == "ok" and (self.code is not None or self.params):
            raise ValueError("a layer with status ok has no code and no parameters")
        if self.level != "ok" and self.code is None:
            raise ValueError("a layer with a warning or an error needs a code")
        return self


class Layer(Model):
    id: Id
    role: Role
    name: Name
    files: tuple[FileRef, ...] = Field(min_length=1)    # more than one for the holes (plated + non-plated)
    side: Side = Side.TOP
    on: bool
    status: LayerStatus = LayerStatus()
    color: Optional[Color] = None                        # chosen by the user, used only by the Material view

    @model_validator(mode="after")
    def _ignored_layers_stay_off(self):
        if self.role is Role.IGNORE and self.on:
            raise ValueError("a layer whose role is ignore cannot be switched on")
        return self

    @property
    def draws(self) -> bool:
        return self.role in DRAWING_ROLES


class Size(Model):
    width_mm: float = Field(gt=0, le=2000)
    height_mm: float = Field(gt=0, le=2000)


class BoardPlacement(Model):
    """Centre of the board's extent on the plane (mm; u left to right, v front to back), angle in degrees
    counterclockwise seen from above, and mirror left-right applied before the rotation. Both about the centre."""
    x: float = Field(ge=-100_000, le=100_000)
    y: float = Field(ge=-100_000, le=100_000)
    angle: float = Field(default=0.0, ge=-100_000, le=100_000)
    mirror: bool = False

    def to_core(self) -> Placement:
        return Placement(center=(self.x, self.y), angle=self.angle, mirror=self.mirror)


def area_outline(layers) -> Optional["Layer"]:
    """The layer a board's area comes from: among the outline layers without an error the one with the smallest id, whether or
    not it is switched on (switching the outline off only stops its line from being drawn; the board stays where it is) and
    wherever it stands in the list (the order of the layers is the user's to change; the area must not follow it)."""
    return min((layer for layer in layers if layer.role is Role.OUTLINE and layer.status.level != "error"),
               key=lambda layer: layer.id, default=None)


class Board(Model):
    id: Id
    name: Name
    source: Optional[FileName] = None                    # the zip it came from
    size: Size
    # centre of the board's extent in the coordinates of its own files (mm). The placement refers to this point, and it
    # is fixed when the zip is opened (from the outline if there is one), so that switching a layer on or off never
    # moves the board.
    source_center: tuple[float, float] = (0.0, 0.0)
    placement: BoardPlacement
    layers: tuple[Layer, ...] = Field(min_length=1)

    @field_validator("source_center")
    @classmethod
    def _sane_center(cls, v):
        if any(abs(c) > 100_000 for c in v):
            raise ValueError("source_center is out of range")
        return v

    @model_validator(mode="after")
    def _unique_layer_ids(self):
        ids = [layer.id for layer in self.layers]
        if len(set(ids)) != len(ids):
            raise ValueError("layer ids must be unique within a board")
        return self

    @property
    def drawing_layers_on(self) -> tuple[Layer, ...]:
        return tuple(layer for layer in self.layers if layer.on and layer.draws)

    @property
    def area_outline(self) -> Optional[Layer]:
        return area_outline(self.layers)


class Project(Model):
    """The printer is referenced by id. The recipe is a snapshot (id and name, and the polarity below) and the dosage is the one chosen
    among the recipe's dosages for the printer: all of it is only a reference, so that the project can find them again, and the exposure
    values are never part of the project (they come from the dosage, or are set by hand). The polarity is the project's own: with a
    recipe it is the recipe's (which never changes), so that opening the project against a library where the recipe is not there, or
    where it differs, can be flagged: a wrong polarity ruins the board. With no recipe it is the only information."""
    format: Literal["gerberslap"] = "gerberslap"
    schema_version: Literal[2] = PROJECT_SCHEMA_VERSION
    printer_id: Optional[Id] = None
    recipe_id: Optional[Id] = None
    recipe_name: Optional[Name] = None
    dosage_id: Optional[Id] = None
    polarity: Optional[Polarity] = None
    min_outline_mm: float = Field(default=0.3, ge=0, le=5)
    boards: tuple[Board, ...] = ()

    @model_validator(mode="after")
    def _unique_board_ids(self):
        ids = [board.id for board in self.boards]
        if len(set(ids)) != len(ids):
            raise ValueError("board ids must be unique within a project")
        return self
