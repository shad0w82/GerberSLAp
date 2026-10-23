"""The Creality LD-002H driver: a mask on the plane becomes a .ctb file for the printer to expose.

What it does, all of it verified on the printer (see ctb_v5_ld002h_formato.md):
  - the image of the file is the plane seen from above turned a quarter turn: file = plane rotated 90 degrees clockwise,
    with no reflection (the file's top edge is the printer's left, its left edge the front). The mirror of a board is
    the user's choice on the placed board and never added here;
  - a dose of T seconds in N flashes is N identical layers of T/N seconds, because the printer reads one exposure time
    from the header for every layer; the rest is the only pause of darkness, written as the rest before lift;
  - the movement (lift distances, speeds, second stages, the other rests) is always copied from a template that the
    user made in ChiTuBox, never invented; a lift distance of 0 would make the printer do a 5 mm cycle, so a template
    with one is refused;
  - every layer is at one low Z (the park height), the preview is the first layer cropped to what is lit, and the
    file is read back and compared with what was meant before it is put where it was asked.

The writing itself is `ctbio.write_ctb`, untouched; this module decides what to give it.
"""
import math
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

import numpy as np
from pydantic import Field, ValidationError

from ...core import Grid
from ...model import C, ExposureLimits, ExposureValues, Issue, Plane, PrinterConfig, Severity
from ...model.base import Model
from ..base import (BuildError, BuildResult, BuildSummary, DriverDescriptor, PrinterDriver, SettingsError,
                    TemplateError)
from . import ctbio
from .ctbio import CTB, PANEL_MM_X, PANEL_MM_Y, PITCH_MM, RES_X, RES_Y, Layer, write_ctb

PITCH = 0.051
assert abs(PITCH_MM - PITCH) < 1e-9
MIN_FLASH_S = 1.0               # a layer under 1 s has not been tried on the printer
MAX_PROVEN_FLASH_S = 20.0       # nor one over 20 s
LIFT_LARGE_MM = 1.0             # a template that lifts more than this makes every flash slow (the advice is 0.001 mm)
_RECORD = "<11f"                # the per-layer record from +40: lift d/s, 2nd stage d/s, retract s, 2nd d/s, three rests, LED
_REST_BEFORE = 7                # index of the rest before lift in the 11 floats (record +68)


class LD002HSettings(Model):
    park_z_mm: float = Field(default=1.0, gt=0, le=30)        # every layer is at this Z, so the carriage hardly moves
    start_delay_s: float = Field(default=0.0, ge=0, le=600)   # time to place the board after the Z0 homing (0: none)
    cycle_s: float = Field(default=8.0, ge=1, le=120)         # estimate of the printer's own 5 mm cycle; sizes the delay only


@dataclass(frozen=True)
class TemplateInfo:
    layers: int
    lift_mm: float
    lift_speed: float
    retract_speed: float
    rest_before_s: float
    rest_after_lift_s: float
    rest_after_retract_s: float


def _f32(v: float) -> float:
    return struct.unpack("<f", struct.pack("<f", v))[0]


def _record(t: CTB, i: int) -> tuple:
    return struct.unpack_from(_RECORD, t.d, t.layers[i].data_off - 84 + 40)


class LD002HDriver(PrinterDriver):
    descriptor = DriverDescriptor(
        id="ld002h", name="Creality LD-002H",
        plane=Plane(width_mm=PANEL_MM_Y, height_mm=PANEL_MM_X),
        grid=Grid(width=RES_Y, height=RES_X, pitch=PITCH),
        limits=ExposureLimits(min_flash_s=MIN_FLASH_S, max_proven_flash_s=MAX_PROVEN_FLASH_S),
        requires_template=True, template_name="template.ctb", file_extension=".ctb")

    # ---- settings and template ---------------------------------------------------------------------------------
    def parse_settings(self, settings: Optional[Mapping]) -> LD002HSettings:
        try:
            return LD002HSettings.model_validate(dict(settings or {}))
        except ValidationError as exc:
            first = exc.errors()[0]
            raise SettingsError(f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}",
                                field=".".join(str(p) for p in first["loc"]) or None, message=first["msg"]) from None

    def validate_template(self, path: Path) -> TemplateInfo:
        def refuse(reason, **p):
            raise TemplateError(f"the template cannot be used: {reason}", reason=reason, **p)
        try:
            t = CTB(os.fspath(path))
        except FileNotFoundError:
            refuse("missing")
        except ValueError:
            refuse("not_a_ctb")
        except (OSError, struct.error, IndexError):
            refuse("unreadable")
        if t.version != 5:
            refuse("bad_version", version=t.version)
        if not t.crc_ok:
            refuse("bad_crc")
        if struct.unpack_from("<II", t.d, ctbio.H_RES_X) != (RES_X, RES_Y):
            refuse("bad_resolution")
        if t.layer_count < 1:
            refuse("no_layers")
        try:
            t.layer_image(t.layer_count - 1)                                     # the data must decode
            first, last = _record(t, 0), _record(t, t.layer_count - 1)
        except Exception:                                                        # noqa: BLE001 - any failure means "not usable"
            refuse("undecodable")
        for rec in (first, last):
            if not rec[0] > 0:
                refuse("lift_distance_zero")          # the printer would do its own 5 mm cycle instead
            if not rec[1] >= 1 or not rec[4] >= 1:
                refuse("lift_speed_invalid")
        return TemplateInfo(layers=t.layer_count, lift_mm=last[0], lift_speed=last[1], retract_speed=last[4],
                            rest_before_s=last[7], rest_after_lift_s=last[8], rest_after_retract_s=last[9])

    def check(self, exposure, config: PrinterConfig, template_path: Optional[Path]) -> list:
        out = []
        try:
            self.parse_settings(config.settings)
        except SettingsError as exc:
            out.append(Issue(code=C.PRINTER_SETTINGS_INVALID, severity=Severity.ERROR, blocking=True,
                             params={"field": exc.params.get("field"), "message": exc.params.get("message")}))
        if template_path is None or not Path(template_path).is_file():
            out.append(Issue(code=C.TEMPLATE_MISSING, severity=Severity.ERROR, blocking=True,
                             params={"printer_id": config.id}))
            return out
        try:
            info = self.validate_template(template_path)
        except TemplateError as exc:
            out.append(Issue(code=C.TEMPLATE_INVALID, severity=Severity.ERROR, blocking=True,
                             params={"reason": exc.params.get("reason")}))
            return out
        if info.lift_mm > LIFT_LARGE_MM:
            out.append(Issue(code=C.TEMPLATE_LIFT_LARGE, severity=Severity.WARNING, params={"lift_mm": info.lift_mm}))
        return out

    # ---- the image -----------------------------------------------------------------------------------------------
    def to_printer_image(self, mask: np.ndarray) -> np.ndarray:
        m = np.asarray(mask)
        if m.shape != (RES_X, RES_Y):
            raise BuildError("the mask is not the size of the plane", code="mask_shape", shape=list(m.shape),
                             expected=[RES_X, RES_Y])
        # plane rows run from the back and columns from the left; the file's rows run left to right and its columns
        # front to back: a clockwise quarter turn, no reflection
        return np.ascontiguousarray(np.rot90(m.astype(bool), k=-1))

    # ---- the file ------------------------------------------------------------------------------------------------
    def build(self, mask, exposure: ExposureValues, config: PrinterConfig, template_path: Optional[Path],
              out_path: Path) -> BuildResult:
        return self._write([mask], exposure.pulses, exposure.total_s / exposure.pulses, exposure.rest_s, config, template_path, out_path)

    def build_sequence(self, masks, flashes: int, flash_s: float, rest_s: float, config: PrinterConfig, template_path: Optional[Path],
                       out_path: Path) -> BuildResult:
        return self._write(list(masks), flashes, flash_s, rest_s, config, template_path, out_path)

    def _write(self, masks, flashes: int, flash: float, rest: float, config: PrinterConfig, template_path: Optional[Path],
               out_path: Path) -> BuildResult:
        """One layer per flash, `flashes` for each mask, all of the same time (the printer takes one). A single mask is a board; several are a ladder, whose first
        layer (the one that lights most) is also the preview."""
        settings = self.parse_settings(config.settings)
        if template_path is None:
            raise BuildError("this printer has no template", code="template_missing", printer_id=config.id)
        info = self.validate_template(template_path)
        if flash < MIN_FLASH_S:
            raise BuildError("a flash under 1 s has not been tried on the printer", code="flash_below_minimum",
                             flash_s=flash, min_s=MIN_FLASH_S)
        images = [self.to_printer_image(m) for m in masks]
        lit = int(np.count_nonzero(images[0]))
        if lit == 0 or any(not img.any() for img in images):
            raise BuildError("nothing would be lit", code="mask_all_dark")
        delay = max(1, math.ceil(settings.start_delay_s / (1.0 + rest + settings.cycle_s))) if settings.start_delay_s > 0 else 0
        black = np.zeros((RES_Y, RES_X), bool)
        layers = [Layer(black, 1.0) for _ in range(delay)] + [Layer(img, flash) for img in images for _ in range(flashes)]
        out_path = Path(out_path)
        tmp = out_path.with_name(f".{out_path.name}.part")
        try:
            write_ctb(os.fspath(template_path), os.fspath(tmp), layers, rest_before_lift_s=rest, bottom_layers=delay,
                      header_exposure_s=flash, header_bottom_exposure_s=(1.0 if delay else flash), preview=images[0],
                      preview_crop=True, motion_from_template=True, rest_override_s=rest, park_z_mm=settings.park_z_mm)
            estimated = self._verify(tmp, layers, template_path, flash=flash, delay=delay, rest=rest, park_z=settings.park_z_mm)
            os.replace(tmp, out_path)
        except BuildError:
            raise
        except Exception as exc:                                                 # noqa: BLE001 - nothing may escape half-done
            raise BuildError(f"could not write the file: {exc}", code="write_failed", reason=str(exc)[:200]) from exc
        finally:
            tmp.unlink(missing_ok=True)
        count = len(images) * flashes
        summary = BuildSummary(
            layers=count, delay_layers=delay, flash_s=flash, rest_s=rest, total_light_s=flash * count,
            estimated_s=estimated, lit_pixels=lit, lit_area_mm2=lit * PITCH_MM ** 2, file_bytes=out_path.stat().st_size,
            details={"park_z_mm": settings.park_z_mm, "template": Path(template_path).name, "lift_mm": info.lift_mm,
                     "lift_speed": info.lift_speed, "retract_speed": info.retract_speed, "start_delay_s": settings.start_delay_s})
        return BuildResult(path=out_path, summary=summary, verified=True)

    def _verify(self, path: Path, layers, template_path: Path, *, flash: float, delay: int, rest: float, park_z: float) -> int:
        """Read the file back and compare it with what was meant: every layer's image, the header's exposure, bottom count and
        rest, every layer's Z and exposure, and the copied movement. Returns the printer's estimate of the run, in seconds."""
        def bad(reason, **p):
            raise BuildError(f"the file written does not match what was meant: {reason}", code="verification_failed",
                             reason=reason, **p)
        c, t = CTB(os.fspath(path)), CTB(os.fspath(template_path))
        if not c.crc_ok:
            bad("crc")
        if c.layer_count != len(layers):
            bad("layer_count", got=c.layer_count, expected=len(layers))
        if struct.unpack_from("<f", c.d, ctbio.H_EXP)[0] != _f32(flash):
            bad("exposure")
        if struct.unpack_from("<f", c.d, ctbio.H_BOT_EXP)[0] != _f32(1.0 if delay else flash):
            bad("bottom_exposure")
        if struct.unpack_from("<I", c.d, ctbio.H_BOT_COUNT)[0] != delay:
            bad("bottom_count")
        if struct.unpack_from("<II", c.d, ctbio.H_RES_X) != (RES_X, RES_Y):
            bad("resolution")
        ext2 = struct.unpack_from("<I", c.d, ctbio.H_EXT2_OFF)[0]
        if struct.unpack_from("<f", c.d, ext2 + 24)[0] != _f32(rest):
            bad("rest_before_lift")
        tpl_bottom, tpl_normal = _record(t, 0), _record(t, t.layer_count - 1)
        for i, layer in enumerate(layers):
            info = c.layers[i]
            if info.z != _f32(park_z):
                bad("z", layer=i)
            if info.exposure != _f32(layer.exposure_s):
                bad("layer_exposure", layer=i)
            if not np.array_equal(c.layer_image(i) > 0, layer.image):
                bad("layer_image", layer=i)
            rec, tpl = _record(c, i), (tpl_bottom if i < delay else tpl_normal)
            same = all(a == b for k, (a, b) in enumerate(zip(rec, tpl)) if k != _REST_BEFORE)
            if not same or rec[_REST_BEFORE] != _f32(rest):
                bad("motion", layer=i)
            if not rec[0] > 0:
                bad("lift_distance_zero", layer=i)
        return struct.unpack_from("<I", c.d, ctbio.H_PRINT_TIME)[0]


DRIVER = LD002HDriver()
