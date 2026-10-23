"""The data model: what it accepts, what it refuses, and that a project survives a round trip through JSON."""
import math
from datetime import datetime, timedelta, timezone

import pytest
from modelfactory import EXPOSURE, H, PLANE, board, default_layers, layer, project
from pydantic import ValidationError
from shapely.geometry import box

from gerberslap.core import place
from gerberslap.model import (MAX_DOSAGES, Dosage, ExposureValues, FileRef, LayerStatus, Polarity, PrinterFile, Project, Recipe, Role,
                              board_extent, is_outside, margins, overlaps)


# ---- round trip --------------------------------------------------------------------------------------------------
def test_project_round_trips_through_json():
    p = project(board("b1"), board("b2", x=20, y=20, w=30, h=20, angle=30, mirror=True), polarity=Polarity.POSITIVE,
                min_outline_mm=0.4)
    again = Project.model_validate_json(p.model_dump_json())
    assert again == p
    assert again.boards[1].placement.mirror and again.boards[1].placement.angle == 30


def test_json_uses_plain_values_for_enums_and_arrays_for_tuples():
    import json
    data = json.loads(project(polarity=Polarity.NEGATIVE).model_dump_json())
    assert data["polarity"] == "negative" and data["format"] == "gerberslap" and data["schema_version"] == 2
    assert isinstance(data["boards"], list) and data["boards"][0]["layers"][0]["role"] == "copper"


def test_models_are_immutable():
    p = project()
    with pytest.raises(ValidationError):
        p.min_outline_mm = 1.0
    with pytest.raises(ValidationError):
        p.boards[0].placement.x = 1.0


def test_unknown_fields_are_refused():
    data = project().model_dump()
    data["surprise"] = 1
    with pytest.raises(ValidationError):
        Project.model_validate(data)
    data = project().model_dump()
    data["boards"][0]["layers"][0]["colour"] = "#ffffff"          # a typo in a field name must not pass silently
    with pytest.raises(ValidationError):
        Project.model_validate(data)


# ---- identifiers end up in file paths ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["", ".hidden", "../x", "a/b", "a\\b", "a b", "x" * 65, "é", "a\nb", "/etc"])
def test_ids_that_could_escape_a_folder_are_refused(bad):
    with pytest.raises(ValidationError):
        board(id=bad)
    with pytest.raises(ValidationError):
        layer(id=bad)


@pytest.mark.parametrize("good", ["b1", "scheda_A", "A.1", "x-2", "0", "x" * 64])
def test_ordinary_ids_are_accepted(good):
    assert board(id=good).id == good


def test_file_names_cannot_be_paths():
    with pytest.raises(ValidationError):
        FileRef(name="../secret.gbr", sha256=H)
    with pytest.raises(ValidationError):
        FileRef(name="a/b.gbr", sha256=H)
    assert FileRef(name="board-F_Cu.gbr", sha256=H).name == "board-F_Cu.gbr"


@pytest.mark.parametrize("bad", ["", "ab", "AB" * 32, "g" * 64, "ab" * 33])
def test_hashes_must_be_lowercase_sha256(bad):
    with pytest.raises(ValidationError):
        FileRef(name="a.gbr", sha256=bad)


def test_names_have_no_control_characters():
    with pytest.raises(ValidationError):
        board(name="two\nlines")
    with pytest.raises(ValidationError):
        board(name="   ")
    assert board(name="  scheda A  ").name == "scheda A"


# ---- numbers -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("field,value", [("x", math.nan), ("x", math.inf), ("angle", -math.inf), ("y", 1e9)])
def test_placement_numbers_must_be_finite_and_sane(field, value):
    with pytest.raises(ValidationError):
        board(**{field: value})


@pytest.mark.parametrize("w,h", [(0, 10), (10, 0), (-1, 10), (10, 5000), (math.nan, 10)])
def test_board_size_must_be_positive_and_finite(w, h):
    with pytest.raises(ValidationError):
        board(w=w, h=h)


def test_minimum_outline_width_range():
    assert project(min_outline_mm=0).min_outline_mm == 0
    with pytest.raises(ValidationError):
        project(min_outline_mm=-0.1)
    with pytest.raises(ValidationError):
        project(min_outline_mm=50)


# ---- structure ---------------------------------------------------------------------------------------------------
def test_ids_must_be_unique():
    with pytest.raises(ValidationError):
        project(board("b1"), board("b1"))
    with pytest.raises(ValidationError):
        board(layers=(layer("a"), layer("a", Role.OUTLINE)))


def test_a_board_needs_a_layer_and_a_layer_needs_a_file():
    with pytest.raises(ValidationError):
        board(layers=())
    with pytest.raises(ValidationError):
        layer(files=())


def test_an_ignored_layer_cannot_be_on():
    assert layer("paste", Role.IGNORE, on=False).on is False
    with pytest.raises(ValidationError):
        layer("paste", Role.IGNORE, on=True)


def test_layer_status_needs_a_code_unless_ok():
    assert LayerStatus().level == "ok"
    assert LayerStatus(level="warning", code="mask_no_openings", params={"n": 0}).code == "mask_no_openings"
    with pytest.raises(ValidationError):
        LayerStatus(level="error")
    with pytest.raises(ValidationError):
        LayerStatus(level="ok", code="x")
    with pytest.raises(ValidationError):
        LayerStatus(level="maybe", code="x")


def test_the_holes_layer_can_hold_several_files_and_does_not_draw():
    drill = default_layers()[-1]
    assert drill.role is Role.DRILL and len(drill.files) == 2 and not drill.draws
    assert all(l.draws for l in default_layers() if l.role in (Role.COPPER, Role.OUTLINE, Role.MASK, Role.SILK))


def test_drawing_layers_on_leaves_out_the_holes_and_the_switched_off():
    b = board()
    assert [l.id for l in b.drawing_layers_on] == ["copper", "outline"]


def test_inner_copper_is_a_side_and_the_source_centre_is_kept():
    from gerberslap.model import Side
    inner = layer("in1", Role.COPPER, on=False, side=Side.INNER)
    b = board(layers=(layer("copper"), inner), source_center=(98.5, 75.0))
    again = Project.model_validate_json(project(b).model_dump_json())
    assert again.boards[0].layers[1].side is Side.INNER and again.boards[0].source_center == (98.5, 75.0)
    assert board().source_center == (0.0, 0.0)
    for bad in ((1e9, 0), (math.nan, 0), (math.inf, 0)):
        with pytest.raises(ValidationError):
            board(source_center=bad)


def test_colours_are_hex():
    assert layer(color="#a1B2c3").color == "#a1B2c3"
    for bad in ("red", "#fff", "a1b2c3", "#a1b2c"):
        with pytest.raises(ValidationError):
            layer(color=bad)


# ---- placement against the core ---------------------------------------------------------------------------------
@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("angle", [0, 30, 90, 137.5, -45, 270, 359.9])
def test_extent_matches_what_the_core_does_to_a_rectangle(angle, mirror):
    b = board(x=50.5, y=33.25, w=80, h=50, angle=angle, mirror=mirror)
    placed = place(box(-40, -25, 40, 25), b.placement.to_core(), (0, 0))
    minx, miny, maxx, maxy = placed.bounds
    e = board_extent(b)
    assert (e.minx, e.maxx, e.miny, e.maxy) == pytest.approx((minx, maxx, miny, maxy), abs=1e-9)
    assert e.center == pytest.approx((50.5, 33.25), abs=1e-9)             # the extent stays centred on the placement


def test_rotating_by_90_swaps_width_and_height():
    e = board_extent(board(w=80, h=50, angle=90))
    assert (e.width, e.height) == pytest.approx((50, 80))


def test_margins_and_outside():
    e = board_extent(board(x=65, y=41, w=80, h=50))
    m = margins(e, PLANE)
    assert (m.left, m.right, m.front, m.back) == pytest.approx((25, 25.56, 16, 16.62))
    assert not is_outside(e, PLANE)
    assert is_outside(board_extent(board(x=20, y=41)), PLANE)             # 20 - 40 < 0
    assert not is_outside(board_extent(board(x=40, y=25)), PLANE)         # exactly touching the corner is inside


def test_overlap_needs_both_axes_and_more_than_the_tolerance():
    a = board_extent(board("a", x=40, y=41, w=40, h=40))
    assert overlaps(a, board_extent(board("b", x=70, y=41, w=40, h=40)))             # 10 mm on x
    assert not overlaps(a, board_extent(board("c", x=80, y=41, w=40, h=40)))         # touching edges
    assert not overlaps(a, board_extent(board("d", x=40.0, y=82.0, w=40, h=40)))     # 0 mm apart on y
    assert not overlaps(a, board_extent(board("e", x=200, y=200, w=10, h=10)))


# ---- exposure and calibrations ----------------------------------------------------------------------------------
def test_flash_is_total_over_pulses():
    assert EXPOSURE.flash_s == 20
    assert ExposureValues(total_s=45, pulses=3, rest_s=4).flash_s == 15


@pytest.mark.parametrize("kw", [dict(total_s=0, pulses=1, rest_s=0), dict(total_s=-1, pulses=1, rest_s=0),
                                dict(total_s=10, pulses=0, rest_s=0), dict(total_s=10, pulses=1.5, rest_s=0),
                                dict(total_s=10, pulses=1, rest_s=-1), dict(total_s=math.inf, pulses=1, rest_s=0),
                                dict(total_s=10, pulses=2000, rest_s=0)])
def test_exposure_values_are_validated(kw):
    with pytest.raises(ValidationError):
        ExposureValues(**kw)


def dosage(i="d1", printer="ld002h", when=None, **kw):
    return Dosage(id=i, printer_id=printer, updated=when or datetime(2026, 10, 3, 9, 0, 0, tzinfo=timezone.utc),
                  **{"total_s": 80, "pulses": 4, "rest_s": 5, **kw})


def test_a_dosage_has_the_values_of_an_exposure_and_a_time_in_utc():
    rome = timezone(timedelta(hours=2))
    d = dosage(when=datetime(2026, 10, 12, 14, 0, 0, tzinfo=rome))
    assert d.updated.utcoffset() == timedelta(0) and d.updated.hour == 12
    assert d.values == EXPOSURE and d.flash_s == 20
    with pytest.raises(ValidationError):
        Dosage(id="d", printer_id="p", updated="2026-10-12T12:00:00", total_s=1, pulses=1, rest_s=0)      # naive times are refused


@pytest.mark.parametrize("kw", [dict(total_s=0), dict(pulses=0), dict(pulses=1.5), dict(rest_s=-1), dict(name="a\nb"), dict(name="x" * 61), dict(note="x" * 501),
                                dict(printer="../x")])
def test_a_dosage_is_validated(kw):
    with pytest.raises(ValidationError):
        dosage(**kw)


def test_a_recipe_has_its_dosages_and_they_must_be_distinct_and_few():
    r = Recipe(id="r", name="Dry film", polarity="negative", dosages=(dosage("a"), dosage("b")))
    assert r.dosage("a").id == "a" and r.dosage("zz") is None
    with pytest.raises(ValidationError):
        Recipe(id="r", name="x", polarity="negative", dosages=(dosage("a"), dosage("a")))                  # ids are unique within a recipe
    Recipe(id="r", name="x", polarity="negative", dosages=tuple(dosage(f"d{i}") for i in range(MAX_DOSAGES)))
    with pytest.raises(ValidationError):
        Recipe(id="r", name="x", polarity="negative", dosages=tuple(dosage(f"d{i}") for i in range(MAX_DOSAGES + 1)))


def test_the_dosages_for_a_printer_are_the_last_changed_first_and_only_that_printers():
    t = datetime(2026, 10, 3, 9, 0, 0, tzinfo=timezone.utc)
    r = Recipe(id="r", name="x", polarity="positive", dosages=(
        dosage("old", when=t), dosage("other", printer="fabula", when=t + timedelta(days=30)), dosage("new", when=t + timedelta(days=9)),
        dosage("tie-1", when=t + timedelta(days=5)), dosage("tie-2", when=t + timedelta(days=5))))
    assert [d.id for d in r.dosages_for("ld002h")] == ["new", "tie-2", "tie-1", "old"]                    # of two at the same moment, the later in the list
    assert [d.id for d in r.dosages_for("fabula")] == ["other"] and r.dosages_for("none") == ()


@pytest.mark.parametrize("kw", [dict(resist="a\nb"), dict(development="x" * 201), dict(notes="x" * 2001), dict(notes="bad \x00 byte"), dict(polarity="neutral")])
def test_a_recipe_is_validated(kw):
    with pytest.raises(ValidationError):
        Recipe(**{"id": "r", "name": "x", "polarity": "negative", **kw})


def test_the_notes_of_a_recipe_may_have_several_lines():
    assert Recipe(id="r", name="x", polarity="negative", notes="one\ntwo\tthree").notes == "one\ntwo\tthree"


def test_what_a_person_may_write_for_a_printer_is_only_its_settings():
    assert PrinterFile().settings == {} and PrinterFile(settings={"park_z_mm": 2}).settings == {"park_z_mm": 2}
    with pytest.raises(ValidationError):
        PrinterFile(settings={}, template="template.ctb")                              # where the template is, is not written down any more


# ---- the order of a board's layers: the user's to change, so nothing may follow it by accident -----------------------
def test_the_area_outline_is_the_same_whatever_order_the_layers_are_in():
    a, b = layer("a_outline", Role.OUTLINE, on=False), layer("b_outline", Role.OUTLINE)
    bad = layer("0_bad_outline", Role.OUTLINE, status=LayerStatus(level="error", code="negative_image"))      # smallest id, but refused
    others = (layer("copper"), layer("drill", Role.DRILL))
    for order in ([a, b, bad], [b, a, bad], [bad, b, a]):
        assert board(layers=(*order, *others)).area_outline.id == "a_outline"                                # on or off does not matter either
    assert board(layers=others).area_outline is None


def test_only_copper_mask_and_silkscreen_are_in_the_stack():
    from gerberslap.model import STACK_ROLES
    assert STACK_ROLES == {Role.COPPER, Role.MASK, Role.SILK} and Role.OUTLINE not in STACK_ROLES and Role.DRILL not in STACK_ROLES
