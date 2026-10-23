"""The area of a board: what the outline file encloses. Closed contours are filled with the even-odd rule (a contour inside another is
a cut-out), pieces whose ends differ by a few micrometres are joined, and nothing is guessed when the contours do not make up the
whole drawing."""
import math
import random
from pathlib import Path

import pytest
from shapely.geometry import Point, Polygon, box

import testdata
from gerberslap.core import area_or_rectangle, board_area, read_file

REPO = Path(__file__).resolve().parent.parent
EXT = REPO / "experiments" / "fase2" / "external"
RECT = [(10, 5), (50, 5), (50, 35), (10, 35), (10, 5)]                  # 40 x 30 mm, centre (30, 20)


def outline(*contours, width=0.1, extra=()):
    """An outline file: each contour is a list of points drawn with lines (a contour is closed when its last point is its first)."""
    body = ["D10*"]
    for pts in contours:
        body += [testdata.move(*pts[0]), *(testdata.draw(*p) for p in pts[1:])]
    return testdata.gerber("Profile,NP", [*body, *extra], [f"%ADD10C,{width:.6f}*%"])


def area_of(text, **kw):
    return board_area(read_file("outline.gbr", text.encode()).file, **kw)


def circle_ops(cx, cy, r):
    """A full circle as one arc starting and ending on the right-hand point, drawn counterclockwise."""
    return [testdata.move(cx + r, cy), *testdata.arc(cx + r, cy, cx + r, cy, cx, cy)]


def same(a, b, tol=0.02):
    return a.symmetric_difference(b).area <= tol


# ---- what it returns --------------------------------------------------------------------------------------------
def test_a_closed_rectangle_gives_its_interior():
    a = area_of(outline(RECT))
    assert a.reason is None and same(a.geometry, box(10, 5, 50, 35))
    assert a.geometry.area == pytest.approx(1200, abs=0.05)


def test_the_width_of_the_line_does_not_change_the_area():
    assert area_of(outline(RECT, width=0.05)).geometry.area == pytest.approx(area_of(outline(RECT, width=0.8)).geometry.area, abs=0.05)


def test_the_order_and_direction_of_the_segments_do_not_matter():
    pieces = list(zip(RECT, RECT[1:]))
    random.Random(7).shuffle(pieces)
    body = ["D10*"]
    for (x0, y0), (x1, y1) in pieces:                                       # each side on its own, some of them backwards
        body += [testdata.move(x1, y1), testdata.draw(x0, y0)] if (x0 + y0) % 20 else [testdata.move(x0, y0), testdata.draw(x1, y1)]
    text = testdata.gerber("Profile,NP", body, ["%ADD10C,0.100000*%"])
    assert same(area_of(text).geometry, box(10, 5, 50, 35))


def test_a_closed_contour_inside_another_is_a_cutout():
    text = outline(RECT, extra=circle_ops(20, 20, 2) + circle_ops(40, 20, 1.5))
    g = area_of(text).geometry
    assert g.area == pytest.approx(1200 - math.pi * 2 ** 2 - math.pi * 1.5 ** 2, rel=2e-3)
    assert len(g.interiors) == 2 and not g.contains(Point(20, 20)) and g.contains(Point(30, 20))


def test_an_island_inside_a_cutout_is_board_again():
    big = [(15, 10), (45, 10), (45, 30), (15, 30), (15, 10)]                   # a cutout 30 x 20 inside the board...
    island = [(25, 15), (35, 15), (35, 25), (25, 25), (25, 15)]                # ...with a 10 x 10 island in it
    g = area_of(outline(RECT, big, island)).geometry
    assert g.area == pytest.approx(1200 - 600 + 100, abs=0.1)
    assert g.contains(Point(30, 20)) and not g.contains(Point(20, 20)) and g.contains(Point(12, 7))


def test_two_separate_contours_are_two_boards():
    other = [(60, 5), (80, 5), (80, 35), (60, 35), (60, 5)]
    g = area_of(outline(RECT, other)).geometry
    assert g.area == pytest.approx(1200 + 600, abs=0.1) and len(g.geoms) == 2


def test_rounded_corners_are_followed():
    r = 3.0
    ops = [testdata.move(10 + r, 5), testdata.draw(50 - r, 5), *testdata.arc(50 - r, 5, 50, 5 + r, 50 - r, 5 + r),
           testdata.draw(50, 35 - r), *testdata.arc(50, 35 - r, 50 - r, 35, 50 - r, 35 - r),
           testdata.draw(10 + r, 35), *testdata.arc(10 + r, 35, 10, 35 - r, 10 + r, 35 - r),
           testdata.draw(10, 5 + r), *testdata.arc(10, 5 + r, 10 + r, 5, 10 + r, 5 + r)]
    text = testdata.gerber("Profile,NP", ["D10*", *ops], ["%ADD10C,0.100000*%"])
    assert area_of(text).geometry.area == pytest.approx(1200 - (4 - math.pi) * r * r, rel=1e-3)


def test_an_outline_drawn_as_a_filled_region_gives_the_region():
    text = testdata.gerber("Profile,NP", ["D10*", *testdata.region([testdata.move(10, 5), testdata.draw(50, 5), testdata.draw(50, 35),
                                                                      testdata.draw(10, 35), testdata.draw(10, 5)])], ["%ADD10C,0.100000*%"])
    assert same(area_of(text).geometry, box(10, 5, 50, 35))


# ---- the small gaps real files have ----------------------------------------------------------------------------
@pytest.mark.parametrize("gap_um", [0.1, 1.0, 1.9])
def test_ends_a_few_micrometres_apart_are_joined(gap_um):
    pts = [*RECT[:-1], (10, 5 + gap_um / 1000)]                                # the last side stops short of where it began
    a = area_of(outline(pts))
    assert a.reason is None and a.geometry.area == pytest.approx(1200, abs=0.1)


@pytest.mark.parametrize("gap_um", [4.0, 20.0, 500.0])
def test_a_wider_gap_is_an_open_contour(gap_um):
    pts = [*RECT[:-1], (10, 5 + gap_um / 1000)]
    a = area_of(outline(pts))
    assert a.geometry is None and a.reason == "not_closed"


# ---- what is not guessed ----------------------------------------------------------------------------------------
def test_an_open_contour_is_not_closed_for_you():
    a = area_of(outline(RECT[:-2]))                                             # three sides
    assert (a.geometry, a.reason) == (None, "not_closed")


def test_an_open_contour_next_to_a_closed_circle_is_not_the_circle():
    """The closed circle is the only face there is; taking it as the board would be the worst answer."""
    a = area_of(outline(RECT[:-2], extra=circle_ops(20, 20, 2)))
    assert (a.geometry, a.reason) == (None, "not_closed")


def test_a_dimension_line_outside_the_board_is_not_closed_for_you():
    a = area_of(outline(RECT, [(10, 40), (50, 40)]))                           # a line above the board: the drawing is not the board
    assert (a.geometry, a.reason) == (None, "not_closed")


def test_no_lines_means_no_outline():
    a = area_of(testdata.gerber("Profile,NP", [], ["%ADD10C,0.100000*%"]))
    assert (a.geometry, a.reason) == (None, "no_outline")


# ---- the area, or the rectangle ---------------------------------------------------------------------------------
def rect_of(text):
    return read_file("outline.gbr", text.encode()).file


def test_the_area_is_the_rectangle_when_there_is_no_outline_file():
    g, why = area_or_rectangle(None, size=(40, 30), center=(30, 20))
    assert why == "no_outline" and same(g, box(10, 5, 50, 35))


def test_the_area_is_the_rectangle_when_the_outline_does_not_close():
    g, why = area_or_rectangle(rect_of(outline(RECT[:-2])), size=(40, 30), center=(30, 20))
    assert why == "not_closed" and same(g, box(10, 5, 50, 35))


def test_the_area_is_the_outlines_when_it_closes_and_matches_the_extent():
    g, why = area_or_rectangle(rect_of(outline(RECT, extra=circle_ops(20, 20, 2))), size=(40, 30), center=(30, 20))
    assert why is None and len(g.interiors) == 1


def test_an_outline_that_is_not_the_extent_the_board_has_gives_the_rectangle():
    g, why = area_or_rectangle(rect_of(outline(RECT)), size=(40, 30), center=(35, 20))          # centre 5 mm off
    assert why == "extent_mismatch" and same(g, box(15, 5, 55, 35))
    _, ok = area_or_rectangle(rect_of(outline(RECT)), size=(40.04, 30.04), center=(30, 20))     # 0.02 mm: the extent of a stroked outline
    assert ok is None


# ---- real boards ------------------------------------------------------------------------------------------------
def real(name):
    from gerberslap.model import Plane, Role
    from gerberslap.services.importer import import_zip
    from gerberslap.services.pipeline import PipelineCache, Reader
    imp = import_zip(EXT / name, board_id="b1", source_name=name, plane=Plane(width_mm=130.56, height_mm=82.62))
    layer = next(l for l in imp.board.layers if l.role is Role.OUTLINE)
    return imp.board, Reader(imp.files, PipelineCache()).read(layer.files[0]).file


@pytest.mark.skipif(not (EXT / "altium_flight_controller.zip").exists(), reason="the Altium example is not in experiments/fase2/external/")
def test_the_real_altium_outline_closes_though_its_ends_are_0_1_um_apart():
    board, f = real("altium_flight_controller.zip")
    g, why = area_or_rectangle(f, size=(board.size.width_mm, board.size.height_mm), center=board.source_center)
    assert why is None and g.area == pytest.approx(4253.1, abs=1.0) and not list(g.interiors)


@pytest.mark.skipif(not (EXT / "eagle9_torazza.zip").exists(), reason="the EAGLE 9 example is not in experiments/fase2/external/")
def test_the_real_eagle_outline_has_its_mounting_holes_as_cutouts():
    board, f = real("eagle9_torazza.zip")
    g, why = area_or_rectangle(f, size=(board.size.width_mm, board.size.height_mm), center=board.source_center)
    assert why is None and len(g.interiors) == 21 and g.area == pytest.approx(19114.6, abs=1.0)


@pytest.mark.skipif(not (EXT / "kicad_uni_mosfet_key.zip").exists(), reason="the KiCad example is not in experiments/fase2/external/")
def test_the_real_kicad_outline_follows_its_rounded_corners():
    board, f = real("kicad_uni_mosfet_key.zip")
    g, why = area_or_rectangle(f, size=(board.size.width_mm, board.size.height_mm), center=board.source_center)
    assert why is None and g.area == pytest.approx(896.6, abs=0.5) and isinstance(g, Polygon)
