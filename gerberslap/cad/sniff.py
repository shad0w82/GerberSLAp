"""Looking at what a file is from its first bytes: Gerber, Excellon or neither, and what it says about itself."""
import re
from pathlib import PurePosixPath

from ..core import sniff_kind
from .base import Probe

HEAD_BYTES = 64 * 1024

# X2 attributes appear as %TF.Name,v1,v2*%, as Gerber comments "G04 #@! TF.Name,v1,v2*", and in Excellon comments
# "; #@! TF.Name,v1,v2"
_TF = re.compile(r"(?:%|G04[ \t]*#@![ \t]*|;[ \t]*#@![ \t]*)TF\.(\w+),([^*%\r\n]*)")
_FORMAT = re.compile(r"%FS[LT]?[AI]X\d\dY\d\d\*%")
_IPNEG = re.compile(r"%IPNEG\*%")
_IN = re.compile(r"%IN([^*%\r\n]*)\*%")


def attributes(text: str) -> dict:
    out = {}
    for m in _TF.finditer(text):
        out.setdefault(m.group(1), tuple(v.strip() for v in m.group(2).split(",")))
    return out


def probe(name: str, data: bytes) -> Probe:
    head = data[:HEAD_BYTES].decode("utf-8-sig", errors="replace")
    attrs = attributes(head)
    if sniff_kind(head) == "excellon":
        kind = "excellon"
    elif _FORMAT.search(head):
        kind = "gerber"                              # a format statement is what makes a file RS-274X
    else:
        kind = "other"
    negative = bool(_IPNEG.search(head)) or (attrs.get("FilePolarity", ("",))[0].lower() == "negative")
    m = _IN.search(head)
    return Probe(name=name, basename=PurePosixPath(name.replace("\\", "/")).name, kind=kind, head=head,
                 attributes=attrs, negative=negative, inline_name=(m.group(1).strip() or None) if m else None)


def software(probes) -> str:
    """What the files say generated them, lower-cased, for the recognisers to look at."""
    found = []
    for p in probes:
        found.extend(p.attributes.get("GenerationSoftware", ()))
        first = next((l for l in p.head.splitlines()[:8] if l.startswith("G04")), "")
        found.append(first)
        if p.basename.lower().endswith(".gbrjob"):
            found.append(p.head[:2000])
    return " ".join(found).lower()
