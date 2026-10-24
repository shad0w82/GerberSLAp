---
icon: material/sitemap-outline
---

# Overview

How GerberSLAp is built: the principles it rests on, the layers the code is divided into and the data flow from the Gerber zip to the print file. The next pages go into detail: [From project to file](pipeline.md) and [Server and page](web-app.md). To install and start the app, see [Installing the app](../installation/install.md); for the file format and the verified behaviour of the printer, the [format document](https://github.com/shad0w82/GerberSLAp/blob/main/gerberslap/printers/ld002h/docs/ctb_v5_ld002h_formato.md) (in Italian).

## Principles

1. **The server keeps nothing of the user's.** The project (the boards, where they are, which layers are on) lives in the browser, which sends it to the server with every request. The server keeps in memory only the Gerber files it has read, indexed by hash, and loses them on restart: the page gives them back from the working copy. On the server's disk there is only the data folder, with the printers' templates and the recipe library. A public server would have no one else's projects to protect.
2. **The final raster is computed on the server from the vector geometry**, with the final transform. The browser's preview is never resampled to produce the file: the *Exact* view and the generated file come from the same mask.
3. **Everything that depends on the printer lives in a driver** (`printers/<id>/`): name, screen size, file format, limits. The core, the data model, the CAD recognisers and the services never name either the `.ctb` format or the LD-002H (a test checks it). Adding a printer needs no change to the rest.
4. **The movement is always copied from a template** made in ChiTuBox, never invented. The app changes only the images, the exposure and the Z height.
5. **Every file written is read back and compared** before it is handed over: the driver decodes the file and compares it with what was meant, and a file that does not match does not go out.
6. **The server sends codes, the page writes the sentences.** Warnings, errors and layer states arrive as codes with parameters; the text, in Italian and English, is all in the page's catalogue. The server knows no language.
7. **Nothing is decided in silence.** A file that cannot be read, a layer drawn as a negative, a mask that covers almost the whole board: everything doubtful is marked with a code on the layer or among the warnings, and a layer with an error starts switched off. Generation is blocked only for what would make the file wrong.

## Overview of the flow

```text
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

All coordinates are in **millimetres on the exposure plane seen from above, with the user in front of the printer**.

- `u` (or `x`) runs from left to right, `v` (or `y`) from front to back. Zero is the bottom-left corner of the plane, that of the Rulers.
- The **mask** is a boolean array `(height, width)` of the plane's grid: row 0 is the **back**, column 0 the **left**. It is the same orientation as the page, the same for every printer; each driver turns it the way its file wants.
- The pitch and the grid are parameters of each printer: for the LD-002H, 0.051 mm and 2560 × 1620 pixels, that is 130.56 × 82.62 mm.
- **Position of a board**: the centre of its extent on the plane. The angle is in degrees, counter-clockwise seen from above. Mirror is left-right, applied before the rotation, also about the centre of the extent. Mirroring is a **user's choice on the placed board** (typically when the copper faces down), not an automatic consequence.
- Everything is converted to polygons **before** any transform, so mirroring does not reverse the direction of arcs and any angle works.

## The modules, layer by layer

Dependencies point downwards: each layer knows only those below it.

```text
web/          HTTP routes and the page         (FastAPI; static/ = the page)
services/     checks, import, pipeline, library, generation, project file
printers/     one driver per printer           (printers/<id>/)
cad/          recognition of the files in a zip
model/        validated, immutable data        (pydantic)
core/         geometry, Gerber/Excellon, raster, ladder   (no printer)
```

### `core/`: the printer-independent core

- `gerber_io.py`: reading Gerber (RS-274X) and Excellon with `gerbonara`, and opening zips safely (limits on the number and size of files, filtered names). `gerbonara` 1.6.3 has two defects that are fixed here at run time (step-and-repeat blocks not expanded, aperture macros with primitive 22): each fix has a test, and a version other than the one tried gives a warning. It must not be updated without redoing the tests.
- `geometry.py`: from files read to `shapely` geometry. Outline (lines with a minimum thickness), drills (which are subtracted), material, **board area** (the inside of the closed outline, falling back on the extent rectangle with a warning), placement on the plane.
- `raster.py`: per-pixel coverage of a geometry on a regular grid. Each pixel is sampled at 16 × 16 points (minimum 8: with 4 × 4 thin lines come out wrong) with the even-odd rule on the edges, with no intermediate images; then the mask is “at least half covered”.
- `ladder.py`: the layout of the calibration ladder and the pixels of each step ([The calibration ladder](pipeline.md#the-calibration-ladder)).

### `cad/`: recognition

Given the list of the files in a zip, each recogniser (KiCad, Altium, EAGLE, generic) says how much the zip looks like its program and assigns every file a role (copper, outline, mask, silkscreen, drills, ignored), a side (top, bottom, inner), a confidence and a reason. The signals, in order of strength: the **X2 attributes** inside the files, the names and extensions typical of the program, the content. It never reads the geometry.

It refuses old EAGLE exports, which lack the information needed (`ImportRefused`, with the reason). A `.gbrjob` file (KiCad, EAGLE) gives the declared size of the board, which is checked against the outline.

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
- `pipeline.py`: from project to mask ([From project to mask](pipeline.md#from-project-to-mask)). `vector.py`: the polygons of a layer for the browser, relative to the board's centre, with the drills already cut out and lightly simplified (2 µm, far less than a pixel).
- `checks.py`: the checks as code: layout, references (printer, recipe, polarity) and exposure values. A list of `Issue` in a fixed order.
- `generate.py` and `ladder.py`: the board's file and the ladder's file.
- `installation.py`: a printer's configuration, its “ready” state and the installation of the template. `store.py`: the data folder. `library.py`: the operations on the library. `projectfile.py`: the `.gslp` file. `files.py`: atomic writes.
