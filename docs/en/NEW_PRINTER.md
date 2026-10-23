[Italiano](../NUOVA_STAMPANTE.md) | English

# Adding a printer

A guide for developers: how to write the driver of a new printer and how to create and install its *template*. For the general architecture see [ARCHITECTURE.md](ARCHITECTURE.md); to install and run the app, [INSTALLATION.md](INSTALLATION.md).

A printer is **a folder**: `gerberslap/printers/<id>/` with a driver and a photo. The app finds it by itself at start-up and the page shows it (a card in *Settings*, the choice of printer, the "Ready" state). You touch neither the core, nor the data model, nor the page.

- [What a driver does](#what-a-driver-does)
- [Before writing code](#before-writing-code)
- [Structure of a driver](#structure-of-a-driver)
- [The descriptor](#the-descriptor)
- [The methods](#the-methods)
- [The template](#the-template)
- [The driver's settings](#the-drivers-settings)
- [Warnings, errors and sentences](#warnings-errors-and-sentences)
- [The photo](#the-photo)
- [A complete example](#a-complete-example)
- [Tests to write](#tests-to-write)
- [Documenting](#documenting)
- [Common mistakes](#common-mistakes)

## What a driver does

| The app decides | The driver decides |
|---|---|
| Where each board sits on the plane; the plane's **mask**: a boolean array `(height, width)` of the printer's grid, row 0 = **back**, column 0 = **left**, true where the light must pass. | How big the screen is and what the printer is called. |
| The requested **dose**: total light time, number of flashes and rest (`ExposureValues`). | **How to realise it** in layers: for example *N* identical layers of *T/N* seconds. |
| The checks, the warnings, the page, the data folder, the download. | The **orientation** of the image in the file (rotation, reflection), the file format, the preview. |
| The language and the sentences. | The **movement** (copied from the template), the **limits** of a flash, the check of the file written. |

The core, the data model, the CAD recognisers and the services **never name the printer or the format of its file**: a test checks it. Everything that depends on a printer lives in its folder.

## Before writing code

The answers to these questions have to be found first, and **tried on the printer**: no behaviour is claimed that has not been verified (in the repository, the verified facts of the LD-002H are in [ctb_v5_ld002h_formato.md](../../gerberslap/printers/ld002h/docs/ctb_v5_ld002h_formato.md) (in Italian), each with its level of certainty).

| Question | Why it is needed | How to find out |
|---|---|---|
| The **size of the screen** (mm) and its **resolution** (pixels). Is the pixel square? | They give the plane and the grid. The grid has **a single pitch** for both axes: a screen with non-square pixels is not supported. | The data sheet; then measure an image with a square of known side. |
| **The file format** and how to write it | It is the heart of the driver. | Public documentation, or decode files produced by the manufacturer's slicer and check by **rebuilding a file from its own pixels and parameters**: the result must match the original (for the LD-002H it differs by 18 bytes, all explained). Check the licence and the copyright of the format. |
| **Orientation**: how does the image arrive on the screen? | The mask has the back in row 0 and the left in column 0, seen from above with the user in front: the driver has to turn it the way the file wants. | A file with an **asymmetric** image (an "F", a square in one corner, a circle in another, a 50 mm graduated scale), looked at on the screen from above. The F tells rotation from reflection; the scale checks the pitch. |
| **Where it reads the exposure time**: in the header or in each layer? And the rest? | It decides how a dose is realised and where the rest is written. | A file with layers of different times and one where header and layers disagree, timing the flashes. |
| **Limits of a flash**: minimum and maximum tried | They become `limits` in the descriptor: below the minimum the file is not generated, above the maximum it is generated with a warning. | Try the extreme values; those not tried are not declared. |
| **Movement**: lift distance and speed, Z height, second stages | It is **copied from the template**, not invented. You need to know which values are dangerous. | Change one value at a time and observe. For the LD-002H a distance of 0 makes the printer do a fallback 5 mm cycle: the driver never writes it and refuses templates that use it. |
| The **preview** the printer shows | It is a field of the file. | Try a shape and a size and look at the printer's screen. |

For the LD-002H, these trials are in the [`pcb_ctb.py`](../../gerberslap/printers/ld002h/docs/pcb_ctb.py) command line (`test` for the orientation, `expprobe`, `bottomprobe`, `headerlift`, `speedprobe`): they are research tools of the same kind as the ones to write for a new printer. The method is always the same: prepare a test file, have the printer run it and note what happened, **then** write the code. When you discover something new, update the format document.

## Structure of a driver

```
gerberslap/printers/<id>/
  __init__.py     from .driver import DRIVER
  driver.py       the driver's class and DRIVER = <the class>()
  icon.png        the upright photo of the printer
```

If needed, the same folder also holds the driver's other modules, for example the reading and writing of the printer's file (`ctbio.py` in the LD-002H), and a `docs/` subfolder with the format document and the trial tools (like `ctb_v5_ld002h_formato.md` and `pcb_ctb.py`): the `docs/` folders do not go into the Docker image.

Discovery rules (`printers/__init__.py`):

- The **id** is the folder's name and must match `descriptor.id`; it is also the name of a Python package, so lowercase letters, digits and underscores, starting with a letter. It is also the folder of its data: `<data folder>/printers/<id>/`.
- `DRIVER` must be an instance of `PrinterDriver`. A folder that fails to load (an error, a wrong id, no `DRIVER`) is reported and **does not stop the others**; folders starting with `_` are ignored.
- The default printer, the one of a project that names none, is the **first by id in alphabetical order**: adding one with an id that comes before the others changes the default.
- The driver is a single object, used by several requests at once: it **must not keep state** between one call and the next.

After adding the folder, **restart the server** (drivers are looked for at start-up). In *Settings* the card appears, with "Not ready" until the template is installed.

## The descriptor

`DriverDescriptor` (in `printers/base.py`) says everything that needs to be known without using the printer:

| Field | Meaning |
|---|---|
| `id`, `name` | The id (like the folder) and the name shown. |
| `plane` | `Plane(width_mm, height_mm)`: the screen **seen from above with the user in front**. `width_mm` runs from left to right, `height_mm` from front to back. A screen that is upright in its frame is described the same way, turned as it lies on the work surface. |
| `grid` | `Grid(width, height, pitch)`: the mask's pixels, in the same orientation as the plane. **`width × pitch` must equal `width_mm` and `height × pitch` `height_mm`** (the LD-002H driver's test checks it: write the same for yours). |
| `limits` | `ExposureLimits(min_flash_s, max_proven_flash_s)`; `None` where a limit is not known. |
| `requires_template` | Whether the printer needs a template. |
| `template_name` | The template's file name in the data folder: required if a template is needed, forbidden otherwise. Letters, digits, `_`, `.` and `-`, up to 64 characters; not `printer.json`. |
| `file_extension` | The extension of the file it writes, with the dot, in lowercase (`.ctb`, `.zip`…): the app uses it to name the download. Default `.bin`. |

## The methods

The driver extends `PrinterDriver`. Errors are exceptions with a stable `code` and parameters (numbers and strings): **never a text to show**, the page writes the sentences.

| Method | Job |
|---|---|
| `parse_settings(settings)` | Validates the driver's settings (a dictionary that lives in `printer.json`, see below) and returns them in typed form. `SettingsError` if they are wrong. |
| `validate_template(path)` | Judges a template supplied by a person. `TemplateError` with a stable `reason` if it is not good; if it is, it returns what it has learnt. **It is called before installing the template**: a refused template leaves no trace. |
| `check(exposure, config, template)` | This printer's warnings, as a list of `Issue` (see below): template missing or invalid, wrong settings, its own rules on the values. `exposure` is `None` when only "is it ready?" is asked, and the real values when generating. Whoever uses it knows whether it is "ready" by looking at whether any warning blocks. |
| `to_printer_image(mask)` | The plane's mask as the file's image: this is where the rotation or reflection you discovered lives. It refuses a mask of the wrong shape (`mask_shape`). It does not modify its argument. |
| `build(mask, exposure, config, template, path)` | Writes the file to `path`, **reads it back and compares it** with what it meant to write, and only then puts it where it was asked: if it does not match it raises `BuildError` and **leaves nothing behind**. It first writes to a temporary file next to it (`.<name>.part`) and renames it with `os.replace`. Returns `BuildResult(path, BuildSummary, verified=True)`. |
| `build_sequence(masks, flashes, flash_s, rest_s, config, template, path)` | **Optional.** Writes a file of several masks in a row (the calibration ladder: each step lights more of the plane than the one before): each mask for `flashes` layers of `flash_s` seconds, with `rest_s` of darkness after each, all with the same time. If you do not implement it, the ladder answers `sequence_unsupported` (with the sentence ready); everything else works. |

**Realising the dose.** The app says "T seconds of light in N flashes with R seconds of rest"; how to do it depends on the printer. For the LD-002H, which reads **a single time from the header**, it is *N* identical layers of *T/N* seconds, and the rest is the pause of darkness between one layer and the next. A printer that reads the time from each layer behaves differently: that is exactly what the trial in the previous section must clarify.

**The summary.** `BuildSummary` says what the file will do, in numbers: layers, initial wait layers, flash, rest, total light, time estimated by the printer (in seconds), lit pixels and area, file size and a free `details` dictionary for the driver's particularities. The page shows it after "Generate".

**Write error codes.** The ones the page already knows how to say: `mask_shape`, `mask_all_dark` (the mask lights nothing), `flash_below_minimum`, `template_missing`, `write_failed`, `verification_failed`, `sequence_unsupported`. `write_failed` and `verification_failed` are server faults (500, with no parameters in the response, because they might name a path); the others are refusals (422) with their parameters. You can add others: they need sentences (see below).

## The template

### What it is for

For many printers the file to be fed is a format that only the manufacturer's slicer writes well, with fields nobody documents and a movement that must not be invented. The driver then **does not write the file from scratch**: it starts from a file made by the slicer, the *template*, and changes only what is its own (the images, the exposure, the Z height); the rest it copies as it is. The template is also how whoever uses the app chooses how the printer moves during the exposure.

If instead the format is open and the driver can write all of it, **no template is needed**: `requires_template=False`, `template_name` left out, and `validate_template` may do nothing.

### How to create the template of a new printer

The template is a file produced with the manufacturer's slicer. The recipe, in general:

1. **Choose the right printer profile** in the slicer: so the resolution, the volume and the printer model name in the file are the true ones. A wrong profile gives a file the driver will refuse (or, worse, accept).
2. **Slice a simple object** (a cube will do): the content of the images does not matter, the app replaces them.
3. **Set the movement as you want it during the exposure**: the **smallest lift distance the printer accepts** (and **never zero** if, as in the LD-002H, zero makes it do a fallback cycle), reasonable speeds, and the rest times **at zero** (the app decides the rest) with the mode that waits "only the rest", if the slicer offers it. A single initial (bottom) layer, if the format distinguishes them.
4. **Save the file** in the printer's format. That is the template.

For the LD-002H, in ChiTuBox: *Waiting Mode* "Resting time" with the three rests at 0; bottom and normal lift distance 0.001 mm (and 0 for the second value, the one after the "+"); the four speeds at 500 mm/min (and 0 for the second values); one bottom layer. (See [INSTALLATION.md](INSTALLATION.md#the-printer-template).)

Note in the format document **which slicer settings** are needed, so that whoever installs the app for that printer knows what to do.

### What the driver must do with the template

- **`validate_template`** refuses, with a stable `reason`, everything that would make the file wrong or dangerous: a file that is not of the format, of another version, damaged (if the format has an integrity check), with the resolution of another screen, with no layers, with data that cannot be read, **with a dangerous movement** (the LD-002H's distance 0, an invalid speed). A template that works but is not ideal (for the LD-002H, a large lift distance makes the flashes slow) is accepted and flagged with a warning from `check`.
- **`check`** gives `template_missing` if the file is not there and `template_invalid` (with `reason`) if `validate_template` refuses it.
- **`build`** copies from the template the part that is not its own and replaces only what is its own, recomputes what depends on the content (offsets, sizes, CRC) and then **reads back** the file written.
- Nothing is invented: if a field is not understood, it is copied from the template as it is.

### Where it lives and how it is installed

The template lives in the data folder: `<data folder>/printers/<id>/<template_name>`. It is installed with the app's command, which judges it with the driver **before** writing anything:

```bash
.venv/bin/python -m gerberslap.web --install-template <id> /path/to/template
```

It exits with 0 (installed), 1 (file or folder refused: it says why) or 2 (there is no printer with that id); running it again replaces the template. In Docker the same command is used with the data folder in the volume (see [INSTALLATION.md](INSTALLATION.md#docker-installation-planned)). Then just reload the page: the template is re-read on every request and the printer's card becomes "Ready".

### Copyright

A slicer's files often contain the manufacturer's copyright notice, which also ends up in the files the app generates. That is why **the template never goes into the repository or a Docker image**: everyone prepares their own. For a new format, **add its extension to `.gitignore`** (today there is `*.ctb`) and, if needed, to the test samples.

## The driver's settings

The adjustments a person may want to change (for example the Z height at which the layers sit) are the driver's *settings*:

- They are declared with a `pydantic` model (`gerberslap.model.base.Model`) with default values and limits, and `parse_settings` validates it.
- Whoever installs writes them in `<data folder>/printers/<id>/printer.json`, an **optional** file:

  ```json
  { "format": "gerberslap-printer", "schema_version": 1, "printer": { "settings": { "compress_level": 9 } } }
  ```
- Unreadable or invalid settings do not bring the app down: `check` reports them with `printer_settings_invalid` (with the field and the reason) and generation is blocked.

## Warnings, errors and sentences

The server sends **codes with parameters**; the page turns them into sentences in Italian and English.

- The warning codes are in `gerberslap/model/issues.py` (class `C`). A driver may reuse the ones that are already there: `TEMPLATE_MISSING`, `TEMPLATE_INVALID` (with `reason`), `TEMPLATE_LIFT_LARGE`, `PRINTER_SETTINGS_INVALID`. A warning is an `Issue(code, severity, blocking, params)`: `blocking=True` **stops generation**, the others inform.
- For a **new code** (a warning, a template `reason`, a `build` error) its sentences are needed in `gerberslap/web/static/js/i18n.js`, **in both languages**: `i_<code>` for warnings, `i_template_invalid_<reason>` for the reasons a template is refused, `err_<code>` for write errors. Without the sentence, the page shows the raw code. The codes' parameters are used in sentences as `{name}`.
- Parameters are numbers and strings: no server paths and no ready-written texts.

## The photo

Every driver brings its `icon.png`: the **upright** photo of the printer (a PNG taller than wide, with a transparent background, up to 512 KB; the LD-002H's is 107 × 180 pixels). The driver finds it by itself next to its module, the app serves it at `/api/printers/<id>/picture`, and the page shows it on the card and in the printer menu; without a photo it draws a generic printer. **A test fails if a driver in the repository has no `icon.png`.**

## A complete example

A minimal but complete driver, with a template: an imaginary printer that takes a **zip of PNG layers** with a `manifest.json`, and whose template is a small `template.json` with the lift settings. It shows everything: descriptor, settings, template validation, warnings, orientation (here the file has the *front* as its first row), writing with read-back and comparison. Tried: found by the registry, "Not ready" without a template, template refused and then installed, file generated by the app, too-short flash blocked, calibration ladder answering `sequence_unsupported` (it does not implement `build_sequence`).

`gerberslap/printers/zipdemo/__init__.py`:

```python
"""Demo printer: takes a zip of PNG layers and a manifest, with the lift settings copied from a template."""
from .driver import DRIVER

__all__ = ["DRIVER"]
```

`gerberslap/printers/zipdemo/driver.py`:

```python
import io
import json
import os
import zipfile
from pathlib import Path
from typing import Mapping, Optional

import numpy as np
from PIL import Image
from pydantic import Field, ValidationError

from gerberslap.core import Grid
from gerberslap.model import C, ExposureLimits, ExposureValues, Issue, Plane, PrinterConfig, Severity
from gerberslap.model.base import Model
from gerberslap.printers.base import (BuildError, BuildResult, BuildSummary, DriverDescriptor, PrinterDriver,
                                      SettingsError, TemplateError)

PITCH = 0.05                          # mm per pixel, the same on both axes
MIN_FLASH_S = 0.5                     # under this the printer was never tried
MAX_PROVEN_FLASH_S = 30.0


class DemoSettings(Model):
    """The driver's own settings (`printers/zipdemo/printer.json`), all optional."""
    compress_level: int = Field(default=6, ge=0, le=9)


class ZipDemoDriver(PrinterDriver):
    descriptor = DriverDescriptor(
        id="zipdemo", name="Zip demo printer",
        plane=Plane(width_mm=100.0, height_mm=60.0),            # the screen seen from above, the user in front (mm)
        grid=Grid(width=2000, height=1200, pitch=PITCH),        # 2000 x 1200 px: width x PITCH = 100 mm, height x PITCH = 60 mm
        limits=ExposureLimits(min_flash_s=MIN_FLASH_S, max_proven_flash_s=MAX_PROVEN_FLASH_S),
        requires_template=True, template_name="template.json", file_extension=".zip")

    # ---- settings and template ----------------------------------------------------------------------------------
    def parse_settings(self, settings: Optional[Mapping]) -> DemoSettings:
        try:
            return DemoSettings.model_validate(dict(settings or {}))
        except ValidationError as exc:
            first = exc.errors()[0]
            raise SettingsError(f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}",
                                field=".".join(str(p) for p in first["loc"]) or None, message=first["msg"]) from None

    def validate_template(self, path: Path) -> dict:
        def refuse(reason, **params):
            raise TemplateError(f"the template cannot be used: {reason}", reason=reason, **params)
        try:
            body = json.loads(Path(path).read_text())
        except FileNotFoundError:
            refuse("missing")
        except (OSError, ValueError):
            refuse("not_json")
        if not isinstance(body, dict) or not isinstance(body.get("lift_mm"), (int, float)) or not isinstance(body.get("lift_mm_per_min"), (int, float)):
            refuse("fields_missing")
        if not body["lift_mm"] > 0:
            refuse("lift_distance_zero")                         # the printer does its own long cycle with a lift of 0
        if not body["lift_mm_per_min"] >= 1:
            refuse("lift_speed_invalid")
        return body

    def check(self, exposure: Optional[ExposureValues], config: PrinterConfig, template_path: Optional[Path]) -> list:
        out = []
        try:
            self.parse_settings(config.settings)
        except SettingsError as exc:
            out.append(Issue(code=C.PRINTER_SETTINGS_INVALID, severity=Severity.ERROR, blocking=True,
                             params={"field": exc.params.get("field"), "message": exc.params.get("message")}))
        if template_path is None or not Path(template_path).is_file():
            out.append(Issue(code=C.TEMPLATE_MISSING, severity=Severity.ERROR, blocking=True, params={"printer_id": config.id}))
            return out
        try:
            self.validate_template(template_path)
        except TemplateError as exc:
            out.append(Issue(code=C.TEMPLATE_INVALID, severity=Severity.ERROR, blocking=True, params={"reason": exc.params.get("reason")}))
        return out

    # ---- the image and the file ---------------------------------------------------------------------------------
    def to_printer_image(self, mask: np.ndarray) -> np.ndarray:
        m = np.asarray(mask)
        if m.shape != (1200, 2000):
            raise BuildError("the mask is not the size of the plane", code="mask_shape", shape=list(m.shape), expected=[1200, 2000])
        return np.ascontiguousarray(np.flipud(m.astype(bool)))   # this printer's file has the FRONT as row 0 (the plane has the back)

    def build(self, mask, exposure: ExposureValues, config: PrinterConfig, template_path: Optional[Path], out_path: Path) -> BuildResult:
        settings = self.parse_settings(config.settings)
        if template_path is None:
            raise BuildError("this printer has no template", code="template_missing", printer_id=config.id)
        template = self.validate_template(template_path)
        flash = exposure.total_s / exposure.pulses
        if flash < MIN_FLASH_S:
            raise BuildError("a flash this short has not been tried", code="flash_below_minimum", flash_s=flash, min_s=MIN_FLASH_S)
        image = self.to_printer_image(mask)
        if not image.any():
            raise BuildError("nothing would be lit", code="mask_all_dark")
        png = io.BytesIO()
        Image.fromarray(image.astype(np.uint8) * 255).save(png, format="PNG")
        manifest = {"layers": exposure.pulses, "flash_s": flash, "rest_s": exposure.rest_s,
                    "lift_mm": template["lift_mm"], "lift_mm_per_min": template["lift_mm_per_min"]}   # the movement is the template's, copied
        out_path = Path(out_path)
        tmp = out_path.with_name(f".{out_path.name}.part")
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=settings.compress_level) as z:
                z.writestr("manifest.json", json.dumps(manifest, indent=2))
                for i in range(exposure.pulses):                  # one layer per flash, all the same
                    z.writestr(f"layer_{i:03d}.png", png.getvalue())
            self._verify(tmp, image, manifest)                    # read back and compare BEFORE it takes its place
            os.replace(tmp, out_path)
        except BuildError:
            raise
        except Exception as exc:                                  # noqa: BLE001 - nothing may escape half done
            raise BuildError(f"could not write the file: {exc}", code="write_failed", reason=str(exc)[:200]) from exc
        finally:
            tmp.unlink(missing_ok=True)
        lit = int(np.count_nonzero(image))
        summary = BuildSummary(layers=exposure.pulses, delay_layers=0, flash_s=flash, rest_s=exposure.rest_s, total_light_s=exposure.total_s,
                               estimated_s=int(exposure.pulses * (flash + exposure.rest_s)), lit_pixels=lit, lit_area_mm2=lit * PITCH ** 2,
                               file_bytes=out_path.stat().st_size, details={"template": Path(template_path).name})
        return BuildResult(path=out_path, summary=summary, verified=True)

    @staticmethod
    def _verify(path: Path, image: np.ndarray, manifest: dict) -> None:
        def bad(reason, **params):
            raise BuildError(f"the file written does not match what was meant: {reason}", code="verification_failed", reason=reason, **params)
        with zipfile.ZipFile(path) as z:
            if json.loads(z.read("manifest.json")) != manifest:
                bad("manifest")
            names = sorted(n for n in z.namelist() if n.startswith("layer_"))
            if len(names) != manifest["layers"]:
                bad("layer_count", got=len(names))
            for n in names:
                if not np.array_equal(np.asarray(Image.open(io.BytesIO(z.read(n)))) > 0, image):
                    bad("layer_image", layer=n)


DRIVER = ZipDemoDriver()
```

This printer's template (a `template.json` file, to be installed with `--install-template zipdemo template.json`):

```json
{ "lift_mm": 0.001, "lift_mm_per_min": 500 }
```

For a real printer, `build` does not write a manifest but the manufacturer's format, copying from the template everything that is not its own; the structure is identical. The reference real driver is `gerberslap/printers/ld002h/driver.py`.

## Tests to write

A driver's tests are like those of `tests/test_printers.py`. The minimum list:

- **The descriptor**: `grid × pitch = plane`; an invalid `template_name` or extension is refused (the constructor does it by itself).
- **The orientation**: a mask with a single pixel in a known corner arrives in the corner you measured on the printer; the wrong shape is refused with `mask_shape`. If possible, a second check computed another way (an independent oracle).
- **The template**: one case for each `reason` of `validate_template`, and a good one. The test template **is built in the test** (a manufacturer's file is not committed); tests that need a real template skip themselves when it is missing, as `needs_template` does in `tests/test_printers.py`.
- **The checks**: `template_missing`, `template_invalid`, `printer_settings_invalid`, and "no warnings" when all is well.
- **The writing**: the file is read back and matches what was meant; **refusals happen before writing** (no file left, no `.part`); the dose is realised as it should be (number and time of layers, rest).
- **The read-back**: a test that alters the written file (or simulates an error) and checks that `build` hands over nothing.
- **From scratch up to the app**: the driver in a `Registry`, a temporary `DataStore`, the template installed with `install_template`, a zip uploaded and `POST /api/generate` (see `tests/test_generate.py` and `tests/support/fakeprinters.py`, which has a fake printer that writes a few bytes).
- **The ladder**, if you implement `build_sequence`: several masks, in order, with the right flashes.
- **The boundaries**: add the printer's name and the format's extension to the expression in `test_the_generic_packages_never_name_a_printer_or_its_file_format` in `tests/test_printers.py` (today `ctb|ld-?002h|creality`), so that nobody writes them by mistake in the core, the data model or the services.
- **The photo**: the test that runs through all the drivers already checks it.

An example, for the driver above (`tests/test_zipdemo.py`):

```python
"""Tests of a new driver (the example of the guide), written the way tests/test_printers.py writes them."""
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from gerberslap.printers.zipdemo import DRIVER
from gerberslap.model import ExposureValues, PrinterConfig
from gerberslap.printers.base import BuildError, SettingsError, TemplateError

CFG = PrinterConfig(id="zipdemo", name="Zip demo printer", driver="zipdemo")
GOOD = {"lift_mm": 0.001, "lift_mm_per_min": 500}


def template(tmp_path, body, name="template.json"):
    path = tmp_path / name
    path.write_text(body if isinstance(body, str) else json.dumps(body))
    return path


def test_the_plane_and_the_grid_describe_the_same_screen():
    d = DRIVER.descriptor
    assert d.grid.width * d.grid.pitch == pytest.approx(d.plane.width_mm) and d.grid.height * d.grid.pitch == pytest.approx(d.plane.height_mm)


def test_the_image_of_the_file_is_the_plane_turned_the_way_the_printer_wants():
    mask = np.zeros((1200, 2000), bool)
    mask[0, 0] = True                                                  # the back-left corner of the plane (row 0 is the back, column 0 the left)
    image = DRIVER.to_printer_image(mask)
    assert image[1199, 0] and image.sum() == 1                         # this printer's file has the front as its first row: the corner is on the last
    with pytest.raises(BuildError) as e:
        DRIVER.to_printer_image(np.zeros((10, 10), bool))
    assert e.value.code == "mask_shape"


@pytest.mark.parametrize("body, reason", [("not json", "not_json"), ({"lift_mm": 1}, "fields_missing"), ({**GOOD, "lift_mm": 0}, "lift_distance_zero"),
                                          ({**GOOD, "lift_mm_per_min": 0}, "lift_speed_invalid")])
def test_a_template_that_cannot_be_used_is_refused_with_its_reason(tmp_path, body, reason):
    with pytest.raises(TemplateError) as e:
        DRIVER.validate_template(template(tmp_path, body))
    assert e.value.params["reason"] == reason
    assert DRIVER.validate_template(template(tmp_path, GOOD, "ok.json")) == GOOD


def test_the_checks_say_what_is_missing(tmp_path):
    assert [i.code for i in DRIVER.check(None, CFG, None)] == ["template_missing"]
    assert [i.code for i in DRIVER.check(None, CFG, template(tmp_path, {**GOOD, "lift_mm": 0}))] == ["template_invalid"]
    assert DRIVER.check(None, CFG, template(tmp_path, GOOD)) == []
    assert [i.code for i in DRIVER.check(None, CFG.model_copy(update={"settings": {"compress_level": 99}}), template(tmp_path, GOOD))] == ["printer_settings_invalid"]
    with pytest.raises(SettingsError):
        DRIVER.parse_settings({"compress_level": "high"})


def test_the_file_is_read_back_and_is_what_was_meant(tmp_path):
    mask = np.zeros((1200, 2000), bool)
    mask[100:300, 200:900] = True
    result = DRIVER.build(mask, ExposureValues(total_s=6, pulses=3, rest_s=1), CFG, template(tmp_path, GOOD), tmp_path / "out.zip")
    assert result.verified and result.summary.layers == 3 and result.summary.flash_s == 2.0 and result.summary.lit_pixels == 200 * 700
    with zipfile.ZipFile(result.path) as z:
        assert json.loads(z.read("manifest.json"))["lift_mm"] == 0.001                 # the movement is the template's
        assert len([n for n in z.namelist() if n.startswith("layer_")]) == 3
    assert not list(tmp_path.glob(".*.part"))                                          # nothing left behind


def test_what_a_driver_refuses_it_refuses_before_writing_anything(tmp_path):
    lit = np.ones((1200, 2000), bool)
    for mask, values, code in ((lit, ExposureValues(total_s=1, pulses=10, rest_s=0), "flash_below_minimum"), (np.zeros_like(lit), ExposureValues(total_s=6, pulses=3, rest_s=1), "mask_all_dark")):
        with pytest.raises(BuildError) as e:
            DRIVER.build(mask, values, CFG, template(tmp_path, GOOD), tmp_path / "x.zip")
        assert e.value.code == code and not (tmp_path / "x.zip").exists()
    with pytest.raises(BuildError) as e:
        DRIVER.build(lit, ExposureValues(total_s=6, pulses=3, rest_s=1), CFG, None, tmp_path / "x.zip")
    assert e.value.code == "template_missing"
```

To try the integration by hand: restart the server with a trial data folder, install the template, open a Gerber zip, choose the printer from the pill at the top left and generate the file; then open it with the format's tools (for the LD-002H's `.ctb`, `python3 gerberslap/printers/ld002h/ctbio.py info file.ctb` and `... layer file.ctb N out.png`).

## Documenting

- The **file format** and the **verified behaviour** of the printer in a document like `ctb_v5_ld002h_formato.md`: each fact with its level of certainty (tried on the printer, matches in several files, deduced, unknown) and the open points.
- The **slicer settings** to make the template, in [INSTALLATION.md](INSTALLATION.md#the-printer-template) (one section per printer) and the list of supported printers in `README.md`.
- If anything in the architecture changes, [ARCHITECTURE.md](ARCHITECTURE.md).

## Common mistakes

- **Orientation and mirror confused.** The mask already has the back in row 0 and the left in column 0; a board's **mirror** (copper facing down) is a user's choice made *before*, on the placed board: the driver **never** mirrors by itself.
- **`grid × pitch` different from `plane`.** The boards would come out at the wrong size.
- **Writing an invented movement.** It is always copied from the template; a dangerous value (like the distance 0) has to be refused in `validate_template`.
- **Leaving a half-written file.** Write to a temporary file, read back, rename with `os.replace`; on an error nothing is left.
- **A single exposure time.** If the printer reads it from one place only, all normal layers have the same time: a dose is "N layers of T/N", not layers of different times.
- **Declaring limits not tried.** `max_proven_flash_s` is "the maximum tried", not "the theoretical maximum".
- **Forgetting the sentences** of a new code, in either language.
- **State in the driver.** It is used by several requests at once: no variables that change between one call and the next.
- **The template in the repository.** The extension in `.gitignore`, never in the Docker image.
- **A different id and folder**, or an id that passes `ld002h` in alphabetical order without meaning to (it becomes the default printer).
