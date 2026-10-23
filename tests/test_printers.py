"""Printer drivers: how they are found, the LD-002H driver's image orientation, its template and settings, the file it writes
(read back and compared, identical to what pcb_ctb.py makes for the same image), and the whole chain from a board to the pixels in the
file. Tests that need the user's template (samples/speedCube.ctb, not in the repository) are skipped without it."""
import importlib
import itertools
import math
import re
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from markerboard import imported, marker_files, project_of
from PIL import Image

from gerberslap.core import Grid
from gerberslap.model import C, ExposureValues, Polarity, PrinterConfig, Recipe, Role, Side
from gerberslap.printers import (BuildError, SettingsError, TemplateError, UnknownDriver, discover, get_driver, registry)
from gerberslap.printers.base import DriverDescriptor
from gerberslap.printers.ld002h import ctbio, driver as ld
from gerberslap.services.checks import check_project
from gerberslap.services.pipeline import render

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "samples" / "speedCube.ctb"
needs_template = pytest.mark.skipif(not TEMPLATE.exists(), reason="samples/speedCube.ctb is not here (it is not in the repository)")
DRV = get_driver("ld002h")
P = 0.051
CFG = PrinterConfig(id="lab", name="LD-002H laboratorio", driver="ld002h")
POSITIVE = Recipe(id="pos35", name="Positivo", polarity="positive")


def plane_mask(*rects):
    """A plane mask (1620 rows from the back, 2560 columns from the left) lit inside the given (row0, row1, col0, col1) boxes."""
    m = np.zeros((1620, 2560), bool)
    for r0, r1, c0, c1 in rects:
        m[r0:r1, c0:c1] = True
    return m


MASK = plane_mask((100, 300, 200, 900), (800, 900, 1500, 1600), (1500, 1600, 2400, 2500))       # three boxes, none symmetric


def lit(path, i=0):
    return ctbio.CTB(str(path)).layer_image(i) > 0


# ---- how drivers are found ---------------------------------------------------------------------------------------
_counter = itertools.count()
DUMMY = '''
from gerberslap.core import Grid
from gerberslap.model import ExposureLimits, Plane
from gerberslap.printers.base import DriverDescriptor, PrinterDriver


class Dummy(PrinterDriver):
    descriptor = DriverDescriptor(id="{id}", name="Dummy", plane=Plane(width_mm=10, height_mm=10), grid=Grid(10, 10, 1.0),
                                  limits=ExposureLimits(), requires_template=False)
    def parse_settings(self, settings): return settings
    def validate_template(self, path): return None
    def check(self, exposure, config, template_path): return []
    def to_printer_image(self, mask): return mask
    def build(self, *args, **kwargs): raise NotImplementedError


DRIVER = Dummy()
'''


def fake_package(tmp_path, monkeypatch, folders):
    """A package of printers: {folder name: source of its __init__.py}. Returns the imported package."""
    name = f"fakeprinters_{next(_counter)}"
    root = tmp_path / name
    root.mkdir()
    (root / "__init__.py").write_text("")
    for folder, source in folders.items():
        (root / folder).mkdir()
        (root / folder / "__init__.py").write_text(source)
    (root / "readme.py").write_text("raise RuntimeError('a module that is not a printer must not be imported')")
    monkeypatch.syspath_prepend(str(tmp_path))
    return importlib.import_module(name)


def test_the_ld002h_driver_is_found_without_being_registered_anywhere():
    reg = discover()
    assert "ld002h" in reg.ids() and reg.problems == () and reg.get("ld002h") is DRV
    assert registry() is registry()                                            # found once, then kept


def test_a_new_printer_is_just_a_new_folder(tmp_path, monkeypatch):
    pkg = fake_package(tmp_path, monkeypatch, {"alpha": DUMMY.format(id="alpha"), "beta": DUMMY.format(id="beta")})
    reg = discover(pkg)
    assert reg.ids() == ["alpha", "beta"] and reg.problems == () and reg.get("beta").descriptor.id == "beta"


def test_a_folder_that_fails_to_load_is_reported_and_the_others_still_work(tmp_path, monkeypatch):
    pkg = fake_package(tmp_path, monkeypatch, {
        "good": DUMMY.format(id="good"), "broken": "raise RuntimeError('boom')",
        "wrongid": DUMMY.format(id="other"), "notdriver": "DRIVER = 3", "nodriver": "X = 1", "_private": "raise SystemExit",
        "duck": "class D:\n    class descriptor:\n        id = 'duck'\nDRIVER = D()"})                     # looks like a driver, is not one
    reg = discover(pkg)
    assert reg.ids() == ["good"]
    problems = {p.package: p.reason for p in reg.problems}
    assert set(problems) == {"broken", "wrongid", "notdriver", "nodriver", "duck"}
    assert "boom" in problems["broken"] and "wrongid" in problems["wrongid"] and "other" in problems["wrongid"]
    assert "PrinterDriver" in problems["notdriver"] and "PrinterDriver" in problems["duck"]


def test_an_unknown_driver_is_named():
    with pytest.raises(UnknownDriver) as e:
        get_driver("nope")
    assert "nope" in str(e.value)


@pytest.mark.parametrize("package", ["core", "model", "cad", "services"])
def test_the_generic_packages_never_name_a_printer_or_its_file_format(package):
    """The core, the model, the recognisers and the services do not know the LD-002H or the .ctb format; only a driver does."""
    pattern = re.compile(r"ctb|ld-?002h|creality", re.IGNORECASE)
    offenders = [f"{f.relative_to(REPO)}:{n}" for f in (REPO / "gerberslap" / package).rglob("*.py")
                 for n, line in enumerate(f.read_text().splitlines(), 1) if pattern.search(line)]
    assert offenders == []


def test_the_driver_interface_and_registry_do_not_name_one_either():
    pattern = re.compile(r"ctb|ld-?002h|creality", re.IGNORECASE)
    for f in (REPO / "gerberslap" / "printers" / "base.py", REPO / "gerberslap" / "printers" / "__init__.py"):
        assert not pattern.search(f.read_text()), f.name


# ---- what the driver says about itself ---------------------------------------------------------------------------
@pytest.mark.parametrize("requires, name", [(True, None), (False, "template.bin"), (True, "printer.json"), (True, "../x"), (True, ".hidden"), (True, "a/b"), (True, "")])
def test_a_descriptor_that_needs_a_template_names_a_usable_file_and_one_that_does_not_names_none(requires, name):
    d = DRV.descriptor
    with pytest.raises(ValueError):
        DriverDescriptor(id=d.id, name=d.name, plane=d.plane, grid=d.grid, limits=d.limits, requires_template=requires, template_name=name)


def test_every_driver_brings_its_picture_in_its_own_folder_as_an_upright_png():
    """Whoever adds a printer adds `printers/<id>/icon.png` with it (the page shows it on the printer's card): a PNG taller than wide, small enough to be loaded at once."""
    from PIL import Image
    reg = registry()
    assert reg.ids() and not reg.problems
    for driver_id in reg.ids():
        folder = REPO / "gerberslap" / "printers" / driver_id
        icon = reg.get(driver_id).picture_file()
        assert icon == (folder / "icon.png").resolve() and icon.is_file(), driver_id
        data = icon.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) <= 512 * 1024, driver_id                                 # a real PNG, not a big file
        with Image.open(icon) as img:
            w, h = img.size
            assert h > w and img.mode in ("RGBA", "LA", "P"), (driver_id, img.size, img.mode)                       # upright, and with room for a transparent background


def test_a_driver_that_is_not_in_its_own_folder_has_no_picture_and_neither_has_one_whose_folder_has_none(tmp_path):
    from fakeprinters import LARGE
    assert LARGE.picture_file() is None                                                                           # a driver made in a test: its module is not in a printers/<id>/ folder
    from gerberslap.web.devprinters import DEMO_SMALL
    assert DEMO_SMALL.picture_file() is None                                                                      # nor the made-up ones of --dev-printers


def test_the_picture_is_looked_for_beside_the_module_of_the_driver_and_nowhere_else(tmp_path):
    import importlib.util, sys
    folder = tmp_path / "somewhere"
    folder.mkdir()
    (folder / "drv.py").write_text("from gerberslap.printers.base import PrinterDriver\nclass D(PrinterDriver):\n    pass\nD.__abstractmethods__ = frozenset()     # only the picture is tried\n")
    spec = importlib.util.spec_from_file_location("tmp_drv_module", folder / "drv.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tmp_drv_module"] = mod
    try:
        spec.loader.exec_module(mod)
        d = object.__new__(mod.D)
        assert d.picture_file() is None                                                                           # no icon.png beside it
        (folder / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        assert d.picture_file() == (folder / "icon.png").resolve()                                                # now there is
    finally:
        sys.modules.pop("tmp_drv_module", None)


def test_the_descriptor():
    d = DRV.descriptor
    assert (d.id, d.requires_template, d.template_name) == ("ld002h", True, "template.ctb")
    assert (d.plane.width_mm, d.plane.height_mm) == (130.56, 82.62)
    assert d.grid == Grid(width=2560, height=1620, pitch=0.051)
    assert d.grid.width * d.grid.pitch == pytest.approx(d.plane.width_mm) and d.grid.height * d.grid.pitch == pytest.approx(d.plane.height_mm)
    assert (d.limits.min_flash_s, d.limits.max_proven_flash_s) == (1.0, 20.0)
    assert (ctbio.RES_X, ctbio.RES_Y) == (d.grid.height, d.grid.width)


# ---- settings ----------------------------------------------------------------------------------------------------
def test_settings_have_defaults_and_ranges():
    s = DRV.parse_settings({})
    assert (s.park_z_mm, s.start_delay_s, s.cycle_s) == (1.0, 0.0, 8.0)
    assert DRV.parse_settings(None).park_z_mm == 1.0
    assert DRV.parse_settings({"park_z_mm": 2.5, "start_delay_s": 20}).start_delay_s == 20


@pytest.mark.parametrize("raw,field", [({"park_z_mm": 0}, "park_z_mm"), ({"park_z_mm": 31}, "park_z_mm"),
                                       ({"start_delay_s": -1}, "start_delay_s"), ({"cycle_s": 0.5}, "cycle_s"),
                                       ({"park_z_mm": "high"}, "park_z_mm"), ({"surprise": 1}, "surprise")])
def test_bad_settings_are_refused_naming_the_field(raw, field):
    with pytest.raises(SettingsError) as e:
        DRV.parse_settings(raw)
    assert e.value.code == "bad_settings" and e.value.params["field"] == field


# ---- the image: the plane turned a quarter turn, never reflected -------------------------------------------------
def test_the_four_corners_of_the_plane_land_where_the_format_document_says():
    """Document: the file's top edge is the printer's left, its right edge the back, its bottom edge the right, its left edge
    the front; the top-left pixel of the file is the front-left corner of the screen."""
    m = np.zeros((1620, 2560), bool)
    m[1619, 0] = m[0, 0] = m[1619, 2559] = m[0, 2559] = True              # front-left, back-left, front-right, back-right
    img = DRV.to_printer_image(m)
    assert img.shape == (2560, 1620)
    assert img[0, 0] and img[0, 1619] and img[2559, 0] and img[2559, 1619] and np.count_nonzero(img) == 4
    back_left, front_left = (0, 1619), (0, 0)
    one = np.zeros((1620, 2560), bool)
    one[0, 0] = True
    assert np.argwhere(DRV.to_printer_image(one))[0].tolist() == list(back_left)
    one[:] = False
    one[1619, 0] = True
    assert np.argwhere(DRV.to_printer_image(one))[0].tolist() == list(front_left)


def test_it_is_a_pure_rotation_and_not_a_reflection():
    f = plane_mask((10, 60, 10, 20), (10, 20, 20, 50), (30, 40, 20, 40))                  # an F: no symmetry at all
    img = DRV.to_printer_image(f)
    assert np.array_equal(img, np.rot90(f, k=-1))                                          # a clockwise quarter turn
    assert not np.array_equal(img, f.T) and not np.array_equal(img, np.rot90(f, k=1))


def test_the_mask_must_be_the_size_of_the_plane():
    for shape in ((10, 10), (2560, 1620), (1620, 2559), (1621, 2560)):
        with pytest.raises(BuildError) as e:
            DRV.to_printer_image(np.zeros(shape, bool))
        assert e.value.code == "mask_shape" and e.value.params["expected"] == [1620, 2560]
    assert DRV.to_printer_image(np.zeros((1620, 2560), np.uint8)).dtype == bool


# ---- the template ------------------------------------------------------------------------------------------------
def variant(tmp_path, name="variant.ctb", **motion):
    """A template made from the real one with other motion (the way pcb_ctb.py's probes are made)."""
    out = tmp_path / name
    ctbio.write_ctb(str(TEMPLATE), str(out), [ctbio.Layer(np.zeros((ctbio.RES_Y, ctbio.RES_X), bool), 1.0)], park_z_mm=1.0, **motion)
    return out


@needs_template
def test_the_users_template_is_accepted_and_described():
    info = DRV.validate_template(TEMPLATE)
    assert info.layers == 400 and info.lift_mm == pytest.approx(0.001) and info.lift_speed == 500 and info.retract_speed == 500
    assert (info.rest_before_s, info.rest_after_lift_s, info.rest_after_retract_s) == (0, 0, 0)


@needs_template
@pytest.mark.parametrize("motion,reason", [(dict(lift_mm=0.0, lift_speed=500.0, retract_speed=500.0), "lift_distance_zero"),
                                           (dict(lift_mm=0.001, lift_speed=0.5, retract_speed=500.0), "lift_speed_invalid"),
                                           (dict(lift_mm=0.001, lift_speed=500.0, retract_speed=0.5), "lift_speed_invalid")])
def test_a_template_whose_motion_the_printer_would_not_follow_is_refused(tmp_path, motion, reason):
    with pytest.raises(TemplateError) as e:
        DRV.validate_template(variant(tmp_path, **motion))
    assert e.value.code == "template_invalid" and e.value.params["reason"] == reason


@needs_template
def test_files_that_are_not_templates_are_refused_with_a_reason(tmp_path):
    good = TEMPLATE.read_bytes()
    cases = {"garbage.ctb": (b"this is not a ctb file at all" * 100, {"not_a_ctb"}), "empty.ctb": (b"", {"not_a_ctb", "unreadable"}),
             "truncated.ctb": (good[: len(good) // 2], {"unreadable", "bad_crc", "undecodable"}),
             "badcrc.ctb": (good[:-1] + bytes([good[-1] ^ 0xFF]), {"bad_crc"}),
             "badversion.ctb": (good[:4] + struct.pack("<I", 4) + good[8:], {"bad_version", "bad_crc"})}
    for name, (data, reasons) in cases.items():
        (tmp_path / name).write_bytes(data)
        with pytest.raises(TemplateError) as e:
            DRV.validate_template(tmp_path / name)
        assert e.value.params["reason"] in reasons, (name, e.value.params)
    with pytest.raises(TemplateError) as e:
        DRV.validate_template(tmp_path / "missing.ctb")
    assert e.value.params["reason"] == "missing"


@needs_template
def test_the_drivers_issues_for_a_printer(tmp_path):
    assert DRV.check(None, CFG, TEMPLATE) == []
    assert [i.code for i in DRV.check(None, CFG, tmp_path / "nope.ctb")] == [C.TEMPLATE_MISSING]
    assert [i.code for i in DRV.check(None, CFG, None)] == [C.TEMPLATE_MISSING]
    (tmp_path / "junk.ctb").write_bytes(b"junk" * 50)
    (issue,) = DRV.check(None, CFG, tmp_path / "junk.ctb")
    assert (issue.code, issue.blocking, issue.params["reason"]) == (C.TEMPLATE_INVALID, True, "not_a_ctb")
    slow = DRV.check(None, CFG, variant(tmp_path, "slow.ctb", lift_mm=7.0, lift_speed=65.0, retract_speed=150.0))
    assert [(i.code, i.blocking) for i in slow] == [(C.TEMPLATE_LIFT_LARGE, False)] and slow[0].params["lift_mm"] == 7.0
    bad = DRV.check(None, CFG.model_copy(update={"settings": {"park_z_mm": 0}}), TEMPLATE)
    assert [(i.code, i.blocking, i.params["field"]) for i in bad] == [(C.PRINTER_SETTINGS_INVALID, True, "park_z_mm")]


# ---- the file ----------------------------------------------------------------------------------------------------
def build(tmp_path, mask=MASK, total=60, pulses=4, rest=5, settings=None, name="out.ctb"):
    cfg = CFG.model_copy(update={"settings": settings or {}})
    return DRV.build(mask, ExposureValues(total_s=total, pulses=pulses, rest_s=rest), cfg, TEMPLATE, tmp_path / name)


def tpl_record(i):
    t = ctbio.CTB(str(TEMPLATE))
    return ld._record(t, i)


@needs_template
def test_the_file_has_the_layers_header_and_motion_the_printer_needs(tmp_path):
    r = build(tmp_path)
    c = ctbio.CTB(str(r.path))
    expect = DRV.to_printer_image(MASK)
    assert c.crc_ok and c.layer_count == 4
    for i in range(4):
        assert np.array_equal(c.layer_image(i) > 0, expect)                               # every flash has the same image
        assert c.layers[i].z == pytest.approx(1.0) and c.layers[i].exposure == pytest.approx(15.0)
        rec = ld._record(c, i)
        assert rec[7] == 5.0 and rec[0] == pytest.approx(0.001) and rec[:7] == tpl_record(399)[:7] and rec[8:] == tpl_record(399)[8:]
    assert struct.unpack_from("<f", c.d, ctbio.H_EXP)[0] == 15.0                            # the header is what the printer reads
    assert struct.unpack_from("<I", c.d, ctbio.H_BOT_COUNT)[0] == 0
    ext2 = struct.unpack_from("<I", c.d, ctbio.H_EXT2_OFF)[0]
    assert struct.unpack_from("<f", c.d, ext2 + 24)[0] == 5.0
    pv = c.preview_image(0)
    assert max(pv.shape[:2]) == 500 and pv.max() > 200 and pv.min() < 60                    # 500 px on the long side, in two tones


@needs_template
def test_the_summary_is_numbers_for_the_interface_to_word(tmp_path):
    r = build(tmp_path, total=16, pulses=2, rest=4)
    s = r.summary
    assert r.verified and r.path == tmp_path / "out.ctb" and s.file_bytes == r.path.stat().st_size
    assert (s.layers, s.delay_layers, s.flash_s, s.rest_s, s.total_light_s) == (2, 0, 8.0, 4.0, 16.0)
    assert s.lit_pixels == int(MASK.sum()) and s.lit_area_mm2 == pytest.approx(MASK.sum() * P * P)
    assert s.estimated_s >= 16 + 8 and s.details["park_z_mm"] == 1.0 and s.details["template"] == "speedCube.ctb"
    assert s.details["lift_mm"] == pytest.approx(0.001)


def cli(tmp_path, img, total, pulses, rest, *extra):
    png = tmp_path / "board.png"
    Image.fromarray(img.astype(np.uint8) * 255).save(png)
    out = tmp_path / "cli.ctb"
    run = subprocess.run([sys.executable, str(REPO / "gerberslap" / "printers" / "ld002h" / "docs" / "pcb_ctb.py"), "png", str(png), "-t", str(TEMPLATE), "-o", str(out), "--dpi",
                          repr(25.4 / 0.051), "--exposure", str(total), "--pulses", str(pulses), "--rest", str(rest),
                          "--motion-from-template", *extra], capture_output=True, text=True, cwd=REPO)
    assert run.returncode == 0, run.stderr + run.stdout
    return out.read_bytes()


@needs_template
@pytest.mark.parametrize("total,pulses,rest,extra,settings", [
    (20, 1, 0, (), {}), (60, 4, 5, (), {}), (16, 2, 4, (), {}),
    (16, 2, 4, ("--park-z", "2.5"), {"park_z_mm": 2.5}),
    (16, 2, 4, ("--start-delay", "20"), {"start_delay_s": 20}),
    (30, 3, 6, ("--start-delay", "45", "--cycle-s", "10", "--park-z", "1.5"), {"start_delay_s": 45, "cycle_s": 10, "park_z_mm": 1.5})])
def test_the_file_is_identical_byte_for_byte_to_what_pcb_ctb_makes_for_the_same_image(tmp_path, total, pulses, rest, extra, settings):
    mine = build(tmp_path, total=total, pulses=pulses, rest=rest, settings=settings).path.read_bytes()
    assert mine == cli(tmp_path, DRV.to_printer_image(MASK), total, pulses, rest, *extra)


@needs_template
def test_the_start_delay_adds_black_layers_that_are_bottom_layers(tmp_path):
    r = build(tmp_path, total=16, pulses=2, rest=4, settings={"start_delay_s": 25})        # ceil(25 / (1 + 4 + 8)) = 2
    c = ctbio.CTB(str(r.path))
    assert r.summary.delay_layers == 2 and c.layer_count == 4
    assert struct.unpack_from("<I", c.d, ctbio.H_BOT_COUNT)[0] == 2 and struct.unpack_from("<f", c.d, ctbio.H_BOT_EXP)[0] == 1.0
    assert not (c.layer_image(0) > 0).any() and not (c.layer_image(1) > 0).any() and (c.layer_image(2) > 0).any()
    assert ld._record(c, 0)[:7] == tpl_record(0)[:7] and ld._record(c, 3)[:7] == tpl_record(399)[:7]      # bottom and normal motion


@needs_template
def test_the_limits_on_a_flash_are_enforced_by_the_driver_itself(tmp_path):
    with pytest.raises(BuildError) as e:
        build(tmp_path, total=8, pulses=10, rest=5)                                       # 0.8 s a flash
    assert e.value.code == "flash_below_minimum" and e.value.params["flash_s"] == pytest.approx(0.8)
    assert build(tmp_path, total=10, pulses=10, rest=5).verified                          # exactly 1 s is fine
    assert build(tmp_path, total=120, pulses=4, rest=5, name="long.ctb").verified          # over 20 s: a warning elsewhere, not a refusal


@needs_template
def test_a_mask_that_lights_nothing_is_refused(tmp_path):
    with pytest.raises(BuildError) as e:
        build(tmp_path, mask=np.zeros((1620, 2560), bool))
    assert e.value.code == "mask_all_dark" and not (tmp_path / "out.ctb").exists()


@needs_template
def test_a_printer_without_a_template_cannot_build(tmp_path):
    with pytest.raises(BuildError) as e:
        DRV.build(MASK, ExposureValues(total_s=20, pulses=1, rest_s=0), CFG, None, tmp_path / "out.ctb")
    assert e.value.code == "template_missing"
    with pytest.raises(TemplateError):
        DRV.build(MASK, ExposureValues(total_s=20, pulses=1, rest_s=0), CFG, tmp_path / "missing.ctb", tmp_path / "out.ctb")
    with pytest.raises(SettingsError):
        DRV.build(MASK, ExposureValues(total_s=20, pulses=1, rest_s=0), CFG.model_copy(update={"settings": {"park_z_mm": -1}}),
                  TEMPLATE, tmp_path / "out.ctb")
    assert list(tmp_path.iterdir()) == []


def tamper(monkeypatch, **override):
    real = ld.write_ctb

    def fake(*args, **kwargs):
        kwargs.update(override)
        return real(*args, **kwargs)
    monkeypatch.setattr(ld, "write_ctb", fake)


@needs_template
@pytest.mark.parametrize("override,reason", [(dict(header_exposure_s=99.0), "exposure"), (dict(park_z_mm=2.0), "z"),
                                             (dict(rest_override_s=9.0), "rest_before_lift"),
                                             (dict(motion_from_template=False, lift_mm=0.0), "motion"),
                                             (dict(bottom_layers=1, header_bottom_exposure_s=1.0), "bottom_exposure")])
def test_a_file_that_does_not_match_what_was_meant_is_never_delivered(tmp_path, monkeypatch, override, reason):
    out = tmp_path / "out.ctb"
    out.write_bytes(b"a good earlier file")
    tamper(monkeypatch, **override)
    with pytest.raises(BuildError) as e:
        build(tmp_path)
    assert e.value.code == "verification_failed" and e.value.params["reason"] in {reason, "bottom_count"}
    assert out.read_bytes() == b"a good earlier file"                                       # the earlier file is untouched
    assert [p.name for p in tmp_path.iterdir()] == ["out.ctb"]                              # and no temporary file is left


@needs_template
def test_a_layer_image_that_reads_back_wrong_is_caught(tmp_path, monkeypatch):
    real = ctbio.CTB.layer_image

    def wrong(self, i):
        img = real(self, i).copy()
        img[0, 0] = 127 if img[0, 0] == 0 else 0
        return img
    monkeypatch.setattr(ctbio.CTB, "layer_image", wrong)
    with pytest.raises(BuildError) as e:
        build(tmp_path)
    assert e.value.code == "verification_failed" and e.value.params["reason"] == "layer_image"
    assert list(tmp_path.iterdir()) == []


@needs_template
def test_a_failure_while_writing_leaves_nothing_behind_and_says_why(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(ld, "write_ctb", boom)
    with pytest.raises(BuildError) as e:
        build(tmp_path)
    assert e.value.code == "write_failed" and "disk full" in e.value.params["reason"] and list(tmp_path.iterdir()) == []


@needs_template
def test_a_build_replaces_an_earlier_file_only_when_it_succeeds(tmp_path):
    first = build(tmp_path, total=20, pulses=1, rest=0).path.read_bytes()
    second = build(tmp_path, total=40, pulses=2, rest=3).path.read_bytes()
    assert first != second and ctbio.CTB(str(tmp_path / "out.ctb")).layer_count == 2 and [p.name for p in tmp_path.iterdir()] == ["out.ctb"]


# ---- the whole chain: a board to the pixels in the file ----------------------------------------------------------
GRID = DRV.descriptor.grid


def file_bbox_mm(path):
    """The lit area of layer 0 in the file, as (u0, u1, v0, v1) in mm: file rows run left to right and file columns front to back."""
    rows, cols = np.nonzero(lit(path))
    return rows.min() * P, (rows.max() + 1) * P, cols.min() * P, (cols.max() + 1) * P


@needs_template
@pytest.mark.parametrize("angle,mirror,centre,size", [
    (0, False, (70.0, 48.0), (4, 2)), (0, True, (50.0, 48.0), (4, 2)), (90, False, (52.0, 50.0), (2, 4)), (90, True, (52.0, 30.0), (2, 4))])
def test_a_pad_placed_on_the_plane_ends_up_where_the_format_says_in_the_file(tmp_path, angle, mirror, centre, size):
    """The asymmetric marker, from the board's files through the pipeline and the driver into the .ctb, then decoded: the plane
    position (u from the left, v from the front) is the file's row (u) and column (v), at 51 um."""
    imp = imported(marker_files())
    proj = project_of(imp, angle=angle, mirror=mirror, on={"outline": False, "drill": False})
    rend = render(proj, imp.files, GRID, Polarity.NEGATIVE, supersample=16)
    path = DRV.build(rend.mask, ExposureValues(total_s=20, pulses=1, rest_s=0), CFG, TEMPLATE, tmp_path / "board.ctb").path
    cx, cy = centre
    u0, u1, v0, v1 = file_bbox_mm(path)
    assert (u0, u1, v0, v1) == pytest.approx((cx - size[0] / 2, cx + size[0] / 2, cy - size[1] / 2, cy + size[1] / 2), abs=1.5 * P)
    img = lit(path)
    assert img[int(cx / P), int(cy / P)]                                                   # the pad's centre is lit
    assert not img[int((130.56 - cx) / P), int(cy / P)] and not img[int(cx / P), int((82.62 - cy) / P)]      # not its reflections


@needs_template
def test_with_positive_resist_the_pad_is_the_dark_hole_in_a_lit_file(tmp_path):
    imp = imported(marker_files())
    rend = render(project_of(imp, on={"outline": False, "drill": False}), imp.files, GRID, Polarity.POSITIVE, supersample=16)
    path = DRV.build(rend.mask, ExposureValues(total_s=20, pulses=1, rest_s=0), CFG, TEMPLATE, tmp_path / "p.ctb").path
    img = lit(path)
    assert not img[int(70.0 / P), int(48.0 / P)] and img[0, 0] and img[-1, -1]
    assert np.count_nonzero(~img) == pytest.approx(8.0 / (P * P), rel=0.01)


KICAD = REPO / "experiments" / "fase2" / "external" / "kicad_uni_mosfet_key.zip"


@needs_template
@pytest.mark.skipif(not KICAD.exists(), reason="the KiCad example is not in experiments/fase2/external/")
def test_a_real_board_goes_all_the_way_into_the_file(tmp_path):
    from gerberslap.model import Project
    from gerberslap.services.importer import import_zip
    imp = import_zip(KICAD, board_id="b1", source_name=KICAD.name, plane=DRV.descriptor.plane)
    proj = Project(printer_id="lab", recipe_id="pos35", polarity=Polarity.POSITIVE, boards=(imp.board,))
    exposure = ExposureValues(total_s=80, pulses=4, rest_s=5)
    issues = check_project(proj, plane=DRV.descriptor.plane, printer=CFG, recipe=POSITIVE, exposure=exposure,
                           limits=DRV.descriptor.limits)
    assert issues == []                                                                       # the two masks are usable now, and off
    rend = render(proj, imp.files, GRID, POSITIVE.polarity, supersample=16)
    r = DRV.build(rend.mask, exposure, CFG, TEMPLATE, tmp_path / "kicad.ctb")
    c = ctbio.CTB(str(r.path))
    assert c.layer_count == 4 and r.summary.lit_pixels == rend.lit_pixels
    for i in range(4):
        assert np.array_equal(c.layer_image(i) > 0, DRV.to_printer_image(rend.mask))      # the file holds exactly the mask, rotated


@needs_template
@pytest.mark.skipif(not KICAD.exists(), reason="the KiCad example is not in experiments/fase2/external/")
def test_the_solder_mask_of_a_real_board_goes_all_the_way_into_the_file(tmp_path):
    """The mask exposed as a negative-acting one lights the board except its openings; the openings are where KiCad says."""
    from gerberslap.core import area_or_rectangle, layer_geometry, read_file
    from gerberslap.model import Project
    from gerberslap.services.importer import import_zip
    from gerberslap.services.pipeline import PipelineCache, Reader
    imp = import_zip(KICAD, board_id="b1", source_name=KICAD.name, plane=DRV.descriptor.plane)
    b = imp.board
    layers = tuple(l.model_copy(update={"on": l.role is Role.MASK and l.side is Side.TOP}) for l in b.layers)
    board = b.model_copy(update={"layers": layers})
    proj = Project(printer_id="lab", recipe_id="mask", polarity=Polarity.NEGATIVE, boards=(board,))
    rend = render(proj, imp.files, GRID, Polarity.NEGATIVE, supersample=16)
    c = ctbio.CTB(str(DRV.build(rend.mask, ExposureValues(total_s=40, pulses=2, rest_s=5), CFG, TEMPLATE, tmp_path / "mask.ctb").path))
    assert np.array_equal(c.layer_image(0) > 0, DRV.to_printer_image(rend.mask))

    reader = Reader(imp.files, PipelineCache())
    outline = next(l for l in b.layers if l.role is Role.OUTLINE)
    mask_layer = next(l for l in layers if l.on)
    area, why = area_or_rectangle(reader.read(outline.files[0]).file, size=(b.size.width_mm, b.size.height_mm), center=b.source_center)
    drawn = layer_geometry(reader.read(mask_layer.files[0]).file)
    assert why is None
    assert rend.lit_pixels * P * P == pytest.approx(area.difference(drawn).area, rel=0.004)

    def pixel(pt):                                                                              # a point of the file -> the plane -> the mask
        x, y = pt.x - b.source_center[0] + b.placement.x, pt.y - b.source_center[1] + b.placement.y
        col, row = GRID.to_pixel(x, y)
        return rend.mask[int(row), int(col)]
    openings = sorted(drawn.geoms, key=lambda g: -g.area)[:6]
    assert openings and not any(pixel(g.representative_point()) for g in openings)              # the openings are dark
    solid = area.difference(drawn.buffer(0.3))
    assert pixel(solid.representative_point())                                                  # and the mask between them is lit


@needs_template
def test_the_checks_use_what_the_driver_declares(tmp_path):
    imp = imported(marker_files())
    proj = project_of(imp)
    long_flash = ExposureValues(total_s=100, pulses=2, rest_s=5)                            # 50 s a flash
    issues = check_project(proj, plane=DRV.descriptor.plane, printer=CFG, recipe=POSITIVE, exposure=long_flash, limits=DRV.descriptor.limits)
    assert [i.code for i in issues] == [C.FLASH_BEYOND_PROVEN]
    short = ExposureValues(total_s=5, pulses=10, rest_s=5)
    issues = check_project(proj, plane=DRV.descriptor.plane, printer=CFG, recipe=POSITIVE, exposure=short, limits=DRV.descriptor.limits)
    assert [(i.code, i.blocking) for i in issues] == [(C.FLASH_BELOW_MINIMUM, True)]
