"""Regression of ctbio.py: rebuilding samples/boxsmall.ctb from its own pixels and parameters must
differ in exactly 18 bytes (resin estimates zeroed on purpose and three Z values rounded differently)."""
import os

import pytest

SRC = os.path.join(os.path.dirname(__file__), "..", "samples", "boxsmall.ctb")


@pytest.mark.skipif(not os.path.exists(SRC), reason="samples/boxsmall.ctb is not in the repository (copyright)")
def test_boxsmall_rebuild_differs_in_18_bytes(tmp_path):
    from gerberslap.printers.ld002h.ctbio import CTB, Layer, write_ctb
    s = CTB(SRC)
    layers = [Layer(s.layer_image(i), s.layers[i].exposure) for i in range(s.layer_count)]
    out = str(tmp_path / "boxsmall_rebuilt.ctb")
    write_ctb(SRC, out, layers, layer_height_mm=0.05, lift_mm=7.0, bottom_lift_mm=6.0, lift_speed=65,
              retract_speed=150, rest_before_lift_s=1.5, rest_after_lift_s=2.5, rest_after_retract_s=3.5,
              bottom_layers=2)
    a, b = open(SRC, "rb").read(), open(out, "rb").read()
    assert len(a) == len(b)
    assert sum(1 for i in range(len(a) - 4) if a[i] != b[i]) == 18
