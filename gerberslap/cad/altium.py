"""Altium Designer: names like `Project_Copper_Signal_Top.gbr`, `_Legend_Top`, `_Soldermask_Top`, `_Profile` (or the Protel
extensions .GTL .GBL .GKO...). The files carry `TF.GenerationSoftware,Altium...` and `TF.FilePolarity`, but not
`TF.FileFunction`, so the role comes from the name. Layers drawn as negative images (the planes, and the masks as
openings) say so in `FilePolarity`."""
from .base import Recognizer
from .generic import normalise, _tok
from .sniff import software

_NAMES = _tok(r"copper_signal_\w+|copper_plane_\d+|legend_top|legend_bot(tom)?|soldermask_top|soldermask_bot(tom)?|profile")
_EXTRA = _tok(r"extrep|rep|apr|apr_lib|gko|gm1|gd1|gg1")


class AltiumRecognizer(Recognizer):
    name = "altium"

    def score(self, probes) -> float:
        if "altium" in software(probes):
            return 1.0
        names = [normalise(p.basename) for p in probes]
        if sum(1 for n in names if _NAMES.search(n)) >= 3:
            return .8
        return .5 if sum(1 for n in names if _EXTRA.search(n)) >= 2 else 0.0
