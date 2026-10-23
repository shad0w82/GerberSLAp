"""What the person who installs the app puts in the data folder, and what the app makes of it.

A printer is a kind of printer, not one unit: its configuration is the driver's own defaults unless someone wrote a `printer.json` with
settings for it, and the only thing it cannot do without is the template that the driver copies the movement from (never in the
repository or the image: whoever installs the app puts it in the data folder). Where the template is, is not written anywhere: the
folder is `printers/<driver id>/` and the file name is the one the driver says. Here lives the check "is this printer ready?" that the
page shows, and the installation of a template that the driver has judged first.
"""
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from ..model import C, Issue, PrinterConfig, Severity
from .store import MAX_TEMPLATE_BYTES, DataStore, Invalid, NotFound, Refused, StoreError

if TYPE_CHECKING:                                                    # only for the names in the signatures
    from ..printers.base import PrinterDriver


def printer_config(store: Optional[DataStore], driver: "PrinterDriver") -> PrinterConfig:
    """The configuration of a printer: the driver's defaults and the settings someone wrote in `printers/<id>/printer.json`.
    A file that is there and cannot be read is an error (`Invalid`), never replaced by the defaults in silence."""
    d = driver.descriptor
    settings = store.printer_settings(d.id) if store is not None else {}
    return PrinterConfig(id=d.id, name=d.name, driver=d.id, settings=settings)


def template_path(store: Optional[DataStore], driver: "PrinterDriver") -> Optional[Path]:
    """Where the printer's template is, or None when it is not there (or the printer needs none)."""
    d = driver.descriptor
    if store is None or d.template_name is None:
        return None
    try:
        return store.printer_file(d.id, d.template_name)
    except NotFound:
        return None


def printer_issues(store: Optional[DataStore], driver: "PrinterDriver", exposure=None) -> list:
    """What is wrong with the installation of a printer (its template, its settings, a settings file that cannot be read), as issues
    like every other check. A printer is ready when none of them blocks. `exposure` is for a printer's own rules about the values: the
    page asks without them (is it ready?), a file being made asks with them."""
    try:
        config = printer_config(store, driver)
        path = template_path(store, driver)
    except StoreError as exc:
        return [Issue(code=C.PRINTER_CONFIG_INVALID, severity=Severity.ERROR, blocking=True,
                      params={"printer_id": driver.descriptor.id, "reason": exc.code})]
    return driver.check(exposure, config, path)


def install_template(store: DataStore, driver: "PrinterDriver", source: Path) -> Path:
    """Put `source` where the driver will look for the template of its printer, under the name the driver says. The driver judges the
    file first: if it refuses, nothing changes. Installing again replaces the template. Returns where it is now."""
    d = driver.descriptor
    if d.template_name is None:
        raise Refused(f"the printer {d.id!r} needs no template", code="no_template_needed")
    source = Path(source)
    try:
        if source.stat().st_size > MAX_TEMPLATE_BYTES:
            raise Invalid("the template is too large", code="template_too_large")
        data = source.read_bytes()
    except FileNotFoundError:
        raise NotFound(f"no such file: {source}", path=str(source)) from None
    except OSError as exc:
        raise Invalid(f"cannot read {source}: {exc}", path=str(source), code="unreadable") from None
    with tempfile.TemporaryDirectory() as tmp:                        # judged before anything is written, so a refusal leaves no trace
        probe = Path(tmp) / d.template_name
        probe.write_bytes(data)
        try:
            driver.validate_template(probe)
        except Exception as exc:                                      # noqa: BLE001 - whatever the driver says, the file is refused
            raise Invalid(str(exc), code="template_rejected") from exc
    return store.set_template(d.id, d.template_name, data, validate=driver.validate_template)
