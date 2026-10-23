[Italiano](../ARCHITETTURA.md) | English

# Architecture

How GerberSLAp is built: the principles, the layers and the data flow from the Gerber zip to the print file. To install and start it see [INSTALLATION.md](INSTALLATION.md); for the file format and the verified behaviour of the printer, [ctb_v5_ld002h_formato.md](../../ctb_v5_ld002h_formato.md) (in Italian).

- [Principles](#principles)
- [Overview](#overview)
- [Geometric conventions](#geometric-conventions)
- [The modules, layer by layer](#the-modules-layer-by-layer)
- [From project to mask: the pipeline](#from-project-to-mask-the-pipeline)
- [Printers: drivers and template](#printers-drivers-and-template)
- [Exposure, recipes and dosages](#exposure-recipes-and-dosages)
- [The calibration ladder](#the-calibration-ladder)
- [The server](#the-server)
- [The page](#the-page)
- [The `.gslp` project file](#the-gslp-project-file)
- [The data folder](#the-data-folder)
- [Tests](#tests)
- [How to extend it](#how-to-extend-it)

## Principles

1. **The server keeps nothing of the user's.** The project (the boards, where they are, which layers are on) lives in the browser, which sends it to the server with every request; the server keeps in memory only the Gerber files it has read, indexed by hash, and loses them on restart (the page gives them back from the working copy). On the server's disk there is only the data folder: the printers' templates and the recipe library. A public server would have no one else's projects to protect.
2. **The final raster is computed on the server from the vector geometry**, with the final transform. The browser's preview is never resampled to produce the file: the *Exact* view and the generated file come from the same mask.
3. **Everything that depends on the printer lives in a driver** (`printers/<id>/`): name, screen size, file format, limits. The core, the data model, the CAD recognisers and the services never name either the `.ctb` format or the LD-002H (a test checks it). Adding a printer needs no change to the rest.
4. **The movement is always copied from a template** made in ChiTuBox, never invented. The app changes only the images, the exposure and the Z height.
5. **Every file written is read back and compared** before it is handed over (the driver decodes the file and compares it with what was meant); a file that does not match does not go out.
6. **The server sends codes, the page writes the sentences.** Warnings, errors and layer states arrive as codes with parameters; the text, in Italian and English, is all in the page's catalogue. The server knows no language.
7. **Nothing is decided in silence.** A file that cannot be read, a layer drawn as a negative, a mask that covers almost the whole board: everything doubtful is marked with a code on the layer or among the warnings, and a layer with an error starts switched off. Generation is blocked only for what would make the file wrong.

## Overview

```
BROWSER (the page)                         SERVER (FastAPI)
──────────────────                         ────────────────
project: boards, position,                 cad/ + importer
rotation, mirror, layers        ────────►  recognise and read the files of the zip
on (only in the browser)        ◄────────  board: layers by hash, warnings
                                /boards

drawing of the plane            ────────►  vector
(polygons of the layers)        ◄────────  polygons of a layer
                                /geometry

Exact view                      ────────►  pipeline
(the pixel-exact mask)          ◄────────  geometry → 16×16 coverage → mask
                                /render

"Generate" button               ────────►  checks → pipeline → driver
downloads the file              ◄────────  the printer's file, read back and compared
                                /generate
```

The generated file goes onto the USB stick and then to the printer. The browser also holds the working copy (IndexedDB), the downloaded `.gslp` projects and the preferences (localStorage); the server, in the data folder, holds the printers' templates and the recipes.

The server is thin: the routes contain no domain logic, which lives in the modules under `gerberslap/` and can be tried without starting anything.

## Geometric conventions

All coordinates are in **millimetres on the exposure plane seen from above, with the user in front of the printer**:

- `u` (or `x`) runs from left to right; `v` (or `y`) from front to back. Zero is the bottom-left corner of the plane (that of the rulers).
- The **mask** is a boolean array `(height, width)` of the plane's grid: row 0 is the **back**, column 0 the **left**. It is the same orientation as the page, the same for every printer; each driver turns it the way its file wants.
- The pitch and the grid are parameters of each printer (for the LD-002H, 0.051 mm and 2560 × 1620 pixels, that is 130.56 × 82.62 mm).
- Position of a board: the centre of its extent on the plane. Angle in degrees, counter-clockwise seen from above. Mirror is left-right, applied before the rotation, also about the centre of the extent. Mirroring is a **user's choice on the placed board** (typically when the copper faces down), not an automatic consequence.
- Everything is converted to polygons **before** any transform, so mirroring does not reverse the direction of arcs and any angle works.

## The modules, layer by layer

Dependencies point downwards: each layer knows only those below it.

```
web/          HTTP routes and the page         (FastAPI; static/ = the page)
services/     checks, import, pipeline, library, generation, project file
printers/     one driver per printer           (printers/<id>/)
cad/          recognition of the files in a zip
model/        validated, immutable data        (pydantic)
core/         geometry, Gerber/Excellon, raster, ladder   (no printer)
```

### `core/`: the printer-independent core

- `gerber_io.py`: reading Gerber (RS-274X) and Excellon with `gerbonara`, and opening zips safely (limits on the number and size of files, filtered names). `gerbonara` 1.6.3 has two defects that are fixed here at run time (step-and-repeat blocks not expanded, aperture macros with primitive 22); each fix has a test and a version other than the one tried gives a warning.
- `geometry.py`: from files read to `shapely` geometry; outline (lines with a minimum thickness), drills (which are subtracted), material, **board area** (the inside of the closed outline, falling back on the extent rectangle with a warning), placement on the plane.
- `raster.py`: per-pixel coverage of a geometry on a regular grid. Each pixel is sampled at 16 × 16 points (minimum 8: with 4 × 4 thin lines come out wrong) with the even-odd rule on the edges, with no intermediate images; then the mask is "at least half covered".
- `ladder.py`: the layout of the calibration ladder and the pixels of each step (see below).

### `cad/`: recognition

Given the list of the files in a zip, each recogniser (KiCad, Altium, EAGLE, generic) says how much the zip looks like its program and assigns every file a role (copper, outline, mask, silkscreen, drills, ignored), a side (top, bottom, inner), a confidence and a reason. The signals, in order of strength: the **X2 attributes** inside the files, the names and extensions typical of the program, the content. It never reads the geometry. It refuses old EAGLE exports, which lack the information needed (`ImportRefused`, with the reason). A `.gbrjob` file (KiCad, EAGLE) gives the declared size of the board, which is checked against the outline.

### `model/`: the data

Immutable `pydantic` models, with no geometry and no printers: layers refer to files by hash.

| Module | What it holds |
|---|---|
| `project.py` | `Project` (printer, reference recipe and dosage, polarity, minimum outline thickness, boards), `Board` (size, centre, placement, layers), `Layer` (role, side, on, status, files by hash), `BoardPlacement` (x, y, angle, mirror). |
| `layout.py` | `Plane`, extents, margins, overlaps: the simple geometry the warnings are based on. |
| `exposure.py` | `ExposureValues` (total time, flashes, rest) and `ExposureLimits` (what a printer says about a flash). |
| `catalog.py` | `Recipe`, `Dosage`, `RecipeRef`, `PrinterConfig`, `PrinterFile`. |
| `issues.py` | `Issue` (code, severity, whether it blocks, parameters) and the list of codes. |
| `ladder.py` | `LadderSpec`: the ladder's values, with their limits. |

### `services/`

- `importer.py`: from a zip to a `Board` (layers by hash, no geometry) plus the files to put in the cache; it marks every problem with a code on the layer.
- `pipeline.py`: from project to mask (below). `vector.py`: the polygons of a layer for the browser, relative to the board's centre, with the drills already cut out and lightly simplified (2 µm, far less than a pixel).
- `checks.py`: the checks as code: layout, references (printer, recipe, polarity) and exposure values. A list of `Issue` in a fixed order.
- `generate.py` and `ladder.py`: the board's file and the ladder's file (below, and in the server).
- `installation.py`: a printer's configuration, its "ready" state and the installation of the template. `store.py`: the data folder. `library.py`: the operations on the library. `projectfile.py`: the `.gslp` file. `files.py`: atomic writes.

## From project to mask: the pipeline

`services/pipeline.py:render(project, files, grid, polarity)`:

1. **The material of each board**, from the layers that are on, in stack order: copper and silkscreen as drawn; the outline as a line at least `min_outline_mm` wide; the **solder mask** as *the board area minus the openings its file draws* (the polarity declared in the mask file is not used); the drills, if the layer is on, are subtracted. The copper, mask and silkscreen layers form the **stack**: their order in the list is the drawing order in the Material view (reversed if the board is mirrored) and never changes what is exposed; outline and drills stand apart.
2. **Placement** on the plane (position, rotation, mirror).
3. **Union** of all the boards (where they overlap the result is the sum).
4. **Coverage** per pixel from the vector geometry (never by resampling an image), computed once.
5. **Polarity**, last: with the **positive** resist light passes where there is *no* material (where the copper is to be removed); with the **negative** one, where there is.

Reading the Gerber files and building the material are the slow part, and are kept in a cache by file hash and by what is on: moving a board costs a raster, not a re-read. Outside the plane the material is cut, with a warning.

## Printers: drivers and template

A driver is an object in `printers/<id>/__init__.py` (exposed as `DRIVER`); the folder is named after the driver's id and also holds `icon.png`, the upright photo (transparent background) the page shows. Drivers are found by themselves at start-up.

**The descriptor** says what needs to be known about the printer without using it: id and name, the plane in mm, the pixel grid, the limits of a flash (minimum, and maximum tried), whether a template is needed, the template's file name and the extension of the file it writes.

**The interface** (`printers/base.py`):

| Method | Job |
|---|---|
| `check(exposure, config, template)` | The printer's warnings (template missing or invalid, wrong settings), like every other check. |
| `validate_template(file)` | Judges a template the user supplied; refuses with a reason. |
| `to_printer_image(mask)` | The plane's mask as the image of the printer's file. |
| `build(mask, exposure, config, template, path)` | Writes the file for one mask, reads it back, compares it and only then hands it over; otherwise `BuildError`. |
| `build_sequence(masks, flashes, …)` | Writes a file of several masks in a row (the ladder); a driver that cannot do it says so. |

**The LD-002H driver** (`printers/ld002h/`), on top of `ctbio.py`, which is in the same folder (reading and writing the `.ctb` v5: encryption, RLE, previews, CRC; validated byte by byte against ChiTuBox files). In the `docs/` subfolder are the document of the format and the verified behaviour of the printer (`ctb_v5_ld002h_formato.md`, in Italian) and `pcb_ctb.py`, a trial command line from which the driver and that document were born:

- The file's image is the plane turned a quarter turn clockwise, with no reflection.
- A dose of *T* seconds in *N* flashes is *N* identical layers of *T/N* seconds: the printer reads **a single exposure time from the header** and applies it to every layer. The **rest** between flashes is the only pause of darkness (it is written as the rest before lift).
- The movement (distances and speeds, second stages, the other rests) is copied from the template; a lift distance of 0 is never written (the printer would do a 5 mm cycle). All layers sit at the same low Z height (default 1 mm).
- The file's preview is the first layer, seen from above, cropped to what is lit.
- **The template** is judged before use: a `.ctb` v5 file, correct CRC, the screen's resolution, at least one layer that decodes, lift distances greater than 0 and valid speeds. A template with a large lift distance (over 1 mm) is accepted but gives a warning, because it makes the flashes slow.
- Limits: the minimum flash is 1 s (below it nothing is generated); over 20 s the file is generated with a warning (not tried).
- **The check before handing over**: the file is written to a hidden temporary file, read back, and compared: the CRC, the number of layers, the exposure and the number of bottom layers in the header, the resolution, the rest, and for each layer the Z height, the exposure, the copied movement and the pixels. Only if everything matches does the file take its place.

**The `.ctb` template is not in the repository** (it contains the manufacturer's copyright notice, which also ends up in the generated files) and is installed in the data folder: `printers/<id>/template.ctb`.

## Exposure, recipes and dosages

- **Printer**: the type of printer (the driver's id), not the unit with its serial number. It has no exposure values.
- **Recipe**: name, **polarity** (which cannot be changed after creation: if the resist changes, it is another recipe), resist, development, notes and its dosages.
- **Dosage**: total light time, number of flashes and rest **found by trying, for one printer**, with an optional date, name and note. A recipe's dosages for a printer are all valid alternatives (for example for fine tracks or for large ground planes), not versions of one another. "Dose" is only the total light time.

The project never holds the exposure values: it holds a reference (the recipe's id and name, the polarity, the chosen dosage) and the values come from the dosage or are entered by hand. When a project is opened, the recipe's polarity wins over the saved one (a wrong polarity ruins the board) and says so; a recipe the library does not have is reported, and the project keeps the saved polarity and no recipe.

**The library** lives in the data folder (`recipes/<id>.json`, one recipe per file) and is managed from the page through the `/api/recipes` routes. Every operation answers with the recipe as it is afterwards; a dosage's date changes only if its values change; changes are read-changed-written inside a lock, so two browsers do not lose each other's changes. Ceilings: 500 recipes and 100 dosages per recipe. With `--no-library` these routes are not registered (404).

**The server generates with what it receives**: the generation request carries the project, the polarity, the three values and, if there is one, the chosen recipe (id, name, polarity). It never reads the library, which is why it works the same with `--no-library`.

## The calibration ladder

It serves to find the right time for a resist: a single file in which strips side by side receive increasing times. Strip *k* is lit for *k* times the time of the first: step *i* of the file lights the strips from *i* on, with one time per layer, the same for all (the printer uses one). Each step is made of `pulses` flashes of `step / pulses` seconds with the rest between them, so the file has `bands × pulses` layers.

Each strip (size of your choice, 13 × 76 mm to start with, 1 mm of dark between one strip and the next, centred on the plane) carries its time at the top and, under it, the chosen **patterns**: vertical and horizontal lines and spaces from 0.10 to 0.40 mm, pairs of pads with narrow gaps, a SOIC-8, a fine pitch, passives (0805, 0603, 0402) and pads with a hole. The patterns are laid out in rows (`strip_drawing`), which adapt to the width and the height; those with no room are declared.

- **Positive resist**: the strip is lit, except where the copper stays (the patterns and the time text). **Negative**: only the copper is lit. **Mirror**: everything turned over left to right, the text included.
- **The layout is defined twice, and identically**: in `core/ladder.py` (for the file) and in `static/js/ladder.js` (for the page's preview). A test runs `ladder.js` with Node and compares, number by number, the patterns, the layout, the text, the position of the strips and the warnings. Only the shape of the letters differs (the page uses the browser's font, the file the one Pillow carries inside itself, thickened: there is no font file to install).
- Each strip is drawn in a small window of the grid aligned to the pixels, which gives the same pixels as the whole grid and is much faster.
- The file is written by the driver with `build_sequence`; it is named `scala_<first step>s_x<steps>` (for example `scala_10s_x8.ctb`).

## The server

`gerberslap/web/app.py`: a thin FastAPI app, local and single-user, which also serves the static page. `python -m gerberslap.web` starts it with `uvicorn` (a single process).

### Routes

| Route | What it does |
|---|---|
| `GET /api/info` | Version, default printer, printers (plane, grid, limits, **whether they are ready and why not**, photo), whether the library exists, which options the app was started with. It is re-read on every request: installing the template needs no restart. |
| `GET /api/printers/<id>/picture` | The printer's photo (kept by the browser for an hour). |
| `POST /api/boards` | Opens a zip: recognises, reads, returns the board (layers by hash) with warnings and the CAD program. The files stay in the server's cache. |
| `POST /api/geometry` | The polygons of a layer, to draw them. |
| `POST /api/render` | The exact mask (1-bit PNG in base64) for a project and a polarity, with the raster's warnings. |
| `POST /api/check` | The checks of a project. If the request carries `exposure` (even `null`) they are all of them: layout, references and values; without it, only the layout. |
| `POST /api/generate` | The print file of a project. |
| `POST /api/generate/ladder` | The calibration ladder's file. |
| `POST /api/project/save`, `POST /api/project/open` | Writes and reads the `.gslp` file. |
| `/api/recipes…` | The library: list, create, edit, delete, duplicate a recipe; add, edit, delete and copy a dosage. Only with the library on. |
| `GET /dev/samples/<name>` | Only with `--dev-samples`. |

Requests are validated with `pydantic` (unknown fields refused, no NaN or infinities). Errors always have the form `{"error": {"code": "...", "params": {...}}}`: a stable code, never a server path nor a text to show.

**Generation** (`services/generate.py`): it runs all the checks (layout, references, values, and the driver's own on the printer); if something **blocks**, it answers 422 `generation_blocked` with *all* the warnings; otherwise it draws the mask with the pipeline, asks the driver to write into a temporary folder that then disappears, and answers with the file's bytes (`application/octet-stream`), `Content-Disposition` (the project's name made safe, with the driver's extension) and the summary in `X-Build-Summary` (JSON: layers, flashes, rest, total light, time estimated by the printer, lit pixels and area, size). A driver's refusal is 422 with its code; a server fault (`write_failed`, `verification_failed`) is 500 with no parameters.

### State in memory

- **`FileStore`** (`web/filestore.py`): the Gerber files read, by hash, with a limit (1 GiB) and the least used discarded first. A project whose files were discarded receives `file_missing` and has to be opened again: the page does it by itself from the working copy.
- **`PipelineCache`**: the files already interpreted and the materials already built (256 entries).

### Protections

A local server, but every request is checked: the `Host` header must be a local name (or one given with `--allowed-host`: it protects against DNS rebinding), and a request that changes something must come from the page itself (`Origin` and `Sec-Fetch-Site`). No caching of responses (except the photos), `nosniff`, zips and projects treated as hostile input (limits and entry-by-entry checks). There is no authentication and there are no users: see [Network and security](INSTALLATION.md#network-and-security).

## The page

Plain JavaScript in ES modules, with no framework and no build step, in `gerberslap/web/static/` (`index.html`, `css/style.css`, `js/`). It draws the plane with Canvas 2D.

| Module | Role |
|---|---|
| `app.js` | Wires the page to the server: state, panels, events. |
| `api.js` | The calls to the server; every error becomes an `ApiError` with a code and parameters. |
| `model.js` | The boards in the browser and the maths of placement (centre of the extent, rotation, mirror). |
| `plane.js` | The plane view: zoom around the cursor, dragging with snapping, rulers, exact view. |
| `exposure.js` | Recipes, dosages, values, requests to the server and the reason "Generate" is off: logic with no DOM. |
| `ladder.js` | The ladder: values, layout, SVG preview, zoom: logic with no DOM. |
| `placement.js`, `printercards.js` | The drawing of the margins; the printers' cards: they return markup and numbers. |
| `workcopy.js` | The working copy in the browser. |
| `i18n.js`, `flags.js` | The text catalogues (Italian and English) and the flags. |

The modules "with no DOM" are tried with Node.js, by the tests.

- **State**: boards are plain data; undo and redo are snapshots (up to 80). Preferences (language, last recipe, last values by hand, the ladder's values, panel widths…) live in `localStorage`; they are not a library and, if they are missing, the page works all the same.
- **Working copy** (`workcopy.js`): the project as of the last "Save", in the browser (IndexedDB, one copy per browser tab, with Web Locks for recovery after a close) and nowhere else. The "Download" button produces the `.gslp` file.
- **Texts**: there is no sentence in the code; every string is a key of the catalogue. The server sends codes (`ls_*` for the state of layers, `i_*` for warnings, `err_*` for errors) and the page turns them into sentences.
- **What the page decides and what the server does**: the page holds where each board is and what is on; the server reads the files, sends the shapes to draw, and computes the exact mask and the checks. Nothing about a board is invented by the page.

## The `.gslp` project file

A project and the Gerber files it uses, in a single zip that needs nothing else to be opened again: `project.json` (the project as it is in the data model, with `format`, `schema_version`, `name` and, for each board, the CAD program and the notes made when the zip was opened) and, for each Gerber or Excellon file a layer refers to, `files/<sha256>` (one per distinct content: boards that share files cost nothing).

Writing is deterministic (same project, same bytes) and the file is read back and compared before it is handed over. Reading is strict, because the archive comes from outside: only those entries, no duplicates, bounded sizes, every file checked against its hash, nothing unused; a file that is missing or altered refuses the whole project, saying which. A newer version of the format is refused, an older one is migrated.

## The data folder

```
data/
  printers/<id>/template.ctb      the template (never in the repository)
  printers/<id>/printer.json      optional: the driver's settings
  recipes/<id>.json               one recipe per file
```

It is the only state on the server's disk. One process per folder (calls are serialised with a lock); writes are atomic; a file that cannot be read is reported and never repaired by guesswork. It becomes the Docker volume. Details in [INSTALLATION.md](INSTALLATION.md#the-data-folder).

## Tests

`pytest` (about 1160 tests, a couple of minutes). Synthetic data in `tests/support/testdata.py`; an **independent oracle** (`oracle.py`) computes exact areas by another method, to check the raster; a board of known shape (`markerboard.py`) fixes where everything lands; fake printers (`fakeprinters.py`) make it possible to try the server without the real template.

- The **format regression test**: rebuilding `boxsmall.ctb` (a ChiTuBox file, not in the repository) from its own pixels and parameters must give 18 bytes of difference (the resin estimates, zeroed on purpose, and three Z values rounded differently).
- The server tests use FastAPI's test client; the page's logic with no DOM is tried with Node.js; the ladder's layout is compared between Python and JavaScript.
- Some tests use third-party files (KiCad, Altium and EAGLE Gerber zips, in `experiments/fase1/external/` and `experiments/fase2/external/`) or the printer's template (`samples/speedCube.ctb`): they are not in the repository, and those folders are in the `.gitignore`. Those tests skip themselves when the files are missing.
- A test checks that the core, the data model, `cad/` and `services/` name neither the printer nor its file format, and that every driver has its `icon.png`.
- `tests/test_docker.py` checks, without Docker, what goes into the image (it works out the build context from `.dockerignore`: no `.ctb`, no data, no tests) and that the `Dockerfile` and `compose.yaml` have the properties that matter (unprivileged user, volume, local-only port); `tests/test_startup_env.py` tests the start-up environment variables.

## How to extend it

**Adding a printer.** The complete guide, with a working example, the tests to write and how to create and install the template, is [NEW_PRINTER.md](NEW_PRINTER.md). In brief: a folder `gerberslap/printers/<id>/` with an `__init__.py` that exposes `DRIVER` (a `PrinterDriver`: descriptor, `check`, `validate_template`, `to_printer_image`, `build` and possibly `build_sequence`) and `icon.png` (an upright photo, a PNG taller than wide, transparent background, up to 512 KB). The rest of the app finds it by itself: it appears in the page, has its "ready" state and its data folder. If a template is needed, the driver says the name of its file and the template is installed with `--install-template <id> <file>`. There is no need to touch the core, the data model or the page.

**Adding a language.** A catalogue in `static/js/i18n.js` with the same keys and an entry in `static/js/flags.js`.

**Adding a CAD program.** A recogniser in `gerberslap/cad/` with the same interface as the others (a score and the assignment of files) and a test with a real zip.
