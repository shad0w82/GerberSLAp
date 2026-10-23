"""What a printer driver is. The core states a mask on the exposure plane and a dose; a driver turns them into the file its
printer wants. Adding a printer means adding a folder `printers/<id>/` with a driver; nothing else changes.

A driver tells the rest of the app what it needs through its descriptor (the plane and the pixel grid, the limits on a
flash, whether it needs a template) and through `check`, which returns issues like every other check. `build` writes the
file, reads it back and compares it with what was meant, and only then puts it where it was asked.
"""
import re
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

import numpy as np

from ..core import Grid
from ..model import ExposureLimits, ExposureValues, Issue, Plane, PrinterConfig


ICON_NAME = "icon.png"          # the picture of a printer, in the folder of its driver: whoever adds a printer adds it there


class DriverError(Exception):
    """Something a driver refuses or cannot do. `code` and `params` are for the interface, which owns the wording."""
    code = "driver_error"

    def __init__(self, detail: str = "", *, code: Optional[str] = None, **params):
        super().__init__(detail or (code or self.code))
        self.detail = detail
        if code:
            self.code = code
        self.params = params


class BuildError(DriverError):
    code = "build_error"


class TemplateError(DriverError):
    code = "template_invalid"


class SettingsError(DriverError):
    code = "bad_settings"


@dataclass(frozen=True)
class DriverDescriptor:
    id: str
    name: str
    plane: Plane                    # the exposure plane in mm, seen from above with the user in front of the printer
    grid: Grid                      # the pixel grid of that plane: row 0 is the back, column 0 the left
    limits: ExposureLimits          # what is known about a single flash
    requires_template: bool
    template_name: Optional[str] = None     # the file name the template has in the printer's folder of the data folder: the driver says it,
                                            # the rest of the app never guesses (a template exists exactly when a driver needs one)
    file_extension: str = ".bin"            # the ending of the file it writes (with its dot): the app names a download with it. A driver that writes
                                            # no file (a made-up printer) keeps the default.

    def __post_init__(self):
        if not re.fullmatch(r"\.[a-z0-9]{1,8}", self.file_extension):
            raise ValueError(f"not a usable file extension: {self.file_extension!r}")
        if self.requires_template != (self.template_name is not None):
            raise ValueError("a driver that needs a template says its file name, and one that does not has none")
        if self.template_name is not None and (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", self.template_name)
                                               or self.template_name == "printer.json"):
            raise ValueError(f"not a usable template file name: {self.template_name!r}")


@dataclass(frozen=True)
class BuildSummary:
    """What the file will do, as numbers; the interface writes the sentences."""
    layers: int                     # exposure layers (one per flash)
    delay_layers: int               # layers added before them to give time to place the board
    flash_s: float
    rest_s: float
    total_light_s: float
    estimated_s: int                # the printer's own estimate of the whole run
    lit_pixels: int
    lit_area_mm2: float
    file_bytes: int
    details: Mapping = field(default_factory=dict)      # driver specific (the park height, the copied motion...)


@dataclass(frozen=True)
class BuildResult:
    path: Path
    summary: BuildSummary
    verified: bool                  # the file was read back and matched; `build` raises otherwise, so this is True
    issues: tuple = ()


class PrinterDriver(ABC):
    descriptor: DriverDescriptor

    def picture_file(self) -> Optional[Path]:
        """The printer's picture (a PNG, upright, with a transparent background): `icon.png` in the folder of the driver's module, which is the folder
        `printers/<id>/` of a real driver. None if the file is not there (the page then draws a generic printer): a driver made in a test or by the
        option that adds made-up printers is not in such a folder, and has none."""
        module = sys.modules.get(type(self).__module__)
        origin = getattr(module, "__file__", None)
        path = Path(origin).resolve().parent / ICON_NAME if origin else None
        return path if path is not None and path.is_file() else None

    @abstractmethod
    def parse_settings(self, settings: Mapping):
        """Validate the driver's settings (an opaque mapping in the data folder). Raises SettingsError."""

    @abstractmethod
    def validate_template(self, path: Path):
        """Check a template file the user supplied. Raises TemplateError with a reason; returns what was learned of it."""

    @abstractmethod
    def check(self, exposure: Optional[ExposureValues], config: PrinterConfig, template_path: Optional[Path]) -> list:
        """Issues about this printer's setup (template, settings), in the same form as every other check."""

    @abstractmethod
    def to_printer_image(self, mask: np.ndarray) -> np.ndarray:
        """The plane's mask (rows from the back, columns from the left) as the image the printer's file holds."""

    @abstractmethod
    def build(self, mask: np.ndarray, exposure: ExposureValues, config: PrinterConfig, template_path: Optional[Path],
              out_path: Path) -> BuildResult:
        """Write the file for `mask` and `exposure` to `out_path`, read it back and compare. Nothing is left at `out_path`
        unless the file matched; raises BuildError otherwise."""

    def build_sequence(self, masks, flashes: int, flash_s: float, rest_s: float, config: PrinterConfig, template_path: Optional[Path],
                       out_path: Path) -> BuildResult:
        """Write a file of several masks in a row (a calibration ladder: each step lights more of the plane than the one before): every mask is shown for `flashes`
        flashes of `flash_s` seconds with `rest_s` of darkness after each, in the order given. As `build`: read back, compared, and nothing left at `out_path` unless
        it matched. A driver that cannot do it says so (the default)."""
        raise BuildError("this printer cannot write a file of several masks", code="sequence_unsupported")
