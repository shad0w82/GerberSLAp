"""What a recogniser works with and returns. A recogniser looks at the files of a zip and says which program made
them, and what each file is (copper, outline, holes...). It never reads geometry: that is the importer's job."""
from dataclasses import dataclass, field
from typing import Mapping, Optional

from ..model import Role, Side


class ImportRefused(Exception):
    """The zip cannot be used. `code` and `params` are for the interface, which owns the wording."""
    code = "import_refused"

    def __init__(self, detail="", *, code=None, params=None):
        super().__init__(detail or (code or self.code))
        self.detail = detail
        if code:
            self.code = code
        self.params = dict(params or {})


class Incompatible(ImportRefused):
    """The export comes from a program or a version the app does not support."""
    code = "incompatible_export"


@dataclass(frozen=True)
class Probe:
    """What can be known about a file from its first bytes, without parsing it."""
    name: str                       # the member's name in the zip
    basename: str
    kind: str                       # "gerber", "excellon" or "other" (a report, a pick-and-place list, a job file...)
    head: str                       # the first characters, decoded leniently
    attributes: Mapping             # X2 attributes by name: {"FileFunction": ("Copper", "L1", "Top"), ...}
    negative: bool                  # the file is a negative image (FilePolarity,Negative or the old IPNEG)
    inline_name: Optional[str]      # the layer name written inside the file by %IN...*% (EAGLE does)


@dataclass(frozen=True)
class Assignment:
    name: str
    role: Role
    side: Side
    confidence: float               # 1.0: stated in the file (X2); about 0.9: a clear name; lower: a guess
    reason: str                     # a code: "x2", "name:f_cu", "ext:gtl", "content:excellon", "not_gerber", "unknown"
    kind: str                       # as in Probe
    plated: Optional[bool] = None   # for drill files, when known
    negative: bool = False


@dataclass(frozen=True)
class Recognition:
    cad: str                        # "kicad", "altium", "eagle" or "generic"
    score: float
    assignments: tuple
    info: Mapping = field(default_factory=dict)      # e.g. {"software": "KiCad", "job_size_mm": (172.0, 112.0)}


class Recognizer:
    """One per program. `check` may refuse an export outright; `score` says how likely it is that this program made it."""
    name = "generic"

    def check(self, probes) -> None:
        return None

    def score(self, probes) -> float:
        return 0.0

    def info(self, probes, members) -> Mapping:
        from .jobfile import job_info
        return job_info(probes, members)
