"""The Docker files: what the image is made of is a list, so that no .ctb file (it carries the manufacturer's copyright notice) and nothing of the
developer's can end up in it, and what the program reads at run time outside its package is in it. Checked without Docker: the build context is worked out
from `.dockerignore` the way Docker reads it (the last pattern that matches wins, and a pattern that matches a folder takes its whole content)."""
import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DOCKERFILE = (REPO / "Dockerfile").read_text()
COMPOSE = (REPO / "compose.yaml").read_text()
SKIP_WALK = {".venv", ".git", ".pytest_cache", "node_modules"}                 # all of them are left out by the first pattern (checked below as paths)


def patterns():
    return [line.strip() for line in (REPO / ".dockerignore").read_text().splitlines() if line.strip() and not line.strip().startswith("#")]


def regex(pattern: str) -> re.Pattern:
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def in_context(path: str) -> bool:
    """Whether the file is sent to the build: the patterns in order, the last that matches the path (or one of its folders) decides."""
    included = True
    parts = path.split("/")
    candidates = ["/".join(parts[:n]) for n in range(1, len(parts) + 1)]
    for pat in patterns():
        negate = pat.startswith("!")
        rx = regex(pat[1:] if negate else pat)
        if any(rx.match(c) for c in candidates):
            included = negate
    return included


def context_files():
    found = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_WALK]
        for name in files:
            rel = (Path(root) / name).relative_to(REPO).as_posix()
            if in_context(rel):
                found.append(rel)
    return sorted(found)


def test_the_build_context_is_the_program_and_nothing_else():
    files = context_files()
    assert "requirements.txt" in files and "gerberslap/web/app.py" in files and "LICENSE" in files
    assert "gerberslap/printers/ld002h/ctbio.py" in files and "gerberslap/printers/ld002h/icon.png" in files                  # the writer of the printer's file, the photo of the printer
    assert "gerberslap/web/static/index.html" in files and "gerberslap/web/static/js/app.js" in files                           # the page
    top = {f.split("/")[0] for f in files}
    assert top == {"requirements.txt", "LICENSE", "gerberslap"}, top                                                         # tests, samples, data, docs, experiments, mockup: none
    assert not [f for f in files if f.endswith((".ctb", ".pyc")) or "__pycache__" in f]                                       # no .ctb, whatever folder it is in
    assert not [f for f in files if "/docs/" in f]                                                                          # the documents that sit next to a driver stay in the repository


@pytest.mark.parametrize("path", [".venv/bin/python", ".git/config", "data/printers/ld002h/template.ctb", "samples/speedCube.ctb", "tests/test_docker.py", "docs/en/installation/install.md", "mkdocs.yml", "mkdocs-require.txt", "overrides/partials/toc.html", ".github/workflows/docs.yml",
                                  "experiments/fase2/external/x.zip", "mockup/index.html", "README.md", "Dockerfile", "compose.yaml", "gerberslap/printers/ld002h/template.ctb",
                                  "gerberslap/web/__pycache__/app.cpython-314.pyc", "ctbio.ctb", "assets/other/x.png", "LICENSE.ctb",
                                  "gerberslap/printers/ld002h/docs/pcb_ctb.py", "gerberslap/printers/ld002h/docs/ctb_v5_ld002h_formato.md"])
def test_what_must_stay_out_of_the_image_is_out_of_the_context(path):
    assert not in_context(path), path


def test_the_first_pattern_leaves_everything_out_and_the_rest_let_in_only_what_the_program_needs():
    pats = patterns()
    assert pats[0] == "*"
    assert [p for p in pats if p.startswith("!")] == ["!requirements.txt", "!LICENSE", "!gerberslap", "!gerberslap/**"]
    assert {"**/*.ctb", "**/docs"} <= set(pats) and min(pats.index("**/*.ctb"), pats.index("**/docs")) > max(i for i, p in enumerate(pats) if p.startswith("!"))   # the exclusions come after, so that they win


def test_everything_the_program_needs_is_in_its_package_and_is_copied():
    assert re.search(r"^COPY gerberslap \./gerberslap$", DOCKERFILE, re.M)
    assert re.search(r"^COPY LICENSE \./$", DOCKERFILE, re.M) and 'org.opencontainers.image.licenses="AGPL-3.0-only"' in DOCKERFILE    # the licence goes with every copy of the program
    assert (REPO / "LICENSE").read_text().startswith("                    GNU AFFERO GENERAL PUBLIC LICENSE")
    assert (REPO / "gerberslap" / "printers" / "ld002h" / "ctbio.py").is_file() and "from . import ctbio" in (REPO / "gerberslap" / "printers" / "ld002h" / "driver.py").read_text()   # the .ctb reader and writer is the driver's own
    assert not list((REPO / "gerberslap").rglob("*.ttf")) and "assets" not in (REPO / "gerberslap" / "services" / "ladder.py").read_text()          # no font file: the time of a strip is written with the one Pillow carries
    copied = re.findall(r"^COPY (\S+)", DOCKERFILE, re.M)
    assert copied == ["requirements.txt", "LICENSE", "gerberslap"]                                                           # in this order: the dependencies first, so that their layer is kept


def test_the_image_runs_the_app_as_an_unprivileged_user_with_its_data_in_a_volume():
    assert re.search(r"^FROM python:3\.(1[2-9]|[2-9]\d)-slim$", DOCKERFILE, re.M)                                            # 3.12 or newer, the slim image (never alpine: the wheels are for glibc)
    assert DOCKERFILE.index("USER gerberslap") < DOCKERFILE.index("ENTRYPOINT")
    assert "10001" in DOCKERFILE and "chown gerberslap:gerberslap /data" in DOCKERFILE and DOCKERFILE.index("chown") < DOCKERFILE.index("VOLUME /data")   # the folder is the user's before it is a volume
    assert "GERBERSLAP_HOST=0.0.0.0" in DOCKERFILE and "GERBERSLAP_DATA=/data" in DOCKERFILE and "EXPOSE 8800" in DOCKERFILE
    assert 'ENTRYPOINT ["python", "-m", "gerberslap.web"]' in DOCKERFILE and "CMD" not in re.sub(r"HEALTHCHECK[^\n]*\n\s*CMD", "", DOCKERFILE)    # the options follow the image name
    assert "HEALTHCHECK" in DOCKERFILE and "/api/info" in DOCKERFILE


def test_the_dependencies_of_the_image_are_the_runtime_ones():
    requirements = (REPO / "requirements.txt").read_text()
    assert "pytest" not in requirements and "httpx" not in requirements                                                       # the tools of the tests stay out
    assert "pip install" in DOCKERFILE and "-r requirements.txt" in DOCKERFILE


def test_the_compose_file_keeps_the_app_on_this_computer_with_its_data_in_a_named_volume():
    assert '"127.0.0.1:${GERBERSLAP_PORT:-8800}:${GERBERSLAP_PORT:-8800}"' in COMPOSE                                         # not published to the network unless the person says so
    assert "gerberslap-data:/data" in COMPOSE and re.search(r"^volumes:\n  gerberslap-data:", COMPOSE, re.M)
    assert "restart: unless-stopped" in COMPOSE and "build: ." in COMPOSE
    assert re.search(r"^\s+# GERBERSLAP_ALLOWED_HOSTS:", COMPOSE, re.M) and re.search(r"^\s+# GERBERSLAP_NO_LIBRARY:", COMPOSE, re.M)   # offered, off


def test_the_gitignore_still_keeps_the_ctb_files_and_the_data_folder_out_of_the_repository():
    ignored = (REPO / ".gitignore").read_text().splitlines()
    assert "*.ctb" in ignored and "/data/" in ignored
