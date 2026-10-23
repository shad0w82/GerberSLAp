"""A small board with a known shape, to pin down where things land: an outline 40 x 30 mm and one 4 x 2 mm pad, off centre."""
import io
import zipfile

import testdata

from gerberslap.model import BoardPlacement, Plane, Project
from gerberslap.services.importer import import_zip

PLANE = Plane(width_mm=130.56, height_mm=82.62)


def make_zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


OUTLINE_BODY = [testdata.move(10, 5), testdata.draw(50, 5), testdata.draw(50, 35), testdata.draw(10, 35), testdata.draw(10, 5)]
CUTOUT = [testdata.move(22, 20), *testdata.arc(22, 20, 22, 20, 20, 20)]                  # a circle of 2 mm radius at (20, 20): 10 mm left of the centre


def marker_files(hole=False, mask=False, cutout=False, open_outline=False):
    """Outline 40 x 30 mm (10..50, 5..35: centre 30, 20) and one 4 x 2 mm pad at (40, 28): 10 mm right of and 8 mm above the centre.

    `mask` adds a solder mask whose one opening is 6 x 4 mm around the pad (a mask file draws the openings); `cutout` a 2 mm radius
    circle drawn in the outline at (20, 20); `open_outline` leaves the last side of the outline out; `hole`, a hole of 1 mm at the pad."""
    body = OUTLINE_BODY[:-1] if open_outline else OUTLINE_BODY
    outline = testdata.gerber("Profile,NP", ["D10*", *body, *(CUTOUT if cutout else [])], ["%ADD10C,0.100000*%"])
    copper = testdata.gerber("Copper,L1,Top", ["D10*", testdata.flash(40, 28)], ["%ADD10R,4.000000X2.000000*%"])
    files = {"b-F_Cu.gbr": copper, "b-Edge_Cuts.gbr": outline}
    if mask:
        files["b-F_Mask.gbr"] = testdata.gerber("Soldermask,Top", ["D10*", testdata.flash(40, 28)], ["%ADD10R,6.000000X4.000000*%"])
    if hole:
        files["b-PTH.drl"] = testdata.excellon("Plated,1,2,PTH", {1: 1.0}, [(1, 40.0, 28.0)])
    return files


def imported(files, **kw):
    return import_zip(make_zip(files), board_id=kw.pop("board_id", "b1"), source_name="b.zip", plane=PLANE, **kw)


def project_of(imp, *, centre=(60.0, 40.0), angle=0.0, mirror=False, on=None, min_outline=0.3, extra=()):
    """The imported board at the given placement, with layers switched on or off by role ('copper', 'outline', 'drill', ...)."""
    on = on or {}
    layers = tuple(l.model_copy(update={"on": on.get(l.role.value, l.on) and l.status.level != "error"}) for l in imp.board.layers)
    board = imp.board.model_copy(update={"layers": layers, "placement": BoardPlacement(x=centre[0], y=centre[1], angle=angle, mirror=mirror)})
    return Project(printer_id="lab", recipe_id="pos35", min_outline_mm=min_outline, boards=(board, *extra))
