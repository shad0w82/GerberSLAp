"""KiCad: Gerber X2 with `TF.GenerationSoftware,KiCad,...` and names like `board-F_Cu.gbr`, `board-Edge_Cuts.gbr`."""
from .base import Recognizer
from .generic import normalise, _tok
from .sniff import software

_NAMES = _tok(r"f_cu|b_cu|edge_cuts|f_mask|b_mask|f_silkscreen|b_silkscreen|in\d+_cu")


class KicadRecognizer(Recognizer):
    name = "kicad"

    def score(self, probes) -> float:
        if "kicad" in software(probes):
            return 1.0
        hits = sum(1 for p in probes if _NAMES.search(normalise(p.basename)))
        return .8 if hits >= 2 else 0.0
