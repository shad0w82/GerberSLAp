import random

import numpy as np
import pytest
from shapely.geometry import MultiPolygon, Point, box

import oracle
import testdata
from gerberslap.core import Grid, Placement, binarize, coverage, exposure_mask, extent_center, layer_geometry, place, \
    read_file

ALL = list(testdata.TESTS) + list(testdata.DRILLS)
SUBSET = ["f01_rect_region.gbr", "f03_lines.gbr", "f04_arcs.gbr", "f05_region_arcs.gbr", "f06_macros.gbr",
          "f07_clear.gbr", "f09_outline_open.gbr", "f11_macro_prims.gbr", "f13_islands_in_holes.gbr"]


def parsed(data_dir, name):
    return layer_geometry(read_file(name, (data_dir / name).read_bytes()).file)


@pytest.mark.parametrize("S", [8, 16])
@pytest.mark.parametrize("name", ALL)
def test_coverage_has_no_wrong_pixel_against_the_exact_reference(data_dir, reference, name, S):
    grid = oracle.make_grid(reference[name])
    cov = coverage(parsed(data_dir, name), grid, S)
    ref = oracle.exact_coverage(reference[name], grid)
    assert oracle.far_errors(cov, ref) == 0
    assert oracle.max_error(cov, ref) <= (0.10 if S == 8 else 0.07)


@pytest.mark.parametrize("angle,mirror", [(37.0, True), (12.5, False), (90.0, True), (180.0, False)])
@pytest.mark.parametrize("name", SUBSET)
def test_rotation_and_mirror_of_the_vector_geometry(data_dir, reference, name, angle, mirror):
    c = reference[name].centroid
    pl = Placement((c.x, c.y), angle, mirror)
    ref = place(reference[name], pl, (c.x, c.y))
    ours = place(parsed(data_dir, name), pl, (c.x, c.y))
    grid = oracle.make_grid(ref)
    assert oracle.far_errors(coverage(ours, grid, 16), oracle.exact_coverage(ref, grid)) == 0


@pytest.mark.parametrize("seed", range(5))
def test_islands_inside_holes_whatever_the_order_of_the_parts(seed):
    rng = random.Random(seed)
    centres = [(8 + 8 * i, 8 + 8 * j) for i in range(4) for j in range(4)]
    pour = box(0, 0, 40, 40)
    for x, y in centres:
        pour = pour.difference(Point(x, y).buffer(3.0))
    parts = [pour] + [Point(x, y).buffer(1.2) for x, y in centres]
    rng.shuffle(parts)
    geom = MultiPolygon(parts)
    grid = oracle.make_grid(geom)
    assert oracle.far_errors(coverage(geom, grid, 8), oracle.exact_coverage(geom, grid)) == 0


def test_a_supersampling_below_8_is_refused():
    with pytest.raises(ValueError):
        coverage(box(0, 0, 1, 1), Grid(50, 50), supersample=4)


def test_empty_geometry_and_geometry_outside_the_grid_give_zeros():
    grid = Grid(100, 80, 0.051)
    assert not coverage(Polygon_empty(), grid).any()
    assert not coverage(box(100, 100, 110, 110), grid).any()


def Polygon_empty():
    from shapely.geometry import Polygon
    return Polygon()


def test_a_window_equals_the_same_crop_of_a_larger_grid(reference):
    geom = reference["f05_region_arcs.gbr"]
    big = Grid(700, 400, 0.051, 9.0, 8.0)
    small = Grid(300, 200, 0.051, 9.0 + 120 * 0.051, 8.0 + 90 * 0.051)          # lower-left shifted by (120, 90) px
    a = coverage(geom, big, 16)
    b = coverage(geom, small, 16)
    r0 = big.height - 90 - small.height
    crop = a[r0:r0 + small.height, 120:120 + small.width]
    assert np.abs(crop - b).max() <= 1 / 64


def test_exposure_mask_polarity():
    cov = np.array([[1.0, 0.7, 0.5, 0.49, 0.0]], dtype=np.float32)
    assert exposure_mask(cov, "negative").tolist() == [[True, True, True, False, False]]
    assert exposure_mask(cov, "positive").tolist() == [[False, False, False, True, True]]
    with pytest.raises(ValueError):
        exposure_mask(cov, "both")


def test_binarize_threshold_is_half_coverage():
    assert binarize(np.array([0.49, 0.5, 0.51], dtype=np.float32)).tolist() == [False, True, True]
