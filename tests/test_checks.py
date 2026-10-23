"""The checks: one test per code, the clean case, what blocks and what only informs, and the order of the list."""
import pytest
from modelfactory import EXPOSURE, NEGATIVE, PLANE, POSITIVE, PRINTER, board, default_layers, layer, project

from gerberslap.model import C, ExposureLimits, ExposureValues, LayerStatus, Polarity, RecipeRef, Role, Severity
from gerberslap.services.checks import blocking, check_project

LIMITS = ExposureLimits(min_flash_s=1.0, max_proven_flash_s=20.0)


def run(p, **kw):
    kw.setdefault("printer", PRINTER)
    kw.setdefault("recipe", POSITIVE)
    kw.setdefault("exposure", EXPOSURE)
    kw.setdefault("limits", LIMITS)
    return check_project(p, plane=PLANE, **kw)


def codes(issues):
    return [i.code for i in issues]


def only(issues, code):
    found = [i for i in issues if i.code == code]
    assert len(found) == 1, f"expected exactly one {code}, got {codes(issues)}"
    return found[0]


def with_layers(**on):
    """The default layers with the given ones switched on or off (by id)."""
    return tuple(l.model_copy(update={"on": on.get(l.id, l.on)}) for l in default_layers())


# ---- the clean case ----------------------------------------------------------------------------------------------
def test_a_valid_project_has_no_issues():
    assert run(project(polarity=Polarity.POSITIVE)) == []


# ---- what blocks -------------------------------------------------------------------------------------------------
def test_an_empty_project_has_no_layer_on_and_blocks():
    issues = run(project(*[]).model_copy(update={"boards": ()}))
    assert codes(blocking(issues)) == [C.NO_LAYER_ON]


def test_the_holes_alone_do_not_count_as_a_layer_on():
    p = project(board(layers=with_layers(copper=False, outline=False)))
    issues = run(p)
    assert C.NO_LAYER_ON in codes(blocking(issues)) and C.BOARD_NO_LAYER_ON in codes(blocking(issues))
    assert only(issues, C.BOARD_NO_LAYER_ON).board_id == "b1"


def test_a_board_without_a_drawing_layer_blocks_even_if_another_board_has_one():
    p = project(board("b1"), board("b2", x=20, y=20, w=10, h=10, layers=with_layers(copper=False, outline=False)))
    issues = run(p)
    assert codes(blocking(issues)) == [C.BOARD_NO_LAYER_ON]               # the project does have a layer on
    assert blocking(issues)[0].board_id == "b2"


def test_a_layer_with_an_error_that_is_on_blocks():
    bad = layer("mask", Role.MASK, on=True, status=LayerStatus(level="error", code="mask_unsupported"))
    p = project(board(layers=(layer("copper"), bad)))
    issues = run(p)
    b = only(issues, C.LAYER_ERROR_ON)
    assert b.blocking and b.layer_id == "mask" and b.severity is Severity.ERROR
    issue = only(issues, C.LAYER_ISSUE)
    assert issue.params["status_code"] == "mask_unsupported" and issue.severity is Severity.ERROR and not issue.blocking


def test_a_layer_with_an_error_that_is_off_only_informs():
    off = layer("mask", Role.MASK, on=False, status=LayerStatus(level="error", code="mask_unsupported"))
    issues = run(project(board(layers=(layer("copper"), off))))
    assert codes(issues) == [C.LAYER_ISSUE] and blocking(issues) == []


def test_a_missing_printer_and_missing_values_block_and_a_recipe_that_was_never_chosen_does_not():
    issues = run(project(printer_id=None, recipe_id=None), printer=None, recipe=None, exposure=None)
    assert [i.code for i in blocking(issues)] == [C.PRINTER_MISSING, C.EXPOSURE_INVALID]
    assert C.DOSAGE_MISSING not in codes(issues) and C.RECIPE_MISSING not in codes(issues)     # nothing to calibrate, and no recipe is needed


def test_values_set_by_hand_need_no_recipe():
    assert run(project(recipe_id=None), recipe=None) == []


def test_a_recipe_the_project_refers_to_and_is_not_found_blocks():
    b = only(run(project(recipe_id="lost"), recipe=None), C.RECIPE_MISSING)
    assert b.blocking and b.params == {"recipe_id": "lost"}


def test_the_recipe_the_page_chose_is_enough_without_its_dosages():
    assert run(project(), recipe=RecipeRef(id="pos35", name="Positivo", polarity=Polarity.POSITIVE)) == []


def test_the_missing_ids_are_reported():
    issues = run(project(printer_id="gone", recipe_id="lost"), printer=None, recipe=None, exposure=None)
    assert only(issues, C.PRINTER_MISSING).params == {"printer_id": "gone"}
    assert only(issues, C.RECIPE_MISSING).params == {"recipe_id": "lost"}


def test_no_exposure_values_warn_and_block_and_name_the_printer_and_recipe():
    issues = run(project(), exposure=None)
    w = only(issues, C.DOSAGE_MISSING)
    assert w.severity is Severity.WARNING and not w.blocking and w.params == {"printer_id": "lab", "recipe_id": "pos35"}
    b = only(issues, C.EXPOSURE_INVALID)
    assert b.blocking and b.params == {"reason": "missing"}


def test_a_flash_below_the_minimum_blocks():
    issues = run(project(), exposure=ExposureValues(total_s=8, pulses=10, rest_s=5))          # 0.8 s per flash
    b = only(issues, C.FLASH_BELOW_MINIMUM)
    assert b.blocking and b.params["flash_s"] == pytest.approx(0.8) and b.params["min_s"] == 1.0


def test_the_flash_limits_are_inclusive():
    assert run(project(), exposure=ExposureValues(total_s=10, pulses=10, rest_s=5)) == []     # exactly 1 s
    assert run(project(), exposure=ExposureValues(total_s=80, pulses=4, rest_s=5)) == []       # exactly 20 s
    assert codes(run(project(), exposure=ExposureValues(total_s=80.4, pulses=4, rest_s=5))) == [C.FLASH_BEYOND_PROVEN]


# ---- what only informs -------------------------------------------------------------------------------------------
def test_a_flash_beyond_what_was_tried_warns_but_does_not_block():
    issues = run(project(), exposure=ExposureValues(total_s=60, pulses=2, rest_s=5))          # 30 s per flash
    w = only(issues, C.FLASH_BEYOND_PROVEN)
    assert not w.blocking and w.params == {"flash_s": 30.0, "max_s": 20.0}


def test_without_known_limits_no_flash_is_questioned():
    p = project()
    assert run(p, limits=ExposureLimits(), exposure=ExposureValues(total_s=3600, pulses=1, rest_s=0)) == []


def test_a_board_outside_the_plane_warns():
    issues = run(project(board(x=20, y=41)))
    w = only(issues, C.BOARD_OUTSIDE_PLANE)
    assert w.board_id == "b1" and w.severity is Severity.WARNING and not w.blocking and blocking(issues) == []


def test_overlapping_boards_warn_once_per_pair():
    p = project(board("a", x=40, y=41, w=40, h=40), board("b", x=60, y=41, w=40, h=40),
                board("c", x=110, y=41, w=20, h=20))
    issues = run(p)
    w = only(issues, C.BOARDS_OVERLAP)
    assert w.params == {"board_a": "a", "board_b": "b"}


def test_a_layer_warning_is_reported_with_its_code_and_parameters():
    warn = LayerStatus(level="warning", code="few_holes", params={"n": 2})
    issues = run(project(board(layers=(layer("copper", status=warn), layer("outline", Role.OUTLINE)))))
    w = only(issues, C.LAYER_ISSUE)
    assert w.severity is Severity.WARNING and w.layer_id == "copper" and w.params == {"status_code": "few_holes", "n": 2}
    assert blocking(issues) == []


def test_several_layer_types_on_in_one_board_warn_that_the_result_is_the_sum():
    issues = run(project(board(layers=with_layers(mask=True))))
    assert codes(issues) == [C.BOARD_LAYER_SUM]


def test_copper_and_outline_are_the_same_kind_and_the_holes_do_not_count():
    assert run(project(board(layers=with_layers(copper=True, outline=True, drill=True)))) == []


def test_different_types_in_different_boards_of_one_file_warn_once():
    p = project(board("a", x=30, y=41, w=40, h=40), board("b", x=100, y=41, w=40, h=40, layers=with_layers(copper=False, outline=False, mask=True)))
    issues = run(p)
    assert codes(issues) == [C.LAYER_TYPES_MIXED]


def test_the_mixed_warning_is_not_repeated_when_a_board_already_warns_of_the_sum():
    p = project(board("a", x=30, y=41, w=40, h=40, layers=with_layers(mask=True)),
                board("b", x=100, y=41, w=40, h=40, layers=with_layers(silk=True)))
    issues = run(p)
    assert codes(issues) == [C.BOARD_LAYER_SUM, C.BOARD_LAYER_SUM]               # one per board, and no "mixed" on top
    assert [i.board_id for i in issues] == ["a", "b"]


# ---- polarity ----------------------------------------------------------------------------------------------------
def test_a_polarity_that_changed_since_saving_warns():
    issues = run(project(polarity=Polarity.NEGATIVE), recipe=POSITIVE)
    w = only(issues, C.POLARITY_MISMATCH)
    assert w.params == {"project": "negative", "recipe": "positive"} and not w.blocking


def test_the_same_polarity_or_none_saved_does_not_warn():
    assert run(project(polarity=Polarity.NEGATIVE), recipe=NEGATIVE) == []
    assert run(project(polarity=None), recipe=NEGATIVE) == []


# ---- the list ----------------------------------------------------------------------------------------------------
def test_issues_come_in_a_fixed_order():
    bad = LayerStatus(level="error", code="x")
    p = project(board("a", x=20, y=41, layers=(layer("copper"), layer("mask", Role.MASK, status=bad))),
                board("b", x=40, y=41, w=40, h=40), polarity=Polarity.NEGATIVE)
    issues = run(p, exposure=None)
    order = codes(issues)
    assert order == [C.BOARD_OUTSIDE_PLANE, C.LAYER_ISSUE, C.LAYER_ERROR_ON, C.BOARD_LAYER_SUM, C.BOARDS_OVERLAP,
                     C.POLARITY_MISMATCH, C.DOSAGE_MISSING, C.EXPOSURE_INVALID]
    assert order == codes(run(p, exposure=None))                                 # and it is deterministic


def test_blocking_picks_only_the_blocking_ones_in_order():
    issues = run(project(printer_id=None), printer=None, exposure=None)
    assert codes(blocking(issues)) == [C.PRINTER_MISSING, C.EXPOSURE_INVALID]
    assert all(i.blocking for i in blocking(issues))


def test_issues_serialise_to_plain_json():
    import json
    issues = run(project(), exposure=ExposureValues(total_s=60, pulses=2, rest_s=5))
    data = json.loads(issues[0].model_dump_json())
    assert data == {"code": "flash_beyond_proven", "severity": "warning", "blocking": False, "board_id": None,
                    "layer_id": None, "params": {"flash_s": 30.0, "max_s": 20.0}}
