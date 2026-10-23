"""The web API: opening a zip, the shapes sent to the browser, the exact preview, the layout checks, what the server refuses to do for
a page that is not its own, the static page, and the bounded store of files."""
import base64
import hashlib
import io
import math
from pathlib import Path

import numpy as np
import pytest
import testdata
from fastapi.testclient import TestClient
from fakeprinters import LARGE, SMALL, registry_of
from markerboard import make_zip, marker_files
from PIL import Image

from gerberslap.model import Board, BoardPlacement, Polarity, Project
from gerberslap.services.pipeline import render
from gerberslap.web import create_app
from gerberslap.web.app import MAX_UPLOAD_BYTES
from gerberslap.web.filestore import FileStore, StoreFull

REPO = Path(__file__).resolve().parent.parent
EXT = REPO / "experiments" / "fase2" / "external"


def make_client(**kw):
    kw.setdefault("allowed_hosts", ["testserver"])
    app = create_app(**kw)
    return TestClient(app, raise_server_exceptions=False), app


@pytest.fixture
def client():
    return make_client()[0]


def upload(client, files=None, name="b.zip", **form):
    return client.post("/api/boards", files={"file": (name, make_zip(files or marker_files()), "application/zip")}, data=form)


def shoelace(ring):
    xs, ys = ring[0::2], ring[1::2]
    return sum(xs[i] * ys[(i + 1) % len(xs)] - xs[(i + 1) % len(xs)] * ys[i] for i in range(len(xs))) / 2


def area(polygons):
    return sum(abs(shoelace(p[0])) - sum(abs(shoelace(h)) for h in p[1:]) for p in polygons)


def layer(board, role):
    return next(l for l in board["layers"] if l["role"] == role)


def geometry(client, board, role, **kw):
    lay = layer(board, role)
    body = {"role": role, "files": lay["files"], "center": board["source_center"], **kw}
    return client.post("/api/geometry", json=body)


# ---- info --------------------------------------------------------------------------------------------------------
def test_info_describes_the_plane_the_grid_and_the_limits(client):
    j = client.get("/api/info").json()
    assert j["app"] == "GerberSLAp" and j["default_printer"] == "ld002h" and j["dev_samples"] is None
    (ld,) = j["printers"]                                                         # the only printer this app has so far
    assert ld["id"] == "ld002h" and ld["name"] == "Creality LD-002H"
    assert ld["plane"] == {"width_mm": 130.56, "height_mm": 82.62}
    assert ld["grid"] == {"width": 2560, "height": 1620, "pitch": 0.051}
    assert ld["limits"] == {"min_flash_s": 1.0, "max_proven_flash_s": 20.0}


# ---- more than one printer: the plane and the grid are the project's printer's ---------------------------------------------
def two_printers(**kw):
    return make_client(printers=registry_of(LARGE, SMALL), **kw)


def project_for(client, printer_id, *, x=50, y=30):
    board = upload(client, marker_files(), board_id="b1", **({"printer_id": printer_id} if printer_id else {})).json()["board"]
    b = Board.model_validate(board)
    return Project(printer_id=printer_id, boards=(b.model_copy(update={"placement": BoardPlacement(x=x, y=y)}),))


def test_the_info_lists_every_printer_with_its_plane_and_grid_and_names_the_default():
    c, _ = two_printers()
    j = c.get("/api/info").json()
    assert [p["id"] for p in j["printers"]] == ["large", "small"] and j["default_printer"] == "large"                # by id; the first is the default
    small = j["printers"][1]
    assert small["name"] == "Small test printer" and small["plane"] == {"width_mm": 100.0, "height_mm": 60.0}
    assert small["grid"] == {"width": 500, "height": 300, "pitch": 0.2} and set(small["limits"]) == {"min_flash_s", "max_proven_flash_s"}
    c2, _ = two_printers(driver_id="small")
    assert c2.get("/api/info").json()["default_printer"] == "small"


def test_the_preview_is_made_on_the_grid_of_the_projects_printer():
    c, _ = two_printers()
    for printer_id, size in (("small", (500, 300)), ("large", (1000, 600)), (None, (1000, 600))):                   # no printer: the default one
        proj = project_for(c, printer_id)
        j = c.post("/api/render", json={"project": proj.model_dump(mode="json"), "polarity": "positive", "supersample": 8}).json()
        img = Image.open(io.BytesIO(base64.b64decode(j["png"])))
        assert (j["width"], j["height"]) == size and img.size == size, printer_id


def test_a_board_is_outside_the_plane_of_one_printer_and_not_of_another():
    c, _ = two_printers()
    for printer_id, expected in (("small", ["board_outside_plane"]), ("large", [])):                                # 40 x 30 mm centred at x=90
        proj = project_for(c, printer_id, x=90, y=30)
        issues = c.post("/api/check", json={"project": proj.model_dump(mode="json")}).json()["issues"]
        assert [i["code"] for i in issues] == expected, printer_id
        clipped = c.post("/api/render", json={"project": proj.model_dump(mode="json"), "polarity": "positive", "supersample": 8}).json()["issues"]
        assert [i["code"] for i in clipped] == (["board_clipped"] if expected else []), printer_id


def test_a_zip_is_placed_at_the_middle_of_the_plane_of_the_printer_it_is_opened_for():
    c, _ = two_printers()
    for printer_id, centre in (("small", (50.0, 30.0)), ("large", (100.0, 60.0)), (None, (100.0, 60.0))):
        board = upload(c, printer_id=printer_id).json()["board"] if printer_id else upload(c).json()["board"]
        assert (board["placement"]["x"], board["placement"]["y"]) == centre, printer_id


def test_a_printer_this_app_does_not_know_is_refused_and_named_not_replaced_in_silence():
    c, _ = two_printers()
    proj = project_for(c, None).model_copy(update={"printer_id": "elegoo_mars"})
    for route, body in (("/api/check", {"project": proj.model_dump(mode="json")}),
                        ("/api/render", {"project": proj.model_dump(mode="json"), "polarity": "positive"})):
        r = c.post(route, json=body)
        assert r.status_code == 422 and r.json()["error"] == {"code": "unknown_printer", "params": {"printer_id": "elegoo_mars"}}, route
    r = upload(c, printer_id="elegoo_mars")
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_printer"
    bad = upload(c, printer_id="../x")
    assert bad.status_code == 422 and bad.json()["error"] == {"code": "bad_id", "params": {"field": "printer_id"}}


def test_an_app_with_no_printer_does_not_start_and_a_default_that_does_not_exist_is_named():
    from gerberslap.printers import Registry, UnknownDriver
    with pytest.raises(RuntimeError):
        create_app(printers=Registry(drivers={}))
    with pytest.raises(UnknownDriver):
        create_app(printers=registry_of(SMALL), driver_id="large")


# ---- opening a zip -----------------------------------------------------------------------------------------------
def test_a_zip_becomes_a_board_the_browser_can_keep(client):
    r = upload(client, marker_files(hole=True), board_id="bx", mirror="true")
    assert r.status_code == 200
    j = r.json()
    board = Board.model_validate(j["board"])                                  # the very model the rest of the app uses
    assert board.id == "bx" and board.placement.mirror is True and j["cad"] == "kicad" and j["issues"] == []
    assert (board.size.width_mm, board.size.height_mm) == pytest.approx((40, 30)) and board.source == "b.zip"
    assert (board.placement.x, board.placement.y) == (65.28, 41.31)           # centred on the LD-002H plane
    assert [(l.role.value, l.on) for l in board.layers] == [("copper", True), ("outline", True), ("drill", True)]


def test_a_board_id_is_made_when_none_is_given_and_a_bad_one_is_refused(client):
    assert upload(client).json()["board"]["id"].startswith("b-")
    for bad in ("../x", "a b", ""):
        r = upload(client, board_id=bad) if bad else upload(client, board_id="")
        assert r.status_code in (200, 422)
    r = upload(client, board_id="../x")
    assert r.status_code == 422 and r.json()["error"] == {"code": "bad_id", "params": {"field": "board_id"}}


def test_findings_about_the_zip_come_with_the_board(client):
    files = {k: v for k, v in marker_files(hole=True).items() if k != "b-Edge_Cuts.gbr"}
    codes = [i["code"] for i in upload(client, files).json()["issues"]]
    assert codes == ["no_outline"]
    assert [i["code"] for i in upload(client).json()["issues"]] == ["no_drill"]
    assert upload(client, marker_files(hole=True)).json()["issues"] == []
    assert [i["code"] for i in upload(client, {"b-F_Cu.gbr": marker_files()["b-F_Cu.gbr"]}).json()["issues"]] == ["no_outline", "no_drill"]


def test_the_files_are_kept_by_hash_for_the_next_calls():
    c, app = make_client()
    j = upload(c, marker_files(hole=True)).json()
    shas = {f["sha256"] for l in j["board"]["layers"] for f in l["files"]}
    assert shas and all(sha in app.state.files for sha in shas)


@pytest.mark.parametrize("make_request,status,code", [
    (lambda c: c.post("/api/boards", files={"file": ("x.zip", b"not a zip at all", "application/zip")}), 422, "bad_zip"),
    (lambda c: c.post("/api/boards", files={"file": ("x.zip", b"", "application/zip")}), 422, "empty_file"),
    (lambda c: upload(c, {"readme.txt": "hello"}), 422, "no_copper"),
    (lambda c: c.post("/api/boards"), 422, "invalid_request")])
def test_zips_that_cannot_be_opened_say_why(client, make_request, status, code):
    r = make_request(client)
    assert r.status_code == status and r.json()["error"]["code"] == code


def test_an_old_eagle_export_is_refused_with_its_reason(client):
    old = "G75*\n%MOIN*%\n%OFA0B0*%\n%FSLAX25Y25*%\n%IPPOS*%\n%LPD*%\nM02*\n"
    r = upload(client, {"b.GTL": old, "b.GBL": old})
    err = r.json()["error"]
    assert r.status_code == 422 and err["code"] == "incompatible_export" and err["params"]["cad"] == "eagle"


def test_an_upload_over_the_limit_is_refused_before_it_is_opened():
    c, _ = make_client(max_upload=200)
    r = upload(c)
    assert r.status_code == 413 and r.json()["error"] == {"code": "too_large", "params": {"max_bytes": 200}}
    assert MAX_UPLOAD_BYTES == 64 * 1024 * 1024


def test_a_store_that_is_too_small_says_so():
    c, _ = make_client(store_bytes=10)
    r = upload(c)
    assert r.status_code == 507 and r.json()["error"]["code"] == "store_full"


# ---- shapes for the browser --------------------------------------------------------------------------------------
@pytest.fixture
def marker(client):
    return client, upload(client, marker_files(hole=True)).json()["board"]


def test_the_copper_comes_as_polygons_relative_to_the_boards_centre(marker):
    c, board = marker
    j = geometry(c, board, "copper").json()
    assert len(j["polygons"]) == 1 and len(j["polygons"][0]) == 1                  # one pad, no holes
    assert j["bounds"] == pytest.approx([8, 7, 12, 9], abs=1e-3)                   # (40, 28) minus the centre (30, 20), 4 x 2 mm
    assert area(j["polygons"]) == pytest.approx(8.0, abs=1e-3) and j["vertices"] == 4


def test_the_holes_are_cut_out_of_the_shapes_so_the_browser_needs_no_compositing(marker):
    c, board = marker
    holes = layer(board, "drill")["files"]
    j = geometry(c, board, "copper", holes=holes).json()
    assert len(j["polygons"]) == 1 and len(j["polygons"][0]) == 2                  # the pad and its hole
    assert area(j["polygons"]) == pytest.approx(8.0 - math.pi * 0.25, abs=0.01)
    d = geometry(c, board, "drill").json()
    assert area(d["polygons"]) == pytest.approx(math.pi * 0.25, abs=0.01) and d["bounds"] == pytest.approx([9.5, 7.5, 10.5, 8.5], abs=0.005)


def test_the_outline_is_a_line_at_least_as_wide_as_the_minimum(marker):
    c, board = marker
    thin, wide = geometry(c, board, "outline").json(), geometry(c, board, "outline", min_outline_mm=1.0).json()
    assert thin["bounds"] == pytest.approx([-20.15, -15.15, 20.15, 15.15], abs=1e-3)            # 0.3 mm: the default minimum
    assert wide["bounds"] == pytest.approx([-20.5, -15.5, 20.5, 15.5], abs=1e-3)
    assert area(wide["polygons"]) == pytest.approx(140 * 1.0, rel=0.01)


def test_shapes_are_simplified_but_stay_within_a_few_microns():
    c, _ = make_client()
    files, refs = testdata.synth_board()
    board = upload(c, files).json()["board"]
    j = geometry(c, board, "copper").json()
    full = refs["copper"]
    assert abs(area(j["polygons"]) - full.area) / full.area < 0.002
    assert j["vertices"] == sum(len(r) // 2 for p in j["polygons"] for r in p)


@pytest.mark.parametrize("body,status,code", [
    ({"role": "silk"}, None, None),
    ({"role": "nonsense"}, 422, "invalid_request")])
def test_roles_without_shapes_or_unknown_are_refused(marker, body, status, code):
    c, board = marker
    r = c.post("/api/geometry", json={"files": layer(board, "copper")["files"], "center": [0, 0], **body})
    if status:
        assert r.status_code == status and r.json()["error"]["code"] == code
    else:
        assert r.status_code == 200                                                 # silkscreen follows the copper rule


def test_unknown_files_and_negative_images_are_refused(client):
    ghost = {"name": "x.gbr", "sha256": "ab" * 32}
    r = client.post("/api/geometry", json={"role": "copper", "files": [ghost], "center": [0, 0]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "file_missing" and r.json()["error"]["params"]["file"] == "x.gbr"
    files = marker_files()
    files["b-F_Cu.gbr"] = "%TF.FilePolarity,Negative*%\n" + files["b-F_Cu.gbr"]
    board = upload(client, files).json()["board"]
    assert layer(board, "copper")["status"]["code"] == "negative_image"            # the importer marked it...
    r = geometry(client, board, "copper")
    assert r.status_code == 422 and r.json()["error"]["code"] == "negative_layer"  # ...and the server will not draw it anyway


def test_a_bad_request_body_says_which_field(client):
    r = client.post("/api/geometry", json={"role": "copper", "files": [], "center": [0, 0]})
    err = r.json()["error"]
    assert r.status_code == 422 and err["code"] == "invalid_request" and any("files" in f["loc"] for f in err["params"]["fields"])
    ghost = {"name": "x.gbr", "sha256": "ab" * 32}
    nan = client.post("/api/geometry", content=b'{"role": "copper", "files": [{"name": "x.gbr", "sha256": "' + b"ab" * 32 + b'"}], "center": [0, NaN]}',
                      headers={"content-type": "application/json"})
    assert nan.status_code == 422 and nan.json()["error"]["code"] == "invalid_request"            # not "file missing": it never got that far
    extra = client.post("/api/geometry", json={"role": "copper", "files": [ghost], "center": [0, 0], "surprise": 1})
    assert extra.status_code == 422 and extra.json()["error"]["code"] == "invalid_request"


# ---- the solder mask: the board's area minus its openings, with the outline the area comes from ------------------------
def mask_geometry(client, board, *, outline="layer", size=None, **kw):
    """The mask's shapes. `outline`: "layer" sends the board's outline file, None sends none."""
    ol = layer(board, "outline")["files"][0] if outline == "layer" else None
    body = {"role": "mask", "files": layer(board, "mask")["files"], "center": board["source_center"],
            "area": {"outline": ol, "size": size or board["size"]}, **kw}
    return client.post("/api/geometry", json=body)


@pytest.fixture
def masked(client):
    return client, upload(client, marker_files(mask=True)).json()["board"]


def test_a_zip_with_a_mask_opens_it_usable_and_off(masked):
    m = layer(masked[1], "mask")
    assert m["status"] == {"level": "ok", "code": None, "params": {}} and m["on"] is False


def test_the_mask_comes_as_the_board_with_the_opening_cut_out(masked):
    c, board = masked
    j = mask_geometry(c, board).json()
    assert len(j["polygons"]) == 1 and len(j["polygons"][0]) == 2                       # the board, and the 6 x 4 mm opening as its hole
    assert area(j["polygons"]) == pytest.approx(1200 - 24, abs=0.5)
    assert j["bounds"] == pytest.approx([-20, -15, 20, 15], abs=0.01)                   # relative to the board's centre


def test_a_cutout_in_the_outline_is_not_part_of_the_mask(client):
    board = upload(client, marker_files(mask=True, cutout=True)).json()["board"]
    j = mask_geometry(client, board).json()
    assert len(j["polygons"][0]) == 3 and area(j["polygons"]) == pytest.approx(1200 - 24 - math.pi * 4, abs=0.5)


def test_the_holes_are_cut_out_of_the_mask_too(client):
    files = {**marker_files(mask=True), "b-PTH.drl": testdata.excellon("Plated,1,2,PTH", {1: 1.0}, [(1, 20.0, 10.0)])}
    board = upload(client, files).json()["board"]
    j = mask_geometry(client, board, holes=layer(board, "drill")["files"]).json()
    assert area(j["polygons"]) == pytest.approx(1200 - 24 - math.pi * 0.25, abs=0.5)


def test_without_an_outline_the_mask_uses_the_rectangle_of_the_extent(masked):
    c, board = masked
    j = mask_geometry(c, board, outline=None).json()
    assert area(j["polygons"]) == pytest.approx(1200 - 24, abs=0.5)


def test_the_mask_cannot_be_drawn_without_its_area(masked):
    c, board = masked
    r = c.post("/api/geometry", json={"role": "mask", "files": layer(board, "mask")["files"], "center": board["source_center"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "area_missing"


def test_the_area_of_a_mask_must_name_a_file_the_server_has_and_a_size(masked):
    c, board = masked
    ghost = {"name": "x.gbr", "sha256": "cd" * 32}
    r = mask_geometry(c, board)
    assert r.status_code == 200
    gone = c.post("/api/geometry", json={"role": "mask", "files": layer(board, "mask")["files"], "center": board["source_center"],
                                         "area": {"outline": ghost, "size": board["size"]}})
    assert gone.status_code == 422 and gone.json()["error"]["code"] == "file_missing"
    for bad in ({"outline": None, "size": {"width_mm": 0, "height_mm": 30}}, {"outline": None, "size": board["size"], "x": 1}, {"outline": None}):
        r = c.post("/api/geometry", json={"role": "mask", "files": layer(board, "mask")["files"], "center": board["source_center"], "area": bad})
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"


def test_the_exact_preview_of_a_mask_names_an_area_it_had_to_estimate():
    c, _ = make_client()
    opened = upload(c, marker_files(mask=True, open_outline=True)).json()
    assert "board_area_estimated" in [i["code"] for i in opened["issues"]]                    # said when the zip is opened...
    b = Board.model_validate(opened["board"])
    layers = tuple(l.model_copy(update={"on": l.role.value == "mask"}) for l in b.layers)
    proj = Project(printer_id="ld002h", recipe_id="pos35", boards=(b.model_copy(update={"layers": layers, "placement": BoardPlacement(x=60, y=40)}),))
    j = c.post("/api/render", json={"project": proj.model_dump(mode="json"), "polarity": "negative"}).json()
    assert [(i["code"], i["params"]) for i in j["issues"]] == [("board_area_estimated", {"reason": "not_closed"})]       # ...and when it is exposed
    assert j["lit_pixels"] * 0.051 ** 2 == pytest.approx(1200 - 24, rel=0.01)


# ---- the exact preview -------------------------------------------------------------------------------------------
def project_from(board, **placement):
    b = Board.model_validate(board)
    return Project(printer_id="ld002h", recipe_id="pos35", boards=(b.model_copy(update={"placement": BoardPlacement(**placement)}),))


def test_the_exact_preview_is_the_pipelines_mask_as_a_one_bit_png():
    c, app = make_client()
    board = upload(c, marker_files(hole=True)).json()["board"]
    proj = project_from(board, x=60, y=40, angle=30, mirror=True)
    r = c.post("/api/render", json={"project": proj.model_dump(mode="json"), "polarity": "positive", "supersample": 8})
    assert r.status_code == 200
    j = r.json()
    img = Image.open(io.BytesIO(base64.b64decode(j["png"])))
    assert img.mode == "1" and img.size == (2560, 1620) and (j["width"], j["height"]) == (2560, 1620)
    direct = render(proj, app.state.files, app.state.driver.descriptor.grid, Polarity.POSITIVE, supersample=8)
    assert np.array_equal(np.asarray(img), direct.mask) and j["lit_pixels"] == direct.lit_pixels and j["issues"] == []


def test_the_preview_reports_a_board_that_goes_past_the_plane():
    c, _ = make_client()
    board = upload(c).json()["board"]
    r = c.post("/api/render", json={"project": project_from(board, x=125, y=40).model_dump(mode="json"), "polarity": "negative"})
    assert [i["code"] for i in r.json()["issues"]] == ["board_clipped"]


@pytest.mark.parametrize("supersample", [4, 7, 17, 64])
def test_the_preview_refuses_too_little_or_too_much_sampling(client, supersample):
    board = upload(client).json()["board"]
    r = client.post("/api/render", json={"project": project_from(board, x=60, y=40).model_dump(mode="json"),
                                         "polarity": "positive", "supersample": supersample})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"


def test_the_preview_says_what_the_pipeline_refuses(client):
    board = upload(client).json()["board"]
    proj = project_from(board, x=60, y=40)
    off = proj.model_copy(update={"boards": (proj.boards[0].model_copy(update={"layers": tuple(l.model_copy(update={"on": False}) for l in proj.boards[0].layers)}),)})
    r = client.post("/api/render", json={"project": off.model_dump(mode="json"), "polarity": "positive"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_layer_on"
    ghost = proj.boards[0].layers[0].files[0].model_copy(update={"sha256": "cd" * 32})
    moved = proj.model_copy(update={"boards": (proj.boards[0].model_copy(update={"layers": (proj.boards[0].layers[0].model_copy(update={"files": (ghost,)}), *proj.boards[0].layers[1:])}),)})
    r = client.post("/api/render", json={"project": moved.model_dump(mode="json"), "polarity": "positive"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "file_missing"
    assert client.post("/api/render", json={"project": {"boards": "x"}, "polarity": "positive"}).status_code == 422


# ---- layout checks -----------------------------------------------------------------------------------------------
def test_the_checks_are_the_ones_of_the_backend(client):
    a = upload(client, board_id="a").json()["board"]
    b = upload(client, board_id="b").json()["board"]
    both = Project(printer_id="ld002h", recipe_id="p", boards=(Board.model_validate(a).model_copy(update={"placement": BoardPlacement(x=40, y=40)}),
                                                            Board.model_validate(b).model_copy(update={"placement": BoardPlacement(x=60, y=40)})))
    codes = [i["code"] for i in client.post("/api/check", json={"project": both.model_dump(mode="json")}).json()["issues"]]
    assert codes == ["boards_overlap"]
    outside = project_from(a, x=10, y=40)
    codes = [i["code"] for i in client.post("/api/check", json={"project": outside.model_dump(mode="json")}).json()["issues"]]
    assert codes == ["board_outside_plane"]
    assert client.post("/api/check", json={"project": project_from(a, x=65, y=41).model_dump(mode="json")}).json() == {"issues": []}


# ---- the project file ----------------------------------------------------------------------------------------------
def save_request(board, name="my project", **placement):
    proj = project_from(board, **{"x": 60, "y": 40, **placement})
    return {"project": proj.model_dump(mode="json"), "name": name, "info": {board["id"]: {"cad": "kicad", "notes": []}}}


def open_bytes(client, data, name="p.gslp"):
    return client.post("/api/project/open", files={"file": (name, data, "application/zip")})


def test_a_project_opens_by_its_content_not_by_its_name_so_a_renamed_old_file_still_opens():
    c, _ = make_client()
    board = upload(c, marker_files(), board_id="b1").json()["board"]
    saved = c.post("/api/project/save", json=save_request(board)).content
    import io, json, zipfile
    assert json.loads(zipfile.ZipFile(io.BytesIO(saved)).read("project.json"))["format"] == "gerberslap"      # the format's name inside the file is not the extension
    for name in ("p.gslp", "old.gerberslap", "renamed.gerberslap.gslp", "no-extension"):
        assert open_bytes(c, saved, name=name).status_code == 200, name


def test_a_project_is_saved_as_a_download_and_opens_as_the_same_project():
    c, _ = make_client()
    board = upload(c, marker_files(mask=True, hole=True), board_id="b1").json()["board"]
    body = save_request(board, angle=33.5, mirror=True)
    saved = c.post("/api/project/save", json=body)
    assert saved.status_code == 200 and saved.headers["content-type"] == "application/zip"
    assert saved.headers["content-disposition"] == 'attachment; filename="my_project.gslp"' and saved.headers["cache-control"] == "no-store"
    opened = open_bytes(c, saved.content)
    assert opened.status_code == 200
    j = opened.json()
    assert Project.model_validate(j["project"]) == Project.model_validate(body["project"])
    assert j["name"] == "my project" and j["info"] == {"b1": {"cad": "kicad", "notes": []}}


def test_a_saved_project_opens_in_a_server_that_has_never_seen_the_zip_and_exposes_the_same():
    """A project file needs nothing else: a new server (empty store) reads it and renders exactly what the first one did."""
    first, app1 = make_client()
    board = upload(first, marker_files(mask=True, hole=True), board_id="b1").json()["board"]
    body = save_request(board, angle=17, mirror=True)
    data = first.post("/api/project/save", json=body).content
    second, app2 = make_client()
    assert len(app2.state.files) == 0
    j = open_bytes(second, data).json()
    assert len(app2.state.files) == len(app1.state.files) > 0
    ask = {"project": j["project"], "polarity": "positive", "supersample": 8}
    a = first.post("/api/render", json={**ask, "project": body["project"]}).json()
    b = second.post("/api/render", json=ask).json()
    assert a["png"] == b["png"] and b["lit_pixels"] > 0


def test_a_project_cannot_be_saved_when_the_server_no_longer_has_its_files():
    c, _ = make_client()
    board = upload(c, marker_files(), board_id="b1").json()["board"]
    fresh, _ = make_client()                                                  # a restarted server: the page still holds the board
    r = fresh.post("/api/project/save", json=save_request(board))
    err = r.json()["error"]
    assert r.status_code == 422 and err["code"] == "file_missing" and err["params"]["file"].endswith(".gbr")


def test_a_project_without_a_name_is_named_after_its_first_board(client):
    board = upload(client, marker_files(), board_id="b1").json()["board"]
    body = save_request(board, name=None)
    body["project"]["boards"][0]["name"] = "Flight Controller v2"
    assert client.post("/api/project/save", json=body).headers["content-disposition"] == 'attachment; filename="Flight_Controller_v2.gslp"'


@pytest.mark.parametrize("name,expect", [("a b/c\\d\"e", "a_b_c_d_e"), ("../../etc/passwd", "etc_passwd"), ("progetto àèì", "progetto"), ("....", "project"),
                                         ("x" * 200, "x" * 80), ("--rf", "rf")])
def test_the_name_of_the_download_is_safe_whatever_the_project_is_called(client, name, expect):
    board = upload(client, marker_files(), board_id="b1").json()["board"]
    r = client.post("/api/project/save", json=save_request(board, name=name))
    assert r.status_code == 200 and r.headers["content-disposition"] == f'attachment; filename="{expect}.gslp"'


def test_a_name_with_a_line_break_is_refused(client):
    board = upload(client, marker_files(), board_id="b1").json()["board"]
    r = client.post("/api/project/save", json=save_request(board, name="two\nlines"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("edit", [lambda b: b.update(surprise=1), lambda b: b["info"].update(ghost={"cad": None, "notes": []}),
                                  lambda b: b["project"].update(min_outline_mm=-3), lambda b: b["info"]["b1"].update(cad="Not A Code")])
def test_saving_refuses_a_request_that_is_not_a_good_project(client, edit):
    board = upload(client, marker_files(), board_id="b1").json()["board"]
    body = save_request(board)
    edit(body)
    r = client.post("/api/project/save", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] in ("invalid_request", "invalid_project")


def test_opening_refuses_what_is_not_a_project_and_keeps_nothing():
    c, app = make_client()
    board = upload(c, marker_files(), board_id="b1").json()["board"]
    good = c.post("/api/project/save", json=save_request(board)).content
    other, other_app = make_client()
    import zipfile
    def with_extra(extra):
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(good)) as zin, zipfile.ZipFile(out, "w") as zout:
            for i in zin.infolist():
                zout.writestr(i.filename, zin.read(i))
            zout.writestr(extra, b"x")
        return out.getvalue()
    for data, code in [(b"not a zip", "bad_zip"), (b"", "empty_file"), (with_extra("../evil"), "bad_entry"), (with_extra("files/" + hashlib.sha256(b"x").hexdigest()), "unreferenced_file"),
                       (make_zip({"project.json": "{}"}), "not_a_project")]:
        r = open_bytes(other, data)
        assert r.status_code == 422 and r.json()["error"]["code"] == code, (code, r.json())
        assert len(other_app.state.files) == 0                                 # a refused project leaves no file behind
    assert open_bytes(other, good).status_code == 200 and len(other_app.state.files) > 0


def test_opening_refuses_a_file_that_is_too_large_and_a_store_that_is_full():
    c, _ = make_client(max_upload=300)
    r = open_bytes(c, b"x" * 400)
    assert r.status_code == 413 and r.json()["error"] == {"code": "too_large", "params": {"max_bytes": 300}}
    big, _ = make_client()
    board = upload(big, marker_files(), board_id="b1").json()["board"]
    data = big.post("/api/project/save", json=save_request(board)).content
    tiny, app = make_client(store_bytes=10)
    r = open_bytes(tiny, data)
    assert r.status_code == 507 and r.json()["error"]["code"] == "store_full" and len(app.state.files) == 0


@pytest.mark.parametrize("route", ["/api/project/save", "/api/project/open"])
def test_the_project_routes_refuse_another_site_like_every_route_that_changes_something(client, route):
    for headers in ({"Origin": "http://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
        r = client.post(route, headers=headers, files={"file": ("p.gslp", b"x")} if route.endswith("open") else None,
                        json=None if route.endswith("open") else {"project": {}})
        assert r.status_code == 403 and r.json()["error"]["code"] == "cross_site"


# ---- a local server is not open to the whole web -----------------------------------------------------------------
def test_requests_for_a_name_that_is_not_local_are_refused(client):
    for path in ("/api/info", "/"):
        r = client.get(path, headers={"host": "evil.example"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "bad_host"
    local = TestClient(create_app())
    for host in ("localhost:8800", "127.0.0.1:8800", "[::1]:8800", "localhost"):
        assert local.get("/api/info", headers={"host": host}).status_code == 200, host
    assert local.get("/api/info", headers={"host": "testserver"}).status_code == 403          # not allowed unless asked
    assert TestClient(create_app(allowed_hosts=["gerber.lan"])).get("/api/info", headers={"host": "gerber.lan:80"}).status_code == 200


def test_a_request_that_changes_something_must_come_from_the_page_itself(client):
    body = {"project": {"boards": []}}
    ok = lambda **h: client.post("/api/check", json=body, headers=h).status_code           # noqa: E731
    assert ok() == 200                                                                      # no headers: a script, curl, a test
    assert ok(origin="http://testserver") == 200 and ok(**{"sec-fetch-site": "same-origin"}) == 200
    for h in ({"origin": "http://evil.example"}, {"origin": "http://localhost:9999"}, {"sec-fetch-site": "cross-site"}, {"sec-fetch-site": "same-site"}):
        r = client.post("/api/check", json=body, headers=h)
        assert r.status_code == 403 and r.json()["error"]["code"] == "cross_site", h
    assert client.post("/api/boards", files={"file": ("b.zip", make_zip(marker_files()))}, headers={"origin": "http://evil.example"}).status_code == 403
    assert client.get("/api/info", headers={"origin": "http://evil.example"}).status_code == 200      # reading is harmless


def test_unexpected_errors_do_not_leak_details(monkeypatch):
    c, _ = make_client()
    import gerberslap.web.app as web

    def boom(*a, **k):
        raise RuntimeError("secret detail /Users/someone/path")
    monkeypatch.setattr(web, "layout_issues", boom)
    r = c.post("/api/check", json={"project": {"boards": []}})
    assert r.status_code == 500 and r.json() == {"error": {"code": "internal", "params": {}}} and "secret" not in r.text


def test_unknown_api_paths_are_a_json_404(client):
    for r in (client.get("/api/zzz"), client.post("/api/zzz"), client.get("/api/boards")):
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


# ---- the page ----------------------------------------------------------------------------------------------------
def test_info_says_where_the_picture_of_a_printer_is_and_the_route_serves_it_to_be_kept_for_a_while(client):
    (ld,) = client.get("/api/info").json()["printers"]
    assert ld["picture"] == "/api/printers/ld002h/picture"
    r = client.get(ld["picture"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.headers["cache-control"] == "public, max-age=3600"
    assert r.content == (Path(__file__).resolve().parents[1] / "gerberslap" / "printers" / "ld002h" / "icon.png").read_bytes() and r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/info").headers["cache-control"] == "no-store"                                          # everything else is still never kept


def test_a_printer_without_a_picture_has_none_and_the_route_says_not_found_for_it_and_for_a_name_that_is_not_a_printer():
    from gerberslap.web.devprinters import with_demo_printers
    from gerberslap.printers import registry
    c, _ = make_client(printers=with_demo_printers(registry()))
    by_id = {p["id"]: p for p in c.get("/api/info").json()["printers"]}
    assert by_id["demo_small"]["picture"] is None and by_id["ld002h"]["picture"] == "/api/printers/ld002h/picture"
    for path in ("/api/printers/demo_small/picture", "/api/printers/nope/picture", "/api/printers/..%2F..%2Fetc%2Fpasswd/picture", "/api/printers/ld002h/picture.png"):
        r = c.get(path)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", path


def test_the_page_is_served_and_never_cached(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert r.headers["cache-control"] == "no-store" and client.get("/api/info").headers["cache-control"] == "no-store"
    assert client.get("/api/info").headers["x-content-type-options"] == "nosniff"
    assert client.get("/no/such/file.js").status_code == 404


# ---- sample boards, only on request ------------------------------------------------------------------------------
def test_samples_are_not_offered_unless_the_server_was_started_with_a_folder(client):
    assert client.get("/dev/samples/a.zip").status_code == 404 and client.get("/api/info").json()["dev_samples"] is None


def test_a_folder_of_samples_is_served_zip_by_zip_and_nothing_else(tmp_path):
    folder = tmp_path / "samples"
    folder.mkdir()
    (folder / "a.zip").write_bytes(make_zip(marker_files()))
    (folder / "notes.txt").write_text("not a zip")
    (tmp_path / "secret.zip").write_bytes(b"outside the folder")
    c, _ = make_client(dev_samples=folder)
    assert c.get("/api/info").json()["dev_samples"] == ["a.zip"]
    got = c.get("/dev/samples/a.zip")
    assert got.status_code == 200 and got.content == (folder / "a.zip").read_bytes() and got.headers["content-type"] == "application/zip"
    for name in ("notes.txt", "missing.zip", "..%2fsecret.zip", "%2e%2e/secret.zip", "../secret.zip", "a.zip/", ".hidden.zip", "a%00.zip"):
        assert c.get(f"/dev/samples/{name}").status_code == 404, name


def test_a_symbolic_link_in_the_samples_folder_cannot_lead_out_of_it(tmp_path):
    import os
    folder = tmp_path / "samples"
    folder.mkdir()
    (tmp_path / "secret.zip").write_bytes(b"outside the folder")
    try:
        os.symlink(tmp_path / "secret.zip", folder / "link.zip")
    except OSError:
        pytest.skip("cannot create symlinks here")
    c, _ = make_client(dev_samples=folder)
    assert c.get("/dev/samples/link.zip").status_code == 404


# ---- the store of files ------------------------------------------------------------------------------------------
def test_the_store_is_a_mapping_that_drops_the_least_recently_used_first():
    s = FileStore(max_bytes=10)
    s.add({"a": b"1234"})
    s.add({"b": b"1234"})
    assert s["a"] == b"1234"                                    # a is used now, so b is the oldest
    s.add({"c": b"1234"})                                       # 12 bytes: b goes
    assert set(s) == {"a", "c"} and "b" not in s and len(s) == 2 and s.size_bytes == 8
    assert s.get("b") is None and dict(s) == {"a": b"1234", "c": b"1234"}


def test_a_batch_larger_than_the_whole_store_is_refused_and_nothing_is_dropped():
    s = FileStore(max_bytes=10)
    s.add({"a": b"1234"})
    with pytest.raises(StoreFull):
        s.add({"big": b"x" * 11})
    assert set(s) == {"a"} and s.size_bytes == 4


def test_adding_a_file_that_is_already_there_keeps_one_copy():
    s = FileStore(max_bytes=10)
    s.add({"a": b"1234"})
    s.add({"a": b"1234"})
    assert len(s) == 1 and s.size_bytes == 4


# ---- the real boards through the API -----------------------------------------------------------------------------
@pytest.mark.parametrize("name,size", [("kicad_uni_mosfet_key", (30.0, 30.0)), ("altium_flight_controller", (74.42, 57.25)),
                                       ("eagle9_torazza", (172.0, 112.0))])
def test_the_real_boards_open_and_draw_through_the_api(name, size):
    path = EXT / f"{name}.zip"
    if not path.exists():
        pytest.skip("the example is not in experiments/fase2/external/")
    c, _ = make_client()
    r = c.post("/api/boards", files={"file": (path.name, path.read_bytes(), "application/zip")})
    assert r.status_code == 200
    board = r.json()["board"]
    assert (board["size"]["width_mm"], board["size"]["height_mm"]) == pytest.approx(size, abs=0.05)
    g = geometry(c, board, "copper")
    cu = next(l for l in board["layers"] if l["role"] == "copper" and l["on"])
    g = c.post("/api/geometry", json={"role": "copper", "files": cu["files"], "center": board["source_center"], "holes": next((l["files"] for l in board["layers"] if l["role"] == "drill"), [])})
    assert g.status_code == 200 and g.json()["polygons"] and g.json()["vertices"] > 100
    b = g.json()["bounds"]
    assert abs((b[0] + b[2]) / 2) < size[0] / 2 and abs((b[1] + b[3]) / 2) < size[1] / 2          # relative to the centre, not to the file
