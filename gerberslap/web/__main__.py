"""python -m gerberslap.web  ->  the app on http://127.0.0.1:8800 (this machine only).

python -m gerberslap.web --install-template ID FILE  ->  puts the template of printer ID in the data folder and stops (no server).
python -m gerberslap.web --no-library  ->  without the recipe library: no recipes and no dosages, the polarity and the times are set by hand
(it turns off the library and nothing else: it does not make the server safe to put on the internet).

Besides the options, the environment can say where to listen and which names to accept (the way a container is configured): GERBERSLAP_HOST, GERBERSLAP_PORT,
GERBERSLAP_ALLOWED_HOSTS (names separated by commas), GERBERSLAP_DATA and GERBERSLAP_NO_LIBRARY. An option on the command line wins over the variable."""
import argparse
import os
import sys
from pathlib import Path

import uvicorn

from ..printers import UnknownDriver, registry
from ..services.installation import install_template
from ..services.store import DataStore, StoreError
from .app import create_app
from .devprinters import with_demo_printers


def install(store: DataStore, printer_id: str, source: Path, drivers, out=sys.stdout, err=sys.stderr) -> int:
    """The command that puts a printer's template in the data folder. 0: done; 1: the file or the folder refused it; 2: no such printer."""
    try:
        driver = drivers.get(printer_id)
    except UnknownDriver:
        print(f"error: there is no printer {printer_id!r} (the ones this version has: {', '.join(drivers.ids())})", file=err)
        return 2
    try:
        installed = install_template(store, driver, source)
    except StoreError as exc:
        print(f"error: the template was not installed: {exc.detail or exc.code}", file=err)
        return 1
    except OSError as exc:                                                    # the folder cannot be written (permissions, disk full)
        print(f"error: the template was not installed: {exc}", file=err)
        return 1
    print(f"Template installed for {driver.descriptor.name} ({printer_id}): {installed}", file=out)
    print(f"Start the app with the same data folder ({store.root}) and the printer will be ready.", file=out)
    return 0


def _env_port(ap: argparse.ArgumentParser) -> int:
    """The port the environment asks for (GERBERSLAP_PORT), or the default; a value that is not a port stops the start-up with a clear message."""
    raw = os.environ.get("GERBERSLAP_PORT", "").strip()
    if not raw:
        return 8800
    if not raw.isdigit() or not 1 <= int(raw) <= 65535:
        ap.error(f"GERBERSLAP_PORT must be a number from 1 to 65535, not {raw!r}")
    return int(raw)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m gerberslap.web", description="GerberSLAp, the web app.")
    ap.add_argument("--host", default=os.environ.get("GERBERSLAP_HOST", "").strip() or "127.0.0.1",
                    help="address to listen on (default: $GERBERSLAP_HOST, else this machine only: 127.0.0.1)")
    ap.add_argument("--port", type=int, default=_env_port(ap), help="port (default: $GERBERSLAP_PORT, else 8800)")
    ap.add_argument("--allowed-host", action="append", default=[],
                    help="another Host name to accept (e.g. behind a proxy); repeatable; the names in $GERBERSLAP_ALLOWED_HOSTS (separated by commas) are accepted too")
    ap.add_argument("--data", type=Path, help="the data folder with the printers' templates (default: $GERBERSLAP_DATA, else ./data)")
    ap.add_argument("--install-template", nargs=2, metavar=("ID", "FILE"),
                    help="put FILE in the data folder as the template of printer ID, then exit; the printer's driver checks the file first")
    ap.add_argument("--no-library", action="store_true",
                    help="no recipe library: no recipes and no dosages, polarity and times by hand (also with GERBERSLAP_NO_LIBRARY=1); "
                         "it does not make the server safe for the internet")
    ap.add_argument("--dev-samples", type=Path, help="a folder of .zip boards offered at /dev/samples/ (for trying the page)")
    ap.add_argument("--dev-printers", action="store_true", help="add three made-up printers (two with other planes, one whose template is not installed), to try choosing a printer and Settings with several (they write no file)")
    a = ap.parse_args(argv)
    a.allowed_host += [name.strip() for name in os.environ.get("GERBERSLAP_ALLOWED_HOSTS", "").split(",") if name.strip()]
    real = registry()
    store = DataStore(a.data)
    if a.install_template:
        sys.exit(install(store, a.install_template[0], Path(a.install_template[1]), real))
    printers, default = (with_demo_printers(real), real.ids()[0]) if a.dev_printers else (real, None)       # the made-up ones are never the default
    library = not (a.no_library or os.environ.get("GERBERSLAP_NO_LIBRARY", "").strip().lower() in ("1", "true", "yes", "on"))
    print(f"GerberSLAp: data folder {store.root}; recipe library " + ("on" if library else "off (--no-library): no recipes and no dosages"), flush=True)
    uvicorn.run(create_app(printers=printers, driver_id=default, allowed_hosts=a.allowed_host, dev_samples=a.dev_samples, store=store, library=library, dev_printers=a.dev_printers),
                host=a.host, port=a.port, log_level="info")


if __name__ == "__main__":
    main()
