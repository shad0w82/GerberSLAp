"""The file of the calibration ladder: what is wrong with its values for a printer, and the file the printer's driver writes from the steps.

Like the file of a board (`generate.py`): the server makes it from what it is given and keeps nothing. The layout is the one of the page (`core/ladder.py`, which a test
compares with `js/ladder.js`); here the strips become one mask for every step and the driver writes them in a row, `pulses` flashes of `step / pulses` seconds for each.
"""
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from ..core import ladder as core
from ..model import ExposureLimits, ExposureValues, Issue, LadderSpec, Plane, Severity, C
from .checks import blocking, exposure_issues
from .generate import GenerationBlocked, Generated
from .installation import printer_config, printer_issues, template_path
from .pipeline import PipelineError
from .store import DataStore

if TYPE_CHECKING:                                                    # only for the names in the signatures
    from ..printers.base import PrinterDriver


def layout_of(spec: LadderSpec, plane: Plane) -> dict:
    return core.ladder_layout(spec.bands, spec.width, spec.height, spec.step, plane.width_mm, plane.height_mm, spec.tests)


def exposure_of(spec: LadderSpec) -> ExposureValues:
    """A step is an exposure like any other: `step` seconds of light in `pulses` flashes with `rest` seconds between them."""
    return ExposureValues(total_s=spec.step, pulses=spec.pulses, rest_s=spec.rest)


def ladder_issues(spec: LadderSpec, plane: Plane, limits: ExposureLimits) -> list[Issue]:
    """What is wrong with the values, for a printer (its plane and what it says of a flash): a flash under the minimum or over the longest tried, a ladder that does not fit
    the plane (a piece of copper has to fit the board: blocks), no tests, tests that have no room in a strip. The same rules as the page's `ladderIssues`."""
    out = exposure_issues(exposure_of(spec), limits, printer=None, recipe=None)
    layout = layout_of(spec, plane)
    if not layout["fits"]:
        out.append(Issue(code=C.LADDER_TOO_BIG, severity=Severity.ERROR, blocking=True, params={
            "width_mm": layout["width"], "height_mm": layout["height"], "plane_w_mm": plane.width_mm, "plane_h_mm": plane.height_mm}))
    if not spec.tests:
        out.append(Issue(code=C.LADDER_NO_TESTS, severity=Severity.WARNING))
    elif layout["drawing"]["dropped"]:
        out.append(Issue(code=C.LADDER_TESTS_DROPPED, severity=Severity.WARNING, params={"ids": layout["drawing"]["dropped"]}))
    return out


def ladder_file_name(spec: LadderSpec) -> str:
    """The name the file is given, without its ending: the first step and the number of steps (`scala_10s_x8`), in letters, digits and underscores so that any drive and any
    screen of a printer takes it."""
    return f"scala_{core.seconds_text(spec.step).replace('.', '_')}s_x{spec.bands}"


def generate_ladder(spec: LadderSpec, *, driver: "PrinterDriver", store: Optional[DataStore], supersample: int = 16) -> Generated:
    """The file of the ladder for `spec`. Raises GenerationBlocked with the issues if something blocks, and the driver's BuildError if the file cannot be written or does
    not match what was meant."""
    d = driver.descriptor
    exposure = exposure_of(spec)
    issues = ladder_issues(spec, d.plane, d.limits) + printer_issues(store, driver, exposure)
    if blocking(issues):
        raise GenerationBlocked(issues)
    if not core.label_font_available():                                              # a Pillow built without FreeType (the ones for sale have it)
        raise PipelineError("font_missing", "this Pillow cannot cut the font of the time written on a strip to a size (it was built without FreeType)")
    masks = core.ladder_step_masks(layout_of(spec, d.plane), d.grid, polarity=spec.polarity.value, mirror=spec.mirror, supersample=supersample)
    with tempfile.TemporaryDirectory(prefix="gerberslap-") as tmp:
        built = driver.build_sequence(masks, spec.pulses, spec.flash_s, spec.rest, printer_config(store, driver), template_path(store, driver),
                                      Path(tmp) / f"out{d.file_extension}")
        data = built.path.read_bytes()
    return Generated(data=data, summary=built.summary, issues=tuple(issues))
