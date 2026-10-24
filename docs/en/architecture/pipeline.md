---
icon: material/pipe
---

# From project to file

How a project becomes the print file: the pipeline that builds the mask, the drivers that write it in the printer's format, the way exposure is described and the calibration ladder. The layers and the conventions are in the [Overview](overview.md).

## From project to mask

`services/pipeline.py:render(project, files, grid, polarity)` takes five steps:

1. **The material of each board**, from the layers that are on, in stack order.
    - Copper and silkscreen are used as drawn.
    - The outline is a line at least `min_outline_mm` wide.
    - The **solder mask** is *the board area minus the openings its file draws*: the polarity declared in the mask file is not used.
    - The drills, if the layer is on, are subtracted.
2. **Placement** on the plane: position, rotation, mirror.
3. **Union** of all the boards. Where they overlap, the result is the sum.
4. **Coverage** per pixel from the vector geometry, never by resampling an image, computed once.
5. **Polarity**, last: with the **positive** resist light passes where there is *no* material (where the copper is to be removed); with the **negative** one, where there is.

The copper, mask and silkscreen layers form the **stack**. Their order in the list is the drawing order in the Material view (reversed if the board is mirrored, because the underside is what you see) and never changes what is exposed. Outline and drills stand apart, at the bottom, and do not move.

Reading the Gerber files and building the material are the slow part, and are kept in a cache by file hash and by what is on: moving a board costs a raster, not a re-read. Outside the plane the material is cut, with a warning.

## Printers: drivers and template

A driver is an object in `printers/<id>/__init__.py`, exposed as `DRIVER`. The folder is named after the driver's id and also holds `icon.png`, the upright photo (transparent background) the page shows. Drivers are found by themselves at start-up; to write one, see [The printer driver](../development/new-printer/driver.md).

**The descriptor** says what needs to be known about the printer without using it: id and name, the plane in mm, the pixel grid, the limits of a flash (minimum, and maximum tried), whether a template is needed, the template's file name and the extension of the file it writes.

**The interface** (`printers/base.py`):

| Method | Job |
|---|---|
| `check` | `(exposure, config, template)`<br>The printer's warnings (template missing or invalid, wrong settings), like every other check. |
| `validate_template` | `(file)`<br>Judges a template the user supplied; refuses with a reason. |
| `to_printer_image` | `(mask)`<br>The plane's mask as the image of the printer's file. |
| `build` | `(mask, exposure, config, template, path)`<br>Writes the file for one mask, reads it back, compares it and only then hands it over; otherwise `BuildError`. |
| `build_sequence` | `(masks, flashes, …)`<br>Writes a file of several masks in a row (the ladder); a driver that cannot do it says so. |

### The LD-002H driver

It lives in `printers/ld002h/`, on top of `ctbio.py` in the same folder: reading and writing the `.ctb` v5 (encryption, RLE, previews, CRC), validated byte by byte against ChiTuBox files. In the `docs/` subfolder are the document of the format and of the verified behaviour of the printer (`ctb_v5_ld002h_formato.md`, in Italian) and `pcb_ctb.py`, a trial command line from which the driver and that document were born.

- The file's image is the plane turned a quarter turn clockwise, with no reflection.
- A dose of *T* seconds in *N* flashes is *N* identical layers of *T/N* seconds: the printer reads **a single exposure time from the header** and applies it to every layer. The **rest** between flashes is the only pause of darkness, and is written as the rest before lift.
- The movement (distances and speeds, second stages, the other rests) is copied from the template. A lift distance of 0 is never written, because the printer would do a 5 mm cycle. All layers sit at the same low Z height (default 1 mm).
- The file's preview is the first layer, seen from above, cropped to what is lit.
- **The template is judged before use**: a `.ctb` v5 file, correct CRC, the screen's resolution, at least one layer that decodes, lift distances greater than 0 and valid speeds. A template with a large lift distance (over 1 mm) is accepted but gives a warning, because it makes the flashes slow.
- Limits: the minimum flash is 1 s (below it nothing is generated); over 20 s the file is generated with a warning, because it has not been tried.
- **The check before handing over.** The file is written to a hidden temporary file, read back, and compared: the CRC, the number of layers, the exposure and the number of bottom layers in the header, the resolution, the rest, and for each layer the Z height, the exposure, the copied movement and the pixels. Only if everything matches does the file take its place.

The `.ctb` template is not in the repository, because it contains the manufacturer's copyright notice, which also ends up in the generated files. It is installed in the data folder, as `printers/<id>/template.ctb` ([Requirements and template](../installation/requirements.md#the-printer-template)).

## Exposure, recipes and dosages

- **Printer**: the type of printer (the driver's id), not the unit with its serial number. It has no exposure values.
- **Recipe**: name, **polarity** (which cannot be changed after creation: if the resist changes, it is another recipe), resist, development, notes and its dosages.
- **Dosage**: total light time, number of flashes and rest **found by trying, for one printer**, with an optional date, name and note. A recipe's dosages for a printer are all valid alternatives (for example for fine tracks or for large ground planes), not versions of one another. “Dose” is only the total light time.

The project never holds the exposure values: it holds a reference (the recipe's id and name, the polarity, the chosen dosage), and the values come from the dosage or are entered by hand. When a project is opened, the recipe's polarity wins over the saved one, because a wrong polarity ruins the board, and says so. A recipe the library does not have is reported, and the project keeps the saved polarity and no recipe.

**The library** lives in the data folder (`recipes/<id>.json`, one recipe per file) and is managed from the page through the `/api/recipes` routes. Every operation answers with the recipe as it is afterwards. A dosage's date changes only if its values change. Changes are read, changed and written inside a lock, so two browsers do not lose each other's changes. The ceilings are 500 recipes and 100 dosages per recipe. With `--no-library` these routes are not registered (404).

**The server generates with what it receives.** The generation request carries the project, the polarity, the three values and, if there is one, the chosen recipe (id, name, polarity). It never reads the library, which is why it works the same with `--no-library`.

## The calibration ladder

It serves to find the right time for a resist: a single file in which strips side by side receive increasing times. Strip *k* is lit for *k* times the time of the first. Step *i* of the file lights the strips from *i* on, with one time per layer, the same for all, because the printer uses one. Each step is made of `pulses` flashes of `step / pulses` seconds with the rest between them, so the file has `bands × pulses` layers.

Each strip (size of your choice, 13 × 76 mm to start with, 1 mm of dark between one strip and the next, centred on the plane) carries its time at the top and, under it, the chosen **patterns**: vertical and horizontal lines and spaces from 0.10 to 0.40 mm, pairs of pads with narrow gaps, a SOIC-8, a fine pitch, passives (0805, 0603, 0402) and pads with a hole. The patterns are laid out in rows (`strip_drawing`), which adapt to the width and the height; those with no room are declared.

- **Positive resist**: the strip is lit, except where the copper stays (the patterns and the time text). **Negative**: only the copper is lit. **Mirror**: everything turned over left to right, the text included.
- **The layout is defined twice, and identically**: in `core/ladder.py` (for the file) and in `static/js/ladder.js` (for the page's preview). A test runs `ladder.js` with Node and compares, number by number, the patterns, the layout, the text, the position of the strips and the warnings. Only the shape of the letters differs: the page uses the browser's font, the file the one Pillow carries inside itself, thickened, so there is no font file to install.
- Each strip is drawn in a small window of the grid aligned to the pixels, which gives the same pixels as the whole grid and is much faster.
- The file is written by the driver with `build_sequence` and is named `scala_<first step>s_x<steps>`, for example `scala_10s_x8.ctb`.
