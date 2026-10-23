"""The catalogue: what a person may write for a printer, and the library of recipes with their dosages.

A recipe is what one does with a resist (its polarity, what it is, how it is developed) and says nothing about a printer. A dosage is
what was found by trying, for one printer: total time of light, number of flashes and rest. The dosages of a recipe are alternatives
that all stay valid (fine tracks, large ground planes...), not versions of one another; each is an independent copy. The polarity of a
recipe is fixed when it is created: if the resist changes it is another recipe.
"""
from datetime import timezone
from typing import Annotated, Optional

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from .base import Id, JsonValue, Model, Name
from .exposure import ExposureValues, PulseCount, RestSeconds, TotalSeconds
from .project import Polarity

MAX_RECIPES = 500                  # a limit against misuse, far above what a person writes
MAX_DOSAGES = 100                  # per recipe


def _line(max_length: int):
    """Text on one line: no control characters (it ends up in menus and summaries)."""
    return Annotated[str, StringConstraints(strip_whitespace=True, max_length=max_length, pattern=r"^[^\x00-\x1f\x7f]*$")]


Resist = _line(200)
Development = _line(200)
DosageName = _line(60)
DosageNote = _line(500)
# free text, new lines allowed
RecipeNotes = Annotated[str, StringConstraints(max_length=2000, pattern=r"^[^\x00-\x08\x0b-\x1f\x7f]*$")]


class RecipeRef(Model):
    """What a check needs to know of the recipe a person chose: which one it is and its polarity. The server does not read the library (the
    page does, and only the page knows what was chosen), so the page says it with each request that depends on it."""
    id: Id
    name: Name
    polarity: Polarity


class PrinterConfig(Model):
    """What a driver is given about its printer: the driver's own name and id, and the settings someone wrote for it (none: the defaults)."""
    id: Id                                               # the id of the driver: a printer is a kind of printer, not one unit
    name: Name
    driver: Id
    settings: dict[str, JsonValue] = Field(default_factory=dict)    # validated by the driver


class PrinterFile(Model):
    """`printers/<id>/printer.json`: optional, only the settings a person wants to change from the driver's defaults."""
    settings: dict[str, JsonValue] = Field(default_factory=dict)


class Dosage(Model):
    id: Id
    printer_id: Id
    updated: AwareDatetime                               # when the values last changed (a new name or note does not change it)
    total_s: TotalSeconds
    pulses: PulseCount
    rest_s: RestSeconds
    name: DosageName = ""                                # optional, short ("fine tracks")
    note: DosageNote = ""

    @field_validator("updated")
    @classmethod
    def _utc(cls, v):
        return v.astimezone(timezone.utc)

    @property
    def values(self) -> ExposureValues:
        return ExposureValues(total_s=self.total_s, pulses=self.pulses, rest_s=self.rest_s)

    @property
    def flash_s(self) -> float:
        return self.total_s / self.pulses


class Recipe(Model):
    id: Id
    name: Name
    polarity: Polarity
    resist: Resist = ""
    development: Development = ""
    notes: RecipeNotes = ""
    dosages: tuple[Dosage, ...] = ()

    @model_validator(mode="after")
    def _dosages_are_sane(self):
        ids = [d.id for d in self.dosages]
        if len(set(ids)) != len(ids):
            raise ValueError("dosage ids must be unique within a recipe")
        if len(ids) > MAX_DOSAGES:
            raise ValueError(f"a recipe holds at most {MAX_DOSAGES} dosages")
        return self

    def dosage(self, dosage_id: str) -> Optional[Dosage]:
        return next((d for d in self.dosages if d.id == dosage_id), None)

    def dosages_for(self, printer_id: str) -> tuple:
        """The dosages for a printer, the last changed first (of two changed at the same moment, the one later in the list)."""
        mine = [(d.updated, i, d) for i, d in enumerate(self.dosages) if d.printer_id == printer_id]
        return tuple(d for _, _, d in sorted(mine, key=lambda t: (t[0], t[1]), reverse=True))
