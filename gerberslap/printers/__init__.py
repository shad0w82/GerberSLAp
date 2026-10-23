"""Printer drivers, one folder each: `printers/<id>/__init__.py` exposes `DRIVER`. They are found at start-up, so a new
printer is a new folder; a folder that fails to load is reported and does not stop the others."""
import importlib
import pkgutil
from dataclasses import dataclass
from types import ModuleType
from typing import Optional

from .base import (BuildError, BuildResult, BuildSummary, DriverDescriptor, DriverError, PrinterDriver, SettingsError,
                   TemplateError)


class UnknownDriver(KeyError):
    pass


@dataclass(frozen=True)
class LoadProblem:
    package: str
    reason: str


@dataclass(frozen=True)
class Registry:
    drivers: dict
    problems: tuple = ()

    def get(self, driver_id: str) -> PrinterDriver:
        try:
            return self.drivers[driver_id]
        except KeyError:
            raise UnknownDriver(driver_id) from None

    def ids(self) -> list:
        return sorted(self.drivers)


def discover(package: Optional[ModuleType] = None) -> Registry:
    """Import every sub-package of `package` (default: this one) and collect its DRIVER. The folder name must be the driver's
    id, which keeps an id and its data folder in step."""
    package = package or importlib.import_module(__name__)
    drivers, problems = {}, []
    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda i: i.name):
        if not info.ispkg or info.name.startswith("_"):
            continue
        name = f"{package.__name__}.{info.name}"
        try:
            driver = importlib.import_module(name).DRIVER
            if not isinstance(driver, PrinterDriver):
                raise TypeError("DRIVER is not a PrinterDriver")
            if driver.descriptor.id != info.name:
                raise ValueError(f"the folder is {info.name!r} but the driver says {driver.descriptor.id!r}")
        except Exception as exc:                                          # noqa: BLE001 - one broken folder must not hide the rest
            problems.append(LoadProblem(package=info.name, reason=f"{type(exc).__name__}: {exc}"))
            continue
        drivers[driver.descriptor.id] = driver
    return Registry(drivers=drivers, problems=tuple(problems))


_registry: Optional[Registry] = None


def registry() -> Registry:
    global _registry
    if _registry is None:
        _registry = discover()
    return _registry


def get_driver(driver_id: str) -> PrinterDriver:
    return registry().get(driver_id)


__all__ = ["BuildError", "BuildResult", "BuildSummary", "DriverDescriptor", "DriverError", "PrinterDriver", "SettingsError",
           "TemplateError", "UnknownDriver", "LoadProblem", "Registry", "discover", "registry", "get_driver"]
