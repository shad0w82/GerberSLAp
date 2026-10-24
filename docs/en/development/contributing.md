---
icon: material/source-pull
---

# Contributing

This page is for whoever wants to work on the code or the documentation of GerberSLAp: how to set up the environment, how to try changes, how the app is extended and what to check before proposing a change. How the app is built inside is explained in the [Architecture](../architecture/overview.md).

## Setting up the environment

```bash
git clone https://github.com/shad0w82/GerberSLAp.git
cd GerberSLAp
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

`requirements-dev.txt` holds the app's dependencies plus those of the tests. Node.js is only needed by the tests of the page logic. To try the page without a real printer:

```bash
.venv/bin/python -m gerberslap.web --dev-printers --dev-samples folder-of-zips
```

`--dev-printers` adds three made-up printers, `--dev-samples` offers the zips in a folder (see [Configuration](../installation/configuration.md#start-up-options)).

!!! info "What is not in the repository"
    The printer template and the third-party files used by some tests (KiCad, Altium and EAGLE Gerber zips) are not in the repository: the `.ctb` files because of the manufacturer's copyright, the zips because they are not ours. The tests that need them skip themselves when they are missing.

## Running the tests

```bash
.venv/bin/python -m pytest -q
```

There are over a thousand tests and they take a couple of minutes. The tests that need something that is missing skip themselves: the third-party files in `experiments/fase1/external/` and `experiments/fase2/external/`, the `samples/speedCube.ctb` template and Node.js. A single file can be tried, for example `.venv/bin/python -m pytest tests/test_printers.py`.

The syntax check of the JavaScript modules uses `node --input-type=module --check` with the file on stdin: `node --check file.js` is not enough, because with Node 26 it accepts modules with errors.

To inspect a generated file there are two commands on the LD-002H's format reader:

```bash
python3 gerberslap/printers/ld002h/ctbio.py info file.ctb          # header and CRC
python3 gerberslap/printers/ld002h/ctbio.py layer file.ctb N out.png   # extracts a layer as an image
```

## How the tests are made

- **Synthetic data** in `tests/support/testdata.py`. An **independent oracle** (`oracle.py`) computes exact areas by another method, to check the raster. A board of known shape (`markerboard.py`) fixes where everything lands, and fake printers (`fakeprinters.py`) make it possible to try the server without the real template.
- The **format regression test** rebuilds `boxsmall.ctb` (a ChiTuBox file, not in the repository) from its own pixels and parameters: it must give 18 bytes of difference, that is the resin estimates, zeroed on purpose, and three Z values rounded differently.
- The server tests use FastAPI's test client. The page's logic with no DOM is tried with Node.js, and the ladder's layout is compared between Python and JavaScript.
- A test checks that the core, the data model, `cad/` and `services/` name neither the printer nor its file format, and that every driver has its `icon.png`.
- `tests/test_docker.py` checks, without Docker, what goes into the image (it works out the build context from `.dockerignore`: no `.ctb`, no data, no tests) and that the `Dockerfile` and `compose.yaml` have the properties that matter: unprivileged user, volume, local-only port. `tests/test_startup_env.py` tests the start-up environment variables.

## Extending the app

**Adding a printer.** A printer is a folder `gerberslap/printers/<id>/` with a driver and a photo. The app finds it by itself at start-up, and there is no need to touch the core, the data model or the page. The complete guide is [The printer driver](new-printer/driver.md), with a [working example](new-printer/example.md).

**Adding a language.** A catalogue in `gerberslap/web/static/js/i18n.js` with the same keys as the existing ones, and an entry in `gerberslap/web/static/js/flags.js`.

**Adding a CAD program.** A recogniser in `gerberslap/cad/`, with the same interface as the others (a score and the assignment of files), and a test with a real zip.

## Writing the documentation

The texts live in `docs/it/` (the default language) and in `docs/en/`, with the same paths and the same file names in both languages: **the two versions must be kept aligned**. The title of every page is its H1; the icon next to the title in the left-hand list is the `icon:` line at the top of the file.

To add a page, create the two files and add a line to the `nav` of `mkdocs.yml`. A page that exists only in Italian also appears in the English site, with the Italian text, until it is translated.

To build the site locally:

```bash
python3 -m venv .venv-docs
.venv-docs/bin/pip install -r mkdocs-require.txt
.venv-docs/bin/mkdocs serve            # preview at http://127.0.0.1:8000/GerberSLAp/
.venv-docs/bin/mkdocs build --strict   # full build, failing on every warning
```

The look of the site is in `docs/stylesheets/extra.css`. The fonts (Inter and JetBrains Mono, SIL OFL licence) are included in `docs/assets/fonts/`, so the site makes no requests to outside providers. The “On this page” title comes from `overrides/partials/toc.html`, a copy of a Material 9.7.7 file to check again if Material is updated. The `docs/javascripts/tables.js` script keeps the first column of a table from wrapping when it holds only short labels.

`mkdocs-require.txt` pins the indirect dependencies too: nothing is updated without redoing the trial, because MkDocs 2.0 is not compatible with Material for MkDocs or its plugins.

The manual's images are redone with one command, from the real app and in both languages: `cd tools/docs_screenshots && npm install && node shoot.mjs`. The script starts the app on a temporary data folder with the printer template (you need a `.ctb` file made with ChiTuBox, in `samples/speedCube.ctb` or given with `GERBERSLAP_TEMPLATE`), opens the example board and saves the PNG files in `docs/it/usage/img/` and `docs/en/usage/img/`. Each chapter has its own file in `tools/docs_screenshots/chapters/`, and `node shoot.mjs interface` redoes only the images of that chapter. The example board is written by `tools/demo_board/make_demo_board.py` into `docs/assets/GerberSLAp-demo.zip`, always with the same bytes; a test checks that the zip on the site is the script's one.

A few rules for writing:

- no development history, only what is needed to understand how the app is built and how it is used;
- the names of the interface zones (MenuBar, SidePanel, CadWindow…) are always those of the [Interface tour](../usage/interface.md);
- the words of the interface are identical to those in `i18n.js`;
- no printer behaviour is claimed that has not been tried;
- in tables of methods the first column holds only the name and the parameters go in the right-hand column: a first column of short labels (up to 60 characters) does not wrap.

## Proposing a change

A change is proposed on GitHub, by opening an issue to talk about it or a pull request with the change. Before proposing it, check that:

1. the tests pass (`pytest`), and that there is one for what you changed;
2. a new text, or a new warning or error code, has its sentence in **both languages** in the `i18n.js` catalogue;
3. the core, the data model, `cad/` and `services/` do not name a printer or its file format: everything that depends on the printer lives in its driver;
4. the documentation is updated in Italian and in English;
5. no `.ctb` file ends up in the repository.

The code and the documentation are distributed under the **GNU AGPL-3.0** licence.
