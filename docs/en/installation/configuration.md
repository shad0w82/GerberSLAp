---
icon: material/tune-variant
---

# Configuration

How the app is started, where it keeps its data and what the server does to protect itself. The options apply to every way of installing; with Docker, environment variables are the normal way to set them.

## Start-up options

```bash
python -m gerberslap.web [options]
```

| Option | Meaning |
|---|---|
| `--host ADDRESS` | Address to listen on. Default `$GERBERSLAP_HOST`, otherwise `127.0.0.1` (this computer only). In a container it must be `0.0.0.0`: the image already sets it. |
| `--port N` | Port. Default `$GERBERSLAP_PORT`, otherwise 8800. |
| `--data FOLDER` | Data folder. Default `$GERBERSLAP_DATA`, otherwise `./data`. |
| `--install-template ID FILE` | Installs the [template](requirements.md#the-printer-template) of printer `ID` and exits. |
| `--allowed-host NAME` | Another name the server can be reached by. It can be repeated and is added to the names in `$GERBERSLAP_ALLOWED_HOSTS`. See [Network and security](#network-and-security). |
| `--no-library` | Turns the recipe library off ([see below](#with-and-without-the-recipe-library)). Also with `GERBERSLAP_NO_LIBRARY=1`. |
| `--dev-samples FOLDER` | For trying the page: offers the zips in the folder, and `/?sample=name.zip` opens one by itself. |
| `--dev-printers` | For trying the page: adds three made-up printers, which write no file. |

The last two are development tools. The options the app was started with appear at the bottom of the page's side panel (the SideStatusBar): only the names, never folders or ports.

## Environment variables

They are the way to configure a container, but they work locally too. **An option written on the command line always wins over the variable**; an empty variable counts as not set.

| Variable | Same as | Notes |
|---|---|---|
| `GERBERSLAP_HOST` | `--host` | |
| `GERBERSLAP_PORT` | `--port` | A value that is not a port (1 to 65535) stops the start-up with a clear message. |
| `GERBERSLAP_ALLOWED_HOSTS` | `--allowed-host` | Several names separated by commas, added to the ones given with the option. |
| `GERBERSLAP_DATA` | `--data` | |
| `GERBERSLAP_NO_LIBRARY` | `--no-library` | `1`, `true`, `yes` or `on`. |

## The data folder

```text
data/
  printers/<printer id>/template.ctb    the template (installed with --install-template)
  printers/<printer id>/printer.json    optional: settings different from the driver's defaults
  recipes/<id>.json                     one recipe per file, with its dosages inside
```

It is the only thing the app keeps on the server, and the one to back up (in Docker, the volume). Users' projects are **never** stored there: they live in the browser and in the `.gslp` files that are downloaded.

Writes are atomic: an interruption leaves the old file, never a half-written one. A file that cannot be read is reported, neither ignored nor "repaired". One process per data folder. The folder is in `.gitignore`: it does not go into the repository.

## Printer settings

The `printer.json` file is optional and only changes the driver's default values. For the LD-002H:

| Setting | Default | Meaning |
|---|---|---|
| `park_z_mm` | 1.0 | Z height, in mm, at which all layers sit: the carriage hardly moves. |
| `start_delay_s` | 0 | Seconds to wait at the start, to put the blank in place after the Z zero (0 = no wait). |
| `cycle_s` | 8 | Estimate of the duration of the printer's own 5 mm cycle: it only sizes the initial wait. |

```json
{
  "format": "gerberslap-printer",
  "schema_version": 1,
  "printer": { "settings": { "park_z_mm": 1.0, "start_delay_s": 0, "cycle_s": 8 } }
}
```

A file that cannot be read, or has invalid values, is reported among the printer's warnings and blocks generation.

## With and without the recipe library

By default recipes and dosages live in the data folder and are shared by every browser that uses that server. It is meant for a home or lab server, where several people try the same resists.

With `--no-library` the server **turns off only the library**:

- the recipe routes do not exist (they answer 404) and the page offers neither the recipe menu nor their management;
- in the Exposure panel the resist switch and the three values (total time, flashes, rest) remain, which the browser remembers on its own; the calibration ladder remembers its own;
- the file is generated the same way: the request carries the polarity and the values, and the server never reads the library;
- the printers' templates stay in the data folder.

!!! warning "It is not a “public” mode"
    `--no-library` does not make the server safe for the Internet. See the next section.

## Network and security

The app is meant for **local use or a trusted network**: the computer of whoever uses it, or a home server. By default it listens only on `127.0.0.1`.

### What the server does to protect itself

Even when it listens only locally, because any program or page on the computer can reach a local port:

- **`Host` header check.** It accepts only `localhost`, `127.0.0.1`, `::1` and the names given with `--allowed-host`. It protects against DNS rebinding attacks.
- **Requests that change something only from the page itself.** Every request that is not read-only (`POST`, `PATCH`, `DELETE`) with an `Origin` different from the server's, or with a `Sec-Fetch-Site` other than `same-origin`, is refused: another site open in the browser cannot use the app.
- **No caching** of responses, except the printers' photos, and `X-Content-Type-Options: nosniff`.
- **Zips and project files treated as hostile input.** An uploaded zip weighs 64 MiB at most; inside it there are at most 500 files, 64 MiB per file and 200 MiB in total. Names are filtered (macOS entries and hidden files are discarded), `.gslp` projects are read back and checked entry by entry, and the files received are kept in memory only.
- **No server path in the responses.** Errors give a code, not where a file is.

### What is not there

There are no authentication, users and sessions, request limits or per-person quotas. The memory of Gerber files is single and shared by everyone (1 GiB in memory). Moreover the server generates files from a `.ctb` template that cannot be distributed, and before any public use that question has to be settled. That is why the app **must not be exposed to the Internet** and `--no-library` is not called `--public`.

If the app is reached from other computers, the network must be trusted. For access from outside the home, use a VPN, not an open port.

!!! danger "Hosting it on a public server is at your own risk and peril"
    The project neither intends nor supports it. Whoever does it with a modified version must, under the AGPL-3.0 licence, make the source of their version available to the users: the "Source code and licence" link on the Help page points to the original repository and has to be changed (`gerberslap/web/static/index.html`, the element with `id="source-link"`).
