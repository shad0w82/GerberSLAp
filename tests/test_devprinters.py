"""The made-up printers for trying the page with more than one printer, and the option that adds them. They must never be part of the app by
accident, never be its default, write nothing and name no real printer."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gerberslap.printers import Registry, registry
from gerberslap.printers.base import BuildError
from gerberslap.web import devprinters
from gerberslap.web.devprinters import DEMO_LARGE, DEMO_NO_TEMPLATE, DEMO_SMALL, fake_driver, with_demo_printers


def test_the_two_made_up_printers_have_other_planes_than_each_other_and_than_the_real_one():
    real = registry().get("ld002h").descriptor
    small, large = DEMO_SMALL.descriptor, DEMO_LARGE.descriptor
    assert (small.plane.width_mm, small.plane.height_mm, small.grid.width, small.grid.height) == (96.0, 64.0, 1200, 800)
    assert (large.plane.width_mm, large.plane.height_mm, large.grid.width, large.grid.height) == (200.0, 125.0, 2000, 1250)
    assert small.plane.width_mm < real.plane.width_mm < large.plane.width_mm and small.plane.height_mm < real.plane.height_mm < large.plane.height_mm
    assert "made up" in small.name and "made up" in large.name                                      # a name that says what they are


def test_the_registry_with_them_has_them_and_the_real_printers_and_the_real_one_wins_an_id():
    real = registry()
    both = with_demo_printers(real)
    assert both.ids() == ["demo_large", "demo_no_template", "demo_small", "ld002h"] and both.problems == real.problems
    clash = with_demo_printers(Registry(drivers={"demo_small": fake_driver("demo_small", "The real one", 10, 10, 1.0)}))
    assert clash.get("demo_small").descriptor.name == "The real one"
    assert "demo_small" not in registry().ids()                                                      # the ordinary registry never has them


def test_a_made_up_printer_writes_no_file(tmp_path):
    out = tmp_path / "out.ctb"
    with pytest.raises(BuildError) as e:
        DEMO_SMALL.build(None, None, None, None, out)
    assert e.value.code == "fake_printer" and not out.exists() and list(tmp_path.iterdir()) == []


def test_the_module_names_no_real_printer_and_no_file_format():
    text = Path(devprinters.__file__).read_text().lower()
    for word in ("ld-002", "ld002", "creality", "chitubox", "ctb"):
        assert word not in text, word


def run_main(monkeypatch, *args):
    """What `python -m gerberslap.web` would serve with these arguments: the app that would have been given to uvicorn."""
    import uvicorn
    from gerberslap.web.__main__ import main
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(app=app, **kw))
    monkeypatch.setattr(sys, "argv", ["gerberslap.web", "--allowed-host", "testserver", *args])
    main()
    return TestClient(seen["app"], raise_server_exceptions=False)


def test_without_the_option_the_app_has_only_its_real_printers(monkeypatch):
    info = run_main(monkeypatch).get("/api/info").json()
    assert [p["id"] for p in info["printers"]] == ["ld002h"] and info["default_printer"] == "ld002h"


def test_with_the_option_the_made_up_printers_are_there_but_the_real_one_stays_the_default(monkeypatch):
    info = run_main(monkeypatch, "--dev-printers").get("/api/info").json()
    assert [p["id"] for p in info["printers"]] == ["demo_large", "demo_no_template", "demo_small", "ld002h"]
    assert info["default_printer"] == "ld002h"                                                       # even though "demo_large" is first by id


def test_the_made_up_printer_with_a_template_is_never_ready_and_the_others_always_are(monkeypatch):
    printers = {p["id"]: p for p in run_main(monkeypatch, "--dev-printers").get("/api/info").json()["printers"]}
    assert printers["demo_no_template"]["ready"] is False
    assert [(i["code"], i["blocking"]) for i in printers["demo_no_template"]["issues"]] == [("template_missing", True)]
    assert printers["demo_small"]["ready"] is True and printers["demo_large"]["ready"] is True
    d = DEMO_NO_TEMPLATE.descriptor
    assert (d.requires_template, d.template_name) == (True, "template.demo") and "made up" in d.name


def test_a_made_up_printer_is_refused_with_words_when_a_file_is_asked_of_it_for_the_board_and_for_the_ladder():
    """The page can try these printers all the way to the Generate button: what comes back has a sentence of its own, not an unknown error."""
    import json

    from markerboard import make_zip, marker_files

    from gerberslap.model import Board, BoardPlacement, Project
    from gerberslap.web import create_app
    client = TestClient(create_app(printers=with_demo_printers(registry()), allowed_hosts=["testserver"], dev_printers=True), raise_server_exceptions=False)
    up = client.post("/api/boards", files={"file": ("b.zip", make_zip(marker_files()), "application/zip")}, data={"board_id": "b1", "printer_id": "demo_large"})
    board = Board.model_validate(up.json()["board"]).model_copy(update={"placement": BoardPlacement(x=100, y=60)})
    project = Project(printer_id="demo_large", boards=(board,))
    r = client.post("/api/generate", json={"project": project.model_dump(mode="json"), "polarity": "positive", "exposure": {"total_s": 8, "pulses": 2, "rest_s": 1}})
    assert r.status_code == 422 and r.json() == {"error": {"code": "fake_printer", "params": {}}}
    r = client.post("/api/generate/ladder", json={"printer_id": "demo_large", "ladder": {"step": 10, "bands": 3, "pulses": 2, "rest": 4, "width": 13, "height": 40}})
    assert r.status_code == 422 and r.json() == {"error": {"code": "sequence_unsupported", "params": {}}}
    i18n = (Path(__file__).resolve().parent.parent / "gerberslap" / "web" / "static" / "js" / "i18n.js").read_text()
    assert i18n.count(" err_fake_printer: '") == 2 and i18n.count(" err_sequence_unsupported: '") == 2 and i18n.count(" err_font_missing: '") == 2
