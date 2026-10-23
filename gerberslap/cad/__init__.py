"""Recognising what the files of a zip are, and which program made them. One module per program (a recogniser that can
refuse an unsupported export and say how likely a program is), and the shared conventions in `generic`."""
from typing import Mapping

from .altium import AltiumRecognizer
from .base import Assignment, ImportRefused, Incompatible, Probe, Recognition, Recognizer
from .eagle import EagleRecognizer
from .generic import GenericRecognizer, classify
from .kicad import KicadRecognizer
from .sniff import probe

# order is the order of preference when two programs score the same: the specific before the generic
RECOGNIZERS = (KicadRecognizer(), AltiumRecognizer(), EagleRecognizer(), GenericRecognizer())


def recognize(members: Mapping) -> Recognition:
    """`members`: file name -> bytes, as `core.zip_members` returns. Raises Incompatible for an export that is not
    supported; otherwise assigns every file a role, and names the program that most likely made them."""
    probes = [probe(name, data) for name, data in members.items()]
    for r in RECOGNIZERS:
        r.check(probes)
    scores = [(r.score(probes), -i, r) for i, r in enumerate(RECOGNIZERS)]
    score, _, best = max(scores, key=lambda t: (t[0], t[1]))
    return Recognition(cad=best.name, score=score, assignments=tuple(classify(p) for p in probes),
                       info=best.info(probes, members))


__all__ = ["Assignment", "ImportRefused", "Incompatible", "Probe", "Recognition", "Recognizer", "RECOGNIZERS", "recognize",
           "classify", "probe"]
