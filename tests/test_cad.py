"""Recognising what the files of a zip are: names and extensions, X2 attributes, polarity, which program made them, and the
refusal of an export that is not supported (the old EAGLE CAM Processor). The three real samples are checked file by file."""
import zipfile
from pathlib import Path

import pytest

from gerberslap.cad import Incompatible, classify, probe, recognize
from gerberslap.core import zip_members
from gerberslap.model import Role, Side

GERBER = "%FSLAX46Y46*%\n%MOMM*%\nM02*\n"            # the least that makes a file RS-274X


def classified(name, text=GERBER):
    return classify(probe(name, text.encode()))


def role_side(name, text=GERBER):
    a = classified(name, text)
    return a.role, a.side


# ---- names and extensions ----------------------------------------------------------------------------------------
KICAD = [("board-F_Cu.gbr", Role.COPPER, Side.TOP), ("board-B_Cu.gbr", Role.COPPER, Side.BOTTOM),
         ("board-In1_Cu.gbr", Role.COPPER, Side.INNER), ("board-In12_Cu.gbr", Role.COPPER, Side.INNER),
         ("board-Edge_Cuts.gbr", Role.OUTLINE, Side.TOP), ("board-F_Mask.gbr", Role.MASK, Side.TOP),
         ("board-B_Mask.gbr", Role.MASK, Side.BOTTOM), ("board-F_Silkscreen.gbr", Role.SILK, Side.TOP),
         ("board-B_Silkscreen.gbr", Role.SILK, Side.BOTTOM), ("board-F_Paste.gbr", Role.IGNORE, Side.TOP),
         ("board-B_Paste.gbr", Role.IGNORE, Side.TOP), ("board-F_Fab.gbr", Role.IGNORE, Side.TOP),
         ("board-B_Crtyd.gbr", Role.IGNORE, Side.TOP), ("board-Dwgs_User.gbr", Role.IGNORE, Side.TOP)]
PROTEL = [("x.GTL", Role.COPPER, Side.TOP), ("x.GBL", Role.COPPER, Side.BOTTOM), ("x.G1", Role.COPPER, Side.INNER),
          ("x.GP2", Role.COPPER, Side.INNER), ("x.GTS", Role.MASK, Side.TOP), ("x.GBS", Role.MASK, Side.BOTTOM),
          ("x.GTO", Role.SILK, Side.TOP), ("x.GBO", Role.SILK, Side.BOTTOM), ("x.GTP", Role.IGNORE, Side.TOP),
          ("x.GBP", Role.IGNORE, Side.TOP), ("x.GKO", Role.OUTLINE, Side.TOP), ("x.GM1", Role.OUTLINE, Side.TOP),
          ("x.GD1", Role.IGNORE, Side.TOP), ("x.GG1", Role.IGNORE, Side.TOP)]
EASYEDA = [("Gerber_TopLayer.GTL", Role.COPPER, Side.TOP), ("Gerber_BottomLayer.GBL", Role.COPPER, Side.BOTTOM),
           ("Gerber_BoardOutlineLayer.GKO", Role.OUTLINE, Side.TOP), ("Gerber_TopSilkscreenLayer.GTO", Role.SILK, Side.TOP),
           ("Gerber_TopSolderMaskLayer.GTS", Role.MASK, Side.TOP), ("Gerber_BottomSolderMaskLayer.GBS", Role.MASK, Side.BOTTOM)]
NEW_STYLE = [("p_Copper_Signal_Top.gbr", Role.COPPER, Side.TOP), ("p_Copper_Signal_Bot.gbr", Role.COPPER, Side.BOTTOM),
             ("p_Copper_Signal_1.gbr", Role.COPPER, Side.INNER), ("p_Copper_Plane_2.gbr", Role.COPPER, Side.INNER),
             ("p_Legend_Top.gbr", Role.SILK, Side.TOP), ("p_Soldermask_Bot.gbr", Role.MASK, Side.BOTTOM),
             ("p_Paste_Top.gbr", Role.IGNORE, Side.TOP), ("p_Profile.gbr", Role.OUTLINE, Side.TOP),
             ("copper_top.gbr", Role.COPPER, Side.TOP), ("copper_bottom.gbr", Role.COPPER, Side.BOTTOM),
             ("silkscreen_top.gbr", Role.SILK, Side.TOP), ("soldermask_bottom.gbr", Role.MASK, Side.BOTTOM),
             ("solderpaste_top.gbr", Role.IGNORE, Side.TOP), ("profile.gbr", Role.OUTLINE, Side.TOP)]


@pytest.mark.parametrize("name,role,side", KICAD + PROTEL + EASYEDA + NEW_STYLE)
def test_names_and_extensions(name, role, side):
    assert role_side(name) == (role, side)


def test_a_folder_in_the_path_does_not_matter_and_neither_does_case():
    assert role_side("Some Folder/Gerbers/BOARD-f_cu.GBR") == (Role.COPPER, Side.TOP)
    assert role_side("a\\b\\BOARD.gtl") == (Role.COPPER, Side.TOP)


def test_names_are_read_token_by_token():
    assert classified("tophat_project.gbr").reason == "unknown"            # "top" inside a word is not a side
    assert classified("solution.gbr").reason == "unknown"                  # nor is "sol" (EAGLE's bottom copper)
    assert classified("reporter.gbr").role is Role.IGNORE and classified("reporter.gbr").reason == "unknown"


def test_an_unrecognised_gerber_is_ignored_with_no_confidence_so_the_user_can_assign_it():
    a = classified("mystery.gbr")
    assert (a.role, a.confidence, a.reason, a.kind) == (Role.IGNORE, 0.0, "unknown", "gerber")


def test_ambiguous_extensions_are_less_certain_than_clear_names():
    assert classified("x.GM1").confidence < classified("x.GKO").confidence < classified("board-Edge_Cuts.gbr").confidence
    assert classified("board-F_Cu.gbr").confidence > classified("x.GTL").confidence


def test_the_layer_name_written_inside_a_file_is_a_last_resort():
    a = classified("layer7.gbr", "%FSLAX34Y34*%\n%MOMM*%\n%INTop Copper*%\nM02*\n")
    assert (a.role, a.side, a.reason) == (Role.COPPER, Side.TOP, "inline:top_copper")
    assert a.confidence < classified("copper_top.gbr").confidence


# ---- X2 attributes -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("function,role,side", [
    ("Copper,L1,Top", Role.COPPER, Side.TOP), ("Copper,L4,Bot", Role.COPPER, Side.BOTTOM),
    ("Copper,L2,Inr", Role.COPPER, Side.INNER), ("Copper,L1,Top,Signal", Role.COPPER, Side.TOP),
    ("Soldermask,Top", Role.MASK, Side.TOP), ("Soldermask,Bot,1", Role.MASK, Side.BOTTOM),
    ("Legend,Top", Role.SILK, Side.TOP), ("Legend,Bot", Role.SILK, Side.BOTTOM),
    ("Paste,Top", Role.IGNORE, Side.TOP), ("SolderPaste,Bot", Role.IGNORE, Side.TOP), ("Profile,NP", Role.OUTLINE, Side.TOP), ("Profile,P", Role.OUTLINE, Side.TOP),
    ("Other,Fab", Role.IGNORE, Side.TOP), ("Keep-out,Top", Role.IGNORE, Side.TOP)])
def test_x2_file_function_wins_over_the_name(function, role, side):
    a = classified("whatever_gtl.gbr", f"%TF.FileFunction,{function}*%\n" + GERBER)
    assert (a.role, a.side, a.reason, a.confidence) == (role, side, "x2", 1.0)


def test_x2_attributes_in_comments_are_read_too():
    a = classified("x.gbr", "G04 #@! TF.FileFunction,Copper,L1,Top*\n" + GERBER)
    assert (a.role, a.reason) == (Role.COPPER, "x2")


def test_an_unknown_x2_function_falls_back_to_the_name():
    a = classified("board-F_Cu.gbr", "%TF.FileFunction,SomethingNew,Top*%\n" + GERBER)
    assert (a.role, a.reason) == (Role.COPPER, "name:f_cu")


# ---- drill files and other files ---------------------------------------------------------------------------------
def test_an_excellon_file_is_a_drill_whatever_it_is_called():
    for name in ("x.drl", "x.TXT", "x.xln", "weird.gbr", "x.drd"):
        a = classified(name, "M48\nMETRIC\nT1C0.8\n%\nT1\nX1.0Y1.0\nM30\n")
        assert (a.role, a.kind, a.reason, a.confidence) == (Role.DRILL, "excellon", "content:excellon", 1.0)


def test_plating_comes_from_x2_or_from_the_name():
    ex = "M48\nMETRIC\n%\nM30\n"
    assert classified("a.drl", "; #@! TF.FileFunction,Plated,1,2,PTH\n" + ex).plated is True
    assert classified("a.drl", "; #@! TF.FileFunction,NonPlated,1,2,NPTH\n" + ex).plated is False
    assert classified("board-NPTH.drl", ex).plated is False and classified("board-PTH.drl", ex).plated is True
    assert classified("board.drl", ex).plated is None


@pytest.mark.parametrize("name,text", [("x.REP", "Gerber File Extension Report\n----\n"), ("x.apr", "D10 C 0.1\n"),
                                       ("x.gbrjob", '{"Header": {}}'), ("PnP_front.txt", "Designator Mid X\n"),
                                       ("readme.txt", "hello")])
def test_files_that_are_not_gerber_or_excellon_are_ignored(name, text):
    a = classified(name, text)
    assert (a.role, a.kind, a.reason) == (Role.IGNORE, "other", "not_gerber")


# ---- polarity ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,negative", [
    ("%TF.FilePolarity,Negative*%\n" + GERBER, True), ("G04 #@! TF.FilePolarity,Negative*\n" + GERBER, True),
    ("%IPNEG*%\n" + GERBER, True), ("%TF.FilePolarity,Positive*%\n" + GERBER, False), (GERBER, False), ("%IPPOS*%\n" + GERBER, False)])
def test_negative_images_are_flagged(text, negative):
    assert classified("x.gbr", text).negative is negative


# ---- which program made them -------------------------------------------------------------------------------------
def members(**files):
    return {name: text.encode() for name, text in files.items()}


def test_kicad_is_recognised_from_the_generation_software():
    r = recognize(members(**{"a.gbr": "%TF.GenerationSoftware,KiCad,Pcbnew,7.0.5*%\n" + GERBER}))
    assert (r.cad, r.score) == ("kicad", 1.0)


def test_kicad_is_recognised_from_its_names_when_the_files_do_not_say():
    r = recognize(members(**{"b-F_Cu.gbr": GERBER, "b-Edge_Cuts.gbr": GERBER}))
    assert r.cad == "kicad" and r.score == .8


def test_altium_and_eagle_are_recognised_from_the_software():
    assert recognize(members(**{"a.gbr": "G04*\nG04 #@! TF.GenerationSoftware,Altium Limited,Altium Designer,24.5.2 (23)*\n" + GERBER})).cad == "altium"
    assert recognize(members(**{"a.gbr": "G04 EAGLE Gerber RS-274X export*\n" + GERBER})).cad == "eagle"


def test_with_nothing_to_go_on_it_is_generic():
    r = recognize(members(**{"layer1.gbr": GERBER, "layer2.gbr": GERBER}))
    assert r.cad == "generic" and r.score == pytest.approx(.1)


def test_the_most_certain_program_wins_and_a_tie_goes_to_the_specific_one():
    both = members(**{"a.gbr": "%TF.GenerationSoftware,KiCad,Pcbnew,7*%\n" + GERBER,
                      "b.gbr": "G04 EAGLE Gerber RS-274X export*\n" + GERBER})
    assert recognize(both).cad == "kicad"                                  # both score 1.0: KiCad is listed first


def test_the_eagle_job_file_gives_the_board_size():
    job = '{"Header": {"GenerationSoftware": {"Application": "EAGLE"}}, "Overall": {"Size": {"X": 172, "Y": 112}}}'
    r = recognize(members(**{"gerber_job.gbrjob": job, "copper_top.gbr": GERBER}))
    assert r.cad == "eagle" and r.info == {"job_size_mm": (172.0, 112.0)}
    assert recognize(members(**{"gerber_job.gbrjob": "{broken", "copper_top.gbr": "G04 EAGLE Gerber RS-274X export*\n" + GERBER})).info == {}


def test_the_kicad_job_file_gives_the_board_size_in_its_own_layout():
    job = '{"Header": {"GenerationSoftware": {"Vendor": "KiCad"}}, "GeneralSpecs": {"Size": {"X": 30.05, "Y": 30.05}}}'
    r = recognize(members(**{"b-job.gbrjob": job, "b-F_Cu.gbr": "%TF.GenerationSoftware,KiCad,Pcbnew,10.0.5*%\n" + GERBER}))
    assert r.cad == "kicad" and r.info == {"job_size_mm": (30.05, 30.05)}


@pytest.mark.parametrize("job", ["{broken", "[]", '{"GeneralSpecs": {}}', '{"Overall": {"Size": {"X": "wide"}}}', '{"GeneralSpecs": {"Size": {"X": 1}}}'])
def test_a_damaged_or_incomplete_job_file_is_not_an_error(job):
    assert recognize(members(**{"x.gbrjob": job, "b-F_Cu.gbr": GERBER, "b-Edge_Cuts.gbr": GERBER})).info == {}


# ---- the export that is refused ----------------------------------------------------------------------------------
OLD_EAGLE_GERBER = "G75*\n%MOIN*%\n%OFA0B0*%\n%FSLAX25Y25*%\n%IPPOS*%\n%LPD*%\nM02*\n"


def test_an_old_eagle_cam_processor_gerber_is_refused_as_incompatible():
    with pytest.raises(Incompatible) as e:
        recognize(members(**{"MUS-1099.GTL": OLD_EAGLE_GERBER, "MUS-1099.GBL": OLD_EAGLE_GERBER}))
    assert e.value.code == "incompatible_export"
    assert e.value.params == {"cad": "eagle", "reason": "old_cam_header", "version": None, "file": "MUS-1099.GTL"}


def test_the_information_files_of_the_old_cam_processor_are_enough_to_refuse():
    dri = "Generated by EAGLE CAM Processor 8.2.1\n\nDrill Station Info File: D:/x.dri\n"
    with pytest.raises(Incompatible) as e:
        recognize(members(**{"board.dri": dri, "board.GTL": GERBER}))
    assert e.value.params["reason"] == "old_cam_processor" and e.value.params["version"] == "8.2.1"
    with pytest.raises(Incompatible):
        recognize(members(**{"board.gpi": "Generated by EAGLE CAM Processor 7.7.0\n"}))


def test_the_new_eagle_export_and_other_programs_are_not_refused():
    recognize(members(**{"copper_top.gbr": "G04 EAGLE Gerber RS-274X export*\nG75*\n%MOMM*%\n%FSLAX34Y34*%\n%IPPOS*%\nM02*\n"}))
    recognize(members(**{"a.gbr": "G75*\n%MOIN*%\n%FSLAX25Y25*%\nM02*\n"}))                 # the same header without the old offset
    recognize(members(**{"b-F_Cu.gbr": "%TF.GenerationSoftware,KiCad,Pcbnew,7*%\n" + GERBER}))


# ---- the real samples --------------------------------------------------------------------------------------------
EXT = Path(__file__).resolve().parent.parent / "experiments" / "fase2" / "external"
ALTIUM, EAGLE_NEW, EAGLE_OLD = EXT / "altium_flight_controller.zip", EXT / "eagle9_torazza.zip", EXT / "eagle_mus1099.zip"
KICAD = EXT / "kicad_uni_mosfet_key.zip"


def table(path):
    r = recognize(zip_members(path).members)
    return r, {a.name.rsplit("/", 1)[-1]: (a.role, a.side, a.negative) for a in r.assignments}


@pytest.mark.skipif(not ALTIUM.exists(), reason="the Altium example is not in experiments/fase2/external/")
def test_the_real_altium_export():
    r, t = table(ALTIUM)
    assert r.cad == "altium"
    P = "Flight_Controller_PCB"
    assert t[f"{P}_Copper_Signal_Top.gbr"] == (Role.COPPER, Side.TOP, False)
    assert t[f"{P}_Copper_Signal_Bot.gbr"] == (Role.COPPER, Side.BOTTOM, False)
    assert t[f"{P}_Copper_Signal_1.gbr"] == (Role.COPPER, Side.INNER, False)
    assert t[f"{P}_Copper_Plane_1.gbr"] == (Role.COPPER, Side.INNER, True)          # a plane, drawn as a negative
    assert t[f"{P}_Soldermask_Top.gbr"] == (Role.MASK, Side.TOP, True) and t[f"{P}_Soldermask_Bot.gbr"][0] is Role.MASK
    assert t[f"{P}_Legend_Top.gbr"] == (Role.SILK, Side.TOP, False) and t[f"{P}_Legend_Bot.gbr"][1] is Side.BOTTOM
    assert t[f"{P}_Profile.gbr"][0] is Role.OUTLINE
    assert t[f"{P}_Paste_Top.gbr"][0] is Role.IGNORE and t[f"{P}_Paste_Bot.gbr"][0] is Role.IGNORE
    for report in (f"{P}.REP", f"{P}.EXTREP", f"{P}.apr", f"{P}-macro.APR_LIB"):
        assert t[report][0] is Role.IGNORE
    assert not any(a.role is Role.DRILL for a in r.assignments)                      # this export has no drill file


@pytest.mark.skipif(not EAGLE_NEW.exists(), reason="the EAGLE 9 example is not in experiments/fase2/external/")
def test_the_real_eagle_9_export():
    r, t = table(EAGLE_NEW)
    assert r.cad == "eagle" and r.info == {"job_size_mm": (172.0, 112.0)}
    assert t["copper_top.gbr"] == (Role.COPPER, Side.TOP, False) and t["copper_bottom.gbr"][1] is Side.BOTTOM
    assert t["profile.gbr"][0] is Role.OUTLINE
    assert t["soldermask_top.gbr"][0] is Role.MASK and t["silkscreen_bottom.gbr"] == (Role.SILK, Side.BOTTOM, False)
    assert t["solderpaste_top.gbr"][0] is Role.IGNORE
    assert t["drill_1_16.xln"][0] is Role.DRILL
    for other in ("gerber_job.gbrjob", "torazza.txt", "PnP_torazza_front.txt", "PnP_torazza_back.txt"):
        assert t[other][0] is Role.IGNORE


@pytest.mark.skipif(not EAGLE_OLD.exists(), reason="the old EAGLE example is not in experiments/fase2/external/")
def test_the_real_old_eagle_export_is_refused():
    with pytest.raises(Incompatible) as e:
        recognize(zip_members(EAGLE_OLD).members)
    assert e.value.code == "incompatible_export" and e.value.params["cad"] == "eagle"


@pytest.mark.skipif(not KICAD.exists(), reason="the KiCad example is not in experiments/fase2/external/")
def test_the_real_kicad_10_export():
    r = recognize(zip_members(KICAD).members)
    assert (r.cad, r.score) == ("kicad", 1.0) and r.info == {"job_size_mm": (30.05, 30.05)}
    by = {a.name.rsplit("/", 1)[-1]: a for a in r.assignments}
    P = "UNI_MOSFET_KEY"
    for name, role, side in ((f"{P}-F_Cu.gbr", Role.COPPER, Side.TOP), (f"{P}-B_Cu.gbr", Role.COPPER, Side.BOTTOM),
                             (f"{P}-Edge_Cuts.gbr", Role.OUTLINE, Side.TOP), (f"{P}-F_Mask.gbr", Role.MASK, Side.TOP),
                             (f"{P}-B_Mask.gbr", Role.MASK, Side.BOTTOM), (f"{P}-F_Silkscreen.gbr", Role.SILK, Side.TOP),
                             (f"{P}-B_Silkscreen.gbr", Role.SILK, Side.BOTTOM), (f"{P}-F_Paste.gbr", Role.IGNORE, Side.TOP),
                             (f"{P}-B_Paste.gbr", Role.IGNORE, Side.TOP)):
        assert (by[name].role, by[name].side, by[name].reason, by[name].confidence) == (role, side, "x2", 1.0), name
    assert by[f"{P}-F_Mask.gbr"].negative and by[f"{P}-B_Mask.gbr"].negative          # KiCad marks the masks as negative too
    assert not by[f"{P}-F_Cu.gbr"].negative and not by[f"{P}-F_Silkscreen.gbr"].negative
    assert (by[f"{P}-PTH.drl"].role, by[f"{P}-PTH.drl"].plated) == (Role.DRILL, True)
    assert (by[f"{P}-NPTH.drl"].role, by[f"{P}-NPTH.drl"].plated) == (Role.DRILL, False)
    assert by[f"{P}-job.gbrjob"].role is Role.IGNORE
