---
icon: material/chip
---

# The printer driver

A printer is **a folder**: `gerberslap/printers/<id>/`, with a driver and a photo. The app finds it by itself at start-up and the page shows it (a card in Settings, the choice of printer, the “Ready” state). You touch neither the core, nor the data model, nor the page.

This page explains what a driver does, what to find out before writing one, how to write it and how to create its *template*. A complete driver, with its tests, is in [Example, tests and documentation](example.md); the general architecture is in [Overview](../../architecture/overview.md).

## What a driver does

| The app decides | The driver decides |
|---|---|
| Where each board sits on the plane and the plane's **mask**: a boolean array `(height, width)` of the printer's grid, with row 0 = **back**, column 0 = **left** and true where the light must pass. | How big the screen is and what the printer is called. |
| The requested **dose**: total light time, number of flashes and rest (`ExposureValues`). | **How to realise it** in layers: for example *N* identical layers of *T/N* seconds. |
| The checks, the warnings, the page, the data folder, the download. | The **orientation** of the image in the file (rotation, reflection), the file format, the preview. |
| The language and the sentences. | The **movement** (copied from the template), the **limits** of a flash, the check of the file written. |

The core, the data model, the CAD recognisers and the services **never name the printer or the format of its file**: a test checks it. Everything that depends on a printer lives in its folder.

## Before writing code

The answers to these questions have to be found first, and **tried on the printer**: no behaviour is claimed that has not been verified. The verified facts of the LD-002H are in the [format document](https://github.com/shad0w82/GerberSLAp/blob/main/gerberslap/printers/ld002h/docs/ctb_v5_ld002h_formato.md) (in Italian), each with its level of certainty.

| Question | Why it is needed | How to find out |
|---|---|---|
| The **size of the screen** (mm) and its **resolution** (pixels). Is the pixel square? | They give the plane and the grid. The grid has **a single pitch** for both axes: a screen with non-square pixels is not supported. | The data sheet; then measure an image with a square of known side. |
| **The file format** and how to write it. | It is the heart of the driver. | Public documentation, or decode files produced by the manufacturer's slicer and check by **rebuilding a file from its own pixels and parameters**: the result must match the original (for the LD-002H it differs by 18 bytes, all explained). Check the licence and the copyright of the format. |
| **Orientation**: how does the image arrive on the screen? | The mask has the back in row 0 and the left in column 0, seen from above with the user in front: the driver has to turn it the way the file wants. | A file with an **asymmetric** image (an “F”, a square in one corner, a circle in another, a 50 mm graduated scale), looked at on the screen from above. The F tells rotation from reflection; the scale checks the pitch. |
| **Where it reads the exposure time**: in the header or in each layer? And the rest? | It decides how a dose is realised and where the rest is written. | A file with layers of different times and one where header and layers disagree, timing the flashes. |
| **Limits of a flash**: minimum and maximum tried. | They become `limits` in the descriptor: below the minimum the file is not generated, above the maximum it is generated with a warning. | Try the extreme values; those not tried are not declared. |
| **Movement**: lift distance and speed, Z height, second stages. | It is **copied from the template**, not invented. You need to know which values are dangerous. | Change one value at a time and observe. For the LD-002H a distance of 0 makes the printer do a fallback 5 mm cycle: the driver never writes it and refuses templates that use it. |
| The **preview** the printer shows. | It is a field of the file. | Try a shape and a size and look at the printer's screen. |

For the LD-002H these trials are in the [`pcb_ctb.py`](https://github.com/shad0w82/GerberSLAp/blob/main/gerberslap/printers/ld002h/docs/pcb_ctb.py) command line (`test` for the orientation, `expprobe`, `bottomprobe`, `headerlift`, `speedprobe`): they are research tools of the same kind as the ones to write for a new printer. The method is always the same: prepare a test file, have the printer run it and note what happened, **then** write the code. When you discover something new, update the format document.

## Structure of a driver

```text
gerberslap/printers/<id>/
  __init__.py     from .driver import DRIVER
  driver.py       the driver's class and DRIVER = <the class>()
  icon.png        the upright photo of the printer
```

If needed, the same folder also holds the driver's other modules, for example the reading and writing of the printer's file (`ctbio.py` in the LD-002H), and a `docs/` subfolder with the format document and the trial tools. The `docs/` folders do not go into the Docker image.

The rules by which the app discovers drivers (`printers/__init__.py`):

- The **id** is the folder's name and must match `descriptor.id`. It is also the name of a Python package, so lowercase letters, digits and underscores, starting with a letter. It is also the folder of its data: `<data folder>/printers/<id>/`.
- `DRIVER` must be an instance of `PrinterDriver`. A folder that fails to load (an error, a wrong id, no `DRIVER`) is reported and **does not stop the others**; folders starting with `_` are ignored.
- The default printer, the one of a project that names none, is the **first by id in alphabetical order**: adding one with an id that comes before the others changes the default.
- The driver is a single object, used by several requests at once: it **must not keep state** between one call and the next.

After adding the folder, **restart the server**, because drivers are looked for at start-up. In Settings the card appears, with “Not ready” until the template is installed.

## The descriptor

`DriverDescriptor` (in `printers/base.py`) says everything that needs to be known without using the printer:

| Field | Meaning |
|---|---|
| `id`, `name` | The id (like the folder) and the name shown. |
| `plane` | `Plane(width_mm, height_mm)`: the screen **seen from above with the user in front**. `width_mm` runs from left to right, `height_mm` from front to back. A screen that is upright in its frame is described the same way, turned as it lies on the work surface. |
| `grid` | `Grid(width, height, pitch)`: the mask's pixels, in the same orientation as the plane. **`width × pitch` must equal `width_mm` and `height × pitch` `height_mm`**: the LD-002H driver's test checks it, and your driver's test must do the same. |
| `limits` | `ExposureLimits(min_flash_s, max_proven_flash_s)`; `None` where a limit is not known. |
| `requires_template` | Whether the printer needs a template. |
| `template_name` | The template's file name in the data folder: required if a template is needed, forbidden otherwise. Letters, digits, `_`, `.` and `-`, up to 64 characters; not `printer.json`. |
| `file_extension` | The extension of the file it writes, with the dot, in lowercase (`.ctb`, `.zip`…): the app uses it to name the download. Default `.bin`. |

## The methods

The driver extends `PrinterDriver`. Errors are exceptions with a stable `code` and parameters (numbers and strings): **never a text to show**, because the page writes the sentences.

| Method | Job |
|---|---|
| `parse_settings` | `(settings)`<br>Validates the driver's settings (a dictionary that lives in `printer.json`, see below) and returns them in typed form. `SettingsError` if they are wrong. |
| `validate_template` | `(path)`<br>Judges a template supplied by a person. `TemplateError` with a stable `reason` if it is not good; if it is, it returns what it has learnt. **It is called before installing the template**: a refused template leaves no trace. |
| `check` | `(exposure, config, template)`<br>This printer's warnings, as a list of `Issue` (see below): template missing or invalid, wrong settings, its own rules on the values. `exposure` is `None` when only “is it ready?” is asked, and carries the real values when generating. Whoever uses it knows whether the printer is “ready” by looking at whether any warning blocks. |
| `to_printer_image` | `(mask)`<br>The plane's mask as the file's image: this is where the rotation or reflection found with the trials lives. It refuses a mask of the wrong shape (`mask_shape`). It does not modify its argument. |
| `build` | `(mask, exposure, config, template, path)`<br>Writes the file to `path`, **reads it back and compares it** with what it meant to write, and only then puts it where it was asked. If it does not match it raises `BuildError` and **leaves nothing behind**: it first writes to a temporary file next to it (`.<name>.part`) and renames it with `os.replace`. Returns `BuildResult(path, BuildSummary, verified=True)`. |
| `build_sequence` | `(masks, flashes, flash_s, rest_s, config, template, path)`<br>**Optional.** Writes a file of several masks in a row (the calibration ladder: each step lights more of the plane than the one before): each mask for `flashes` layers of `flash_s` seconds, with `rest_s` of darkness after each, all with the same time. If you do not implement it, the ladder answers `sequence_unsupported` (with the sentence ready) and everything else works. |

### Realising the dose

The app says “T seconds of light in N flashes with R seconds of rest”; how to do it depends on the printer. For the LD-002H, which reads **a single time from the header**, it is *N* identical layers of *T/N* seconds, and the rest is the pause of darkness between one layer and the next. A printer that reads the time from each layer behaves differently: that is exactly what the trial in the previous section must clarify.

### The summary

`BuildSummary` says in numbers what the file will do: layers, initial wait layers, flash, rest, total light, time estimated by the printer (in seconds), lit pixels and area, file size and a free `details` dictionary for the driver's particularities. The page shows it after “Generate”.

### Write error codes

The ones the page already knows how to say are `mask_shape`, `mask_all_dark` (the mask lights nothing), `flash_below_minimum`, `template_missing`, `write_failed`, `verification_failed` and `sequence_unsupported`. `write_failed` and `verification_failed` are server faults (500, with no parameters in the response, because they might name a path); the others are refusals (422) with their parameters. Others can be added, but they need their sentences (see [Warnings, errors and sentences](#warnings-errors-and-sentences)).

## The template

### What it is for

For many printers the file to be fed is a format that only the manufacturer's slicer writes well, with fields nobody documents and a movement that must not be invented. The driver then **does not write the file from scratch**: it starts from a file made by the slicer, the *template*, and changes only what is its own (the images, the exposure, the Z height); the rest it copies as it is. The template is also how whoever uses the app chooses how the printer moves during the exposure.

If instead the format is open and the driver can write all of it, **no template is needed**: `requires_template=False`, `template_name` left out, and `validate_template` may do nothing.

### How to create the template of a new printer

The template is a file produced with the manufacturer's slicer. The recipe, in general:

1. **Choose the right printer profile** in the slicer, so the resolution, the volume and the printer model name in the file are the true ones. A wrong profile gives a file the driver will refuse or, worse, accept.
2. **Slice a simple object**: a cube will do, because the content of the images does not matter and the app replaces them.
3. **Set the movement as you want it during the exposure**: the **smallest lift distance the printer accepts** (and **never zero** if, as in the LD-002H, zero makes it do a fallback cycle), reasonable speeds, and the rest times **at zero** (the app decides the rest), with the mode that waits “only the rest” if the slicer offers it. A single initial (bottom) layer, if the format distinguishes them.
4. **Save the file** in the printer's format. That is the template.

For the LD-002H the ChiTuBox settings are in [Requirements and template](../../installation/requirements.md#how-to-prepare-it). Those of a new printer should be noted in the format document, so that whoever installs the app for that printer knows what to do.

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

It exits with 0 (installed), 1 (file or folder refused: it says why) or 2 (there is no printer with that id); running it again replaces the template. With Docker the same command is used, with the data folder in the volume ([Docker installation](../../installation/install.md#docker-installation)). Then just reload the page: the template is re-read on every request and the printer's card becomes “Ready”.

### Copyright

!!! warning "The template never goes into the repository"
    A slicer's files often contain the manufacturer's copyright notice, which also ends up in the files the app generates. That is why the template never goes into the repository or a Docker image: everyone prepares their own. For a new format, **add its extension to `.gitignore`** (today there is `*.ctb`) and, if needed, to the test samples.

## The driver's settings

The adjustments a person may want to change (for example the Z height at which the layers sit) are the driver's *settings*:

- they are declared with a `pydantic` model (`gerberslap.model.base.Model`) with default values and limits, and `parse_settings` validates it;
- whoever installs writes them in `<data folder>/printers/<id>/printer.json`, an **optional** file:

  ```json
  { "format": "gerberslap-printer", "schema_version": 1, "printer": { "settings": { "compress_level": 9 } } }
  ```

- unreadable or invalid settings do not bring the app down: `check` reports them with `printer_settings_invalid` (with the field and the reason) and generation is blocked.

## Warnings, errors and sentences

The server sends **codes with parameters**; the page turns them into sentences in Italian and English.

- The warning codes are in `gerberslap/model/issues.py` (class `C`). A driver may reuse the ones that are already there: `TEMPLATE_MISSING`, `TEMPLATE_INVALID` (with `reason`), `TEMPLATE_LIFT_LARGE`, `PRINTER_SETTINGS_INVALID`. A warning is an `Issue(code, severity, blocking, params)`: `blocking=True` **stops generation**, the others inform.
- For a **new code** (a warning, a template `reason`, a `build` error) its sentences are needed in `gerberslap/web/static/js/i18n.js`, **in both languages**: `i_<code>` for warnings, `i_template_invalid_<reason>` for the reasons a template is refused, `err_<code>` for write errors. Without the sentence, the page shows the raw code. The codes' parameters are used in sentences as `{name}`.
- Parameters are numbers and strings: no server paths and no ready-written texts.

## The photo

Every driver brings its `icon.png`: the **upright** photo of the printer, a PNG taller than wide, with a transparent background and up to 512 KB (the LD-002H's is 107 × 180 pixels). The driver finds it by itself next to its module, the app serves it at `/api/printers/<id>/picture`, and the page shows it on the card and in the printer menu; without a photo it draws a generic printer. **A test fails if a driver in the repository has no `icon.png`.**
