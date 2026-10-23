[Italiano](../INSTALLAZIONE.md) | English

# Installation and start

This guide explains how to install GerberSLAp and run it, natively or with Docker. How the app is built inside is in [ARCHITECTURE.md](ARCHITECTURE.md).

- [Requirements](#requirements)
- [The printer template](#the-printer-template)
- [Native installation](#native-installation)
- [Options, environment variables and data folder](#options-environment-variables-and-data-folder)
- [Docker installation](#docker-installation)
- [Network and security](#network-and-security)
- [Updating](#updating)
- [Troubleshooting](#troubleshooting)
- [Running the tests](#running-the-tests)

## Requirements

| | |
|---|---|
| Python | 3.12 or newer (the `gerbonara` library requires it). Tried with 3.14. |
| System | Tried on macOS (Apple Silicon). The code is plain Python and JavaScript, with no system-specific parts; on Linux the same commands apply. |
| Browser | A recent one (tried with Chrome). The page uses IndexedDB and Web Locks for the working copy. |
| Printer template | A `.ctb` file made with ChiTuBox, see below. It is not in the repository. |
| Node.js | Only to run the tests of the page logic (optional). |

The Python dependencies are pinned in `requirements.txt` (numpy, Pillow, shapely, gerbonara, pydantic, fastapi, uvicorn, python-multipart). `gerbonara` 1.6.3 is patched at run time in `gerberslap/core/gerber_io.py`: do not update it without redoing the tests.

## The printer template

**What it is.** The app does not write the `.ctb` file from scratch: it starts from a file made by ChiTuBox, the *template*, and changes only the layer images, the exposure time and the Z height. Everything else (the lift distances and speeds, the second stages, the rests, the fields of the format that are not documented) is copied from the template as it is: they are values the printer has already shown it accepts, and inventing them can make the carriage move in unexpected ways. The template is also how *you* choose how the printer moves during the exposure. (For a printer other than the LD-002H the principle is the same: see [NEW_PRINTER.md](NEW_PRINTER.md#the-template).)

**Why it is not in the repository.** A `.ctb` file contains the copyright notice of CBD Technology, and the same notice ends up in the files the app generates. That is why neither the template nor the generated files go into the repository or a Docker image: everyone prepares their own and installs it in the data folder.

**How to prepare it.** In ChiTuBox, with the *Creality LD-002H* printer, slice any object (a cube will do) with these settings and save the `.ctb` file:

- *Waiting Mode*: "Resting time", with the three rest times at 0;
- bottom lift distance and normal lift distance: **0.001 mm** (and 0 for the second value, the one after the "+");
- the four speeds (lift and retract, bottom and normal): **500 mm/min** (and 0 for the second values);
- a single bottom layer.

Never use a lift distance of 0: the printer would replace it with a 5 mm cycle. The app refuses a template that uses it.

**How to install it.** Once only, from the project folder:

```bash
.venv/bin/python -m gerberslap.web --install-template ld002h /path/to/template.ctb
```

The command checks the file with the printer's driver before writing anything, copies it to `<data folder>/printers/ld002h/template.ctb` and exits without starting the server. It exits with 0 (done), 1 (file or folder refused: it says why) or 2 (there is no printer with that id). Running it again replaces the template.

Once the app is running, in *Settings* the printer's card says **Ready**, and the "Generate" button can turn on. Without a template the warnings icon is red and the button stays off, with the reason written under it.

## Native installation

```bash
git clone https://github.com/shad0w82/GerberSLAp.git GerberSLAp
cd GerberSLAp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Then install the template (above) and start:

```bash
.venv/bin/python -m gerberslap.web
```

The server listens on **http://127.0.0.1:8800**, that is only on this computer, and prints at start-up the data folder in use and whether the recipe library is on. Open that address in the browser and work; to stop the server, `Ctrl+C`.

Notes:

- Start it **from the project folder**: the `gerberslap` package is there, and the default data folder, `./data`, is relative to where you run the command.
- The server is an ordinary process, which ends with the terminal. To keep it always on, use the system's service manager (launchd, systemd) or Docker.
- **Always use the same address in the browser.** The working copy of the projects lives in the browser and depends on the address: `http://127.0.0.1:8800` and `http://localhost:8800` are two different sites to it, with two different copies.

## Options, environment variables and data folder

```
python -m gerberslap.web [options]
```

| Option | Meaning |
|---|---|
| `--host ADDRESS` | Address to listen on. Default `$GERBERSLAP_HOST`, otherwise `127.0.0.1` (this computer only). In a container it must be `0.0.0.0` (the image already sets it). |
| `--port N` | Port. Default `$GERBERSLAP_PORT`, otherwise 8800. |
| `--data FOLDER` | Data folder. Default: `$GERBERSLAP_DATA`, otherwise `./data`. |
| `--install-template ID FILE` | Installs the template of printer `ID` and exits (see above). |
| `--allowed-host NAME` | Another name the server can be reached by (repeatable; added to the names in `$GERBERSLAP_ALLOWED_HOSTS`). See [Network and security](#network-and-security). |
| `--no-library` | Turns the recipe library off (see below). Also with `GERBERSLAP_NO_LIBRARY=1`. |
| `--dev-samples FOLDER` | For trying the page: offers the zips in the folder, and `/?sample=name.zip` opens one by itself. |
| `--dev-printers` | For trying the page: adds three made-up printers (they write no file). |

The last two are development tools. The options the app was started with appear at the bottom of the page's side panel (only the names, never folders or ports).

Environment variables: they are the way to configure a container, but they work locally too. **An option written on the command line always wins over the variable**; an empty variable counts as not set.

| Variable | Same as | Notes |
|---|---|---|
| `GERBERSLAP_HOST` | `--host` | |
| `GERBERSLAP_PORT` | `--port` | A value that is not a port (1 to 65535) stops the start-up with a clear message. |
| `GERBERSLAP_ALLOWED_HOSTS` | `--allowed-host` | Several names separated by commas; added to the ones given with the option. |
| `GERBERSLAP_DATA` | `--data` | |
| `GERBERSLAP_NO_LIBRARY` | `--no-library` | `1`, `true`, `yes` or `on`. |

### The data folder

```
data/
  printers/<printer id>/template.ctb    the template (installed with --install-template)
  printers/<printer id>/printer.json    optional: settings different from the driver's defaults
  recipes/<id>.json                     one recipe per file, with its dosages inside
```

It is the only thing the app keeps on the server, and the one to back up (in Docker, the volume). Users' projects are **never** stored there: they live in the browser and in the `.gslp` files that are downloaded. Writes are atomic (an interruption leaves the old file, never a half-written one) and a file that cannot be read is reported, neither ignored nor "repaired". One process per data folder.

The folder is in `.gitignore`: it does not go into the repository.

### Printer settings (`printer.json`)

Optional: they are only for changing the driver's default values. For the LD-002H:

| Setting | Default | Meaning |
|---|---|---|
| `park_z_mm` | 1.0 | Z height, in mm, at which all layers sit: the carriage hardly moves. |
| `start_delay_s` | 0 | Seconds to wait at the start, to put the blank in place after the Z zero (0 = none). |
| `cycle_s` | 8 | Estimate of the duration of the printer's own 5 mm cycle; it only sizes the initial wait. |

```json
{
  "format": "gerberslap-printer",
  "schema_version": 1,
  "printer": { "settings": { "park_z_mm": 1.0, "start_delay_s": 0, "cycle_s": 8 } }
}
```

A file that cannot be read, or has invalid values, is reported among the printer's warnings and blocks generation.

### With and without the recipe library (`--no-library`)

By default recipes and dosages live in the data folder and are shared by every browser that uses that server (it is meant for a home or lab server, where several people try the same resists).

With `--no-library` the server **turns off only the library**: the recipe routes do not exist (they answer 404) and the page offers neither the recipe menu nor their management. In the Exposure panel the resist switch and the three values (total time, flashes, rest) remain, which the browser remembers on its own; the calibration ladder remembers its own. The file is generated the same way: the request carries the polarity and the values, and the server never reads the library. The printers' templates stay in the data folder.

Note: **it is not a "public" mode and it does not make the server safe for the Internet.** See the next section.

## Docker installation

The image runs on **arm64 and amd64** (tried on both: the same projects give byte-identical files), keeps the data folder in a **volume** and holds **no `.ctb` file**: the template is installed in the volume, once only. You need Docker (Docker Desktop on macOS and Windows, Docker Engine on Linux) and, for the Compose method, the `docker compose` plugin.

**What is in the image.** `python:3.14-slim`, the dependencies in `requirements.txt`, the `gerberslap/` package (with `printers/`, the `icon.png` photos and each driver's reader and writer of its files) and the `LICENSE` file (the licence goes with every copy). Not in it: `.ctb` files, `data/`, `tests/`, `docs/` or the drivers' `docs/` folders. The build context is decided by `.dockerignore`, which leaves everything out and lets in only what is needed; a test (`tests/test_docker.py`) checks that this is so.

**How it runs.** As an unprivileged user (uid and gid 10001, `gerberslap`), with `GERBERSLAP_HOST=0.0.0.0` (inside the container it listens on every interface; who can reach it from outside is decided by publishing the port), `GERBERSLAP_DATA=/data` (the volume), port 8800. The `ENTRYPOINT` is `python -m gerberslap.web` and there is no `CMD`: the options go after the image name, for example `docker run … gerberslap --no-library`. A **health check** (`HEALTHCHECK`) asks `/api/info` on its own address every 30 seconds: `docker ps` shows `healthy`. One container per volume (two processes on the same data folder are not supported).

### With Docker Compose (the recommended way)

The repository's `compose.yaml` builds the image, creates the `gerberslap-data` volume and starts the app so that it restarts by itself:

```bash
# build the image (from the project folder)
docker compose build

# once only: install the printer template in the volume
docker compose run --rm -v "$PWD/template:/in:ro" gerberslap --install-template ld002h /in/template.ctb

# start the app
docker compose up -d
```

Then open **http://127.0.0.1:8800**. For the template, `$PWD/template` is a folder that holds the file `template.ctb` (it is mounted read-only); the command exits with 0 if it installed it, and with 1 or 2 saying why if not (see [The printer template](#the-printer-template)).

How to manage it:

```bash
docker compose logs -f        # the server's messages
docker compose ps             # the state, with "healthy" when it answers
docker compose down           # stops and removes the container: the volume, with template and recipes, stays
docker compose down -v        # removes the volume too (deletes template and recipes)
```

The file publishes the port **on this computer only** (`127.0.0.1`). The port is changed with the `GERBERSLAP_PORT` variable, in the environment or in a `.env` file next to `compose.yaml` (for example `GERBERSLAP_PORT=8812`): it applies both outside and inside the container.

### With docker run

```bash
docker build -t gerberslap .

# once only: the template
docker run --rm -v gerberslap-data:/data -v "$PWD/template:/in:ro" \
    gerberslap --install-template ld002h /in/template.ctb

# start the app (from this computer only)
docker run -d --name gerberslap --restart unless-stopped \
    -p 127.0.0.1:8800:8800 -v gerberslap-data:/data gerberslap
```

The `gerberslap-data` volume holds the template and the recipes: back it up with the usual Docker volume backup. To change the outside port, `-p 127.0.0.1:9000:8800` is enough; to change it inside as well, pass `-e GERBERSLAP_PORT=9000` and publish the same port.

### Reaching it from other computers (a home server)

Take `127.0.0.1:` out of the `ports` line in `compose.yaml` (or out of `-p`) and tell the server which name it is reached by, otherwise it refuses the requests with `bad_host`. With Compose, uncomment the `GERBERSLAP_ALLOWED_HOSTS` line in the file:

```yaml
      GERBERSLAP_ALLOWED_HOSTS: "nas.local,192.168.1.20"
```

and with `docker run`:

```bash
docker run -d --name gerberslap --restart unless-stopped -p 8800:8800 -v gerberslap-data:/data \
    -e GERBERSLAP_ALLOWED_HOSTS=nas.local,192.168.1.20 gerberslap
```

Everything that follows on network and security applies: the app has no authentication.

### A folder on the computer instead of the volume

You can mount a folder (`-v "$PWD/data:/data"`) to see the recipe and template files. The container runs as user 10001: the folder must be writable by it (on Linux `sudo chown -R 10001:10001 data`; with Docker Desktop on macOS it is usually not needed). If it cannot write it, `--install-template` answers with a permissions error and the app cannot save recipes.

## Network and security

The app is meant for **local use or a trusted network** (the computer of whoever uses it, or a home server). By default it listens only on `127.0.0.1`.

What the server does to protect itself, even when it listens only locally (because any program or page on the computer can reach a local port):

- **`Host` header check**: it accepts only `localhost`, `127.0.0.1`, `::1` and the names given with `--allowed-host`. It protects against DNS rebinding attacks.
- **Requests that change something only from the page itself**: every request that is not read-only (`POST`, `PATCH`, `DELETE`) with an `Origin` different from the server's, or with a `Sec-Fetch-Site` other than `same-origin`, is refused (another site open in the browser cannot use the app).
- **No caching** of responses (except the printers' photos) and `X-Content-Type-Options: nosniff`.
- **Zips and project files treated as hostile input**: an uploaded zip can weigh 64 MiB at most; inside it, at most 500 files, 64 MiB per file and 200 MiB in total; names are filtered (macOS entries and hidden files are discarded); `.gslp` projects are read back and checked entry by entry; the files received are kept in memory only.
- **No server path in the responses**: errors give a code, not where a file is.

What is **not** there, and why the app **must not be exposed to the Internet**: authentication, users and sessions, request limits and per-person quotas, and a memory of Gerber files that is single and shared by everyone (1 GiB in memory). Moreover the server generates files from a `.ctb` template that cannot be distributed (see above): before any public use that question has to be settled. `--no-library` turns off the library and nothing else: that is why it is not called `--public`.

If it is reached from other computers, the network must be trusted. For access from outside the home, use a VPN, not an open port.

**Hosting it on a public server** is at your own risk and peril: the project neither intends nor supports it, for the reasons just seen. Whoever does it with a modified version must, under the AGPL-3.0 licence, make the source of their version available to the users: the "Source code and licence" link on the Help page points to the original repository and has to be changed (`gerberslap/web/static/index.html`, the element with `id="source-link"`).

## Updating

Update the code (`git pull`) and the dependencies (`.venv/bin/pip install -r requirements.txt`) and restart; with Docker Compose, `docker compose build && docker compose up -d` (the volume stays as it is). The data folder stays as it is. `.gslp` files carry a version number: an older one is migrated when opened, one newer than the app knows is refused with a clear message. The same goes for the files in the data folder (which today have a single version). After a change to the Python code the server must be restarted (the page files need not: just reload the page).

## Troubleshooting

| Symptom | Cause and remedy |
|---|---|
| `Address already in use` at start | Port 8800 is taken (another start of the app?). Stop the other one or use `--port`. |
| The browser shows "bad_host" (403) | The server is reached by a name it does not know: `--allowed-host name` (in Docker, `GERBERSLAP_ALLOWED_HOSTS`). |
| The warnings icon is red and "Generate" is off: *the printer template file is missing* | The template is not installed in the data folder the server is using (check `--data` or `GERBERSLAP_DATA`: the install command must use the same one). Once installed, just reload the page: the server re-reads the template on every request, no restart needed. |
| The same warning, but *the template file cannot be used (reason)* | The template was refused by the driver. The reasons: *it is not a file of the printer's format*; *the format version is not the expected one* (v5 is needed); *the file is damaged* (CRC); *the resolution is not that of the printer's screen* (an LD-002H is needed, 1620 × 2560); *it holds no layer*; *the layer data cannot be read*; *the lift distance is 0* (make it again with 0.001 mm); *the lift or retract speed is not valid*. |
| Warning: *the movement copied from the template lifts the carriage X mm* | The template has a large lift distance (over 1 mm): every flash becomes slow. 0.001 mm is advised; make the template again. |
| Warning about the `printer.json` file | The printer's settings file cannot be read or has invalid values (see above). |
| Docker: `bind: address already in use` | Port 8800 of the computer is taken: change it with `GERBERSLAP_PORT` (Compose) or with `-p 127.0.0.1:9000:8800` (`docker run`). |
| Docker: `docker ps` says `unhealthy`, or the page does not open | Look at the messages (`docker compose logs`). The check asks the server from the inside, so `unhealthy` means the server did not start: usually a wrong port or environment variable (`GERBERSLAP_PORT must be a number…`). |
| Docker: `--install-template` gives a permissions error | The data folder is not writable by user 10001: it only happens when mounting a folder of the computer instead of the volume (see above). |
| Docker: the page says the template is missing, though I installed it | The template went into another volume: the installation and the app must use the same one (`gerberslap-data`, or the same mounted folder). |
| A zip is refused | Old EAGLE exports (before EAGLE 9's Gerber format) are refused on purpose; a zip with no copper file, or not recognisable, gives a message that says so. |
| "A flash under the minimum" | The flash is `total time / number of flashes`: under 1 s it has never been tried on the printer and the file is not generated. Over 20 s it is generated with a warning (not tried). |
| After the server restarts the page says a file is missing | The server keeps the Gerber files in memory only. If the project was saved (working copy in the browser) the page gives them back by itself; otherwise open the zip again. |
| Saved projects "disappear" | The working copy lives in the browser and depends on the address and the profile: always use the same address and the same browser. To take a project elsewhere, download the `.gslp` file (which also holds the Gerber files). |

## Running the tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

About 1160 tests in a couple of minutes. The tests that need something that is missing skip themselves: third-party files in `experiments/fase1/external/` and `experiments/fase2/external/` (not in the repository), the `samples/speedCube.ctb` template (likewise; `.ctb` files are not published) and Node.js (for the page logic). The syntax check of the JavaScript modules uses `node --input-type=module --check` with the file on stdin: `node --check file.js` is not enough (with Node 26 it accepts modules with errors).

Other useful checks on generated files: `python3 gerberslap/printers/ld002h/ctbio.py info file.ctb` (header and CRC) and `python3 gerberslap/printers/ld002h/ctbio.py layer file.ctb N out.png` (extracts a layer as an image).
