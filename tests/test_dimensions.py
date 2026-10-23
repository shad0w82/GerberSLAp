"""Dimension checks: known shapes must come out with the right size and position, in pixels of 51 um."""
import math

import numpy as np
import pytest
from shapely.affinity import rotate, translate
from shapely.geometry import Point, box

from gerberslap.core import Grid, binarize, coverage

P = 0.051


def test_the_ld002h_plane_is_130_56_by_82_62_mm():
    g = Grid(2560, 1620, P)
    assert g.extent[2] == pytest.approx(130.56, abs=1e-9)
    assert g.extent[3] == pytest.approx(82.62, abs=1e-9)


def test_pixel_and_mm_coordinates_round_trip():
    g = Grid(2560, 1620, P, 3.0, 4.0)
    for x, y in ((3.0, 4.0), (50.123, 33.7), (130.0, 80.0)):
        assert g.to_mm(*g.to_pixel(x, y)) == pytest.approx((x, y), abs=1e-9)
    assert g.to_pixel(3.0, 4.0 + 1620 * P) == pytest.approx((0.0, 0.0))        # top-left corner of the image
    assert g.to_pixel(3.0, 4.0) == pytest.approx((0.0, 1620.0))                # bottom-left corner


def test_rectangle_80_by_50_has_the_right_size_in_pixels():
    grid = Grid(1700, 1100, P, 5.0, 5.0)
    cov = coverage(box(10, 10, 90, 60), grid, 16)
    col, row = (int(v) for v in grid.to_pixel(50, 35))
    assert cov.sum() * P * P == pytest.approx(4000.0, rel=2e-4)               # area is conserved
    assert cov[row].sum() == pytest.approx(80 / P, abs=0.1)                   # width along a row: 1568.63 px
    assert cov[:, col].sum() == pytest.approx(50 / P, abs=0.1)                # height along a column: 980.39 px
    assert abs(binarize(cov)[row].sum() - 80 / P) <= 1                       # the 1 px criterion on the binary mask
    assert abs(binarize(cov)[:, col].sum() - 50 / P) <= 1


def test_the_edge_pixel_holds_the_fractional_part():
    grid = Grid(1700, 1100, P, 5.0, 5.0)
    cov = coverage(box(10, 10, 90, 60), grid, 16)
    col_edge, row = grid.to_pixel(10, 35)[0], int(grid.to_pixel(50, 35)[1])   # 98.039...
    c = int(col_edge)
    assert cov[row, c - 1] == 0 and cov[row, c + 1] == 1
    assert cov[row, c] == pytest.approx(1 - (col_edge - c), abs=0.07)


def test_a_marker_lands_where_the_grid_says():
    grid = Grid(2560, 1620, P)
    for x, y in ((20.0, 10.0), (100.37, 70.21), (3.3, 80.0)):
        cov = coverage(box(x, y, x + 0.5, y + 0.5), grid, 16)
        rows, cols = np.mgrid[0:grid.height, 0:grid.width]
        cx = (cols + 0.5)[cov > 0].dot(cov[cov > 0]) / cov.sum()               # area-weighted centroid, in pixels
        cy = (rows + 0.5)[cov > 0].dot(cov[cov > 0]) / cov.sum()
        assert (cx, cy) == pytest.approx(grid.to_pixel(x + 0.25, y + 0.25), abs=0.03)                 # 1/32 px: half the 16x16 sampling step


def test_a_disc_keeps_its_area():
    grid = Grid(400, 400, P, 0.0, 0.0)
    cov = coverage(Point(10.2, 10.2).buffer(5.0, quad_segs=128), grid, 16)
    assert cov.sum() * P * P == pytest.approx(math.pi * 25, rel=5e-4)


@pytest.mark.parametrize("angle", [0, 37, 90, 133.3])
def test_rotation_does_not_change_the_dimensions(angle):
    rect = rotate(box(10, 10, 90, 60), angle, origin=(50, 35))
    grid = Grid(2000, 2200, P, 0.0, -15.0)                                   # holds the rect at any angle
    cov = coverage(rect, grid, 16)
    assert cov.sum() * P * P == pytest.approx(4000.0, rel=3e-4)


def test_moving_by_whole_pixels_shifts_the_image_exactly():
    grid = Grid(600, 400, P, 0.0, 0.0)
    shape = box(5.0, 4.0, 15.3, 9.7)
    a = coverage(shape, grid, 16)
    b = coverage(translate(shape, 40 * P, -25 * P), grid, 16)
    assert np.abs(np.roll(a, (25, 40), axis=(0, 1)) - b).max() <= 1 / 64
