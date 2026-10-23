"""Making the file: the checks that stop it, the mask and the values the driver is given, the name of the download, what a driver's failure
becomes, that nothing is left behind, and the whole chain with the real printer (skipped without the user's template)."""
import json
from pathlib import Path

import numpy as np
import pytest
from fakeprinters import building_driver, registry_of
from fastapi.testclient import TestClient
from markerboard import make_zip, marker_files

from gerberslap.model import Board, BoardPlacement, ExposureValues, Polarity, Project, RecipeRef
from gerberslap.printers import BuildError, get_driver
from gerberslap.printers.ld002h import ctbio
from gerberslap.services.checks import blocking
from gerberslap.services.generate import GenerationBlocked, generate
from gerberslap.services.installation import install_template
from gerberslap.services.pipeline import render
from gerberslap.services.store import DataStore
from gerberslap.web import create_app

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "samples" / "speedCube.ctb"
needs_template = pytest.mark.skipif(not TEMPLATE.exists(), reason="samples/speedCube.ctb is not here (it is not in the repository)")
VALUES = {"total_s": 8, "pulses": 2, "rest_s": 1}


def setup(driver, *, store=None):
    app = create_app(printers=registry_of(driver), allowed_hosts=["testserver"], store=store)
    return TestClient(app, raise_server_exceptions=False), app


def upload(client, files=None, board_id="b1", printer_id=None):
    form = {"board_id": board_id, **({"printer_id": printer_id} if printer_id else {})}
    r = client.post("/api/boards", files={"file": ("b.zip", make_zip(files or marker_files()), "application/zip")}, data=form)
    assert r.status_code == 200, r.text
    return Board.model_validate(r.json()["board"])


def project_of(board, printer_id, centre, **kw):
    board = board.model_copy(update={"placement": BoardPlacement(x=centre[0], y=centre[1])})
    return Project(printer_id=printer_id, boards=(board,), **kw)


def body(project, **kw):
    return {"project": project.model_dump(mode="json"), "polarity": "positive", "exposure": VALUES, **kw}


@pytest.fixture
def made():
    """A client for a printer that writes a few bytes, the driver (to see what it was given) and a project of one board on its plane."""
    drv = building_driver()
    drv.calls.clear()
    client, app = setup(drv)
    return client, app, drv, project_of(upload(client, printer_id="build"), "build", (50, 30))


# ---- what the driver is given and what comes back ------------------------------------------------------------------
def test_the_file_is_made_from_the_mask_of_the_project_with_the_values_it_was_given(made):
    client, app, drv, project = made
    r = client.post("/api/generate", json=body(project))
    assert r.status_code == 200 and r.headers["content-type"] == "application/octet-stream" and r.content == b"FAKE\x02"
    (call,) = drv.calls
    expected = render(project.model_copy(update={"polarity": Polarity.POSITIVE}), app.state.files, drv.descriptor.grid, Polarity.POSITIVE, supersample=16).mask
    assert call["mask"].shape == (300, 500) and np.array_equal(call["mask"], expected) and call["mask"].any()
    assert call["exposure"] == ExposureValues(**VALUES) and call["config"].id == "build"


def test_the_polarity_of_the_request_is_the_one_used(made):
    client, app, drv, project = made
    client.post("/api/generate", json=body(project))
    client.post("/api/generate", json=body(project, polarity="negative"))
    positive, negative = (c["mask"] for c in drv.calls)
    assert np.array_equal(positive, ~negative) and negative.any() and positive.any()                 # light where there is no material, or where there is


def test_the_summary_comes_in_a_header_as_the_driver_gave_it(made):
    client, _, drv, project = made
    r = client.post("/api/generate", json=body(project))
    summary = json.loads(r.headers["x-build-summary"])
    assert summary["layers"] == 2 and summary["flash_s"] == 4.0 and summary["rest_s"] == 1.0 and summary["total_light_s"] == 8.0
    assert summary["estimated_s"] == 42 and summary["file_bytes"] == 5 and summary["lit_pixels"] == int(drv.calls[0]["mask"].sum())
    assert summary["details"] == {"template": None}


def test_the_file_takes_the_extension_the_driver_says_and_the_name_of_the_project(made):
    client, _, _, project = made
    r = client.post("/api/generate", json=body(project, name="my project"))
    assert r.headers["content-disposition"] == 'attachment; filename="my_project.fake"'


@pytest.mark.parametrize("name,expect", [("a b/c\\d\"e", "a_b_c_d_e"), ("../../etc/passwd", "etc_passwd"), ("progetto àèì", "progetto"), ("....", "project"),
                                         ("x" * 200, "x" * 80), ("--rf", "rf")])
def test_the_name_of_the_download_is_safe_whatever_the_project_is_called(made, name, expect):
    client, _, _, project = made
    r = client.post("/api/generate", json=body(project, name=name))
    assert r.status_code == 200 and r.headers["content-disposition"] == f'attachment; filename="{expect}.fake"'


def test_a_project_without_a_name_is_named_after_its_first_board(made):
    client, _, _, project = made
    named = project.model_copy(update={"boards": (project.boards[0].model_copy(update={"name": "Flight Controller v2"}),)})
    assert client.post("/api/generate", json=body(named)).headers["content-disposition"] == 'attachment; filename="Flight_Controller_v2.fake"'


def test_nothing_is_left_behind(made):
    client, _, drv, project = made
    client.post("/api/generate", json=body(project))
    out = drv.calls[0]["out"]
    assert out.name == "out.fake" and not out.exists() and not out.parent.exists()                 # the folder the driver wrote in is gone


# ---- what stops the file ---------------------------------------------------------------------------------------------
def test_a_project_with_no_layer_on_is_refused_and_the_driver_is_never_asked(made):
    client, _, drv, project = made
    off = project.model_copy(update={"boards": tuple(b.model_copy(update={"layers": tuple(l.model_copy(update={"on": False}) for l in b.layers)})
                                                     for b in project.boards)})
    r = client.post("/api/generate", json=body(off))
    assert r.status_code == 422 and r.json()["error"]["code"] == "generation_blocked"
    issues = r.json()["error"]["params"]["issues"]
    assert {"no_layer_on", "board_no_layer_on"} <= {i["code"] for i in issues} and any(i["blocking"] for i in issues)
    assert drv.calls == []


def test_a_flash_under_the_minimum_is_refused_with_its_numbers(made):
    client, _, drv, project = made
    r = client.post("/api/generate", json=body(project, exposure={"total_s": 8, "pulses": 10, "rest_s": 5}))
    assert r.status_code == 422
    (issue,) = [i for i in r.json()["error"]["params"]["issues"] if i["code"] == "flash_below_minimum"]
    assert issue["blocking"] and issue["params"]["min_s"] == 1.0 and issue["params"]["flash_s"] == pytest.approx(0.8)
    assert drv.calls == []


def test_the_issues_that_only_inform_do_not_stop_it(made):
    client, _, drv, project = made
    r = client.post("/api/generate", json=body(project, exposure={"total_s": 100, "pulses": 1, "rest_s": 0}))            # a flash over the longest tried
    assert r.status_code == 200 and len(drv.calls) == 1


def test_no_recipe_is_needed_but_one_the_project_refers_to_must_be_given(made):
    client, _, drv, project = made
    assert client.post("/api/generate", json=body(project)).status_code == 200                       # values and polarity by hand
    refers = project.model_copy(update={"recipe_id": "pos35", "recipe_name": "Positivo"})
    r = client.post("/api/generate", json=body(refers))
    assert r.status_code == 422 and "recipe_missing" in [i["code"] for i in r.json()["error"]["params"]["issues"]]
    chosen = {"id": "pos35", "name": "Positivo", "polarity": "positive"}
    assert client.post("/api/generate", json=body(refers, recipe=chosen)).status_code == 200
    assert len(drv.calls) == 2


def test_a_recipe_of_the_other_polarity_than_the_one_used_is_told_but_not_refused():
    drv = building_driver()
    drv.calls.clear()
    client, app = setup(drv)
    project = project_of(upload(client, printer_id="build"), "build", (50, 30), recipe_id="neg", polarity=Polarity.NEGATIVE)
    made_ = generate(project, app.state.files, driver=drv, store=None, polarity=Polarity.POSITIVE, exposure=ExposureValues(**VALUES),
                     recipe=RecipeRef(id="neg", name="N", polarity=Polarity.NEGATIVE))
    assert "polarity_mismatch" in [i.code for i in made_.issues] and not blocking(made_.issues)


def test_a_printer_that_needs_a_template_is_not_asked_without_it_and_is_given_it_with_it(tmp_path):
    drv = building_driver("tpl", template=True)
    drv.calls.clear()
    store = DataStore(tmp_path)
    client, _ = setup(drv, store=store)
    project = project_of(upload(client, printer_id="tpl"), "tpl", (50, 30))
    r = client.post("/api/generate", json=body(project))
    assert r.status_code == 422 and "template_missing" in [i["code"] for i in r.json()["error"]["params"]["issues"]] and drv.calls == []
    install_template(store, drv, _write(tmp_path / "t.tpl", b"TPL1"))
    assert client.post("/api/generate", json=body(project)).status_code == 200
    assert drv.calls[0]["template"].name == "template.tpl" and json.loads(client.post("/api/generate", json=body(project)).headers["x-build-summary"])["details"] == {"template": "template.tpl"}


def test_a_settings_file_that_cannot_be_read_is_said_by_the_check_and_stops_the_file_and_never_breaks_the_route(tmp_path):
    drv = building_driver()
    drv.calls.clear()
    store = DataStore(tmp_path)
    (tmp_path / "printers" / "build").mkdir(parents=True)
    (tmp_path / "printers" / "build" / "printer.json").write_bytes(b"this is not a settings file")
    client, _ = setup(drv, store=store)
    project = project_of(upload(client, printer_id="build"), "build", (50, 30))
    checked = client.post("/api/check", json={"project": project.model_dump(mode="json"), "exposure": VALUES})
    assert checked.status_code == 200 and checked.json() == {"issues": []}                       # the printer's own problem is told with the printer (/api/info)
    r = client.post("/api/generate", json=body(project))
    assert r.status_code == 422 and r.json()["error"]["code"] == "generation_blocked" and drv.calls == []
    assert [i["code"] for i in r.json()["error"]["params"]["issues"]] == ["printer_config_invalid"]


def _write(path, data):
    path.write_bytes(data)
    return path


# ---- what a driver's failure becomes ---------------------------------------------------------------------------------
def test_a_driver_that_refuses_says_why_and_the_page_gets_its_code_and_parameters():
    drv = building_driver(fail=BuildError("nothing would be lit", code="mask_all_dark"))
    client, _ = setup(drv)
    project = project_of(upload(client, printer_id="build"), "build", (50, 30))
    r = client.post("/api/generate", json=body(project))
    assert r.status_code == 422 and r.json() == {"error": {"code": "mask_all_dark", "params": {}}}


@pytest.mark.parametrize("code", ["verification_failed", "write_failed"])
def test_a_failure_of_the_server_is_a_500_that_says_the_code_and_never_a_path(code):
    drv = building_driver(fail=BuildError("could not write /private/tmp/secret/out.fake", code=code, reason="/private/tmp/secret"))
    client, _ = setup(drv)
    project = project_of(upload(client, printer_id="build"), "build", (50, 30))
    r = client.post("/api/generate", json=body(project))
    assert r.status_code == 500 and r.json() == {"error": {"code": code, "params": {}}} and "secret" not in r.text


# ---- the request ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("edit", [lambda b: b.pop("exposure"), lambda b: b.pop("polarity"), lambda b: b.update(extra=1),
                                  lambda b: b.update(exposure={"total_s": 0, "pulses": 1, "rest_s": 0}), lambda b: b.update(supersample=4),
                                  lambda b: b.update(polarity="sideways")])
def test_a_request_that_is_not_good_is_refused_before_anything_is_made(made, edit):
    client, _, drv, project = made
    b = body(project)
    edit(b)
    r = client.post("/api/generate", json=b)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request" and drv.calls == []


def test_a_file_the_server_no_longer_has_is_named_not_replaced_by_something_else(made):
    client, app, drv, project = made
    other = Project(printer_id="build", boards=(project.boards[0].model_copy(update={"layers": tuple(
        l.model_copy(update={"files": tuple(f.model_copy(update={"sha256": "0" * 64}) for f in l.files)}) for l in project.boards[0].layers)}),))
    r = client.post("/api/generate", json=body(other))
    assert r.status_code == 422 and r.json()["error"]["code"] == "file_missing" and drv.calls == []


def test_the_route_refuses_another_site_like_every_route_that_changes_something(made):
    client, _, drv, project = made
    for headers in ({"Origin": "http://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
        r = client.post("/api/generate", headers=headers, json=body(project))
        assert r.status_code == 403 and r.json()["error"]["code"] == "cross_site"
    assert drv.calls == []


def test_an_unknown_printer_is_named():
    client, _ = setup(building_driver())
    project = project_of(upload(client, printer_id="build"), "nobody", (50, 30))
    r = client.post("/api/generate", json=body(project))
    assert r.status_code == 422 and r.json()["error"] == {"code": "unknown_printer", "params": {"printer_id": "nobody"}}


# ---- the complete check -------------------------------------------------------------------------------------------------
def test_the_check_says_only_the_layout_when_the_exposure_is_not_mentioned(made):
    client, _, _, project = made
    assert client.post("/api/check", json={"project": project.model_dump(mode="json")}).json() == {"issues": []}


def test_the_check_with_no_values_says_so_and_blocks(made):
    client, _, _, project = made
    r = client.post("/api/check", json={"project": project.model_dump(mode="json"), "exposure": None}).json()["issues"]
    assert [(i["code"], i["blocking"]) for i in r] == [("exposure_invalid", True)]                     # no recipe, so no dosage to miss


def test_the_check_with_values_and_a_recipe_is_clean_and_names_what_is_wrong(made):
    client, _, _, project = made
    refers = project.model_copy(update={"recipe_id": "pos35", "polarity": Polarity.NEGATIVE})
    chosen = {"id": "pos35", "name": "Positivo", "polarity": "positive"}
    ok = client.post("/api/check", json={"project": refers.model_dump(mode="json"), "exposure": VALUES, "recipe": chosen}).json()["issues"]
    assert [i["code"] for i in ok] == ["polarity_mismatch"]                                              # saved negative, the recipe is positive
    lost = client.post("/api/check", json={"project": refers.model_dump(mode="json"), "exposure": VALUES}).json()["issues"]
    assert [(i["code"], i["blocking"]) for i in lost] == [("recipe_missing", True)]
    short = client.post("/api/check", json={"project": project.model_dump(mode="json"), "exposure": {"total_s": 1, "pulses": 2, "rest_s": 0}}).json()["issues"]
    assert [i["code"] for i in short] == ["flash_below_minimum"]


# ---- the whole chain with the real printer ---------------------------------------------------------------------------
@needs_template
def test_the_real_printer_makes_a_file_that_reads_back_as_the_mask_of_the_board(tmp_path):
    drv = get_driver("ld002h")
    store = DataStore(tmp_path / "data")
    install_template(store, drv, TEMPLATE)
    app = create_app(store=store, allowed_hosts=["testserver"])
    client = TestClient(app, raise_server_exceptions=False)
    project = project_of(upload(client, printer_id="ld002h"), "ld002h", (65.28, 41.31))
    r = client.post("/api/generate", json=body(project, name="my board", supersample=8))
    assert r.status_code == 200 and r.headers["content-disposition"] == 'attachment; filename="my_board.ctb"'
    out = tmp_path / "out.ctb"
    out.write_bytes(r.content)
    c = ctbio.CTB(str(out))
    assert c.crc_ok and c.layer_count == 2
    mask = render(project.model_copy(update={"polarity": Polarity.POSITIVE}), app.state.files, drv.descriptor.grid, Polarity.POSITIVE, supersample=8).mask
    for i in range(2):
        assert np.array_equal(c.layer_image(i) > 0, drv.to_printer_image(mask))                       # the pixels of the file are the board's mask
    summary = json.loads(r.headers["x-build-summary"])
    assert summary["layers"] == 2 and summary["flash_s"] == 4.0 and summary["file_bytes"] == len(r.content) and summary["lit_pixels"] == int(mask.sum())


@needs_template
def test_the_real_printer_without_its_template_is_refused_and_says_so(tmp_path):
    client = TestClient(create_app(store=DataStore(tmp_path / "data"), allowed_hosts=["testserver"]), raise_server_exceptions=False)
    project = project_of(upload(client, printer_id="ld002h"), "ld002h", (65.28, 41.31))
    r = client.post("/api/generate", json=body(project))
    assert r.status_code == 422 and "template_missing" in [i["code"] for i in r.json()["error"]["params"]["issues"]]


def test_the_file_is_made_without_a_library_too():
    """`--no-library`: the library routes do not exist, and the file is made from what the request carries (a recipe or none), the library being none of its business."""
    drv = building_driver()
    drv.calls.clear()
    app = create_app(printers=registry_of(drv), allowed_hosts=["testserver"], library=False)
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/recipes").status_code == 404
    project = project_of(upload(client, printer_id="build"), "build", (50, 30))
    assert client.post("/api/generate", json=body(project)).status_code == 200
    assert client.post("/api/check", json={"project": project.model_dump(mode="json"), "exposure": VALUES}).json() == {"issues": []}
    assert len(drv.calls) == 1
