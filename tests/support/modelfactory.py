"""Small builders for model objects in tests: a board that is valid by default, changed one field at a time."""
from gerberslap.model import (Board, BoardPlacement, ExposureValues, FileRef, Layer, LayerStatus, Plane, PrinterConfig,
                              Project, Recipe, Role, Size)

PLANE = Plane(width_mm=130.56, height_mm=82.62)         # the LD-002H, but any plane would do
H = "ab" * 32                                           # a stand-in for a sha256


def layer(id="copper", role=Role.COPPER, on=True, status=None, files=None, **kw):
    return Layer(id=id, role=role, name=kw.pop("name", f"{id}.gbr"), on=on,
                 files=files if files is not None else (FileRef(name=f"{id}.gbr", sha256=H),),
                 status=status or LayerStatus(), **kw)


def default_layers():
    return (layer("copper", Role.COPPER), layer("outline", Role.OUTLINE),
            layer("mask", Role.MASK, on=False), layer("silk", Role.SILK, on=False),
            layer("drill", Role.DRILL, files=(FileRef(name="pth.drl", sha256=H), FileRef(name="npth.drl", sha256=H))))


def board(id="b1", x=65.0, y=41.0, w=80.0, h=50.0, angle=0.0, mirror=False, layers=None, name=None, **kw):
    return Board(id=id, name=name or id, size=Size(width_mm=w, height_mm=h),
                 placement=BoardPlacement(x=x, y=y, angle=angle, mirror=mirror),
                 layers=layers if layers is not None else default_layers(), **kw)


def project(*boards, **kw):
    kw.setdefault("printer_id", "lab")
    kw.setdefault("recipe_id", "pos35")
    return Project(boards=boards or (board(),), **kw)


PRINTER = PrinterConfig(id="lab", name="LD-002H laboratorio", driver="ld002h")
POSITIVE = Recipe(id="pos35", name="Positivo, rame 35 µm", polarity="positive")
NEGATIVE = Recipe(id="negdf", name="Negativo, dry film", polarity="negative")
EXPOSURE = ExposureValues(total_s=80, pulses=4, rest_s=5)
