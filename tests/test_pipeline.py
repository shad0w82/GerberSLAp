"""From a project to the mask of the plane. The marker board (an off-centre pad on a known outline) pins down where things land in
pixels for every position, rotation and mirror; the rest covers holes, polarity, several boards, what is refused, the cache, and the
real boards of KiCad, Altium and EAGLE end to end."""
import math
from pathlib import Path

import numpy as np
import pytest
import testdata
from markerboard import PLANE, imported, marker_files, project_of

from gerberslap.core import Grid, area_or_rectangle, holes_geometry, layer_geometry, read_file
from gerberslap.model import C, LayerStatus, Polarity, Project, Role, Side
from gerberslap.services import pipeline
from gerberslap.services.importer import import_zip
from gerberslap.services.pipeline import PipelineCache, PipelineError, render

GRID = Grid(width=2560, height=1620, pitch=0.051)            # the plane of the LD-002H; the pipeline only sees a grid
P = GRID.pitch
S = 16                                                        # the supersampling of the final file; areas are right to about half a sample per edge


def run(project, files, polarity=Polarity.NEGATIVE, supersample=S, cache=None):
    return render(project, files, GRID, polarity, supersample=supersample, cache=cache)


def bbox_mm(cov, thr=0.5):
    rows, cols = np.nonzero(cov >= thr)
    x0, y1 = GRID.to_mm(cols.min(), rows.min())
    x1, y0 = GRID.to_mm(cols.max() + 1, rows.max() + 1)
    return x0, y0, x1, y1


def centroid_mm(cov):
    rows, cols = np.indices(cov.shape)
    w = cov.sum()
    x, y = GRID.to_mm((cols * cov).sum() / w + 0.5, (rows * cov).sum() / w + 0.5)
    return x, y


def area_mm2(cov):
    return float(cov.sum()) * P * P


@pytest.fixture(scope="module")
def marker():
    return imported(marker_files())


@pytest.fixture(scope="module")
def marker_drilled():
    return imported(marker_files(hole=True))


# ---- where things land, for every placement ----------------------------------------------------------------------
@pytest.mark.parametrize("angle,mirror,centre,size", [
    (0, False, (70.0, 48.0), (4, 2)),                     # offset (+10, +8) kept
    (0, True, (50.0, 48.0), (4, 2)),                      # mirrored left-right: (-10, +8)
    (90, False, (52.0, 50.0), (2, 4)),                    # rotated 90 deg counterclockwise: (-8, +10)
    (90, True, (52.0, 30.0), (2, 4)),                     # mirror first, then rotate: (-10, 8) -> (-8, -10)
    (180, False, (50.0, 32.0), (4, 2)),
    (270, False, (68.0, 30.0), (2, 4))])
def test_a_pad_lands_where_the_placement_says_and_has_the_right_size(marker, angle, mirror, centre, size):
    r = run(project_of(marker, angle=angle, mirror=mirror, on={"outline": False, "drill": False}), marker.files)
    cx, cy = centre
    expect = (cx - size[0] / 2, cy - size[1] / 2, cx + size[0] / 2, cy + size[1] / 2)
    assert bbox_mm(r.material) == pytest.approx(expect, abs=P * 1.01)           # to the pixel
    assert area_mm2(r.material) == pytest.approx(8.0, rel=0.004)
    assert centroid_mm(r.material) == pytest.approx(centre, abs=0.01)
    assert r.material.shape == (1620, 2560) and r.material.dtype == np.float32


def test_an_arbitrary_rotation_keeps_the_area_and_moves_the_pad_the_right_way(marker):
    r = run(project_of(marker, angle=30, on={"outline": False, "drill": False}), marker.files)
    a = math.radians(30)
    expect = (60 + 10 * math.cos(a) - 8 * math.sin(a), 40 + 10 * math.sin(a) + 8 * math.cos(a))
    assert centroid_mm(r.material) == pytest.approx(expect, abs=0.01)
    assert area_mm2(r.material) == pytest.approx(8.0, rel=0.004)


def test_the_placement_refers_to_the_centre_of_the_outline_whatever_is_on(marker):
    with_outline = run(project_of(marker, on={"drill": False}), marker.files)
    without = run(project_of(marker, on={"outline": False, "drill": False}), marker.files)
    assert centroid_mm(without.material) == pytest.approx((70, 48), abs=0.01)             # the pad did not move
    # the outline's outer edge is the board's extent plus half the stroke: 40.3 x 30.3 mm centred on the placement
    x0, y0, x1, y1 = bbox_mm(with_outline.material)
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((60, 40), abs=P) and (x1 - x0, y1 - y0) == pytest.approx((40.3, 30.3), abs=2 * P)


def test_the_outline_is_a_hollow_line_at_least_as_wide_as_the_minimum(marker):
    for width in (0.3, 1.0):
        r = run(project_of(marker, on={"copper": False, "drill": False}, min_outline=width), marker.files)
        x0, y0, x1, y1 = bbox_mm(r.material)
        assert (x1 - x0, y1 - y0) == pytest.approx((40 + width, 30 + width), abs=2 * P)
        assert area_mm2(r.material) == pytest.approx(140 * width, rel=0.02)
        r_, c_ = (int(v) for v in (GRID.to_pixel(60, 40)[1], GRID.to_pixel(60, 40)[0]))
        assert r.material[r_, c_] == 0                                                   # the inside is empty
    thin = run(project_of(marker, on={"copper": False, "drill": False}, min_outline=0.0), marker.files)
    assert area_mm2(thin.material) == pytest.approx(140 * 0.1, rel=0.05)             # the Gerber's own width (0.1) when it is larger


# ---- holes -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("angle,mirror", [(0, False), (30, False), (90, True), (137, True)])
def test_the_holes_are_subtracted_where_they_really_are(marker_drilled, angle, mirror):
    on_proj = project_of(marker_drilled, angle=angle, mirror=mirror, on={"outline": False})
    off_proj = project_of(marker_drilled, angle=angle, mirror=mirror, on={"outline": False, "drill": False})
    a = math.radians(angle)
    ox, oy = (-10 if mirror else 10), 8
    cx, cy = 60 + ox * math.cos(a) - oy * math.sin(a), 40 + ox * math.sin(a) + oy * math.cos(a)
    drilled, full = run(on_proj, marker_drilled.files), run(off_proj, marker_drilled.files)
    col, row = (int(v) for v in GRID.to_pixel(cx, cy))
    assert full.material[row, col] == 1.0 and drilled.material[row, col] == 0.0
    assert area_mm2(full.material) - area_mm2(drilled.material) == pytest.approx(math.pi * 0.5 ** 2, rel=0.03)


def test_the_holes_layer_off_leaves_the_pads_full_and_on_by_itself_draws_nothing(marker_drilled):
    only_holes = project_of(marker_drilled, on={"copper": False, "outline": False})
    with pytest.raises(PipelineError) as e:
        run(only_holes, marker_drilled.files)
    assert e.value.code == "no_layer_on"                                                 # the holes alone are not a layer


# ---- polarity ----------------------------------------------------------------------------------------------------
def test_polarity_is_applied_last(marker):
    proj = project_of(marker, on={"drill": False})
    neg, pos = run(proj, marker.files, Polarity.NEGATIVE), run(proj, marker.files, Polarity.POSITIVE)
    solid = neg.material >= 0.5
    assert np.array_equal(neg.mask, solid) and np.array_equal(pos.mask, ~solid)
    assert neg.lit_pixels + pos.lit_pixels == GRID.width * GRID.height
    assert np.array_equal(neg.material, pos.material)                                    # the material does not depend on it
    assert pos.polarity is Polarity.POSITIVE and pos.mask.dtype == bool


def test_with_positive_resist_everything_but_the_material_is_lit_including_outside_the_boards(marker):
    r = run(project_of(marker, on={"drill": False}), marker.files, Polarity.POSITIVE)
    assert r.mask[0, 0] and r.mask[-1, -1] and not r.mask[int(GRID.to_pixel(70, 48)[1]), int(GRID.to_pixel(70, 48)[0])]


# ---- several boards ----------------------------------------------------------------------------------------------
def second_board(imp, board_id, centre, **kw):
    b = project_of(imp, centre=centre, **kw).boards[0]
    return b.model_copy(update={"id": board_id})


def test_boards_far_apart_add_up_and_overlapping_ones_are_merged_not_doubled(marker):
    on = {"outline": False, "drill": False}
    one = run(project_of(marker, on=on), marker.files)
    apart = run(project_of(marker, centre=(40.0, 40.0), on=on, extra=(second_board(marker, "b2", (100.0, 40.0), on=on),)), marker.files)
    assert area_mm2(apart.material) == pytest.approx(2 * area_mm2(one.material), rel=0.004)
    # two pads 2 mm apart in x: 6 x 2 mm together, not 16
    over = run(project_of(marker, centre=(60.0, 40.0), on=on, extra=(second_board(marker, "b2", (62.0, 40.0), on=on),)), marker.files)
    assert area_mm2(over.material) == pytest.approx(12.0, rel=0.004) and over.material.max() <= 1.0


def test_each_board_keeps_its_own_layers_and_holes(marker, marker_drilled):
    b1 = project_of(marker_drilled, centre=(40.0, 40.0), on={"outline": False}).boards[0]
    b2 = project_of(marker, centre=(100.0, 40.0), on={"outline": False, "drill": False}).boards[0].model_copy(update={"id": "b2"})
    r = run(Project(printer_id="lab", recipe_id="pos35", boards=(b1, b2)), {**marker_drilled.files, **marker.files})
    # the first board is drilled, the second is not
    assert area_mm2(r.material) == pytest.approx(16.0 - math.pi * 0.25, rel=0.01)


# ---- the plane's edges -------------------------------------------------------------------------------------------
def test_a_board_that_goes_past_the_plane_is_clipped_and_it_is_said(marker):
    inside = run(project_of(marker, on={"drill": False}), marker.files)
    assert inside.issues == ()
    over = run(project_of(marker, centre=(120.0, 40.0), on={"drill": False}), marker.files)       # outline reaches x = 140
    (issue,) = over.issues
    assert (issue.code, issue.board_id) == (C.BOARD_CLIPPED, "b1") and issue.params["extent_mm"][2] == pytest.approx(140.15, abs=0.01)
    assert 0 < area_mm2(over.material) < 140 * 0.3                                       # what is on the plane is still drawn


def test_a_board_entirely_off_the_plane_renders_empty_with_the_warning(marker):
    r = run(project_of(marker, centre=(500.0, 500.0)), marker.files)
    assert area_mm2(r.material) == 0 and [i.code for i in r.issues] == [C.BOARD_CLIPPED]


# ---- what is refused ---------------------------------------------------------------------------------------------
def refused(project, files, code, **params):
    with pytest.raises(PipelineError) as e:
        run(project, files)
    assert e.value.code == code
    for k, v in params.items():
        assert e.value.params[k] == v, (k, e.value.params)
    return e.value


def test_nothing_on_is_refused(marker):
    refused(project_of(marker, on={"copper": False, "outline": False, "drill": False}), marker.files, "no_layer_on")
    refused(Project(printer_id="lab", recipe_id="pos35", boards=()), {}, "no_layer_on")


def test_a_board_with_nothing_drawing_is_refused_even_if_another_board_has_something(marker):
    off = second_board(marker, "b2", (100.0, 40.0), on={"copper": False, "outline": False})
    refused(project_of(marker, extra=(off,)), marker.files, "board_no_layer_on", board_id="b2")


def test_a_layer_with_an_error_that_is_on_is_refused(marker):
    proj = project_of(marker)
    bad = proj.boards[0].layers[0].model_copy(update={"status": LayerStatus(level="error", code="negative_image"), "on": True})
    proj = proj.model_copy(update={"boards": (proj.boards[0].model_copy(update={"layers": (bad, *proj.boards[0].layers[1:])}),)})
    refused(proj, marker.files, "layer_has_error", status_code="negative_image")


def test_a_file_missing_from_the_cache_is_refused_naming_it(marker):
    files = dict(marker.files)
    sha = next(f.sha256 for l in marker.board.layers if l.role is Role.COPPER for f in l.files)
    del files[sha]
    e = refused(project_of(marker), files, "file_missing")
    assert e.params["sha256"] == sha and e.params["file"] == "b-F_Cu.gbr"


def test_a_file_that_cannot_be_read_is_refused_with_the_reason(marker):
    bad = "%FSLAX46Y46*%\n%MOMM*%\n%ADD10NOSUCHMACRO,1.0X2.0*%\nD10*\nX1000000Y1000000D03*\nM02*\n"
    imp = imported({**marker_files(), "b-F_Cu.gbr": bad})
    assert imp.board.layers[0].status.code == "unreadable"                              # the importer marked it...
    proj = project_of(imp)
    layers = tuple(l.model_copy(update={"status": LayerStatus(), "on": True}) if l.role is Role.COPPER else l for l in proj.boards[0].layers)
    e = refused(proj.model_copy(update={"boards": (proj.boards[0].model_copy(update={"layers": layers}),)}), imp.files, "unreadable")
    assert "NOSUCHMACRO" in e.params["reason"] and e.params["file"] == "b-F_Cu.gbr"     # ...and the pipeline refuses it even unmarked


def test_a_negative_image_is_refused_even_when_the_project_does_not_say_so():
    files = {**marker_files()}
    files["b-F_Cu.gbr"] = "%TF.FilePolarity,Negative*%\n" + files["b-F_Cu.gbr"]
    imp = imported(files)
    proj = project_of(imp)
    layers = tuple(l.model_copy(update={"status": LayerStatus(), "on": True}) if l.role is Role.COPPER else l for l in proj.boards[0].layers)
    refused(proj.model_copy(update={"boards": (proj.boards[0].model_copy(update={"layers": layers}),)}), imp.files, "negative_layer", file="b-F_Cu.gbr")


def test_less_than_8_by_8_samples_is_refused(marker):
    with pytest.raises(ValueError):
        run(project_of(marker), marker.files, supersample=4)


# ---- the cache ---------------------------------------------------------------------------------------------------
@pytest.fixture
def spy(monkeypatch):
    calls = {"read": 0, "geometry": 0}
    real_read, real_geom = pipeline.read_file, pipeline.layer_geometry

    def read(*a, **k):
        calls["read"] += 1
        return real_read(*a, **k)

    def geom(*a, **k):
        calls["geometry"] += 1
        return real_geom(*a, **k)
    monkeypatch.setattr(pipeline, "read_file", read)
    monkeypatch.setattr(pipeline, "layer_geometry", geom)
    return calls


# ---- the solder mask: the board's area minus the openings its file draws -------------------------------------------
MASK_ONLY = {"copper": False, "outline": False, "drill": False, "mask": True}
OPENING_MM2 = 6 * 4                                            # the marker mask's one opening
BOARD_MM2 = 40 * 30


def with_mask_on(imp, **kw):
    """The project with the mask switched on (the importer starts it off)."""
    return project_of(imp, on={**MASK_ONLY, **kw.pop("on", {})}, **kw)


def lit_at(cov, x, y):
    col, row = GRID.to_pixel(x, y)
    return float(cov[int(row), int(col)])


@pytest.fixture(scope="module")
def marker_mask():
    return imported(marker_files(mask=True))


def test_the_mask_is_the_board_minus_its_opening(marker_mask):
    r = run(with_mask_on(marker_mask), marker_mask.files)
    assert area_mm2(r.material) == pytest.approx(BOARD_MM2 - OPENING_MM2, rel=0.004)
    x0, y0, x1, y1 = bbox_mm(r.material)
    assert (x0, y0, x1, y1) == pytest.approx((40, 25, 80, 55), abs=P * 1.01)                 # the board's 40 x 30 mm, at the placement
    assert lit_at(r.material, 60, 40) == 1.0                                                   # the middle of the board: mask
    assert lit_at(r.material, 70, 48) == 0.0                                                   # the opening, where the pad is
    assert lit_at(r.material, 30, 40) == 0.0 and lit_at(r.material, 60, 70) == 0.0           # outside the board: nothing


def test_the_exposure_of_a_negative_acting_mask_lights_the_mask_and_a_positive_one_the_rest(marker_mask):
    proj = with_mask_on(marker_mask)
    neg, pos = run(proj, marker_mask.files, Polarity.NEGATIVE), run(proj, marker_mask.files, Polarity.POSITIVE)
    assert neg.mask[int(GRID.to_pixel(60, 40)[1]), int(GRID.to_pixel(60, 40)[0])] and not neg.mask[int(GRID.to_pixel(70, 48)[1]), int(GRID.to_pixel(70, 48)[0])]
    assert np.array_equal(neg.mask, ~pos.mask)


@pytest.mark.parametrize("angle,mirror,centre,size", [
    (0, False, (70.0, 48.0), (6, 4)), (0, True, (50.0, 48.0), (6, 4)), (90, False, (52.0, 50.0), (4, 6)),
    (90, True, (52.0, 30.0), (4, 6)), (180, False, (50.0, 32.0), (6, 4)), (270, False, (68.0, 30.0), (4, 6))])
def test_the_opening_lands_where_the_placement_says_with_every_rotation_and_mirror(marker_mask, angle, mirror, centre, size):
    r = run(with_mask_on(marker_mask, angle=angle, mirror=mirror), marker_mask.files)
    x0, y0, x1, y1 = bbox_mm(r.material)
    c0, r0 = (int(round(v)) + 3 for v in GRID.to_pixel(x0, y1))                                # inside the board, away from its edge
    c1, r1 = (int(round(v)) - 3 for v in GRID.to_pixel(x1, y0))
    dark = 1.0 - r.material[r0:r1, c0:c1]                                                      # what is not mask there: the opening
    rows, cols = np.indices(dark.shape)
    opening = GRID.to_mm(c0 + (dark * cols).sum() / dark.sum() + 0.5, r0 + (dark * rows).sum() / dark.sum() + 0.5)
    assert opening == pytest.approx(centre, abs=0.02)
    assert dark.sum() * P * P == pytest.approx(OPENING_MM2, rel=0.01)


def test_the_area_comes_from_the_outline_even_when_the_outline_is_off(marker_mask):
    off = run(with_mask_on(marker_mask), marker_mask.files)
    on = run(with_mask_on(marker_mask, on={"outline": True}), marker_mask.files)
    assert area_mm2(off.material) == pytest.approx(BOARD_MM2 - OPENING_MM2, rel=0.004)         # no line drawn, the area is still the board
    assert area_mm2(on.material) - area_mm2(off.material) == pytest.approx(0.5 * 140 * 0.3, rel=0.05)    # the outline adds its outer half


def test_a_cutout_drawn_in_the_outline_is_not_mask():
    imp = imported(marker_files(mask=True, cutout=True))
    r = run(with_mask_on(imp), imp.files)
    assert area_mm2(r.material) == pytest.approx(BOARD_MM2 - OPENING_MM2 - math.pi * 4, rel=0.005)
    assert lit_at(r.material, 50, 40) == 0.0 and lit_at(r.material, 55, 40) == 1.0               # the cutout is 10 mm left of the centre


def test_the_holes_layer_cuts_its_holes_out_of_the_mask():
    files = {**marker_files(mask=True), "b-PTH.drl": testdata.excellon("Plated,1,2,PTH", {1: 1.0}, [(1, 20.0, 10.0)])}
    imp = imported(files)
    no = run(with_mask_on(imp), imp.files)
    yes = run(with_mask_on(imp, on={"drill": True}), imp.files)
    assert area_mm2(no.material) - area_mm2(yes.material) == pytest.approx(math.pi * 0.25, rel=0.03)
    assert lit_at(no.material, 50, 30) == 1.0 and lit_at(yes.material, 50, 30) == 0.0              # the hole at (20, 10), 10 left and 10 below the centre


def test_what_the_mask_file_says_about_its_polarity_is_not_used():
    files = marker_files(mask=True)
    declared = {**files, "b-F_Mask.gbr": "%TF.FilePolarity,Negative*%\n" + files["b-F_Mask.gbr"]}
    a, b = imported(files), imported(declared)
    ra, rb = run(with_mask_on(a), a.files), run(with_mask_on(b), b.files)
    assert next(l for l in b.board.layers if l.role is Role.MASK).status.level == "ok"
    assert np.array_equal(ra.mask, rb.mask) and area_mm2(rb.material) == pytest.approx(BOARD_MM2 - OPENING_MM2, rel=0.004)


def test_copper_and_mask_together_are_the_sum_of_the_two(marker_mask):
    both = run(with_mask_on(marker_mask, on={"copper": True}), marker_mask.files)
    assert lit_at(both.material, 70, 48) == 1.0                                                 # the pad is lit again, inside the opening
    assert lit_at(both.material, 70, 49.5) == 0.0                                               # the rest of the opening (y 46 to 50) stays dark
    assert area_mm2(both.material) == pytest.approx(BOARD_MM2 - OPENING_MM2 + 8, rel=0.004)


def test_an_outline_that_does_not_close_gives_the_extent_rectangle_and_says_so():
    imp = imported(marker_files(mask=True, open_outline=True))
    r = run(with_mask_on(imp), imp.files)
    assert area_mm2(r.material) == pytest.approx(BOARD_MM2 - OPENING_MM2, rel=0.004)             # the extent is the same 40 x 30
    est = [i for i in r.issues if i.code == C.BOARD_AREA_ESTIMATED]
    assert len(est) == 1 and est[0].params == {"reason": "not_closed"} and est[0].board_id == "b1" and est[0].severity.value == "warning"


def test_a_closed_outline_raises_no_estimate_and_neither_does_a_board_without_a_mask(marker_mask):
    assert not [i for i in run(with_mask_on(marker_mask), marker_mask.files).issues if i.code == C.BOARD_AREA_ESTIMATED]
    imp = imported(marker_files(open_outline=True))
    assert not [i for i in run(project_of(imp), imp.files).issues if i.code == C.BOARD_AREA_ESTIMATED]       # no mask: the area is not used


def test_a_board_without_an_outline_file_uses_the_rectangle_of_what_there_is():
    files = marker_files(mask=True)
    del files["b-Edge_Cuts.gbr"]
    imp = imported(files)
    r = run(with_mask_on(imp), imp.files)
    assert [i.params for i in r.issues if i.code == C.BOARD_AREA_ESTIMATED] == [{"reason": "no_outline"}]


def test_the_mask_material_follows_the_outline_file_not_a_stale_cache():
    """Two boards share the mask file but not the outline: with the outline off the layer lists are alike, only the area differs."""
    small = {**marker_files(mask=True)}
    small["b-Edge_Cuts.gbr"] = testdata.gerber("Profile,NP", ["D10*", testdata.move(30, 12), testdata.draw(50, 12), testdata.draw(50, 32),
                                                               testdata.draw(30, 32), testdata.draw(30, 12)], ["%ADD10C,0.100000*%"])
    big_imp, small_imp = imported(marker_files(mask=True)), imported(small)
    cache = PipelineCache()
    big = run(with_mask_on(big_imp), big_imp.files, cache=cache)
    little = run(with_mask_on(small_imp), small_imp.files, cache=cache)
    assert area_mm2(big.material) == pytest.approx(1176, rel=0.004) and area_mm2(little.material) == pytest.approx(20 * 20 - OPENING_MM2, rel=0.004)


def test_two_outlines_with_the_same_extent_but_another_shape_give_other_areas():
    """Same size and centre, so only the outline file tells them apart: one of them has a cutout."""
    plain, cut = imported(marker_files(mask=True)), imported(marker_files(mask=True, cutout=True))
    cache = PipelineCache()
    a = run(with_mask_on(plain), plain.files, cache=cache)
    b = run(with_mask_on(cut), cut.files, cache=cache)
    assert area_mm2(a.material) - area_mm2(b.material) == pytest.approx(math.pi * 4, rel=0.01)


def test_the_order_of_the_layers_changes_nothing_in_the_exposure_and_costs_no_rebuild(marker_mask, spy):
    """The user reorders the layers to change how they are drawn on screen; the exposure is the sum of the layers on, whatever the order."""
    proj = project_of(marker_mask, on={"copper": True, "mask": True, "outline": True, "drill": False})
    board = proj.boards[0]
    shuffled = proj.model_copy(update={"boards": (board.model_copy(update={"layers": tuple(reversed(board.layers))}),)})
    cache = PipelineCache()
    a = run(proj, marker_mask.files, cache=cache)
    built = dict(spy)
    b = run(shuffled, marker_mask.files, cache=cache)
    assert np.array_equal(a.mask, b.mask) and np.array_equal(a.material, b.material)
    assert spy == built                                                                         # the same material: nothing is read or built again
    assert np.array_equal(run(shuffled, marker_mask.files).mask, a.mask)                         # and the same without any cache


def test_a_mask_file_that_cannot_be_read_is_refused():
    files = {**marker_files(mask=True), "b-F_Mask.gbr": "%FSLAX46Y46*%\n%MOMM*%\n%ADD10NOSUCHMACRO,1.0X2.0*%\nD10*\nX1000000Y1000000D03*\nM02*\n"}
    imp = imported(files)
    mask = next(l for l in imp.board.layers if l.role is Role.MASK)
    assert (mask.status.level, mask.status.code) == ("error", "unreadable")
    proj = with_mask_on(imp)
    layers = tuple(l.model_copy(update={"status": LayerStatus(), "on": True}) if l.role is Role.MASK else l for l in proj.boards[0].layers)
    refused(proj.model_copy(update={"boards": (proj.boards[0].model_copy(update={"layers": layers}),)}), imp.files, "unreadable")


def test_moving_a_board_does_not_rebuild_the_mask(marker_mask, spy):
    cache = PipelineCache()
    run(with_mask_on(marker_mask), marker_mask.files, cache=cache)
    first = dict(spy)
    run(with_mask_on(marker_mask, centre=(70.0, 45.0), angle=17, mirror=True), marker_mask.files, cache=cache)
    assert spy == first and first["read"] == 2                                                   # the mask and the outline, once each


def test_moving_a_board_does_not_read_the_files_again(marker, spy):
    cache = PipelineCache()
    run(project_of(marker), marker.files, cache=cache)
    after_first = dict(spy)
    assert after_first["read"] == 2 and after_first["geometry"] == 1                       # copper and outline, once
    for centre in ((61.0, 40.0), (70.0, 45.0)):
        run(project_of(marker, centre=centre, angle=17, mirror=True), marker.files, cache=cache)
    assert spy == after_first


def test_switching_a_layer_or_the_outline_width_builds_a_new_material_but_does_not_reparse(marker, spy):
    cache = PipelineCache()
    run(project_of(marker), marker.files, cache=cache)
    run(project_of(marker, on={"outline": False}), marker.files, cache=cache)
    run(project_of(marker, min_outline=1.0), marker.files, cache=cache)
    assert spy["read"] == 2                                                                 # the parsed files are reused
    assert spy["geometry"] == 3                                                             # the copper shape is rebuilt per material


def test_the_cache_does_not_skip_the_checks(marker):
    cache = PipelineCache()
    proj = project_of(marker)
    run(proj, marker.files, cache=cache)                                                    # fills the cache
    bad = proj.boards[0].layers[0].model_copy(update={"status": LayerStatus(level="error", code="x")})
    again = proj.model_copy(update={"boards": (proj.boards[0].model_copy(update={"layers": (bad, *proj.boards[0].layers[1:])}),)})
    with pytest.raises(PipelineError) as e:
        run(again, marker.files, cache=cache)
    assert e.value.code == "layer_has_error"


def test_a_failure_is_not_cached(marker):
    cache = PipelineCache()
    files = dict(marker.files)
    sha = next(f.sha256 for l in marker.board.layers if l.role is Role.COPPER for f in l.files)
    saved = files.pop(sha)
    with pytest.raises(PipelineError):
        run(project_of(marker), files, cache=cache)
    files[sha] = saved
    assert area_mm2(run(project_of(marker), files, cache=cache).material) > 0


def test_the_cache_is_bounded_and_forgets_the_oldest():
    cache = PipelineCache(max_entries=2)
    for k in "abc":
        cache.get(k, lambda k=k: k)
    assert len(cache) == 2 and cache.get("a", lambda: "again") == "again"                 # "a" was evicted
    assert cache.get("c", lambda: "no") == "c"


def test_rendering_is_repeatable_and_leaves_its_inputs_alone(marker):
    proj, files = project_of(marker), dict(marker.files)
    before = dict(files)
    a, b = run(proj, files), run(proj, files)
    assert np.array_equal(a.material, b.material) and np.array_equal(a.mask, b.mask) and files == before


def test_8_and_16_samples_agree_to_a_few_edge_pixels(marker):
    proj = project_of(marker, angle=30)
    lo, hi = run(proj, marker.files, supersample=8), run(proj, marker.files, supersample=16)
    assert np.count_nonzero(lo.mask != hi.mask) < 0.02 * np.count_nonzero(hi.material >= 0.5)         # only edge pixels differ
    assert area_mm2(lo.material) == pytest.approx(area_mm2(hi.material), rel=0.005)


# ---- the real boards ---------------------------------------------------------------------------------------------
EXT = Path(__file__).resolve().parent.parent / "experiments" / "fase2" / "external"
KICAD, ALTIUM, EAGLE_NEW = EXT / "kicad_uni_mosfet_key.zip", EXT / "altium_flight_controller.zip", EXT / "eagle9_torazza.zip"


def real(path):
    imp = import_zip(path, board_id="b1", source_name=path.name, plane=PLANE)
    return imp, Project(printer_id="lab", recipe_id="pos35", boards=(imp.board,))


@pytest.mark.skipif(not KICAD.exists(), reason="the KiCad example is not in experiments/fase2/external/")
def test_the_real_kicad_board_is_30_mm_square_centred_and_its_holes_line_up_with_its_pads():
    imp, proj = real(KICAD)
    r = run(proj, imp.files, Polarity.POSITIVE)
    assert r.issues == () and r.material.shape == (1620, 2560)
    x0, y0, x1, y1 = bbox_mm(r.material)
    assert (x1 - x0, y1 - y0) == pytest.approx((30.3, 30.3), abs=2 * P)                      # the 30 mm outline plus the 0.3 mm minimum line
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((65.28, 41.31), abs=P)
    # every hole of the drill files: where the copper is drawn under it the pixel is empty with the holes on and solid with them off
    drill = next(l for l in imp.board.layers if l.role is Role.DRILL)
    holes = [holes_geometry(read_file(f.name, imp.files[f.sha256]).file) for f in drill.files]
    off = run(project_of_real(imp, drill=False), imp.files)
    checked = 0
    for g in holes:
        for hole in getattr(g, "geoms", [g]):
            if hole.is_empty:                                                               # the non-plated file has no holes
                continue
            c = hole.centroid
            col, row = (int(v) for v in GRID.to_pixel(65.28 + (c.x - imp.board.source_center[0]), 41.31 + (c.y - imp.board.source_center[1])))
            if off.material[row, col] == 1.0:
                assert r.material[row, col] == 0.0, (c.x, c.y)
                checked += 1
    assert checked >= 3


def project_of_real(imp, drill):
    layers = tuple(l.model_copy(update={"on": l.on and (drill or l.role is not Role.DRILL)}) for l in imp.board.layers)
    return Project(printer_id="lab", recipe_id="pos35", boards=(imp.board.model_copy(update={"layers": layers}),))


@pytest.mark.skipif(not ALTIUM.exists(), reason="the Altium example is not in experiments/fase2/external/")
def test_the_real_altium_board_fits_the_plane_and_is_centred():
    imp, proj = real(ALTIUM)
    r = run(proj, imp.files, Polarity.NEGATIVE)
    assert r.issues == () and r.lit_pixels > 0
    x0, y0, x1, y1 = bbox_mm(r.material)
    assert (x1 - x0, y1 - y0) == pytest.approx((74.42 + 0.3, 57.25 + 0.3), abs=0.1)
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((65.28, 41.31), abs=0.1)


@pytest.mark.skipif(not EAGLE_NEW.exists(), reason="the EAGLE 9 example is not in experiments/fase2/external/")
def test_the_real_eagle_board_is_larger_than_this_plane_and_is_clipped_with_a_warning():
    imp, proj = real(EAGLE_NEW)                                                             # 172 x 112 mm on a 130.56 x 82.62 plane
    r = run(proj, imp.files, Polarity.NEGATIVE)
    assert [i.code for i in r.issues] == [C.BOARD_CLIPPED] and r.lit_pixels > 0
    assert bbox_mm(r.material)[0] == pytest.approx(0.0, abs=P) and bbox_mm(r.material)[2] == pytest.approx(130.56, abs=P)


@pytest.mark.parametrize("path", [KICAD, ALTIUM, EAGLE_NEW], ids=["kicad", "altium", "eagle9"])
@pytest.mark.parametrize("side", [Side.TOP, Side.BOTTOM])
def test_the_real_boards_masks_are_the_board_minus_the_openings_their_files_draw(path, side):
    """Whatever the program (two declare the mask negative, one nothing), the file draws the openings and the pipeline exposes the rest."""
    import shapely
    from shapely.affinity import translate
    from shapely.geometry import box
    if not path.exists():
        pytest.skip(f"{path.name} is not in experiments/fase2/external/")
    imp, _ = real(path)
    b = imp.board
    layers = tuple(l.model_copy(update={"on": l.role is Role.MASK and l.side is side}) for l in b.layers)
    proj = Project(printer_id="lab", recipe_id="neg", boards=(b.model_copy(update={"layers": layers}),))
    r = run(proj, imp.files, Polarity.NEGATIVE)

    reader = pipeline.Reader(imp.files, PipelineCache())
    outline = next(l for l in b.layers if l.role is Role.OUTLINE)
    area, why = area_or_rectangle(reader.read(outline.files[0]).file, size=(b.size.width_mm, b.size.height_mm), center=b.source_center)
    drawn = layer_geometry(reader.read(next(l for l in layers if l.on).files[0]).file)
    assert why is None and 0.01 < drawn.intersection(area).area / area.area < 0.15           # the openings are a few percent of the board

    def placed(g):                                                                          # file coordinates -> plane, clipped to the plane
        return translate(g, b.placement.x - b.source_center[0], b.placement.y - b.source_center[1]).intersection(box(0, 0, 130.56, 82.62))
    assert area_mm2(r.material) == pytest.approx(placed(area.difference(drawn)).area, rel=0.004)
    points = [placed(g.representative_point()) for g in sorted(shapely.get_parts(drawn), key=lambda g: -g.area)]
    points = [pt for pt in points if not pt.is_empty][:8]                                   # the openings whose middle is on the plane
    assert points and all(lit_at(r.material, pt.x, pt.y) == 0.0 for pt in points)
    solid = placed(area.difference(drawn.buffer(0.3)))
    assert lit_at(r.material, *shapely.get_coordinates(solid.representative_point())[0]) == 1.0
