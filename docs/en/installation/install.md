---
icon: material/download-circle-outline
---

# Installing the app

GerberSLAp can be installed in two ways: **natively**, with Python on your own computer, or **with Docker**. Either way you need the [printer template](requirements.md#the-printer-template), to be installed once only.

## Native installation

```bash
git clone https://github.com/shad0w82/GerberSLAp.git GerberSLAp
cd GerberSLAp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Then [install the template](requirements.md#how-to-install-it) and start the app:

```bash
.venv/bin/python -m gerberslap.web
```

The server listens on **http://127.0.0.1:8800**, that is only on this computer, and at start-up it prints the data folder in use and whether the recipe library is on. Open that address in the browser and work; to stop the server, press `Ctrl+C`.

- **Start it from the project folder.** The `gerberslap` package is there, and the default data folder, `./data`, is relative to where you run the command.
- **The server is an ordinary process**, which ends with the terminal. To keep it always on, use the system's service manager (launchd, systemd) or Docker.

!!! warning "Always use the same address in the browser"
    The working copy of the projects lives in the browser and depends on the address: `http://127.0.0.1:8800` and `http://localhost:8800` are two different sites to it, with two different copies.

## Docker installation

The image runs on **arm64 and amd64** (tried on both: the same projects give byte-identical files), keeps the data folder in a **volume** and holds **no `.ctb` file**: the template is installed in the volume, once only. You need Docker (Docker Desktop on macOS and Windows, Docker Engine on Linux) and, for the Compose method, the `docker compose` plugin.

??? info "What is in the image and how it runs"
    **Contents.** `python:3.14-slim`, the dependencies in `requirements.txt`, the `gerberslap/` package (with the drivers, the printers' photos and each driver's reader and writer of its files) and the `LICENSE` file. Not in it: `.ctb` files, `data/`, `tests/`, `docs/` or the drivers' `docs/` folders. The build context is decided by `.dockerignore`, which leaves everything out and lets in only what is needed; a test (`tests/test_docker.py`) checks that this is so.

    **Running.** As an unprivileged user (uid and gid 10001, `gerberslap`), with `GERBERSLAP_HOST=0.0.0.0` (inside the container it listens on every interface; who can reach it from outside is decided by publishing the port), `GERBERSLAP_DATA=/data` (the volume) and port 8800. The `ENTRYPOINT` is `python -m gerberslap.web` and there is no `CMD`: the options go after the image name, for example `docker run … gerberslap --no-library`. A health check (`HEALTHCHECK`) asks `/api/info` every 30 seconds: `docker ps` shows `healthy`. One container per volume: two processes on the same data folder are not supported.

### With Docker Compose

This is the recommended way. The repository's `compose.yaml` builds the image, creates the `gerberslap-data` volume and starts the app so that it restarts by itself:

```bash
# build the image (from the project folder)
docker compose build

# once only: install the printer template in the volume
docker compose run --rm -v "$PWD/template:/in:ro" gerberslap --install-template ld002h /in/template.ctb

# start the app
docker compose up -d
```

Then open **http://127.0.0.1:8800**. For the template, `$PWD/template` is a folder that holds the file `template.ctb`, mounted read-only. The command exits with 0 if it installed it, and with 1 or 2, saying why, if not.

To manage the app:

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

The `gerberslap-data` volume holds the template and the recipes and is backed up with the usual Docker volume backup. To change the outside port, `-p 127.0.0.1:9000:8800` is enough; to change it inside as well, pass `-e GERBERSLAP_PORT=9000` and publish the same port.

### Reaching it from other computers

To use the app from another computer, for example with a home server, take `127.0.0.1:` out of the `ports` line in `compose.yaml` (or out of `-p`) and tell the server which name it is reached by, otherwise it refuses the requests with `bad_host`. With Compose, uncomment the `GERBERSLAP_ALLOWED_HOSTS` line in the file:

```yaml
      GERBERSLAP_ALLOWED_HOSTS: "nas.local,192.168.1.20"
```

With `docker run`, pass the variable:

```bash
docker run -d --name gerberslap --restart unless-stopped -p 8800:8800 -v gerberslap-data:/data \
    -e GERBERSLAP_ALLOWED_HOSTS=nas.local,192.168.1.20 gerberslap
```

!!! warning "The app has no authentication"
    Everything in [Network and security](configuration.md#network-and-security) applies: the network must be trusted.

### A folder on the computer instead of the volume

You can mount a folder (`-v "$PWD/data:/data"`) to see the recipe and template files. The container runs as user 10001, so the folder must be writable by it: on Linux use `sudo chown -R 10001:10001 data`, while with Docker Desktop on macOS it is usually not needed. If the folder is not writable, `--install-template` answers with a permissions error and the app cannot save recipes.
