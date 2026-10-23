"""Dose: total time of light, number of flashes and rest between them.

The model states the dose; it is the driver that decides how to realise it (one driver may write N identical layers of
T/N seconds). The limits belong to the driver too, so they travel as data and the model never names a printer.
"""
from typing import Annotated, Optional

from pydantic import Field

from .base import Model

TotalSeconds = Annotated[float, Field(gt=0, le=36_000)]
PulseCount = Annotated[int, Field(ge=1, le=1000)]
RestSeconds = Annotated[float, Field(ge=0, le=3_600)]


class ExposureValues(Model):
    """The three values that are found together (the rest depends on the length of a single flash)."""
    total_s: TotalSeconds
    pulses: PulseCount
    rest_s: RestSeconds

    @property
    def flash_s(self) -> float:
        return self.total_s / self.pulses


class ExposureLimits(Model):
    """What a driver declares about flashes. `None` means "no limit known"."""
    min_flash_s: Optional[float] = Field(default=None, gt=0)          # below this the file cannot be made
    max_proven_flash_s: Optional[float] = Field(default=None, gt=0)   # above this it was never tried on the printer
