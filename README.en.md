[Italiano](README.md) | English

# GerberSLAp

GerberSLAp uses a resin printer (a monochrome LCD with 405 nm UV light) as an **exposure unit for printed circuit boards** made on photosensitised copper-clad blanks. You open the zip of Gerber files, place the board on the plane that represents the LCD, choose the resist and the exposure, and get the **print file to copy to the printer's USB stick** (the printer has no network). The printer "prints" a single layer for the whole chosen time, and light passes where the file has white pixels: what is left on the blank is the image of the circuit.

It is a web app: a small local Python server (FastAPI) and a page in plain JavaScript. You use it from the browser, locally or from a Docker container on a home server.

Today the **Creality LD-002H** is supported (2K mono LCD, `.ctb` version 5 files). Other printers are added with a driver, without touching the rest (see [Architecture](docs/en/architecture/overview.md) and the [guide to adding one](docs/en/development/new-printer/driver.md)).

## What it does

- **Reads Gerber zips** from KiCad, Altium and EAGLE 9 (Gerber RS-274X and Excellon): it recognises the program and what each file is (copper, outline, solder mask, silkscreen, drills) by itself. Old EAGLE exports are refused.
- **A 2D plane** that is the LCD seen from above, with rulers in millimetres, a grid, zoom and snapping: one or more boards are laid out, each with position, rotation and mirror (for copper facing down). Three views: *Material* (the layers as the CAD draws them), *UV light* (where the light passes) and *Exact* (the pixel-exact mask that will end up in the file).
- **A pixel-exact mask**: computed by the server from the vector geometry, at an exact pitch of 0.051 mm, with 16 × 16 samples per pixel. Positive resist (light passes where the copper is to be removed) or negative.
- **Exposure**: total light time, number of flashes and rest between flashes, set by hand or taken from a **library of recipes and dosages** (a dosage is the triple of values found by trying, for one printer).
- **Calibration ladder**: a test file with strips exposed for increasing times, carrying lines, gaps, footprints (SOIC-8, fine pitch, passives) and pads with a hole, to find the right time for a resist.
- **Checks**: warnings about boards outside the plane or overlapping, layers of different types switched on together, flashes outside the printer's limits and more; generation is blocked only for what would make the file wrong.
- **Projects**: they are saved in the browser (a working copy) and downloaded as `.gslp` files, a self-contained zip that also holds the Gerber files. The server keeps no project.
- **Italian and English.**

Current limits: it is a single-sided version (a file exposes the layers that are on at that moment; the data model already provides for two sides, but aligning successive exposures of the same blank is not handled); negative inner planes are not supported; there is a single printer (the LD-002H).

## Requirements

- **Python 3.12 or newer** (tried with 3.14).
- A recent browser (tried with Chrome): the page uses IndexedDB and Web Locks.
- **The printer template**: a `.ctb` file made with ChiTuBox, from which the app copies the movement. It is not in the repository (it contains the copyright notice of CBD Technology) and has to be prepared once: see [Installation](docs/en/installation/requirements.md#the-printer-template).
- Optional, only for the tests: Node.js.

Tried on macOS (Apple Silicon). The code is plain Python and JavaScript and uses nothing specific to the system.

## Native installation and start in brief

```bash
git clone https://github.com/shad0w82/GerberSLAp.git GerberSLAp && cd GerberSLAp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# once only: the printer template (see docs/en/installation/requirements.md)
.venv/bin/python -m gerberslap.web --install-template ld002h /path/to/template.ctb

# start (from this folder)
.venv/bin/python -m gerberslap.web
```

Then open **http://127.0.0.1:8800** in the browser. The server listens only on this computer; to stop it, `Ctrl+C`. The start-up options, the data folder, the printer configuration, the Docker installation and troubleshooting are in [docs/en/installation/](docs/en/installation/).

## Docker in brief

```bash
docker compose build

# once only: the printer template, into the volume (the template/ folder holds template.ctb)
docker compose run --rm -v "$PWD/template:/in:ro" gerberslap --install-template ld002h /in/template.ctb

docker compose up -d
```

Then open **http://127.0.0.1:8800**. The image (arm64 and amd64) holds no `.ctb` file; the template and the recipes live in the `gerberslap-data` volume. To reach it from other computers, the environment variables and the rest: [docs/en/installation/install.md](docs/en/installation/install.md#docker-installation).

## Usage in brief

1. **Add the Gerber zip** (drag it onto the page or choose it with the button): the board appears on the plane, with its layers recognised and switched on or off.
2. **Place it** in the *Placement* section (or by dragging it): position, rotation and, if the copper faces down, mirror.
3. **Choose resist and exposure** in the *Exposure* section: polarity (positive or negative), total time, flashes and rest, or a recipe with its dosage.
4. **Generate the print file**: the button downloads the `.ctb` named after the project and shows the file's numbers (layers, total light, estimated time, lit area).
5. **Copy it to the USB stick** and start the print from the printer. With the calibration ladder, which is generated the same way, you first find the right time for the resist; the result is saved as a dosage in a recipe.

There is no complete user manual yet.

## Documentation

- [docs/en/installation/](docs/en/installation/): requirements, the printer template, native and Docker installation, configuration, network and security, common problems.
- [docs/en/usage/](docs/en/usage/): the user manual (being written).
- [docs/en/architecture/](docs/en/architecture/): how the app is built: layers, data flow, data model, pipeline, drivers, server, page.
- [docs/en/development/](docs/en/development/): for developers: how to contribute, the tests, how to write the driver of a new printer, and how to create and install its template.
- [gerberslap/printers/ld002h/docs/ctb_v5_ld002h_formato.md](gerberslap/printers/ld002h/docs/ctb_v5_ld002h_formato.md) (in Italian): the `.ctb` v5 format and the verified behaviour of the LD-002H.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

About 1160 tests, a couple of minutes. Some use third-party files or the printer template and are skipped when those are missing; the ones on the page logic use Node.js and are skipped when it is not there.

## Licence

GerberSLAp is free software, released under the **GNU Affero General Public License v3.0** (AGPL-3.0): the full text, which is the one that counts, is in the file [LICENSE](LICENSE). In short: it can be used, studied, modified and redistributed; whoever modifies it and distributes it, or offers it to people who use it over a network (for example with a public server), must make the source of their version available to those users under the same licence.

Copyright (C) 2026 shad0w82.

**Hosting it on a public server is at your own risk and peril**, and the project neither intends nor supports it: the app has no authentication or users, and the server generates files from a `.ctb` template that carries the copyright notice of CBD Technology (see [Installation](docs/en/installation/configuration.md#network-and-security)). Whoever does it with a modified version must also change the "Source code and licence" link on the Help page (`gerberslap/web/static/index.html`, `id="source-link"`) so that it points to the source of their version.

## Third parties

`.ctb` files are not part of the repository.

GerberSLAp is not affiliated with or endorsed by CBD Technology, Creality or ChiTuBox: their names and trademarks belong to their respective owners and are used here only to say what it is compatible with.
