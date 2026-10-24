---
icon: material/alert-circle-outline
---

# Warnings and problems

## Warnings

!!! note "Work in progress"
    The list of warnings, with what they mean and what to do, is being written.

## Common problems

Installation and start-up problems are in [Updating and troubleshooting](../installation/maintenance.md#troubleshooting).

| Symptom | Cause and remedy |
|---|---|
| A zip is refused | Old EAGLE exports (before EAGLE 9's Gerber format) are refused on purpose. A zip with no copper file, or not recognisable, gives a message that says so. |
| "A flash under the minimum" | The flash is `total time / number of flashes`. Under 1 s it has never been tried on the printer and the file is not generated; over 20 s it is generated with a warning (not tried). |
| After a restart a file is missing | The server keeps the Gerber files in memory only. If the project was saved (working copy in the browser) the page gives them back by itself; otherwise open the zip again. |
| Saved projects "disappear" | The working copy lives in the browser and depends on the address and the profile: always use the same address and the same browser. To take a project elsewhere, download the `.gslp` file, which also holds the Gerber files. |
