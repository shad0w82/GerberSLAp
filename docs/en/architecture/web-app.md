---
icon: material/web
---

# Server and page

The FastAPI server, the page in plain JavaScript, the `.gslp` project file and the data folder: what stands on the two sides of the HTTP request. The principles and the layers are in the [Overview](overview.md).

## The server

`gerberslap/web/app.py` is a thin FastAPI app, local and single-user, which also serves the static page. `python -m gerberslap.web` starts it with `uvicorn`, in a single process.

### Routes

| Route | What it does |
|---|---|
| `GET /api/info` | Version, default printer, printers (plane, grid, limits, **whether they are ready and why not**, photo), whether the library exists, which options the app was started with. It is re-read on every request: installing the template needs no restart. |
| `GET /api/printers/<id>/picture` | The printer's photo, kept by the browser for an hour. |
| `POST /api/boards` | Opens a zip: recognises, reads, returns the board (layers by hash) with warnings and the CAD program. The files stay in the server's cache. |
| `POST /api/geometry` | The polygons of a layer, to draw them. |
| `POST /api/render` | The exact mask (1-bit PNG in base64) for a project and a polarity, with the raster's warnings. |
| `POST /api/check` | The checks of a project. If the request carries `exposure` (even `null`) they are all of them: layout, references and values; without it, only the layout. |
| `POST /api/generate` | The print file of a project. |
| `POST /api/generate/ladder` | The calibration ladder's file. |
| `POST /api/project/save`, `POST /api/project/open` | Writes and reads the `.gslp` file. |
| `/api/recipes…` | The library: list, create, edit, delete, duplicate a recipe; add, edit, delete and copy a dosage. Only with the library on. |
| `GET /dev/samples/<name>` | Only with `--dev-samples`. |

Requests are validated with `pydantic`: unknown fields refused, no NaN or infinities. Errors always have the form `{"error": {"code": "...", "params": {...}}}`: a stable code, never a server path nor a text to show.

### Generation

`services/generate.py` runs all the checks: layout, references, values, and the driver's own on the printer. If something **blocks**, it answers 422 `generation_blocked` with *all* the warnings. Otherwise it draws the mask with the pipeline, asks the driver to write into a temporary folder that then disappears, and answers with the file's bytes (`application/octet-stream`), `Content-Disposition` (the project's name made safe, with the driver's extension) and the summary in `X-Build-Summary` (JSON: layers, flashes, rest, total light, time estimated by the printer, lit pixels and area, size).

A driver's refusal is 422 with its code; a server fault (`write_failed`, `verification_failed`) is 500 with no parameters.

### State in memory

- **`FileStore`** (`web/filestore.py`): the Gerber files read, by hash, with a limit of 1 GiB and the least used discarded first. A project whose files were discarded receives `file_missing` and has to be opened again: the page does it by itself from the working copy.
- **`PipelineCache`**: the files already interpreted and the materials already built (256 entries).

### Protections

The server is local, but every request is checked. The `Host` header must be a local name (or one given with `--allowed-host`: it protects against DNS rebinding), and a request that changes something must come from the page itself (`Origin` and `Sec-Fetch-Site`). No caching of responses (except the photos), `nosniff`, zips and projects treated as hostile input (limits and entry-by-entry checks). There is no authentication and there are no users: see [Network and security](../installation/configuration.md#network-and-security).

## The page

Plain JavaScript in ES modules, with no framework and no build step, in `gerberslap/web/static/` (`index.html`, `css/style.css`, `js/`). It draws the plane with Canvas 2D.

| Module | Role |
|---|---|
| `app.js` | Wires the page to the server: state, panels, events. |
| `api.js` | The calls to the server; every error becomes an `ApiError` with a code and parameters. |
| `model.js` | The boards in the browser and the maths of placement (centre of the extent, rotation, mirror). |
| `plane.js` | The plane view: zoom around the cursor, dragging with snapping, Rulers, Exact view. |
| `exposure.js` | Recipes, dosages, values, requests to the server and the reason “Generate” is off: logic with no DOM. |
| `ladder.js` | The ladder: values, layout, SVG preview, zoom: logic with no DOM. |
| `placement.js`, `printercards.js` | The drawing of the margins and the printers' cards: they return markup and numbers. |
| `workcopy.js` | The working copy in the browser. |
| `i18n.js`, `flags.js` | The text catalogues (Italian and English) and the flags. |

The modules “with no DOM” are tried with Node.js, by the tests.

- **State.** Boards are plain data; undo and redo are snapshots, up to 80. Preferences (language, last recipe, last values by hand, the ladder's values, panel widths…) live in `localStorage`: they are not a library and, if they are missing, the page works all the same.
- **Working copy** (`workcopy.js`). The project as of the last “Save” lives in the browser (IndexedDB, one copy per browser tab, with Web Locks for recovery after a close) and nowhere else. The “Download” button produces the `.gslp` file.
- **Texts.** There is no sentence in the code: every string is a key of the catalogue. The server sends codes (`ls_*` for the state of layers, `i_*` for warnings, `err_*` for errors) and the page turns them into sentences.
- **What the page decides and what the server does.** The page holds where each board is and what is on; the server reads the files, sends the shapes to draw, and computes the exact mask and the checks. Nothing about a board is invented by the page.

## The `.gslp` project file

A project and the Gerber files it uses are in a single zip that needs nothing else to be opened again:

- `project.json`: the project as it is in the data model, with `format`, `schema_version`, `name` and, for each board, the CAD program and the notes made when the zip was opened;
- `files/<sha256>`: one for each Gerber or Excellon file a layer refers to, one per distinct content, so boards that share files cost nothing.

Writing is deterministic (same project, same bytes) and the file is read back and compared before it is handed over. Reading is strict, because the archive comes from outside: only those entries, no duplicates, bounded sizes, every file checked against its hash, nothing unused. A file that is missing or altered refuses the whole project, saying which. A newer version of the format is refused, an older one is migrated.

## The data folder

```text
data/
  printers/<id>/template.ctb      the template (never in the repository)
  printers/<id>/printer.json      optional: the driver's settings
  recipes/<id>.json               one recipe per file
```

It is the only state on the server's disk. One process per folder: calls are serialised with a lock. Writes are atomic, and a file that cannot be read is reported and never repaired by guesswork. It becomes the Docker volume. Details in [Configuration](../installation/configuration.md#the-data-folder).
