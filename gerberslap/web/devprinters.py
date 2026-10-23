"""Printers that do not exist, for trying how the page behaves with more than one: the plane changes size, boards fall outside it, a project asks
for a printer that is missing, a printer is not ready because its template is not installed. They are added only with
`python -m gerberslap.web --dev-printers` and are never part of the app: they write no file (`build` refuses) and they name no real printer."""
from pathlib import Path

from ..core import Grid
from ..model import C, ExposureLimits, Issue, Plane, Severity
from ..printers import Registry
from ..printers.base import BuildError, DriverDescriptor, PrinterDriver


def fake_driver(printer_id: str, name: str, cols: int, rows: int, pitch: float, *, template_name=None) -> PrinterDriver:
    """A printer whose plane is `cols` x `rows` pixels of `pitch` mm. With a `template_name` it needs a template (that nobody can install: only
    the real printers are known to the command that does), so it is never ready, and says so like a real one."""
    class Fake(PrinterDriver):
        descriptor = DriverDescriptor(id=printer_id, name=name, plane=Plane(width_mm=round(cols * pitch, 4), height_mm=round(rows * pitch, 4)),
                                      grid=Grid(cols, rows, pitch), limits=ExposureLimits(), requires_template=template_name is not None,
                                      template_name=template_name)

        def parse_settings(self, settings): return settings
        def validate_template(self, path): return None

        def check(self, exposure, config, template_path):
            if self.descriptor.requires_template and (template_path is None or not Path(template_path).is_file()):
                return [Issue(code=C.TEMPLATE_MISSING, severity=Severity.ERROR, blocking=True, params={"printer_id": config.id})]
            return []
        def to_printer_image(self, mask): return mask

        def build(self, *args, **kwargs):
            raise BuildError("a made-up printer writes no file", code="fake_printer")

    return Fake()


# a plane smaller than the real one and one larger, with another shape: boards that fit one do not fit the other
DEMO_SMALL = fake_driver("demo_small", "Demo small (made up)", 1200, 800, 0.08)       # 96 x 64 mm
DEMO_LARGE = fake_driver("demo_large", "Demo large (made up)", 2000, 1250, 0.1)       # 200 x 125 mm
DEMO_NO_TEMPLATE = fake_driver("demo_no_template", "Demo no template (made up)", 1600, 1000, 0.0625, template_name="template.demo")     # 100 x 62.5 mm, never ready


def with_demo_printers(real: Registry) -> Registry:
    """The registry with the three made-up printers added to the real ones (a real printer with the same id wins)."""
    demos = {d.descriptor.id: d for d in (DEMO_SMALL, DEMO_LARGE, DEMO_NO_TEMPLATE)}
    return Registry(drivers={**demos, **real.drivers}, problems=real.problems)
