"""Making the file of a project: the checks, the mask the pipeline draws, and the file the printer's driver writes from it.

The server makes the file from what it is given and keeps nothing: the request carries the project, the polarity, the three values of the
exposure and, if the person chose one, the recipe (the server does not read the library). Everything that can stop the file is checked
first, all of it as issues like every other check; only if nothing blocks is the mask drawn and the driver asked to write. The driver
writes into a folder that is removed afterwards, reads its file back and compares it with what was meant, and only then is the file
handed over, as bytes: nothing of a person's project is left on the server.
"""
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from ..model import ExposureValues, Issue, Polarity, PrinterConfig, Project
from .checks import ChosenRecipe, blocking, check_project
from .installation import printer_config, printer_issues, template_path
from .pipeline import PipelineCache, render
from .store import DataStore, StoreError

if TYPE_CHECKING:                                                    # only for the names in the signatures
    from ..printers.base import BuildSummary, PrinterDriver


class GenerationBlocked(Exception):
    """Something stops the file. `issues` is every issue found, in the order of the checks, not only those that block: the page shows
    them as it shows the others."""

    def __init__(self, issues):
        super().__init__("generation_blocked")
        self.issues = tuple(issues)


@dataclass(frozen=True)
class Generated:
    data: bytes
    summary: "BuildSummary"
    issues: tuple                                                    # what did not stop the file (a board past the plane, an estimated area...)


def reference_config(store: Optional[DataStore], driver: "PrinterDriver") -> PrinterConfig:
    """The configuration of the printer for a check: the real one, or, if the file of its settings cannot be read, the driver's own (the
    printer's issues say why, and block): a check never fails for that."""
    try:
        return printer_config(store, driver)
    except StoreError:
        d = driver.descriptor
        return PrinterConfig(id=d.id, name=d.name, driver=d.id)


def generation_issues(project: Project, *, driver: "PrinterDriver", store: Optional[DataStore], exposure: Optional[ExposureValues],
                      recipe: Optional[ChosenRecipe]) -> list[Issue]:
    """Everything that can be wrong before a file is made: the layout, what the project refers to, the exposure, and the installation of the
    printer (its template, its settings, its own rules about the values)."""
    d = driver.descriptor
    return (check_project(project, plane=d.plane, printer=reference_config(store, driver), recipe=recipe, exposure=exposure, limits=d.limits)
            + printer_issues(store, driver, exposure))


def generate(project: Project, files, *, driver: "PrinterDriver", store: Optional[DataStore], polarity: Polarity, exposure: ExposureValues,
             recipe: Optional[ChosenRecipe] = None, cache: Optional[PipelineCache] = None, supersample: int = 16) -> Generated:
    """The file for `project` with `polarity` and `exposure`. `files` maps sha256 to bytes (what the importer returned). Raises
    GenerationBlocked with the issues if something blocks, PipelineError if the mask cannot be drawn and the driver's BuildError if the
    file cannot be written or does not match what was meant."""
    project = project.model_copy(update={"polarity": polarity})              # the polarity in force is the one being used
    issues = generation_issues(project, driver=driver, store=store, exposure=exposure, recipe=recipe)
    if blocking(issues):
        raise GenerationBlocked(issues)
    d = driver.descriptor
    drawn = render(project, files, d.grid, polarity, supersample=supersample, cache=cache)
    with tempfile.TemporaryDirectory(prefix="gerberslap-") as tmp:
        built = driver.build(drawn.mask, exposure, printer_config(store, driver), template_path(store, driver),
                             Path(tmp) / f"out{d.file_extension}")
        data = built.path.read_bytes()
    return Generated(data=data, summary=built.summary, issues=tuple(issues) + tuple(drawn.issues))
