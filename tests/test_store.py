"""The data folder: atomic writes, the printers' templates and optional settings, the recipes (one file each, with their dosages), and what
happens with files that are damaged, from a newer version, or try to leave the folder."""
import errno
import json
import os
import threading
from datetime import datetime, timezone

import pytest

from gerberslap.model import Dosage, PrinterFile, Recipe
from gerberslap.services import files, store as store_module
from gerberslap.services.store import (AlreadyExists, DataStore, Invalid, MAX_TEMPLATE_BYTES, NotFound, Refused, default_root)

T0 = datetime(2026, 10, 3, 9, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    return DataStore(tmp_path / "data")


def leftovers(root):
    return [p for p in root.rglob("*") if p.name.startswith(".tmp-")]


def dosage(i=1, printer="ld002h", **kw):
    return Dosage(id=f"d{i}", printer_id=printer, updated=T0, total_s=kw.pop("total_s", 80), pulses=kw.pop("pulses", 4), rest_s=kw.pop("rest_s", 5), **kw)


def recipe(i=1, **kw):
    return Recipe(id=kw.pop("id", f"r{i}"), name=kw.pop("name", f"Recipe {i}"), polarity=kw.pop("polarity", "negative"), **kw)


def recipe_path(store, recipe_id):
    return store.root / "recipes" / f"{recipe_id}.json"


def write_printer_json(store, printer_id, body):
    path = store.root / "printers" / printer_id / "printer.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return path


# ---- atomic writes -----------------------------------------------------------------------------------------------
def test_write_atomic_creates_the_folders_and_leaves_no_temporary_file(tmp_path):
    target = tmp_path / "a" / "b" / "f.json"
    files.write_atomic(target, b"one")
    assert target.read_bytes() == b"one" and leftovers(tmp_path) == []


def test_a_failed_replace_leaves_the_old_file_and_cleans_up(tmp_path, monkeypatch):
    target = tmp_path / "f.json"
    files.write_atomic(target, b"old")
    monkeypatch.setattr(files.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError(errno.ENOSPC, "disk full")))
    with pytest.raises(OSError):
        files.write_atomic(target, b"new")
    assert target.read_bytes() == b"old" and leftovers(tmp_path) == []


def test_a_failed_write_of_the_data_leaves_the_old_file(tmp_path, monkeypatch):
    target = tmp_path / "f.json"
    files.write_atomic(target, b"old")
    monkeypatch.setattr(files.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError(errno.EIO, "io error")))
    with pytest.raises(OSError):
        files.write_atomic(target, b"new")
    assert target.read_bytes() == b"old" and leftovers(tmp_path) == []


def test_exclusive_write_never_replaces(tmp_path):
    target = tmp_path / "c.json"
    files.write_atomic(target, b"first", exclusive=True)
    with pytest.raises(FileExistsError):
        files.write_atomic(target, b"second", exclusive=True)
    assert target.read_bytes() == b"first" and leftovers(tmp_path) == []


def test_exclusive_write_still_works_on_a_file_system_without_hard_links(tmp_path, monkeypatch):
    monkeypatch.setattr(files.os, "link", lambda *a, **k: (_ for _ in ()).throw(OSError(errno.ENOTSUP, "no links")))
    target = tmp_path / "c.json"
    files.write_atomic(target, b"first", exclusive=True)
    assert target.read_bytes() == b"first"
    with pytest.raises(FileExistsError):
        files.write_atomic(target, b"second", exclusive=True)
    assert target.read_bytes() == b"first" and leftovers(tmp_path) == []




# ---- root --------------------------------------------------------------------------------------------------------
def test_the_root_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("GERBERSLAP_DATA", str(tmp_path / "elsewhere"))
    assert default_root() == tmp_path / "elsewhere"
    assert DataStore().root == (tmp_path / "elsewhere").absolute()
    monkeypatch.delenv("GERBERSLAP_DATA")
    assert default_root().name == "data"


def test_nothing_is_created_by_looking(store):
    assert store.list_recipes().items == () and store.printer_settings("ld002h") == {}
    assert not store.root.exists()


def test_ids_are_checked_before_they_reach_a_path(store):
    for bad in ("../x", "a/b", "", ".hidden"):
        for call in (store.get_recipe, store.delete_recipe, store.printer_settings, lambda i: store.update_recipe(i, lambda r: r)):
            with pytest.raises(Invalid) as e:
                call(bad)
            assert e.value.code == "bad_id"                               # the same answer everywhere, not "not found"


# ---- the printers' settings --------------------------------------------------------------------------------------
def test_without_a_printer_json_the_settings_are_the_drivers_defaults(store):
    assert store.printer_settings("ld002h") == {}


def test_the_settings_somebody_wrote_are_read(store):
    write_printer_json(store, "ld002h", {"format": "gerberslap-printer", "schema_version": 1, "printer": {"settings": {"park_z_mm": 2.0}}})
    assert store.printer_settings("ld002h") == {"park_z_mm": 2.0}


@pytest.mark.parametrize("body, code", [
    ("{ not json", "bad_json"),
    ({"format": "gerberslap-recipe", "schema_version": 1, "printer": {}}, "wrong_format"),
    ({"format": "gerberslap-printer", "schema_version": 2, "printer": {}}, "newer_schema"),
    ({"format": "gerberslap-printer", "schema_version": 1, "printer": {"settings": {}, "template": "template.ctb"}}, "bad_content"),   # an old file: the template is not named here any more
    ({"format": "gerberslap-printer", "schema_version": 1, "printer": {"id": "ld002h", "name": "x", "driver": "ld002h"}}, "bad_content"),
])
def test_a_settings_file_that_cannot_be_used_is_an_error_not_the_defaults(store, body, code):
    write_printer_json(store, "ld002h", body)
    with pytest.raises(Invalid) as e:
        store.printer_settings("ld002h")
    assert e.value.code == code


def test_a_printer_folder_that_is_a_symlink_out_of_the_data_folder_is_refused(store, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.root / "printers").mkdir(parents=True)
    try:
        os.symlink(outside, store.root / "printers" / "evil")
    except OSError:
        pytest.skip("cannot create symlinks here")
    with pytest.raises(Invalid) as e:
        store.printer_settings("evil")
    assert e.value.code == "outside_root"
    with pytest.raises(Invalid):
        store.set_template("evil", "template.ctb", b"data")
    assert list(outside.iterdir()) == []


# ---- the template ------------------------------------------------------------------------------------------------
def test_installing_a_template_stores_the_file_under_the_name_given_and_says_where(store):
    path = store.set_template("ld002h", "template.ctb", b"CTB bytes")
    assert path == store.root / "printers" / "ld002h" / "template.ctb" and path.read_bytes() == b"CTB bytes"
    assert store.printer_file("ld002h", "template.ctb") == path
    assert sorted(p.name for p in path.parent.iterdir()) == ["template.ctb"]                 # nothing else: no printer.json is written
    assert leftovers(store.root) == []


def test_the_drivers_check_runs_on_the_file_and_can_reject_it(store):
    seen = []

    def check(path):
        seen.append(path.read_bytes())
        raise ValueError("bad magic")
    with pytest.raises(Invalid) as e:
        store.set_template("ld002h", "template.ctb", b"junk", validate=check)
    assert e.value.code == "template_rejected" and "bad magic" in str(e.value) and seen == [b"junk"]
    assert not (store.root / "printers" / "ld002h" / "template.ctb").exists() and leftovers(store.root) == []


def test_a_rejected_replacement_keeps_the_template_that_was_working(store):
    store.set_template("ld002h", "template.ctb", b"good")
    with pytest.raises(Invalid):
        store.set_template("ld002h", "template.ctb", b"bad", validate=lambda p: (_ for _ in ()).throw(ValueError("no")))
    assert store.printer_file("ld002h", "template.ctb").read_bytes() == b"good"


def test_installing_again_replaces_the_template(store):
    store.set_template("ld002h", "template.ctb", b"old")
    store.set_template("ld002h", "template.ctb", b"new")
    assert store.printer_file("ld002h", "template.ctb").read_bytes() == b"new" and leftovers(store.root) == []


@pytest.mark.parametrize("name", ["printer.json", ".hidden", "../x.ctb", "a/b.ctb", ""])
def test_template_names_cannot_clobber_the_stores_own_files_or_leave_the_folder(store, name):
    write_printer_json(store, "ld002h", {"format": "gerberslap-printer", "schema_version": 1, "printer": {"settings": {}}})
    before = (store.root / "printers" / "ld002h" / "printer.json").read_bytes()
    with pytest.raises(Invalid):
        store.set_template("ld002h", name, b"data")
    assert (store.root / "printers" / "ld002h" / "printer.json").read_bytes() == before


def test_empty_and_oversized_templates_are_refused(store):
    with pytest.raises(Invalid) as e:
        store.set_template("ld002h", "t.ctb", b"")
    assert e.value.code == "template_rejected"
    with pytest.raises(Invalid) as e:
        store.set_template("ld002h", "t.ctb", b"x" * (MAX_TEMPLATE_BYTES + 1))
    assert e.value.code == "template_too_large"
    assert not store.root.exists()


def test_printer_file_refuses_names_that_are_paths_or_missing(store):
    store.set_template("ld002h", "template.ctb", b"data")
    with pytest.raises(Invalid):
        store.printer_file("ld002h", "../printer.json")
    with pytest.raises(NotFound):
        store.printer_file("ld002h", "nothing.ctb")
    with pytest.raises(NotFound):
        store.printer_file("other", "template.ctb")


# ---- recipes -----------------------------------------------------------------------------------------------------
def test_a_recipe_round_trips_with_its_dosages(store):
    r = recipe(1, resist="Dry film", development="Soda 1%", notes="line 1\nline 2", dosages=(dosage(1, name="Fine tracks", note="ok"), dosage(2, printer="other")))
    store.create_recipe(r)
    assert store.get_recipe("r1") == r
    assert store.list_recipes().items == (r,)


def test_a_recipe_file_is_plain_readable_json_with_a_version_and_utc_times(store):
    store.create_recipe(recipe(1, dosages=(dosage(1),)))
    body = json.loads(recipe_path(store, "r1").read_text(encoding="utf-8"))
    assert body["format"] == "gerberslap-recipe" and body["schema_version"] == 1
    assert body["recipe"]["dosages"][0] == {"id": "d1", "printer_id": "ld002h", "updated": "2026-10-03T09:00:00Z", "total_s": 80.0, "pulses": 4,
                                            "rest_s": 5.0, "name": "", "note": ""}
    assert leftovers(store.root) == []


def test_the_list_is_by_name_ignoring_case_and_says_nothing_of_other_files(store):
    for i, name in enumerate(["beta", "Alpha", "alpha 2", "Zed"], 1):
        store.create_recipe(recipe(i, name=name))
    (store.root / "recipes" / "notes.txt").write_text("not a recipe")
    (store.root / "recipes" / ".tmp-leftover.part").write_text("x")
    listing = store.list_recipes()
    assert [r.name for r in listing.items] == ["Alpha", "alpha 2", "beta", "Zed"] and listing.problems == ()


def test_create_never_replaces_a_recipe(store):
    store.create_recipe(recipe(1, name="first"))
    before = recipe_path(store, "r1").read_bytes()
    with pytest.raises(AlreadyExists) as e:
        store.create_recipe(recipe(1, name="second"))
    assert e.value.code == "recipe_exists" and recipe_path(store, "r1").read_bytes() == before and leftovers(store.root) == []


def test_update_reads_changes_and_writes(store):
    store.create_recipe(recipe(1))
    new = store.update_recipe("r1", lambda r: r.model_copy(update={"name": "Renamed", "dosages": (dosage(1),)}))
    assert new.name == "Renamed" and store.get_recipe("r1") == new


def test_a_recipes_id_and_polarity_cannot_change(store):
    store.create_recipe(recipe(1, polarity="negative"))
    before = recipe_path(store, "r1").read_bytes()
    with pytest.raises(Refused) as e:
        store.update_recipe("r1", lambda r: r.model_copy(update={"polarity": "positive"}))
    assert e.value.code == "polarity_locked"
    with pytest.raises(Invalid):
        store.update_recipe("r1", lambda r: r.model_copy(update={"id": "other"}))
    assert recipe_path(store, "r1").read_bytes() == before and not recipe_path(store, "other").exists()


def test_a_change_that_raises_leaves_the_file_as_it_was(store):
    store.create_recipe(recipe(1))
    before = recipe_path(store, "r1").read_bytes()

    def boom(r):
        raise RuntimeError("no")
    with pytest.raises(RuntimeError):
        store.update_recipe("r1", boom)
    assert recipe_path(store, "r1").read_bytes() == before


def test_a_recipe_that_is_not_there_says_so_with_its_own_code(store):
    for call in (lambda: store.get_recipe("ghost"), lambda: store.delete_recipe("ghost"), lambda: store.update_recipe("ghost", lambda r: r)):
        with pytest.raises(NotFound) as e:
            call()
        assert e.value.code == "recipe_not_found"


def test_deleting_a_recipe(store):
    store.create_recipe(recipe(1))
    store.create_recipe(recipe(2))
    store.delete_recipe("r1")
    assert [r.id for r in store.list_recipes().items] == ["r2"]


def test_a_damaged_recipe_is_reported_apart_and_the_others_are_still_listed(store):
    store.create_recipe(recipe(1))
    store.create_recipe(recipe(2))
    recipe_path(store, "r2").write_text("{ not json")
    listing = store.list_recipes()
    assert [r.id for r in listing.items] == ["r1"] and [(p.code, p.path.endswith("r2.json")) for p in listing.problems] == [("bad_json", True)]
    with pytest.raises(Invalid) as e:
        store.get_recipe("r2")
    assert e.value.code == "bad_json"


def test_a_file_that_holds_another_recipe_than_its_name_says_is_reported(store):
    store.create_recipe(recipe(1))
    (store.root / "recipes" / "r9.json").write_bytes(recipe_path(store, "r1").read_bytes())
    listing = store.list_recipes()
    assert [r.id for r in listing.items] == ["r1"] and [p.code for p in listing.problems] == ["id_mismatch"]


def test_a_file_from_a_newer_version_is_refused_not_misread(store):
    store.create_recipe(recipe(1))
    body = json.loads(recipe_path(store, "r1").read_text())
    body["schema_version"] = 2
    recipe_path(store, "r1").write_text(json.dumps(body))
    with pytest.raises(Invalid) as e:
        store.get_recipe("r1")
    assert e.value.code == "newer_schema"


def test_a_recipe_file_with_a_value_out_of_range_is_reported_not_repaired(store):
    store.create_recipe(recipe(1, dosages=(dosage(1),)))
    body = json.loads(recipe_path(store, "r1").read_text())
    body["recipe"]["dosages"][0]["pulses"] = 0
    recipe_path(store, "r1").write_text(json.dumps(body))
    with pytest.raises(Invalid) as e:
        store.get_recipe("r1")
    assert e.value.code == "bad_content" and "pulses" in e.value.detail


def test_the_library_has_a_limit(store, monkeypatch):
    monkeypatch.setattr(store_module, "MAX_RECIPES", 3)
    for i in range(3):
        store.create_recipe(recipe(i))
    with pytest.raises(Refused) as e:
        store.create_recipe(recipe(9))
    assert e.value.code == "too_many_recipes" and not recipe_path(store, "r9").exists()


def test_a_recipes_folder_that_is_a_symlink_out_of_the_data_folder_is_refused(store, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    store.root.mkdir(parents=True)
    try:
        os.symlink(outside, store.root / "recipes")
    except OSError:
        pytest.skip("cannot create symlinks here")
    with pytest.raises(Invalid) as e:
        store.create_recipe(recipe(1))
    assert e.value.code == "outside_root" and list(outside.iterdir()) == []


def test_concurrent_creates_do_not_lose_recipes(store):
    threads = [threading.Thread(target=lambda i=i: store.create_recipe(recipe(i))) for i in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r.id for r in store.list_recipes().items) == sorted(f"r{i}" for i in range(24)) and leftovers(store.root) == []


def test_concurrent_changes_to_the_same_recipe_do_not_lose_each_other(store):
    store.create_recipe(recipe(1))

    def add(i):
        store.update_recipe("r1", lambda r: r.model_copy(update={"dosages": (*r.dosages, dosage(i))}))
    threads = [threading.Thread(target=add, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(d.id for d in store.get_recipe("r1").dosages) == sorted(f"d{i}" for i in range(40)) and leftovers(store.root) == []
