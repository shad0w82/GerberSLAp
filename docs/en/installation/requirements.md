---
icon: material/clipboard-check-outline
---

# Requirements and template

To install GerberSLAp you need a few requirements and one file that the app cannot ship with itself: the printer **template**. This page explains both; then you choose between a native installation and Docker in [Installing the app](install.md).

## Requirements

| Requirement | Detail |
|---|---|
| **Python** | 3.12 or newer (the `gerbonara` library requires it); tried with 3.14. Only needed for the native installation: the Docker image already contains it. |
| **System** | Tried on macOS (Apple Silicon). The code is made only of Python and JavaScript, with no system-specific parts: on Linux the same commands apply. |
| **Browser** | A recent one; Chrome is the one tried. The page uses IndexedDB and Web Locks for the working copy of the projects. |
| **Template** | A `.ctb` file made with ChiTuBox, as explained below. It is not in the repository. |
| **Node.js** | Only to run the tests of the page logic: optional. |

The Python dependencies are pinned in `requirements.txt`.

## The printer template

The app does not write the `.ctb` file from scratch: it starts from a file made with ChiTuBox, the **template**, and changes only the layer images, the exposure time and the Z height. Everything else is copied as it is: the lift distances and speeds, the second stages, the rests and the fields of the format that nobody documents. They are values the printer has already shown it accepts, and inventing them can make the carriage move in unexpected ways. The template is also how you choose how the printer moves during the exposure.

!!! info "Why it is not in the repository"
    A `.ctb` file contains the copyright notice of CBD Technology, and the same notice ends up in the files the app generates. That is why neither the template nor the generated files are kept in the repository or in a Docker image: everyone prepares their own and installs it in the data folder.

### How to prepare it

In ChiTuBox, choosing the *Creality LD-002H* printer, slice any object (a cube will do) with these settings and save the `.ctb` file:

- *Waiting Mode*: "Resting time", with the three rest times at 0;
- bottom lift distance and normal lift distance: **0.001 mm** (and 0 for the second value, the one after the "+");
- the four speeds (lift and retract, bottom and normal): **500 mm/min** (and 0 for the second values);
- a single bottom layer.

!!! danger "Never a lift distance of 0"
    The printer would replace it with a 5 mm cycle. The app refuses a template that uses it.

For a printer other than the LD-002H the principle is the same: [The printer driver](../development/new-printer/driver.md#the-template) explains it.

### How to install it

Once only, from the project folder:

```bash
.venv/bin/python -m gerberslap.web --install-template ld002h /path/to/template.ctb
```

The command checks the file with the printer's driver before writing anything, copies it to `<data folder>/printers/ld002h/template.ctb` and exits without starting the server. It exits with 0 (installed), 1 (file or folder refused: it says why) or 2 (there is no printer with that id). Running it again replaces the template. With Docker the same command runs inside the container: see [Docker installation](install.md#docker-installation).

Once the app is running, in Settings the printer's card says **Ready** and the "Generate" button can turn on. Without a template the warnings icon is red and the button stays off, with the reason written under it.
