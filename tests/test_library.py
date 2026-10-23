"""The library of recipes and dosages: what each operation does to a recipe, the rules that never bend (the polarity is fixed, the date of a
dosage moves only with its values, a copy is independent) and that two browsers never lose each other's changes."""
import threading
from datetime import datetime, timedelta, timezone

import pytest

from gerberslap.model import MAX_DOSAGES
from gerberslap.services import library as library_module
from gerberslap.services.library import Library
from gerberslap.services.store import DataStore, Invalid, NotFound, Refused

START = datetime(2026, 10, 12, 14, 30, 5, 123456, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.t = START

    def __call__(self):
        return self.t

    def later(self, **kw):
        self.t += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def lib(tmp_path, clock):
    ids = iter(f"id-{i}" for i in range(10_000))
    return Library(DataStore(tmp_path / "data"), now=clock, new_id=lambda: next(ids))


def new_recipe(lib, **kw):
    return lib.create(**{"name": "Dry film", "polarity": "negative", **kw})


def add(lib, recipe_id, **kw):
    return lib.add_dosage(recipe_id, **{"printer_id": "ld002h", "total_s": 200, "pulses": 5, "rest_s": 4, **kw})


def file_bytes(lib, recipe_id):
    return (lib.store.root / "recipes" / f"{recipe_id}.json").read_bytes()


# ---- recipes -----------------------------------------------------------------------------------------------------
def test_a_recipe_is_created_with_an_id_the_library_chooses_and_no_dosages(lib):
    r = new_recipe(lib, resist="Dry film 25 µm", development="Soda 1%", notes="stendere senza bolle")
    assert (r.id, r.name, r.polarity.value, r.resist, r.development, r.notes, r.dosages) == ("id-0", "Dry film", "negative", "Dry film 25 µm", "Soda 1%", "stendere senza bolle", ())
    assert lib.get("id-0") == r and lib.list().items == (r,)


def test_a_recipe_needs_a_name_and_the_values_are_validated_before_anything_is_written(lib):
    for bad in ({"name": ""}, {"name": "x" * 201}, {"resist": "a\nb"}):
        with pytest.raises(Invalid) as e:
            new_recipe(lib, **bad)
        assert e.value.code == "bad_content"
    assert not lib.store.root.exists()


def test_editing_changes_only_what_is_given_and_keeps_the_dosages(lib):
    new_recipe(lib, notes="one")
    add(lib, "id-0", name="Fine")
    r = lib.edit("id-0", name="Renamed", resist="New resist")
    assert (r.name, r.resist, r.notes) == ("Renamed", "New resist", "one") and [d.name for d in r.dosages] == ["Fine"]
    assert lib.get("id-0") == r


def test_the_polarity_can_be_sent_back_but_not_changed(lib):
    new_recipe(lib, polarity="negative")
    assert lib.edit("id-0", polarity="negative", name="same polarity").name == "same polarity"
    before = file_bytes(lib, "id-0")
    with pytest.raises(Refused) as e:
        lib.edit("id-0", polarity="positive", name="and a new name")
    assert e.value.code == "polarity_locked" and file_bytes(lib, "id-0") == before                    # nothing of it was applied


def test_a_recipe_that_is_not_there_cannot_be_edited_or_deleted(lib):
    with pytest.raises(NotFound) as e:
        lib.edit("ghost", name="x")
    assert e.value.code == "recipe_not_found"
    with pytest.raises(NotFound):
        lib.delete("ghost")


def test_a_duplicate_has_the_text_and_the_dosages_with_new_ids_and_the_polarity_chosen(lib, clock):
    new_recipe(lib, resist="Dry film", notes="n")
    add(lib, "id-0", name="Fine", note="ok")
    clock.later(days=3)
    add(lib, "id-0", printer_id="other", total_s=90, pulses=3, rest_s=2)
    source = lib.get("id-0")
    copy = lib.duplicate("id-0", name="Dry film (copia)", polarity="positive")
    assert (copy.name, copy.polarity.value, copy.resist, copy.notes) == ("Dry film (copia)", "positive", "Dry film", "n")
    assert [(d.printer_id, d.total_s, d.name, d.note, d.updated) for d in copy.dosages] == [(d.printer_id, d.total_s, d.name, d.note, d.updated) for d in source.dosages]
    ids = {copy.id, *(d.id for d in copy.dosages), source.id, *(d.id for d in source.dosages)}
    assert len(ids) == 2 + 2 * 2                                                            # every id is new
    assert lib.get("id-0") == source and lib.get(copy.id) == copy                           # the source is as it was


def test_deleting_a_recipe_takes_its_dosages_with_it(lib):
    new_recipe(lib)
    add(lib, "id-0")
    lib.delete("id-0")
    assert lib.list().items == () and not (lib.store.root / "recipes" / "id-0.json").exists()


# ---- dosages ------------------------------------------------------------------------------------------------------
def test_a_dosage_is_added_with_the_moment_it_was_found(lib):
    new_recipe(lib)
    r = add(lib, "id-0", name="Fine tracks", note="ok")
    d, = r.dosages
    assert (d.printer_id, d.total_s, d.pulses, d.rest_s, d.name, d.note) == ("ld002h", 200, 5, 4, "Fine tracks", "ok")
    assert d.updated == START.replace(microsecond=0) and d.flash_s == 40


def test_dosages_are_alternatives_for_the_same_printer(lib, clock):
    new_recipe(lib)
    add(lib, "id-0", name="Fine")
    clock.later(minutes=5)
    r = add(lib, "id-0", name="Large planes", total_s=120, pulses=3)
    assert [d.name for d in r.dosages_for("ld002h")] == ["Large planes", "Fine"]                  # the last changed first


def test_values_out_of_range_are_refused_and_the_recipe_is_untouched(lib):
    new_recipe(lib)
    before = file_bytes(lib, "id-0")
    for bad in ({"pulses": 0}, {"total_s": 0}, {"rest_s": -1}, {"name": "a\nb"}, {"printer_id": "../x"}):
        with pytest.raises(Invalid) as e:
            add(lib, "id-0", **bad)
        assert e.value.code == "bad_content"
    assert file_bytes(lib, "id-0") == before


def test_a_recipe_holds_a_limited_number_of_dosages(lib):
    new_recipe(lib)
    for _ in range(MAX_DOSAGES):
        add(lib, "id-0")
    with pytest.raises(Refused) as e:
        add(lib, "id-0")
    assert e.value.code == "too_many_dosages" and len(lib.get("id-0").dosages) == MAX_DOSAGES


def test_the_date_of_a_dosage_moves_only_when_its_values_change(lib, clock):
    new_recipe(lib)
    r = add(lib, "id-0", name="Fine")
    did = r.dosages[0].id
    found = r.dosages[0].updated
    clock.later(days=30)
    r = lib.edit_dosage("id-0", did, name="Finer", note="a note")                         # a new name and note: the values still hold from the same day
    assert (r.dosages[0].name, r.dosages[0].note, r.dosages[0].updated) == ("Finer", "a note", found)
    r = lib.edit_dosage("id-0", did, total_s=200, pulses=5, rest_s=4)                     # the same values again: nothing changed
    assert r.dosages[0].updated == found
    r = lib.edit_dosage("id-0", did, rest_s=6)                                            # a value: from now on
    assert (r.dosages[0].rest_s, r.dosages[0].updated) == (6, (START + timedelta(days=30)).replace(microsecond=0))
    assert (r.dosages[0].total_s, r.dosages[0].pulses) == (200, 5)                        # what was not given stays


def test_changing_the_values_of_a_dosage_makes_it_the_preselected_one(lib, clock):
    new_recipe(lib)
    add(lib, "id-0", name="old")
    clock.later(days=1)
    r = add(lib, "id-0", name="newer")
    old_id = next(d.id for d in r.dosages if d.name == "old")
    assert r.dosages_for("ld002h")[0].name == "newer"
    clock.later(days=1)
    r = lib.edit_dosage("id-0", old_id, total_s=210)
    assert r.dosages_for("ld002h")[0].name == "old"


def test_editing_with_bad_values_or_a_missing_dosage_changes_nothing(lib):
    new_recipe(lib)
    add(lib, "id-0")
    before = file_bytes(lib, "id-0")
    with pytest.raises(Invalid):
        lib.edit_dosage("id-0", lib.get("id-0").dosages[0].id, pulses=0)
    for call in (lambda: lib.edit_dosage("id-0", "ghost", name="x"), lambda: lib.delete_dosage("id-0", "ghost"), lambda: lib.copy_dosage("id-0", "ghost", printer_id="p")):
        with pytest.raises(NotFound) as e:
            call()
        assert e.value.code == "dosage_not_found"
    with pytest.raises(NotFound) as e:
        lib.edit_dosage("ghost", "x", name="x")
    assert e.value.code == "recipe_not_found" and file_bytes(lib, "id-0") == before


def test_deleting_a_dosage_leaves_the_others(lib):
    new_recipe(lib)
    add(lib, "id-0", name="a")
    r = add(lib, "id-0", name="b")
    gone = next(d.id for d in r.dosages if d.name == "a")
    r = lib.delete_dosage("id-0", gone)
    assert [d.name for d in r.dosages] == ["b"] and lib.get("id-0") == r


def test_a_copy_of_a_dosage_is_for_another_printer_and_independent_of_its_source(lib, clock):
    new_recipe(lib)
    r = add(lib, "id-0", name="Fine", note="found on the LD")
    source = r.dosages[0]
    clock.later(days=2)
    r = lib.copy_dosage("id-0", source.id, printer_id="fabula", note="Copied from ld002h")
    copy = r.dosage(next(d.id for d in r.dosages if d.printer_id == "fabula"))
    assert (copy.total_s, copy.pulses, copy.rest_s, copy.name, copy.note) == (200, 5, 4, "Fine", "Copied from ld002h")
    assert copy.id != source.id and copy.updated == (START + timedelta(days=2)).replace(microsecond=0)
    r = lib.edit_dosage("id-0", copy.id, total_s=90)                                      # tuning the copy never touches the source
    assert r.dosage(source.id) == source and r.dosage(copy.id).total_s == 90
    r = lib.copy_dosage("id-0", source.id, printer_id="fabula")                           # no note given: the source's
    assert r.dosages[-1].note == "found on the LD"


def test_two_browsers_adding_dosages_to_the_same_recipe_lose_none(lib):
    new_recipe(lib)
    threads = [threading.Thread(target=lambda i=i: add(lib, "id-0", name=f"d{i}")) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(d.name for d in lib.get("id-0").dosages) == sorted(f"d{i}" for i in range(30))


def test_the_library_defaults_to_the_real_clock_and_uuids(tmp_path):
    real = Library(DataStore(tmp_path / "data"))
    r = real.create(name="x", polarity="positive")
    assert len(r.id) == 36 and r.id.count("-") == 4
    d, = real.add_dosage(r.id, printer_id="p", total_s=1, pulses=1, rest_s=0).dosages
    assert abs((datetime.now(timezone.utc) - d.updated).total_seconds()) < 5 and d.updated.microsecond == 0
