"""The project file (`.gslp`): a project and the Gerber files it uses, in one zip that needs nothing else to be opened again.

The archive holds `project.json` and, for every Gerber or Excellon file a layer refers to, `files/<sha256>` (one entry per distinct
content, so boards that share files cost nothing). `project.json` is the project exactly as the model has it (with its `format` and
`schema_version`), plus `name` and `info` (for every board: the CAD program and the notes made when its zip was opened, which cannot be
worked out again once the zip is gone).

Writing is deterministic (the same project gives the same bytes: fixed dates, fixed order) and is read back and compared before the
bytes are handed over. Reading is strict, because the archive comes from outside: only the entries above, no duplicates, sizes
bounded, every file checked against its hash, nothing in the archive that no layer uses, a file format newer than this program refused
and an older one migrated. Nothing is guessed in silence: a missing or altered file refuses the whole project, naming the file.
"""
import hashlib
import io
import json
import re
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Mapping, Optional

from pydantic import Field, TypeAdapter, ValidationError

from ..core.gerber_io import MAX_MEMBERS, MAX_MEMBER_BYTES, MAX_TOTAL_BYTES
from ..model import Issue, Project
from ..model.base import PROJECT_SCHEMA_VERSION, Code, Id, Model, Name

FORMAT = "gerberslap"                                                       # the name of the format inside project.json: it is not the extension (".gslp"), so a renamed old file still opens
PROJECT_JSON = "project.json"
MAX_JSON_BYTES = 4 * 2**20
MAX_NOTES = 200                                     # per board
_FILE_ENTRY = re.compile(r"files/([0-9a-f]{64})")        # always with fullmatch: "$" would let a trailing newline through
_NO_DATE = (1980, 1, 1, 0, 0, 0)                    # the earliest date a zip can hold: the bytes must not depend on the clock

SCHEMA_VERSION = PROJECT_SCHEMA_VERSION             # the version of the file format, what the program writes and the newest it reads


def _v1_to_v2(doc: dict) -> dict:
    """Version 1 named a profile (always empty in practice, and profiles are gone: they became recipes with dosages). Version 2 names a recipe,
    its name and a dosage, all empty here: a project from before has no recipe to find."""
    doc = dict(doc)
    doc.pop("profile_id", None)
    return doc


# From a file format version to the next: MIGRATIONS[1] turns a version 1 document (the parsed project.json) into a version 2 one.
MIGRATIONS: dict[int, Callable[[dict], dict]] = {1: _v1_to_v2}


class ProjectFileError(Exception):
    """The project cannot be written or read. `code` and `params` are for the interface, which owns the wording."""

    def __init__(self, code: str, detail: str = "", **params):
        super().__init__(detail or code)
        self.code, self.detail, self.params = code, detail, params


class BoardInfo(Model):
    """What the page keeps about a board that is not in the project model."""
    cad: Optional[Code] = None
    notes: tuple[Issue, ...] = Field(default=(), max_length=MAX_NOTES)


@dataclass(frozen=True)
class Opened:
    project: Project
    name: Optional[str]
    info: dict                       # board id -> BoardInfo
    files: dict                      # sha256 -> bytes, the files the project refers to


_NAME = TypeAdapter(Optional[Name])
_INFO = TypeAdapter(dict[Id, BoardInfo])


def referenced_files(project: Project) -> dict:
    """sha256 -> the name of one file with that content, for every file a layer of the project refers to."""
    return {f.sha256: f.name for board in project.boards for layer in board.layers for f in layer.files}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entry(name: str) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", "?", name)[:120]


# ---- writing ------------------------------------------------------------------------------------------------------
def _write(project: Project, blobs: Mapping, name: Optional[str], info: Mapping) -> bytes:
    doc = {**project.model_dump(mode="json"), "name": name, "info": {k: v.model_dump(mode="json") for k, v in sorted(info.items())}}
    text = json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=True, allow_nan=False)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for entry, data in [(PROJECT_JSON, text.encode("ascii")), *((f"files/{sha}", blobs[sha]) for sha in sorted(blobs))]:
            zi = zipfile.ZipInfo(entry, date_time=_NO_DATE)
            zi.compress_type, zi.external_attr = zipfile.ZIP_DEFLATED, 0o600 << 16
            z.writestr(zi, data)
    return buf.getvalue()


def save_project(project: Project, files: Mapping, *, name: Optional[str] = None, info: Optional[Mapping] = None) -> bytes:
    """The bytes of the project file. `files` maps sha256 to the bytes of the Gerber files (the server's store); a file the project
    refers to that is not there, or whose content is not its hash, is an error naming it (`file_missing`, `bad_hash`)."""
    info = dict(info or {})
    unknown = sorted(set(info) - {b.id for b in project.boards})
    if unknown:
        raise ProjectFileError("invalid_project", "info for a board that is not in the project", reason="unknown_board", boards=unknown[:5])
    blobs = {}
    for sha, fname in sorted(referenced_files(project).items()):
        data = files.get(sha)
        if data is None:
            raise ProjectFileError("file_missing", f"{fname} is not in the store", file=fname, sha256=sha)
        if _sha(data) != sha:
            raise ProjectFileError("bad_hash", f"{fname} is not what its hash says", entry=f"files/{sha}")
        blobs[sha] = data
    out = _write(project, blobs, name, info)
    back = open_project(out)                                    # every file written is read back and compared
    if back.project != project or back.name != name or back.info != info or back.files != blobs:
        raise ProjectFileError("verification_failed", "the project read back is not the project written")
    return out


# ---- reading ------------------------------------------------------------------------------------------------------
def migrate(doc: dict) -> dict:
    """The document brought to the current file format version. A version this program does not know (newer, or not a number) is
    refused, never read as if it were the current one."""
    version = doc.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ProjectFileError("bad_version", "the file format version is not a positive whole number", found=None)
    if version > SCHEMA_VERSION:
        raise ProjectFileError("newer_version", "this project was saved by a newer program", found=version, supported=SCHEMA_VERSION)
    while version < SCHEMA_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise ProjectFileError("bad_version", f"no way to read file format version {version}", found=version)
        doc = step(dict(doc))
        version += 1
        doc["schema_version"] = version
    return doc


def _reject_constant(token):
    raise ValueError(f"{token} is not allowed in JSON")


def _read_archive(data: bytes) -> tuple:
    """(project.json bytes, {sha256: bytes}) of a well-formed archive. Raises ProjectFileError for anything else."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError, EOFError) as exc:
        raise ProjectFileError("bad_zip", f"not a valid zip archive ({exc})") from exc
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_MEMBERS:
        raise ProjectFileError("too_large", "too many entries")
    for entry, count in Counter(i.filename for i in infos).items():
        if count > 1:
            raise ProjectFileError("duplicate_entry", "an entry appears twice", entry=_entry(entry))
    for i in infos:
        if i.filename != PROJECT_JSON and not _FILE_ENTRY.fullmatch(i.filename):
            raise ProjectFileError("bad_entry", "an entry is neither project.json nor files/<sha256>", entry=_entry(i.filename))
    if PROJECT_JSON not in {i.filename for i in infos}:
        raise ProjectFileError("not_a_project", "there is no project.json")
    blobs, total, text = {}, 0, None
    for info in infos:
        limit = MAX_JSON_BYTES if info.filename == PROJECT_JSON else MAX_MEMBER_BYTES
        try:
            with zf.open(info) as fh:
                blob = fh.read(limit + 1)                       # the declared size may lie
        except (RuntimeError, NotImplementedError, zipfile.BadZipFile, zlib.error, EOFError, OSError) as exc:
            raise ProjectFileError("bad_zip", f"{_entry(info.filename)} cannot be read ({exc})", entry=_entry(info.filename)) from exc
        total += len(blob)
        if len(blob) > limit or total > MAX_TOTAL_BYTES:
            raise ProjectFileError("too_large", "an entry or the whole archive is beyond the limits", entry=_entry(info.filename))
        if info.filename == PROJECT_JSON:
            text = blob
        else:
            blobs[_FILE_ENTRY.fullmatch(info.filename).group(1)] = blob
    return text, blobs


def open_project(data: bytes) -> Opened:
    """The project in a `.gslp` archive, with the files it uses, all checked. Raises ProjectFileError."""
    text, blobs = _read_archive(data)
    try:
        doc = json.loads(text.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ProjectFileError("bad_json", f"project.json is not valid JSON ({exc})") from exc
    if not isinstance(doc, dict):
        raise ProjectFileError("bad_json", "project.json is not an object")
    if doc.get("format") != FORMAT:
        raise ProjectFileError("not_a_project", "project.json is not a GerberSLAp project")
    doc = migrate(doc)
    name, info = doc.pop("name", None), doc.pop("info", {})
    try:
        project, name, info = Project.model_validate(doc), _NAME.validate_python(name), _INFO.validate_python(info)
    except ValidationError as exc:
        raise ProjectFileError("invalid_project", "project.json does not describe a valid project", reason="invalid",
                               fields=[{"loc": [str(p) for p in e["loc"]][:6], "msg": e["msg"]} for e in exc.errors()[:10]]) from exc
    unknown = sorted(set(info) - {b.id for b in project.boards})
    if unknown:
        raise ProjectFileError("invalid_project", "info for a board that is not in the project", reason="unknown_board", boards=unknown[:5])
    refs = referenced_files(project)
    for sha, content in sorted(blobs.items()):
        if _sha(content) != sha:
            raise ProjectFileError("bad_hash", "a file is not what its name says", entry=f"files/{sha}")
        if sha not in refs:
            raise ProjectFileError("unreferenced_file", "a file in the archive is used by no layer", entry=f"files/{sha}")
    for sha, fname in sorted(refs.items()):
        if sha not in blobs:
            raise ProjectFileError("project_file_missing", f"{fname} is not in the archive", file=fname, sha256=sha)
    return Opened(project=project, name=name, info=info, files=blobs)


__all__ = ["BoardInfo", "FORMAT", "MIGRATIONS", "Opened", "ProjectFileError", "migrate", "open_project", "referenced_files", "save_project"]
