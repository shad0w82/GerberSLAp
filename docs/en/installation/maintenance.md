---
icon: material/wrench-outline
---

# Updating and troubleshooting

## Updating

Update the code and the dependencies, then restart the app:

=== "Native installation"

    ```bash
    git pull
    .venv/bin/pip install -r requirements.txt
    ```

    Then restart the server. After a change to the Python code a restart is always needed; for the page files it is enough to reload the page.

=== "Docker Compose"

    ```bash
    git pull
    docker compose build && docker compose up -d
    ```

    The volume stays as it is, with the template and the recipes.

The data folder stays as it is. `.gslp` files carry a version number: an older one is migrated when opened, one newer than the app knows is refused with a clear message. The same goes for the files in the data folder, which today have a single version.

## Troubleshooting

The problems you meet while using the app, for example a refused zip or a warning about the exposure, are in [Warnings and problems](../usage/troubleshooting.md). Here are the ones about installation and start-up.

### Start-up and network

| Symptom | Cause and remedy |
|---|---|
| `Address already in use` at start | Port 8800 is taken, maybe by another start of the app. Stop the other one, or use `--port`. |
| The browser shows "bad_host" (403) | The server is reached by a name it does not know: `--allowed-host name` (in Docker, `GERBERSLAP_ALLOWED_HOSTS`). |

### Template and printer settings

| Symptom | Cause and remedy |
|---|---|
| Red icon and "Generate" off: *the template is missing* | The template is not installed in the data folder the server is using. Check `--data` or `GERBERSLAP_DATA`: the install command must use the same folder. Once installed, just reload the page: the server re-reads the template on every request, no restart needed. |
| Warning: *the template cannot be used (reason)* | The driver refused the template. The reasons: *it is not a file of the printer's format*; *the format version is not the expected one* (v5 is needed); *the file is damaged* (CRC); *the resolution is not that of the printer's screen* (an LD-002H is needed, 1620 × 2560); *it holds no layer*; *the layer data cannot be read*; *the lift distance is 0* (it must be made again with 0.001 mm); *the lift or retract speed is not valid*. |
| Warning: *the movement lifts the carriage X mm* | The template has a large lift distance (over 1 mm) and every flash becomes slow. 0.001 mm is advised: make the template again. |
| Warning about the `printer.json` file | The [printer settings](configuration.md#printer-settings) file cannot be read or has invalid values. |

### Docker

| Symptom | Cause and remedy |
|---|---|
| `bind: address already in use` | Port 8800 of the computer is taken: change it with `GERBERSLAP_PORT` (Compose) or with `-p 127.0.0.1:9000:8800` (`docker run`). |
| `unhealthy`, or the page does not open | Look at the messages with `docker compose logs`. The check asks the server from the inside, so `unhealthy` means the server did not start: usually a wrong port or environment variable (`GERBERSLAP_PORT must be a number…`). |
| `--install-template` gives a permissions error | The data folder is not writable by user 10001. It only happens when mounting a folder of the computer instead of the volume: see [A folder on the computer instead of the volume](install.md#a-folder-on-the-computer-instead-of-the-volume). |
| Template missing, though I installed it | The template went into another volume: the installation and the app must use the same one (`gerberslap-data`, or the same mounted folder). |
