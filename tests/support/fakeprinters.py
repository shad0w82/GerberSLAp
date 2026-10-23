"""Printers that exist only in tests: the planes and grids differ, nothing is written. For what depends on which printer a project is for."""
from gerberslap.web.devprinters import fake_driver
from gerberslap.printers import Registry


def registry_of(*drivers):
    return Registry(drivers={d.descriptor.id: d for d in drivers})


# a small plane (100 x 60 mm) and a large one (200 x 120 mm), with grids small enough for a test to be quick
SMALL = fake_driver("small", "Small test printer", 500, 300, 0.2)
LARGE = fake_driver("large", "Large test printer", 1000, 600, 0.2)


def template_driver(printer_id="tpl", name="Template test printer"):
    """A printer that needs a template: a file that starts with b"TPL" is good, any other is refused for a reason. Nothing is written."""
    from gerberslap.core import Grid
    from gerberslap.model import C, ExposureLimits, Issue, Plane, Severity
    from gerberslap.printers.base import BuildError, DriverDescriptor, PrinterDriver, TemplateError

    class WithTemplate(PrinterDriver):
        descriptor = DriverDescriptor(id=printer_id, name=name, plane=Plane(width_mm=100, height_mm=60), grid=Grid(500, 300, 0.2),
                                      limits=ExposureLimits(), requires_template=True, template_name="template.tpl")

        def parse_settings(self, settings): return settings

        def validate_template(self, path):
            data = path.read_bytes()
            if not data.startswith(b"TPL"):
                raise TemplateError("the template cannot be used: not_a_template", reason="not_a_template")
            return None

        def check(self, exposure, config, template_path):
            if template_path is None or not template_path.is_file():
                return [Issue(code=C.TEMPLATE_MISSING, severity=Severity.ERROR, blocking=True, params={"printer_id": config.id})]
            try:
                self.validate_template(template_path)
            except TemplateError as exc:
                return [Issue(code=C.TEMPLATE_INVALID, severity=Severity.ERROR, blocking=True, params={"reason": exc.params.get("reason")})]
            return []

        def to_printer_image(self, mask): return mask

        def build(self, *args, **kwargs):
            raise BuildError("a test printer writes no file", code="fake_printer")

    return WithTemplate()


def building_driver(printer_id="build", *, template=False, fail=None, limits=None):
    """A printer on a small plane (100 x 60 mm) whose `build` writes a few bytes and notes what it was given in `driver.calls`, so a test can see
    that the mask, the values and the template are the right ones. `fail`: an exception `build` raises instead. With `template=True` it needs a
    template (a file that starts with b"TPL") and checks for it like a real one."""
    from gerberslap.core import Grid
    from gerberslap.model import C, ExposureLimits, Issue, Plane, Severity
    from gerberslap.printers.base import BuildResult, BuildSummary, DriverDescriptor, PrinterDriver, TemplateError

    class Building(PrinterDriver):
        descriptor = DriverDescriptor(id=printer_id, name="Building test printer", plane=Plane(width_mm=100, height_mm=60), grid=Grid(500, 300, 0.2),
                                      limits=limits or ExposureLimits(min_flash_s=1.0, max_proven_flash_s=20.0), requires_template=template,
                                      template_name="template.tpl" if template else None, file_extension=".fake")
        calls = []

        def parse_settings(self, settings): return settings

        def validate_template(self, path):
            if not path.read_bytes().startswith(b"TPL"):
                raise TemplateError("the template cannot be used: not_a_template", reason="not_a_template")

        def check(self, exposure, config, template_path):
            if not template:
                return []
            if template_path is None or not template_path.is_file():
                return [Issue(code=C.TEMPLATE_MISSING, severity=Severity.ERROR, blocking=True, params={"printer_id": config.id})]
            return []

        def to_printer_image(self, mask): return mask

        def build(self, mask, exposure, config, template_path, out_path):
            self.calls.append({"mask": mask.copy(), "exposure": exposure, "config": config, "template": template_path, "out": out_path})
            if fail is not None:
                raise fail
            out_path.write_bytes(b"FAKE" + bytes([exposure.pulses % 256]))
            summary = BuildSummary(layers=exposure.pulses, delay_layers=0, flash_s=exposure.flash_s, rest_s=exposure.rest_s,
                                   total_light_s=exposure.total_s, estimated_s=42, lit_pixels=int(mask.sum()), lit_area_mm2=float(mask.sum()) * 0.04,
                                   file_bytes=out_path.stat().st_size, details={"template": template_path.name if template_path else None})
            return BuildResult(path=out_path, summary=summary, verified=True)

        def build_sequence(self, masks, flashes, flash_s, rest_s, config, template_path, out_path):
            masks = [m.copy() for m in masks]
            self.calls.append({"masks": masks, "flashes": flashes, "flash_s": flash_s, "rest_s": rest_s, "config": config, "template": template_path, "out": out_path})
            if fail is not None:
                raise fail
            out_path.write_bytes(b"SEQ" + bytes([len(masks), flashes]))
            n = len(masks) * flashes
            summary = BuildSummary(layers=n, delay_layers=0, flash_s=flash_s, rest_s=rest_s, total_light_s=flash_s * n, estimated_s=7, lit_pixels=int(masks[0].sum()),
                                   lit_area_mm2=float(masks[0].sum()) * 0.04, file_bytes=out_path.stat().st_size, details={})
            return BuildResult(path=out_path, summary=summary, verified=True)

    return Building()
