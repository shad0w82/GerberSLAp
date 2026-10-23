import math

import pytest
from shapely.geometry import Point, box

import testdata
from gerberslap.core import (Placement, compose_material, extent_center, extent_size, holes_geometry, layer_geometry,
                             outline_lines, outline_strokes, place, read_file)

ALL = list(testdata.TESTS) + list(testdata.DRILLS)


def geom_of(data_dir, name):
    return layer_geometry(read_file(name, (data_dir / name).read_bytes()).file)


def same_shape(a, b, rel=1e-3):
    """Shape equality, not just extents: a rotated rectangle and its bounding box share a bounding box."""
    return a.symmetric_difference(b).area <= max(rel * b.area, 1e-3)


@pytest.mark.parametrize("name", ALL)
def test_geometry_matches_the_independent_reference(data_dir, reference, name):
    assert same_shape(geom_of(data_dir, name), reference[name])


# --- named regressions (each one was a real mistake or a gerbonara defect) ---------------------------------
def test_rotated_rectangle_is_not_its_bounding_box(data_dir):
    g = geom_of(data_dir, "f06_macros.gbr").intersection(box(12, 12, 18, 18))
    assert g.area == pytest.approx(3.0, rel=1e-3)                      # 3 x 1 mm; its bounding box would be 7.3 mm2


def test_step_and_repeat_is_expanded(data_dir):
    g = geom_of(data_dir, "f08_step_repeat.gbr")
    assert g.area == pytest.approx(6 * math.pi * 0.25, rel=1e-3)
    assert g.bounds == pytest.approx((9.5, 9.5, 20.5, 14.5), abs=1e-3)


def test_step_and_repeat_with_two_objects_per_block():
    text = ("%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,1.000000*%\nG75*\nG01*\n%LPD*%\n%SRX3Y2I5.000000J4.000000*%\nD10*\n"
            "X10000000Y10000000D03*\nX12000000Y10000000D03*\n%SR*%\nM02*\n")
    g = layer_geometry(read_file("sr2.gbr", text.encode()).file)
    assert g.area == pytest.approx(12 * math.pi * 0.25, rel=1e-3)


def test_macro_primitive_22_lower_left_rectangle(data_dir):
    g = geom_of(data_dir, "f12_macro_22_lower_left.gbr")
    assert g.area == pytest.approx(2.0, rel=1e-3)                      # 2 x 1 mm, rotated 30 degrees
    assert same_shape(g, testdata.TESTS["f12_macro_22_lower_left.gbr"][1])


def test_macro_primitive_2_is_the_old_name_of_20():
    text = ("%FSLAX46Y46*%\n%MOMM*%\n%AMOld*\n2,1,0.3,0,0,2,0,0*%\n%ADD10Old*%\nG75*\nG01*\n%LPD*%\nD10*\n"
            "X10000000Y10000000D03*\nM02*\n")
    g = layer_geometry(read_file("old2.gbr", text.encode()).file)
    assert g.area == pytest.approx(0.6, rel=1e-3)


def test_island_inside_a_hole_survives(data_dir):
    g = geom_of(data_dir, "f13_islands_in_holes.gbr")
    assert g.contains(Point(17, 17))                                    # island centre
    assert not g.contains(Point(17 + 2.5, 17))                          # clearance ring
    assert same_shape(g, testdata.TESTS["f13_islands_in_holes.gbr"][1])


def test_clear_polarity_removes_only_what_is_drawn_before_it(data_dir):
    g = geom_of(data_dir, "f07_clear.gbr")
    assert not g.contains(Point(15 + 1.5, 15))                          # inside the clear disc, outside the new dot
    assert g.contains(Point(15, 15))                                    # dark dot drawn after the clear


def test_gerbonara_debug_print_does_not_reach_stdout(data_dir, capsys):
    geom_of(data_dir, "f11_macro_prims.gbr")                               # macro polygon primitive: gerbonara prints
    assert capsys.readouterr().out == ""


def test_inch_file_is_converted_to_mm(data_dir):
    g = geom_of(data_dir, "f10_inch.gbr")
    assert g.bounds[0] == pytest.approx(1 * 25.4 - 0.02 * 25.4, abs=1e-3)


# --- outline, holes, material -------------------------------------------------------------------------
@pytest.fixture(scope="module")
def board(synth):
    files, refs = synth
    parse = lambda name: read_file(name, files[name].encode()).file          # noqa: E731
    return {"cu": parse("F_Cu.gbr"), "edge": parse("Edge_Cuts.gbr"), "pth": parse("PTH.drl"),
            "npth": parse("NPTH.drl"), "refs": refs}


def test_board_size_comes_from_the_centre_line_not_the_stroke(board):
    lines = outline_lines(board["edge"])
    assert extent_size(lines) == pytest.approx((80.0, 50.0), abs=1e-6)       # the 0.1 mm stroke would give 80.1 x 50.1
    assert extent_center(lines) == pytest.approx((50.0, 35.0), abs=1e-6)


def test_outline_stroke_is_centred_and_at_least_the_minimum_width(board):
    ref = board["refs"]["outline_centerline"]
    wide = outline_strokes(board["edge"], min_width=0.3)                     # Gerber says 0.1: the minimum wins
    assert same_shape(wide, ref.buffer(0.15, quad_segs=64), rel=2e-3)
    narrow = outline_strokes(board["edge"], min_width=0.05)                  # the Gerber width wins
    assert same_shape(narrow, ref.buffer(0.05, quad_segs=64), rel=2e-3)


def test_open_outline_still_gives_a_stroke(data_dir):
    f = read_file("f09_outline_open.gbr", (data_dir / "f09_outline_open.gbr").read_bytes()).file
    s = outline_strokes(f, min_width=0.1)
    assert same_shape(s, testdata.TESTS["f09_outline_open.gbr"][1], rel=2e-3)


def test_holes_include_plated_unplated_and_slots(board):
    holes = holes_geometry(board["pth"]).union(holes_geometry(board["npth"]))
    assert same_shape(holes, board["refs"]["holes"])
    assert holes.contains(Point(48, 55))                                    # inside the 1 x 6 mm slot


def test_material_is_copper_plus_outline_minus_holes(board):
    refs = board["refs"]
    holes = holes_geometry(board["pth"]).union(holes_geometry(board["npth"]))
    mat = compose_material([layer_geometry(board["cu"])], outline_strokes(board["edge"], 0.3), holes)
    expected = refs["copper"].union(refs["outline_centerline"].buffer(0.15, quad_segs=64)).difference(refs["holes"])
    assert same_shape(mat, expected, rel=2e-3)
    assert mat.intersection(refs["holes"].buffer(-0.001)).area < 1e-4        # nothing left inside any hole


def test_a_through_hole_pad_becomes_a_ring(board):
    holes = holes_geometry(board["pth"])
    mat = compose_material([layer_geometry(board["cu"])], None, holes)
    pad = mat.intersection(box(26.62, 29, 28.62, 31))                        # pad 3, nothing else nearby
    assert pad.area == pytest.approx(math.pi * (0.8 ** 2 - 0.45 ** 2), rel=2e-3)


def test_without_the_holes_layer_nothing_is_subtracted(board):
    """The holes layer can be switched off: then no hole is cut and the pads stay solid discs."""
    cu = layer_geometry(board["cu"])
    mat = compose_material([cu], None, None)
    assert mat.area == pytest.approx(cu.area, rel=1e-9)
    pad = mat.intersection(box(26.62, 29, 28.62, 31))
    assert pad.area == pytest.approx(math.pi * 0.8 ** 2, rel=2e-3)             # a full disc, not a ring


def test_holes_are_subtracted_from_any_layer_not_only_copper(board):
    """The mask and silkscreen use the same rule: material minus holes, whatever the layer."""
    big = box(0, 0, 100, 100)
    out = compose_material([big], None, holes_geometry(board["pth"]))
    assert out.area == pytest.approx(big.area - holes_geometry(board["pth"]).area, rel=1e-6)


# --- placement ------------------------------------------------------------------------------------------
def test_rotation_is_counterclockwise_and_mirror_comes_first():
    c = (10.0, 20.0)
    q = place(Point(1, 0), Placement(c, angle=90), (0, 0))
    assert (q.x, q.y) == pytest.approx((10.0, 21.0), abs=1e-9)               # (1,0) rotated 90 ccw -> (0,1)
    q = place(Point(1, 0), Placement(c, angle=90, mirror=True), (0, 0))
    assert (q.x, q.y) == pytest.approx((10.0, 19.0), abs=1e-9)               # mirrored to (-1,0), then -> (0,-1)
    q = place(Point(1, 0), Placement(c, mirror=True), (0, 0))
    assert (q.x, q.y) == pytest.approx((9.0, 20.0), abs=1e-9)


def test_the_board_centre_lands_on_the_target_whatever_the_transform():
    g = box(0, 0, 40, 10)
    src = extent_center(g)
    for angle in (0, 37, 90, 180, 271.5):
        for mirror in (False, True):
            p = place(g, Placement((65.28, 41.31), angle, mirror), src)
            assert extent_center(p) == pytest.approx((65.28, 41.31), abs=1e-6)     # a rectangle is centrally symmetric
            assert p.centroid.x == pytest.approx(65.28, abs=1e-6)
            assert p.centroid.y == pytest.approx(41.31, abs=1e-6)
            assert p.area == pytest.approx(g.area, rel=1e-9)


def test_mirror_reverses_an_asymmetric_shape():
    from shapely.geometry import Polygon
    ell = Polygon([(0, 0), (4, 0), (4, 1), (1, 1), (1, 3), (0, 3)])
    src = extent_center(ell)
    flipped = place(ell, Placement(src, mirror=True), src)
    assert not flipped.equals(ell)
    again = place(flipped, Placement(src, mirror=True), src)
    assert again.equals_exact(ell, 1e-9) or again.symmetric_difference(ell).area < 1e-9
