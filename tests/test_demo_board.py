"""The demo board of the documentation (tools/demo_board): it must stay valid, deterministic and in step with the zip on the site."""
import importlib.util
from pathlib import Path

import pytest

from gerberslap.cad.base import Role, Side
from gerberslap.services.importer import import_zip

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "demo_board" / "make_demo_board.py"
ASSET = ROOT / "docs" / "assets" / "GerberSLAp-demo.zip"


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location("make_demo_board", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_design_keeps_nets_apart_and_the_silkscreen_off_the_pads(demo):
    demo.check()


def test_the_zip_is_deterministic(demo):
    assert demo.build_zip() == demo.build_zip()


def test_the_zip_on_the_site_is_the_one_the_script_writes(demo):
    assert ASSET.read_bytes() == demo.build_zip(), "run: .venv/bin/python tools/demo_board/make_demo_board.py"


def test_the_app_recognises_the_board_by_itself(demo):
    imported = import_zip(demo.build_zip(), board_id="demo")
    board = imported.board
    assert imported.cad == "kicad" and not imported.issues and not imported.skipped
    assert (board.size.width_mm, board.size.height_mm) == (40.0, 28.0)
    found = {(layer.role, layer.side): layer.on for layer in board.layers}
    assert set(found) == {(Role.COPPER, Side.TOP), (Role.COPPER, Side.BOTTOM), (Role.MASK, Side.TOP), (Role.SILK, Side.TOP),
                          (Role.OUTLINE, Side.TOP), (Role.DRILL, Side.TOP)}
    assert all(layer.status.level == "ok" for layer in board.layers)
