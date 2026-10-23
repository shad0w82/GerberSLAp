"""Reading Gerber and Excellon files (with gerbonara) and unpacking zip archives safely.

gerbonara 1.6.3 has two defects that matter to us, fixed here:
  - step-and-repeat blocks are never expanded (an empty list is "false" in `if self.step_repeat_objects:`);
  - aperture macro primitive 22 (deprecated "lower-left line") is rejected, and 2 (old name of 20) is unknown.
Each fix has a test; a gerbonara version other than the tested one triggers a warning.
"""
import contextlib
import io
import threading
import warnings
import zipfile
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import PurePosixPath

from gerbonara import ExcellonFile, GerberFile, rs274x
from gerbonara.aperture_macros import primitive as _mp

from .errors import GerberError

TESTED_GERBONARA = "1.6.3"
MAX_MEMBERS = 500
MAX_MEMBER_BYTES = 64 * 2**20
MAX_TOTAL_BYTES = 200 * 2**20

# catch_warnings and redirect_stdout change process-wide state, so parsing is serialised
LOCK = threading.RLock()


# --- fixes to gerbonara -------------------------------------------------------------------------
class _SRList(list):
    """Always truthy: gerbonara tests `if self.step_repeat_objects:`, false for the empty list at block start,
    so no object inside an SR block was ever replicated."""

    def __bool__(self):
        return True


class _FixedParser(rs274x.GerberParser):
    @property
    def step_repeat_objects(self):
        return self._sro

    @step_repeat_objects.setter
    def step_repeat_objects(self, value):
        self._sro = None if value is None else _SRList(value)


class _LowerLeftLine:
    """Macro primitive 22 (rectangle given by its lower-left corner) is primitive 21 with the centre moved."""

    @classmethod
    def from_arglist(cls, unit, arglist):
        e, w, h, x, y, *rot = arglist                      # already parsed expressions, not strings
        return _mp.CenterLine.from_arglist(unit, [e, w, h, x + w * 0.5, y + h * 0.5, *rot])


def _apply_fixes():
    rs274x.GerberParser = _FixedParser
    _mp.PRIMITIVE_CLASSES.setdefault(22, _LowerLeftLine)
    _mp.PRIMITIVE_CLASSES.setdefault(2, _mp.VectorLine)


_apply_fixes()
if version("gerbonara") != TESTED_GERBONARA:
    warnings.warn(f"gerbonara {version('gerbonara')} is not the tested version {TESTED_GERBONARA}: "
                  "the local fixes and the geometry tests have not been checked against it")


# --- reading ----------------------------------------------------------------------------------
@dataclass(frozen=True)
class ReadResult:
    name: str
    kind: str                 # "gerber" or "excellon"
    file: object              # gerbonara GerberFile / ExcellonFile
    warnings: tuple           # parser warnings, to show to the user


def sniff_kind(data):
    """'excellon' if an M48 header line appears in the first lines, else 'gerber'."""
    text = data.decode("utf-8", errors="replace") if isinstance(data, (bytes, bytearray)) else data
    for line in text.splitlines()[:30]:
        if line.strip() == "M48":
            return "excellon"
    return "gerber"


def read_file(name, data):
    """Parse one Gerber or Excellon file given as bytes. Raises GerberError (naming the file) on any failure."""
    text = data.decode("utf-8-sig", errors="replace") if isinstance(data, (bytes, bytearray)) else data
    kind = sniff_kind(text)
    with LOCK, warnings.catch_warnings(record=True) as caught, contextlib.redirect_stdout(io.StringIO()):
        warnings.simplefilter("always")
        try:
            if kind == "excellon":
                parsed = ExcellonFile.from_string(text, filename=name)
            else:
                parsed = GerberFile.from_string(text, filename=name)
        except Exception as e:                              # noqa: BLE001 - every parser error must name the file
            raise GerberError(name, f"{type(e).__name__}: {e}") from e
    return ReadResult(name, kind, parsed, tuple(sorted({str(w.message) for w in caught})))


# --- zip archives -----------------------------------------------------------------------------
@dataclass(frozen=True)
class ZipContents:
    members: dict             # name -> bytes, only real design files
    skipped: tuple            # names ignored (macOS resource forks, hidden files, unsafe paths)


def _is_junk(name):
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if not parts or parts[0] == "/" or ".." in parts:
        return True                                           # absolute or escaping path
    return any(p == "__MACOSX" or p.startswith(".") or p.lower() == "thumbs.db" for p in parts)


def zip_members(source):
    """Read an archive (path or bytes) into memory, skipping `__MACOSX/`, `._*`, `.DS_Store` and other hidden
    files. Nothing is extracted to disk. Raises GerberError for invalid or oversized archives."""
    label = str(source) if isinstance(source, (str, PurePosixPath)) or hasattr(source, "__fspath__") else "archive"
    try:
        zf = zipfile.ZipFile(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source)
    except (zipfile.BadZipFile, OSError) as e:
        raise GerberError(label, f"not a valid zip archive ({e})", code="bad_zip") from e
    members, skipped = {}, []
    infos = [i for i in zf.infolist() if not i.is_dir()]
    for info in infos:
        if _is_junk(info.filename):
            skipped.append(info.filename)
    keep = [i for i in infos if i.filename not in skipped]
    if len(keep) > MAX_MEMBERS or sum(i.file_size for i in keep) > MAX_TOTAL_BYTES:
        raise GerberError(label, "archive too large", code="too_large")
    for info in keep:
        with zf.open(info) as fh:
            blob = fh.read(MAX_MEMBER_BYTES + 1)              # the declared size may lie
        if len(blob) > MAX_MEMBER_BYTES:
            raise GerberError(info.filename, "file too large", code="too_large")
        members[info.filename] = blob
    return ZipContents(members, tuple(skipped))
