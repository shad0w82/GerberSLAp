"""Opening a zip: the board it makes, what is switched on, what is marked as unusable and why, and what is refused. Synthetic
KiCad-style zips cover the edge cases; the three real samples (Altium, EAGLE 9, the old EAGLE) are checked end to end."""
import io
import zipfile
from pathlib import Path

import pytest
import testdata
from markerboard import marker_files

from gerberslap.cad import ImportRefused, Incompatible
from gerberslap.core import GerberError
from gerberslap.model import Board, C, LC, Plane, Role, Side
from gerberslap.services.importer import DRILL_MARGIN_MM, import_zip

PLANE = Plane(width_mm=130.56, height_mm=82.62)


def make_zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


@pytest.fixture(scope="module")
def synth():
    files, refs = testdata.synth_board()
    return files, refs


def board_of(files, **kw):
    return import_zip(make_zip(files), board_id="b1", source_name="my_board.zip", plane=PLANE, **kw)


def layers_by_name(imp):
    return {l.name: l for l in imp.board.layers}


def codes(imp):
    return [i.code for i in imp.issues]


# ---- a clean KiCad-style board -----------------------------------------------------------------------------------
def test_a_kicad_style_zip_becomes_a_board(synth):
    files, refs = synth
    imp = board_of(files)
    b = imp.board
    assert imp.cad == "kicad" and imp.issues == () and imp.skipped == ()
    assert (b.size.width_mm, b.size.height_mm) == pytest.approx((80, 50), abs=1e-6)       # the outline's centre line
    assert b.source_center == pytest.approx((50, 35), abs=1e-6)
    assert b.name == "my_board" and b.source == "my_board.zip" and b.id == "b1"
    assert (b.placement.x, b.placement.y, b.placement.angle, b.placement.mirror) == (65.28, 41.31, 0.0, False)


def test_what_is_on_when_a_zip_is_opened(synth):
    imp = board_of(synth[0])
    on = {l.name for l in imp.board.layers if l.on}
    assert on == {"F_Cu.gbr", "Edge_Cuts.gbr", "PTH.drl + NPTH.drl"}                     # copper, outline and holes
    off = layers_by_name(imp)
    assert not off["F_Silkscreen.gbr"].on and not off["F_Mask.gbr"].on


def test_the_two_drill_files_make_one_holes_layer(synth):
    imp = board_of(synth[0])
    drill = [l for l in imp.board.layers if l.role is Role.DRILL]
    assert len(drill) == 1 and [f.name for f in drill[0].files] == ["PTH.drl", "NPTH.drl"]
    assert drill[0].status.level == "ok" and drill[0].draws is False


def test_the_mask_is_read_and_usable_but_starts_off(synth):
    mask = layers_by_name(board_of(synth[0]))["F_Mask.gbr"]
    assert (mask.role, mask.status.level, mask.on) == (Role.MASK, "ok", False)


# ---- the order the layers start in -------------------------------------------------------------------------------
def full_stack():
    """Every layer of a four-layer board, written in the wrong order on purpose; the inner layers are named so that a plain sort
    would put In10 before In2."""
    def gbr(function):
        return testdata.gerber(function, ["D10*", testdata.flash(20, 20)], ["%ADD10C,1.000000*%"])
    outline = testdata.gerber("Profile,NP", ["D10*", testdata.move(10, 5), testdata.draw(50, 5), testdata.draw(50, 35),
                                             testdata.draw(10, 35), testdata.draw(10, 5)], ["%ADD10C,0.100000*%"])
    return {"b-Edge_Cuts.gbr": outline, "b-B_Silkscreen.gbr": gbr("Legend,Bot"), "b-B_Mask.gbr": gbr("Soldermask,Bot"),
            "b-B_Cu.gbr": gbr("Copper,L12,Bot"), "b-In10_Cu.gbr": gbr("Copper,L11,Inr"), "b-In2_Cu.gbr": gbr("Copper,L3,Inr"),
            "b-In1_Cu.gbr": gbr("Copper,L2,Inr"), "b-F_Cu.gbr": gbr("Copper,L1,Top"), "b-F_Mask.gbr": gbr("Soldermask,Top"),
            "b-F_Silkscreen.gbr": gbr("Legend,Top"), "b-PTH.drl": testdata.excellon("Plated,1,12,PTH", {1: 1.0}, [(1, 20.0, 20.0)])}


def test_the_layers_start_in_the_order_of_the_stack_from_the_top_down():
    names = [l.name for l in board_of(full_stack()).board.layers]
    assert names == ["b-F_Silkscreen.gbr", "b-F_Mask.gbr", "b-F_Cu.gbr",               # the top side
                     "b-In1_Cu.gbr", "b-In2_Cu.gbr", "b-In10_Cu.gbr",                  # the inner copper, 10 after 2
                     "b-B_Cu.gbr", "b-B_Mask.gbr", "b-B_Silkscreen.gbr",               # the bottom side
                     "b-Edge_Cuts.gbr", "b-PTH.drl"]                                  # apart from the stack: outline, then the holes


def test_that_order_does_not_depend_on_the_order_of_the_files_in_the_zip():
    files = full_stack()
    reverse = dict(reversed(list(files.items())))
    assert [l.name for l in board_of(files).board.layers] == [l.name for l in board_of(reverse).board.layers]


# ---- the solder mask ---------------------------------------------------------------------------------------------
def marker(**kw):
    """The marker board (40 x 30 mm outline, a 6 x 4 mm opening in the mask) as a zip."""
    return board_of(marker_files(**kw))


def mask_of(imp):
    return next(l for l in imp.board.layers if l.role is Role.MASK)


def test_a_mask_declared_negative_is_not_refused_for_that():
    files = marker_files(mask=True)
    files["b-F_Mask.gbr"] = "%TF.FilePolarity,Negative*%\n" + files["b-F_Mask.gbr"]
    assert mask_of(board_of(files)).status.level == "ok"                      # a mask draws its openings, whatever the file says


def test_a_negative_copper_layer_is_still_refused():
    files = marker_files(mask=True)
    files["b-F_Cu.gbr"] = "%TF.FilePolarity,Negative*%\n" + files["b-F_Cu.gbr"]
    copper = next(l for l in board_of(files).board.layers if l.role is Role.COPPER)
    assert (copper.status.level, copper.status.code) == ("error", LC.NEGATIVE_IMAGE)


def test_a_mask_that_draws_most_of_the_board_is_a_warning_with_the_share():
    files = marker_files(mask=True)
    files["b-F_Mask.gbr"] = testdata.gerber("Soldermask,Top", ["D10*", testdata.flash(30, 20)], ["%ADD10R,36.000000X26.000000*%"])
    m = mask_of(board_of(files))
    assert (m.status.level, m.status.code, m.status.params) == ("warning", LC.MASK_COVERS_BOARD, {"percent": 78})     # 936 of 1200 mm2
    assert not m.on


def test_a_normal_mask_is_not_flagged():
    assert mask_of(marker(mask=True)).status.level == "ok"                    # 24 of 1200 mm2


def test_a_mask_that_cannot_be_read_has_an_error_and_stays_off():
    files = marker_files(mask=True)
    files["b-F_Mask.gbr"] = "%FSLAX46Y46*%\n%MOMM*%\n%ADD10NOSUCHMACRO,1.0X2.0*%\nD10*\nX1000000Y1000000D03*\nM02*\n"
    m = mask_of(board_of(files))
    assert (m.status.level, m.status.code, m.on) == ("error", LC.UNREADABLE, False) and "NOSUCHMACRO" in m.status.params["reason"]


def estimates(files):
    return [i for i in board_of(files).issues if i.code == C.BOARD_AREA_ESTIMATED]


def test_a_mask_with_an_open_outline_says_the_rectangle_is_used():
    est = estimates(marker_files(mask=True, open_outline=True))
    assert len(est) == 1 and est[0].params == {"reason": "not_closed"} and est[0].board_id == "b1" and est[0].severity.value == "warning"


def test_a_mask_with_no_outline_file_says_the_rectangle_is_used():
    files = marker_files(mask=True)
    del files["b-Edge_Cuts.gbr"]
    est = estimates(files)
    assert len(est) == 1 and est[0].params == {"reason": "no_outline"}


def test_no_estimate_is_reported_when_the_outline_closes_or_when_there_is_no_mask():
    assert C.BOARD_AREA_ESTIMATED not in codes(marker(mask=True))
    assert C.BOARD_AREA_ESTIMATED not in codes(marker(open_outline=True))     # without a mask the area is not used
    assert C.BOARD_AREA_ESTIMATED not in codes(marker(mask=True, cutout=True))


def test_layers_come_in_the_default_order_and_ids_are_valid_and_unique(synth):
    imp = board_of(synth[0])
    assert [l.role for l in imp.board.layers] == [Role.SILK, Role.MASK, Role.COPPER, Role.OUTLINE, Role.DRILL]
    ids = [l.id for l in imp.board.layers]
    assert len(set(ids)) == len(ids)
    assert Board.model_validate_json(imp.board.model_dump_json()) == imp.board


def test_the_files_are_returned_for_the_cache_by_hash(synth):
    import hashlib
    files, _ = synth
    imp = board_of(files)
    assert set(imp.files) == {hashlib.sha256(t.encode()).hexdigest() for t in files.values()}
    for layer in imp.board.layers:
        for f in layer.files:
            assert hashlib.sha256(imp.files[f.sha256]).hexdigest() == f.sha256


def test_placement_defaults_and_options(synth):
    files, _ = synth
    mirrored = import_zip(make_zip(files), board_id="b2", plane=PLANE, mirror=True)
    assert mirrored.board.placement.mirror is True and mirrored.board.source is None and mirrored.board.name == "board"
    bare = import_zip(make_zip(files), board_id="b3", name="  my plate  ")
    assert (bare.board.placement.x, bare.board.placement.y) == (0.0, 0.0) and bare.board.name == "my plate"


def test_a_path_works_as_well_as_bytes(synth, tmp_path):
    p = tmp_path / "board.zip"
    p.write_bytes(make_zip(synth[0]))
    assert import_zip(p, board_id="b1", source_name="board.zip").board.size.width_mm == pytest.approx(80)


# ---- the board's size ---------------------------------------------------------------------------------------------
def test_without_an_outline_the_size_comes_from_the_copper_and_it_is_said(synth):
    files, refs = synth
    imp = board_of({k: v for k, v in files.items() if k != "Edge_Cuts.gbr"})
    minx, miny, maxx, maxy = refs["copper"].bounds
    assert (imp.board.size.width_mm, imp.board.size.height_mm) == pytest.approx((maxx - minx, maxy - miny), abs=1e-3)
    assert C.NO_OUTLINE in codes(imp)


def test_the_board_size_does_not_depend_on_which_layers_are_on(synth):
    imp = board_of(synth[0])
    again = Board.model_validate(imp.board.model_copy(update={"layers": tuple(l.model_copy(update={"on": False}) for l in imp.board.layers)}).model_dump())
    assert again.size == imp.board.size and again.source_center == imp.board.source_center


def test_a_zip_with_no_geometry_at_all_is_refused(synth):
    files, _ = synth
    empty = "%TF.FileFunction,Copper,L1,Top*%\n%FSLAX46Y46*%\n%MOMM*%\nM02*\n"
    with pytest.raises(ImportRefused) as e:
        board_of({"F_Cu.gbr": empty})
    assert e.value.code == "no_geometry"


# ---- the holes ----------------------------------------------------------------------------------------------------
def test_without_a_drill_file_the_pads_stay_full_and_it_is_said(synth):
    files, _ = synth
    imp = board_of({k: v for k, v in files.items() if not k.endswith(".drl")})
    assert C.NO_DRILL in codes(imp) and not any(l.role is Role.DRILL for l in imp.board.layers)


def test_holes_that_are_not_on_the_board_are_an_error_not_a_guess(synth):
    files, _ = synth
    far = testdata.excellon("Plated,1,2,PTH", {1: 0.9}, [(1, 500.0, 900.0), (1, 520.0, 910.0)])
    imp = board_of({**{k: v for k, v in files.items() if not k.endswith(".drl")}, "far.drl": far})
    drill = next(l for l in imp.board.layers if l.role is Role.DRILL)
    assert (drill.status.level, drill.status.code, drill.on) == ("error", LC.DRILL_OUTSIDE_BOARD, False)
    assert drill.status.params == {"file": "far.drl", "margin_mm": DRILL_MARGIN_MM}
    assert next(l for l in imp.board.layers if l.role is Role.COPPER).on                    # the rest of the board is usable


def test_a_hole_just_outside_the_extent_is_still_on_the_board(synth):
    files, _ = synth
    edge = testdata.excellon("Plated,1,2,PTH", {1: 0.9}, [(1, 10 - 1.0, 35.0), (1, 90 + 1.0, 35.0)])     # 1 mm beyond the edges
    imp = board_of({**{k: v for k, v in files.items() if not k.endswith(".drl")}, "edge.drl": edge})
    assert next(l for l in imp.board.layers if l.role is Role.DRILL).status.level == "ok"


def test_a_drill_file_that_cannot_be_read_is_an_error(synth):
    files, _ = synth
    broken = "M48\nMETRIC\nT1C0.9\n%\nT1\nX1.0Y1.0\nM30\n".replace("T1C0.9", "TXQC??")
    imp = board_of({**{k: v for k, v in files.items() if not k.endswith(".drl")}, "broken.drl": broken})
    drill = next((l for l in imp.board.layers if l.role is Role.DRILL), None)
    assert drill is not None and drill.status.level in ("ok", "error")                       # parsed leniently, or reported
    if drill.status.level == "error":
        assert drill.status.code in (LC.UNREADABLE, LC.DRILL_OUTSIDE_BOARD) and not drill.on


# ---- layers that cannot be used ----------------------------------------------------------------------------------
def test_an_unreadable_copper_file_is_marked_and_the_board_is_still_opened(synth):
    files, _ = synth
    bad = "%FSLAX46Y46*%\n%MOMM*%\n%ADD10NOSUCHMACRO,1.0X2.0*%\nD10*\nX1000000Y1000000D03*\nM02*\n"
    imp = board_of({**files, "F_Cu.gbr": bad})
    cu = layers_by_name(imp)["F_Cu.gbr"]
    assert (cu.status.level, cu.status.code, cu.on) == ("error", LC.UNREADABLE, False)
    assert "NOSUCHMACRO" in cu.status.params["reason"]
    assert layers_by_name(imp)["Edge_Cuts.gbr"].on                                         # the outline still sizes the board


def test_a_negative_copper_layer_is_marked_and_stays_off(synth):
    files, _ = synth
    neg = "%TF.FilePolarity,Negative*%\n" + files["F_Cu.gbr"]
    cu = layers_by_name(board_of({**files, "F_Cu.gbr": neg}))["F_Cu.gbr"]
    assert (cu.status.level, cu.status.code, cu.on) == ("error", LC.NEGATIVE_IMAGE, False)


def test_bottom_copper_is_used_when_there_is_no_top_copper(synth):
    files, _ = synth
    # X2 says which side, and wins over the name: the attribute has to change as well as the file name
    only_bottom = {("B_Cu.gbr" if k == "F_Cu.gbr" else k): (v.replace("Copper,L1,Top", "Copper,L2,Bot") if k == "F_Cu.gbr" else v)
                   for k, v in files.items()}
    imp = board_of(only_bottom)
    cu = layers_by_name(imp)["B_Cu.gbr"]
    assert cu.side is Side.BOTTOM and cu.on


def test_only_one_of_two_top_copper_files_starts_on(synth):
    files, _ = synth
    imp = board_of({**files, "extra/F_Cu.gbr": files["F_Cu.gbr"]})
    cus = [l for l in imp.board.layers if l.role is Role.COPPER]
    assert len(cus) == 2 and sum(l.on for l in cus) == 1 and len({l.id for l in cus}) == 2


def test_files_with_no_known_role_are_listed_so_the_user_can_assign_them(synth):
    files, _ = synth
    no_x2 = "\n".join(l for l in files["F_Silkscreen.gbr"].splitlines() if not l.startswith("%TF."))      # nothing says what it is
    imp = board_of({**files, "mystery.gbr": no_x2})
    issue = next(i for i in imp.issues if i.code == C.FILES_UNRECOGNISED)
    assert issue.params == {"names": ["mystery.gbr"]}
    assert layers_by_name(imp)["mystery.gbr"].role is Role.IGNORE and not layers_by_name(imp)["mystery.gbr"].on


# ---- zips that are refused or not zips ----------------------------------------------------------------------------
def test_a_zip_without_copper_is_refused(synth):
    files, _ = synth
    with pytest.raises(ImportRefused) as e:
        board_of({"Edge_Cuts.gbr": files["Edge_Cuts.gbr"]})
    assert e.value.code == "no_copper"
    with pytest.raises(ImportRefused):
        board_of({"readme.txt": "hello"})


def test_something_that_is_not_a_zip_is_an_error_naming_it():
    with pytest.raises(GerberError) as e:
        import_zip(b"this is not a zip", board_id="b1")
    assert e.value.code == "bad_zip"


def test_an_old_eagle_export_is_refused_as_incompatible():
    old = "G75*\n%MOIN*%\n%OFA0B0*%\n%FSLAX25Y25*%\n%IPPOS*%\n%LPD*%\nM02*\n"
    with pytest.raises(Incompatible) as e:
        import_zip(make_zip({"b.GTL": old, "b.GBL": old, "b.TXT": "M48\nM72\n%\nM30\n"}), board_id="b1")
    assert e.value.code == "incompatible_export" and e.value.params["cad"] == "eagle"


def test_macos_leftovers_and_reports_are_skipped(synth):
    files, _ = synth
    imp = board_of({**files, "__MACOSX/._F_Cu.gbr": "junk", ".DS_Store": "junk", "report.txt": "Report\n"})
    assert {"__MACOSX/._F_Cu.gbr", ".DS_Store", "report.txt"} <= set(imp.skipped)
    assert not any(l.name in ("report.txt", ".DS_Store") for l in imp.board.layers)


def test_names_with_spaces_and_folders_are_kept_readable_and_ids_stay_valid(synth):
    files, _ = synth
    imp = board_of({f"My Gerbers/My Board {k}": v for k, v in files.items()})
    assert all(" " in l.name or l.role is Role.DRILL for l in imp.board.layers)
    for l in imp.board.layers:
        assert "/" not in l.name and l.id.replace("_", "").replace("-", "").replace(".", "").isalnum()


def test_the_job_file_size_is_checked_against_the_outline(synth):
    files, _ = synth
    job = lambda x, y: ('{"Header": {"GenerationSoftware": {"Application": "EAGLE"}}, "Overall": {"Size": {"X": %s, "Y": %s}}}' % (x, y))
    ok = board_of({**files, "gerber_job.gbrjob": job(80, 50)})
    assert C.JOB_SIZE_MISMATCH not in codes(ok)
    bad = board_of({**files, "gerber_job.gbrjob": job(200, 100)})
    issue = next(i for i in bad.issues if i.code == C.JOB_SIZE_MISMATCH)
    assert issue.params["job_mm"] == [200.0, 100.0] and issue.params["outline_mm"] == pytest.approx([80, 50])


# ---- the real samples ---------------------------------------------------------------------------------------------
EXT = Path(__file__).resolve().parent.parent / "experiments" / "fase2" / "external"
ALTIUM, EAGLE_NEW, EAGLE_OLD = EXT / "altium_flight_controller.zip", EXT / "eagle9_torazza.zip", EXT / "eagle_mus1099.zip"
KICAD = EXT / "kicad_uni_mosfet_key.zip"


@pytest.mark.skipif(not ALTIUM.exists(), reason="the Altium example is not in experiments/fase2/external/")
def test_the_real_altium_board():
    imp = import_zip(ALTIUM, board_id="b1", source_name=ALTIUM.name, plane=PLANE)
    b = imp.board
    assert imp.cad == "altium"
    assert (b.size.width_mm, b.size.height_mm) == pytest.approx((74.42, 57.25), abs=0.05)         # the Profile layer
    assert b.source_center == pytest.approx((98.55, 75.005), abs=0.05)
    by = {l.name: l for l in b.layers}
    P = "Flight_Controller_PCB"
    assert {l.name for l in b.layers if l.on} == {f"{P}_Copper_Signal_Top.gbr", f"{P}_Profile.gbr"}
    assert (by[f"{P}_Copper_Plane_1.gbr"].status.code, by[f"{P}_Copper_Plane_1.gbr"].side) == (LC.NEGATIVE_IMAGE, Side.INNER)
    assert by[f"{P}_Copper_Signal_1.gbr"].status.level == "ok" and by[f"{P}_Copper_Signal_Bot.gbr"].status.level == "ok"
    assert by[f"{P}_Soldermask_Top.gbr"].status.level == "ok" and by[f"{P}_Soldermask_Bot.gbr"].status.level == "ok"     # drawn "Negative", still fine
    assert [l.name.removeprefix(P + "_") for l in b.layers if l.role is not Role.IGNORE] == [
        "Legend_Top.gbr", "Soldermask_Top.gbr", "Copper_Signal_Top.gbr", "Copper_Plane_1.gbr", "Copper_Signal_1.gbr",
        "Copper_Signal_Bot.gbr", "Soldermask_Bot.gbr", "Legend_Bot.gbr", "Profile.gbr"]
    assert by[f"{P}_Legend_Top.gbr"].status.level == "ok" and by[f"{P}_Paste_Top.gbr"].role is Role.IGNORE
    assert codes(imp) == [C.NO_DRILL]                                                           # no drill file in this export
    assert {"Gerber/Flight_Controller_PCB.REP", "Gerber/Flight_Controller_PCB.apr"} <= set(imp.skipped)


@pytest.mark.skipif(not EAGLE_NEW.exists(), reason="the EAGLE 9 example is not in experiments/fase2/external/")
def test_the_real_eagle_9_board():
    imp = import_zip(EAGLE_NEW, board_id="b1", source_name=EAGLE_NEW.name, plane=None)
    b = imp.board
    assert imp.cad == "eagle" and imp.issues == ()                                              # outline, drill and job all agree
    assert (b.size.width_mm, b.size.height_mm) == pytest.approx((172, 112), abs=0.01)
    assert b.source_center == pytest.approx((86, 56), abs=0.01)
    assert {l.name for l in b.layers if l.on} == {"copper_top.gbr", "profile.gbr", "drill_1_16.xln"}
    drill = next(l for l in b.layers if l.role is Role.DRILL)
    assert drill.status.level == "ok"                                                           # 234 holes, all on the board
    assert next(l for l in b.layers if l.name == "copper_bottom.gbr").status.level == "ok"
    assert [l.status.level for l in b.layers if l.role is Role.MASK] == ["ok", "ok"]            # no polarity declared, openings drawn all the same
    assert {"CAMOutputs/GerberFiles/gerber_job.gbrjob", "CAMOutputs/Assembly/torazza.txt"} <= set(imp.skipped)


@pytest.mark.skipif(not EAGLE_OLD.exists(), reason="the old EAGLE example is not in experiments/fase2/external/")
def test_the_real_old_eagle_export_is_refused_when_opened():
    with pytest.raises(Incompatible) as e:
        import_zip(EAGLE_OLD, board_id="b1")
    assert e.value.code == "incompatible_export" and e.value.params["cad"] == "eagle"


@pytest.mark.skipif(not KICAD.exists(), reason="the KiCad example is not in experiments/fase2/external/")
def test_the_real_kicad_10_board():
    imp = import_zip(KICAD, board_id="b1", source_name=KICAD.name, plane=PLANE)
    b = imp.board
    assert imp.cad == "kicad" and imp.issues == ()               # the job file says 30.05 (it counts the line width): within tolerance
    assert (b.size.width_mm, b.size.height_mm) == pytest.approx((30.0, 30.0), abs=0.01)
    assert b.source_center == pytest.approx((115.0, -115.0), abs=0.01)         # KiCad's Y runs the other way: negative is normal
    on = {l.role for l in b.layers if l.on}
    assert on == {Role.COPPER, Role.OUTLINE, Role.DRILL}
    assert next(l for l in b.layers if l.role is Role.COPPER and l.on).side is Side.TOP
    drill = next(l for l in b.layers if l.role is Role.DRILL)
    assert drill.status.level == "ok" and len(drill.files) == 2 and drill.on        # the non-plated file is empty: that is fine
    assert next(l for l in b.layers if l.side is Side.BOTTOM and l.role is Role.COPPER).status.level == "ok"
    masks = [l for l in b.layers if l.role is Role.MASK]
    assert len(masks) == 2 and all(l.status.level == "ok" and not l.on for l in masks)           # declared Negative, drawn as openings
    assert any(n.endswith("job.gbrjob") for n in imp.skipped)
