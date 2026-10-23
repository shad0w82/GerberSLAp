"""The values of a calibration ladder: how long the first step lasts, how many steps, how many flashes in each, the rest between flashes, the size of a strip,
the tests that every strip holds, the resist and whether the ladder is turned over. The same numbers, with the same limits, as the page (`js/ladder.js`).

A ladder is a set of strips side by side, the first on the left; the strip k is lit for k times the time of the first one: step i of the file opens the strips from i on.
Nothing here knows a printer: what a printer says of a flash (its minimum) is checked against `flash_s`, and the size of the plane is a parameter of the layout.
"""
from typing import Annotated

from pydantic import Field, field_validator

from .base import Model
from .project import Polarity

LADDER_TESTS = ("lines_v", "lines_h", "gaps", "soic8", "fine", "passives", "rings")      # the tests a strip can hold, in the order they are laid out
STRIP_GAP_MM = 1.0                                                                          # the dark between two strips


class LadderSpec(Model):
    step: Annotated[float, Field(ge=1, le=600)]            # s: the time of the first strip (and the time every step adds)
    bands: Annotated[int, Field(ge=2, le=20)]              # strips, which are also the steps of the file
    pulses: Annotated[int, Field(ge=1, le=20)]             # flashes in a step
    rest: Annotated[float, Field(ge=0, le=60)]             # s of darkness between two flashes
    width: Annotated[float, Field(ge=6, le=40)]            # mm, of a strip
    height: Annotated[float, Field(ge=15, le=150)]         # mm, of a strip
    tests: tuple[str, ...] = LADDER_TESTS
    polarity: Polarity = Polarity.POSITIVE
    mirror: bool = False                                   # turned over left to right (the copper side down), the text too

    @field_validator("tests")
    @classmethod
    def _known_and_once(cls, v):
        if len(set(v)) != len(v) or any(t not in LADDER_TESTS for t in v):
            raise ValueError("tests must be some of the known ones, each once")
        return v

    @property
    def flash_s(self) -> float:
        return self.step / self.pulses

    @property
    def layers(self) -> int:
        return self.bands * self.pulses
