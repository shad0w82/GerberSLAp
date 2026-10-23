"""The recipe routes: what the page can do with the library, the statuses and codes it gets back, that no path of the server ever reaches it,
that the routes do not exist at all with `--no-library`, and that the protections of the other routes hold here too."""
import json
import sys

import pytest
from fakeprinters import LARGE, SMALL, registry_of
from fastapi.testclient import TestClient

from gerberslap.services import store as store_module
from gerberslap.services.store import DataStore
from gerberslap.web import create_app

PRINTERS = registry_of(SMALL, LARGE)


@pytest.fixture
def store(tmp_path):
    return DataStore(tmp_path / "data")


@pytest.fixture
def client(store):
    return TestClient(create_app(printers=PRINTERS, allowed_hosts=["testserver"], store=store), raise_server_exceptions=False)


def make(client, **kw):
    r = client.post("/api/recipes", json={"name": "Dry film", "polarity": "negative", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def dosage(client, rid, **kw):
    r = client.post(f"/api/recipes/{rid}/dosages", json={"printer_id": "small", "total_s": 200, "pulses": 5, "rest_s": 4, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def err(response):
    return response.status_code, response.json()["error"]["code"]


# ---- the library is on only when it can be ---------------------------------------------------------------------------
def test_info_says_whether_the_library_is_there(client, store):
    assert client.get("/api/info").json()["library"] is True
    off = TestClient(create_app(printers=PRINTERS, allowed_hosts=["testserver"], store=store, library=False))
    assert off.get("/api/info").json()["library"] is False
    no_folder = TestClient(create_app(printers=PRINTERS, allowed_hosts=["testserver"]))                          # no data folder: no library
    assert no_folder.get("/api/info").json()["library"] is False


@pytest.mark.parametrize("make_app", [lambda s: create_app(printers=PRINTERS, allowed_hosts=["testserver"], store=s, library=False),
                                      lambda s: create_app(printers=PRINTERS, allowed_hosts=["testserver"])])
def test_without_the_library_its_routes_are_not_there_at_all(store, make_app):
    c = TestClient(make_app(store), raise_server_exceptions=False)
    for method, url in [("get", "/api/recipes"), ("post", "/api/recipes"), ("get", "/api/recipes/x"), ("patch", "/api/recipes/x"),
                        ("delete", "/api/recipes/x"), ("post", "/api/recipes/x/duplicate"), ("post", "/api/recipes/x/dosages"),
                        ("patch", "/api/recipes/x/dosages/y"), ("delete", "/api/recipes/x/dosages/y"), ("post", "/api/recipes/x/dosages/y/copy")]:
        r = getattr(c, method)(url, **({"json": {"name": "x", "polarity": "positive"}} if method == "post" else {}))
        assert err(r) == (404, "not_found"), (method, url)
    assert not store.root.exists()                                                           # and nothing was written


# ---- recipes -----------------------------------------------------------------------------------------------------
def test_a_recipe_is_created_listed_read_edited_and_deleted(client, store):
    assert client.get("/api/recipes").json() == {"recipes": [], "problems": []}
    r = make(client, resist="Dry film 25 µm", development="Soda 1%", notes="n")
    assert len(r["id"]) == 36 and (r["name"], r["polarity"], r["resist"], r["development"], r["notes"], r["dosages"]) == ("Dry film", "negative", "Dry film 25 µm", "Soda 1%", "n", [])
    assert client.get("/api/recipes").json()["recipes"] == [r] and client.get(f"/api/recipes/{r['id']}").json() == r
    edited = client.patch(f"/api/recipes/{r['id']}", json={"name": "Renamed", "notes": ""})
    assert edited.status_code == 200 and (edited.json()["name"], edited.json()["notes"], edited.json()["resist"]) == ("Renamed", "", "Dry film 25 µm")
    gone = client.delete(f"/api/recipes/{r['id']}")
    assert gone.status_code == 200 and gone.json() == {"deleted": r["id"]}
    assert client.get("/api/recipes").json()["recipes"] == [] and client.get(f"/api/recipes/{r['id']}").status_code == 404


def test_the_polarity_of_a_recipe_does_not_change(client):
    r = make(client, polarity="negative")
    same = client.patch(f"/api/recipes/{r['id']}", json={"polarity": "negative", "name": "ok"})
    assert same.status_code == 200
    assert err(client.patch(f"/api/recipes/{r['id']}", json={"polarity": "positive", "name": "no"})) == (409, "polarity_locked")
    assert client.get(f"/api/recipes/{r['id']}").json()["name"] == "ok"


def test_duplicating_a_recipe_chooses_the_polarity_of_the_copy(client):
    r = make(client, polarity="negative")
    dosage(client, r["id"], name="Fine")
    copy = client.post(f"/api/recipes/{r['id']}/duplicate", json={"name": "Copy", "polarity": "positive"})
    assert copy.status_code == 201
    c = copy.json()
    assert (c["name"], c["polarity"], len(c["dosages"]), c["id"] != r["id"], c["dosages"][0]["id"] != r["dosages"][0]["id"] if r["dosages"] else True) == ("Copy", "positive", 1, True, True)
    assert len(client.get("/api/recipes").json()["recipes"]) == 2


def test_the_list_is_by_name(client):
    for name in ("beta", "Alpha"):
        make(client, name=name)
    assert [r["name"] for r in client.get("/api/recipes").json()["recipes"]] == ["Alpha", "beta"]


@pytest.mark.parametrize("body", [{}, {"name": "x"}, {"polarity": "negative"}, {"name": "", "polarity": "negative"}, {"name": "x", "polarity": "neutral"},
                                  {"name": "x", "polarity": "negative", "extra": 1}, {"name": "x", "polarity": "negative", "resist": "a\nb"},
                                  {"name": "x" * 201, "polarity": "negative"}, {"name": "x", "polarity": "negative", "notes": "y" * 2001}])
def test_a_bad_recipe_is_refused_and_nothing_is_written(client, store, body):
    assert err(client.post("/api/recipes", json=body))[0] == 422
    assert not store.root.exists()


def test_the_library_has_a_limit_of_recipes(client, monkeypatch):
    monkeypatch.setattr(store_module, "MAX_RECIPES", 2)
    make(client)
    make(client)
    assert err(client.post("/api/recipes", json={"name": "x", "polarity": "negative"})) == (409, "too_many_recipes")


# ---- dosages -----------------------------------------------------------------------------------------------------
def test_a_dosage_is_added_edited_copied_and_deleted(client):
    rid = make(client)["id"]
    r = dosage(client, rid, name="Fine", note="ok")
    d, = r["dosages"]
    assert (d["printer_id"], d["total_s"], d["pulses"], d["rest_s"], d["name"], d["note"]) == ("small", 200, 5, 4, "Fine", "ok") and d["updated"].endswith("Z")
    found = d["updated"]
    r = client.patch(f"/api/recipes/{rid}/dosages/{d['id']}", json={"name": "Finer"}).json()
    assert (r["dosages"][0]["name"], r["dosages"][0]["updated"]) == ("Finer", found)         # the date moves with the values only
    r = client.patch(f"/api/recipes/{rid}/dosages/{d['id']}", json={"total_s": 160, "pulses": 4}).json()
    assert (r["dosages"][0]["total_s"], r["dosages"][0]["pulses"], r["dosages"][0]["rest_s"]) == (160, 4, 4)
    copied = client.post(f"/api/recipes/{rid}/dosages/{d['id']}/copy", json={"printer_id": "large", "note": "Copied from small"})
    assert copied.status_code == 201
    two = copied.json()["dosages"]
    assert [(x["printer_id"], x["total_s"], x["note"]) for x in two] == [("small", 160, "ok"), ("large", 160, "Copied from small")]
    left = client.delete(f"/api/recipes/{rid}/dosages/{d['id']}")
    assert left.status_code == 200 and [x["printer_id"] for x in left.json()["dosages"]] == ["large"]


def test_a_dosage_is_for_a_printer_this_version_has(client):
    rid = make(client)["id"]
    r = client.post(f"/api/recipes/{rid}/dosages", json={"printer_id": "mars", "total_s": 10, "pulses": 1, "rest_s": 0})
    assert err(r) == (422, "unknown_printer") and r.json()["error"]["params"] == {"printer_id": "mars"}
    d = dosage(client, rid)["dosages"][0]
    assert err(client.post(f"/api/recipes/{rid}/dosages/{d['id']}/copy", json={"printer_id": "mars"})) == (422, "unknown_printer")
    assert len(client.get(f"/api/recipes/{rid}").json()["dosages"]) == 1


@pytest.mark.parametrize("body", [{"total_s": 10, "pulses": 1}, {"total_s": 0, "pulses": 1, "rest_s": 0}, {"total_s": 10, "pulses": 0, "rest_s": 0},
                                  {"total_s": 10, "pulses": 1.5, "rest_s": 0}, {"total_s": 10, "pulses": 1, "rest_s": -1}, {"total_s": 99999, "pulses": 1, "rest_s": 0},
                                  {"total_s": 10, "pulses": 1, "rest_s": 0, "name": "x" * 61}, {"total_s": 10, "pulses": 1, "rest_s": 0, "updated": "2020-01-01T00:00:00Z"},
                                  {"total_s": "NaN", "pulses": 1, "rest_s": 0}])
def test_a_bad_dosage_is_refused_and_the_recipe_is_untouched(client, body):
    rid = make(client)["id"]
    r = client.post(f"/api/recipes/{rid}/dosages", json={"printer_id": "small", **body})
    assert r.status_code == 422
    assert client.get(f"/api/recipes/{rid}").json()["dosages"] == []                          # a client cannot choose the date of a dosage either


def test_what_is_not_there_says_so(client):
    rid = make(client)["id"]
    assert err(client.get("/api/recipes/ghost")) == (404, "recipe_not_found")
    assert err(client.patch("/api/recipes/ghost", json={"name": "x"})) == (404, "recipe_not_found")
    assert err(client.delete("/api/recipes/ghost")) == (404, "recipe_not_found")
    assert err(client.post("/api/recipes/ghost/duplicate", json={"name": "x", "polarity": "positive"})) == (404, "recipe_not_found")
    assert err(client.post("/api/recipes/ghost/dosages", json={"printer_id": "small", "total_s": 1, "pulses": 1, "rest_s": 0})) == (404, "recipe_not_found")
    assert err(client.patch(f"/api/recipes/{rid}/dosages/ghost", json={"name": "x"})) == (404, "dosage_not_found")
    assert err(client.delete(f"/api/recipes/{rid}/dosages/ghost")) == (404, "dosage_not_found")
    assert err(client.post(f"/api/recipes/{rid}/dosages/ghost/copy", json={"printer_id": "small"})) == (404, "dosage_not_found")


def test_an_id_that_is_not_one_is_refused_before_it_reaches_a_path(client, store):
    for bad in ("a%20b", ".hidden", "x" * 80):
        assert err(client.get(f"/api/recipes/{bad}")) == (422, "bad_id")
        assert err(client.delete(f"/api/recipes/{bad}")) == (422, "bad_id")
    assert not store.root.exists()


# ---- what never reaches the page -------------------------------------------------------------------------------------------
def test_a_damaged_file_is_said_without_telling_the_page_where_it_is(client, store, tmp_path):
    good = make(client, name="good")
    bad = make(client, name="bad")
    (store.root / "recipes" / f"{bad['id']}.json").write_text("{ not json")
    listing = client.get("/api/recipes")
    assert listing.status_code == 200 and [r["id"] for r in listing.json()["recipes"]] == [good["id"]]
    assert listing.json()["problems"] == [{"file": f"{bad['id']}.json", "code": "bad_json"}]            # the file name, never the path
    r = client.get(f"/api/recipes/{bad['id']}")
    assert err(r) == (500, "data_damaged")
    assert str(tmp_path) not in r.text and str(tmp_path) not in listing.text


def test_a_change_to_a_damaged_recipe_is_refused_and_leaves_the_file(client, store):
    bad = make(client)
    path = store.root / "recipes" / f"{bad['id']}.json"
    path.write_text("{ not json")
    assert err(client.patch(f"/api/recipes/{bad['id']}", json={"name": "x"})) == (500, "data_damaged")
    assert path.read_text() == "{ not json"


# ---- the protections of the other routes hold here too -------------------------------------------------------------------------
def test_another_site_cannot_change_the_library(client, store):
    r = client.post("/api/recipes", json={"name": "x", "polarity": "negative"}, headers={"Origin": "http://evil.example"})
    assert err(r) == (403, "cross_site")
    r = client.post("/api/recipes", json={"name": "x", "polarity": "negative"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert err(r) == (403, "cross_site")
    assert not store.root.exists()


def test_a_strange_host_is_refused(client):
    assert err(client.get("/api/recipes", headers={"Host": "evil.example"})) == (403, "bad_host")


def test_what_is_written_is_the_recipe_as_the_library_keeps_it(client, store):
    rid = make(client)["id"]
    dosage(client, rid, name="Fine")
    body = json.loads((store.root / "recipes" / f"{rid}.json").read_text())
    assert body["format"] == "gerberslap-recipe" and body["recipe"] == client.get(f"/api/recipes/{rid}").json()


# ---- the start-up options --------------------------------------------------------------------------------------------------------
def run_main(monkeypatch, tmp_path, *args, env=None):
    import uvicorn
    from gerberslap.web.__main__ import main
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(app=app, **kw))
    monkeypatch.setattr(sys, "argv", ["gerberslap.web", "--allowed-host", "testserver", "--data", str(tmp_path / "d"), *args])
    for key in ("GERBERSLAP_NO_LIBRARY",):
        monkeypatch.delenv(key, raising=False)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    main()
    return TestClient(seen["app"], raise_server_exceptions=False)


def test_the_library_is_on_unless_the_option_or_the_variable_says_otherwise(monkeypatch, tmp_path, capsys):
    assert run_main(monkeypatch, tmp_path).get("/api/info").json()["library"] is True
    assert "recipe library on" in capsys.readouterr().out
    assert run_main(monkeypatch, tmp_path, "--no-library").get("/api/info").json()["library"] is False
    assert "recipe library off (--no-library)" in capsys.readouterr().out
    for value in ("1", "true", "YES", "on"):
        assert run_main(monkeypatch, tmp_path, env={"GERBERSLAP_NO_LIBRARY": value}).get("/api/info").json()["library"] is False
    for value in ("", "0", "no", "false"):
        assert run_main(monkeypatch, tmp_path, env={"GERBERSLAP_NO_LIBRARY": value}).get("/api/info").json()["library"] is True


def test_the_library_lives_in_the_data_folder_the_server_was_started_with(monkeypatch, tmp_path):
    c = run_main(monkeypatch, tmp_path)
    rid = c.post("/api/recipes", json={"name": "x", "polarity": "positive"}).json()["id"]
    assert (tmp_path / "d" / "recipes" / f"{rid}.json").is_file()


# ---- how the app was started, said in /api/info for the page to show (names of options only) ------------------------------------------
def flags_of(monkeypatch, tmp_path, *args, env=None):
    return run_main(monkeypatch, tmp_path, *args, env=env).get("/api/info").json()["flags"]


def test_a_plain_start_has_no_flags(monkeypatch, tmp_path):
    assert flags_of(monkeypatch, tmp_path) == []


def test_each_option_that_changes_what_the_app_is_is_a_flag_and_they_come_in_a_fixed_order(monkeypatch, tmp_path):
    samples = tmp_path / "samples"
    samples.mkdir()
    assert flags_of(monkeypatch, tmp_path, "--no-library") == ["--no-library"]
    assert flags_of(monkeypatch, tmp_path, "--dev-printers") == ["--dev-printers"]
    assert flags_of(monkeypatch, tmp_path, "--dev-samples", str(samples)) == ["--dev-samples"]                                  # the name, never the folder
    assert flags_of(monkeypatch, tmp_path, "--dev-samples", str(samples), "--dev-printers", "--no-library") == ["--no-library", "--dev-printers", "--dev-samples"]


def test_the_variable_that_turns_the_library_off_is_the_same_flag(monkeypatch, tmp_path):
    assert flags_of(monkeypatch, tmp_path, env={"GERBERSLAP_NO_LIBRARY": "1"}) == ["--no-library"]
    assert flags_of(monkeypatch, tmp_path, env={"GERBERSLAP_NO_LIBRARY": "0"}) == []


def test_options_about_where_the_app_listens_or_keeps_its_data_are_never_flags(monkeypatch, tmp_path):
    """The page that shows the flags may be public: no folder, no host, no port, no allowed name."""
    flags = flags_of(monkeypatch, tmp_path, "--port", "9999", "--host", "0.0.0.0", "--allowed-host", "home.example")
    assert flags == []
    every = flags_of(monkeypatch, tmp_path, "--no-library", "--dev-printers", "--port", "9999", "--allowed-host", "home.example")
    assert all(f.startswith("--") and "/" not in f and " " not in f and "=" not in f for f in every) and "9999" not in str(every) and "example" not in str(every)


def test_an_app_made_in_a_test_says_its_flags_from_what_it_was_given(tmp_path):
    from gerberslap.web.app import create_app
    store = DataStore(tmp_path / "d")
    def flags(**kw):
        return TestClient(create_app(printers=PRINTERS, allowed_hosts=["testserver"], store=store, **kw)).get("/api/info").json()["flags"]
    assert flags() == [] and flags(library=False) == ["--no-library"] and flags(dev_printers=True) == ["--dev-printers"]
    assert flags(dev_samples=tmp_path) == ["--dev-samples"]
