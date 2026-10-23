"""Tests on real files by third parties (Altium Designer output, inches, INCH,TZ drill), when they are present.

They live in experiments/fase1/external/ (downloaded from kbralten/gerber_tool, AGPL-3.0, never committed) so the
tests are skipped without them. gerbv, when installed, is only an independent cross-check, not a dependency.
"""
import math
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import oracle
from gerberslap.core import Grid, binarize, compose_material, coverage, holes_geometry, layer_geometry, read_file

EXT = Path(__file__).parent.parent / "experiments" / "fase1" / "external" / "gerber_tool"
pytestmark = pytest.mark.skipif(not (EXT / "copper.gbr").exists(), reason="real example files not downloaded")

WINDOW = Grid(700, 500, 0.051, 100.0, 10.0)           # a busy part of the board, small enough for the exact oracle


@pytest.fixture(scope="module")
def board():
    parse = lambda n: read_file(n, (EXT / n).read_bytes())                    # noqa: E731
    cu, edge, drill = parse("copper.gbr"), parse("outline.gbr"), parse("drill.txt")
    return {"cu": cu, "edge": edge, "drill": drill, "cu_geom": layer_geometry(cu.file),
            "holes": holes_geometry(drill.file)}


def test_the_real_files_are_read(board):
    assert board["cu"].kind == "gerber" and board["drill"].kind == "excellon"
    assert len(board["cu"].file.objects) == 1895
    assert len(board["drill"].file.objects) == 1028
    assert any("G70" in w for w in board["cu"].warnings)                      # deprecated unit statement: reported


def test_the_real_board_is_210_by_58_mm_and_larger_than_the_plane(board):
    from gerberslap.core import extent_size, outline_lines
    w, h = extent_size(outline_lines(board["edge"].file))
    assert (w, h) == pytest.approx((210.82, 58.42), abs=0.05)
    assert w > 130.56 and h < 82.62


def test_holes_are_removed_from_the_real_copper(board):
    mat = compose_material([board["cu_geom"]], None, board["holes"])
    assert mat.area < board["cu_geom"].area
    assert mat.intersection(board["holes"].buffer(-0.001)).area < 1e-3


@pytest.mark.parametrize("S", [8, 16])
def test_coverage_of_the_real_material_matches_the_exact_oracle(board, S):
    mat = compose_material([board["cu_geom"]], None, board["holes"])
    cov = coverage(mat, WINDOW, S)
    ref = oracle.exact_coverage(mat, WINDOW)
    assert oracle.far_errors(cov, ref) == 0
    assert oracle.max_error(cov, ref) <= (0.12 if S == 8 else 0.07)         # real edges: more orientations


@pytest.mark.skipif(shutil.which("gerbv") is None, reason="gerbv not installed")
def test_agrees_with_gerbv_within_a_pixel_at_the_edges(board, tmp_path):
    """gerbv snaps edges to the pixel grid (about half a pixel), so only a small share of the pixels may differ."""
    out = tmp_path / "gerbv.png"
    p = 0.051
    cmd = ["gerbv", "-x", "png", "-u", "mm", "-O", f"{WINDOW.ox};{WINDOW.oy}", "-D", repr(25.4 / p), "-B", "0",
           "-w", f"{WINDOW.width}x{WINDOW.height}", "-a", "-b", "#000000", "-f", "#ffffffff", "-o", str(out),
           str(EXT / "copper.gbr")]
    subprocess.run(cmd, capture_output=True, check=False)
    if not out.exists():
        pytest.skip("this gerbv build refused the window")
    gv = np.asarray(Image.open(out).convert("L"), dtype=float) / 255 >= 0.5
    ours = binarize(coverage(board["cu_geom"], WINDOW, 16))
    differ = int((gv != ours).sum())
    assert differ / max(int(ours.sum()), 1) < 0.02
