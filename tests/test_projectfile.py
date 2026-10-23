"""The project file: written deterministically and read back, read strictly (the archive comes from outside), migrated between versions.
Hostile archives are built in memory from a good one, one defect at a time."""
import hashlib
import io
import json
import warnings
import zipfile
from pathlib import Path

import numpy as np
import pytest
from markerboard import imported, marker_files, project_of

from gerberslap.core import Grid
from gerberslap.model import Polarity, Project
from gerberslap.services import projectfile as pf
from gerberslap.services.importer import import_zip
from gerberslap.services.pipeline import render
from gerberslap.services.projectfile import BoardInfo, ProjectFileError, open_project, save_project

REPO = Path(__file__).resolve().parent.parent
EXT = REPO / "experiments" / "fase2" / "external"
GRID = Grid(width=2560, height=1620, pitch=0.051)


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


@pytest.fixture(scope="module")
def made():
    """A project with the marker board (mask, holes, a custom order and a colour, mirrored and rotated) and what the page keeps about it."""
    imp = imported(marker_files(mask=True, hole=True))
    proj = project_of(imp, angle=33.5, mirror=True, centre=(61.5, 42.25), on={"mask": True})
    board = proj.boards[0]
    layers = tuple(reversed(board.layers))
    layers = tuple(l.model_copy(update={"color": "#12ab34"}) if l.role.value == "copper" else l for l in layers)
    proj = proj.model_copy(update={"boards": (board.model_copy(update={"layers": layers}),), "polarity": Polarity.NEGATIVE, "min_outline_mm": 0.45})
    info = {"b1": BoardInfo(cad="kicad", notes=imp.issues)}
    return proj, imp.files, info, save_project(proj, imp.files, name="my project", info=info)


def entries(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {i.filename: z.read(i) for i in z.infolist()}


def zipped(items, *, attr=None):
    """An archive from (name, bytes) pairs, which may repeat a name or use any name."""
    buf = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")                          # zipfile warns about a duplicate name
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, content in items:
                zi = zipfile.ZipInfo(name, date_time=(2026, 10, 13, 0, 0, 0))
                zi.compress_type = zipfile.ZIP_DEFLATED
                if attr is not None:
                    zi.external_attr = attr << 16
                z.writestr(zi, content)
    return buf.getvalue()


def altered(data, *, doc=None, drop=(), add=(), replace=None):
    """The good archive with one thing changed: `doc` edits the parsed project.json, `drop` removes entries, `add` appends (name, bytes)
    pairs, `replace` maps an entry name to new bytes."""
    parts = entries(data)
    if doc:
        d = json.loads(parts[pf.PROJECT_JSON])
        doc(d)
        parts[pf.PROJECT_JSON] = json.dumps(d).encode()
    for name in drop:
        del parts[name]
    parts.update(replace or {})
    return zipped([*parts.items(), *add])


def refuses(data, code, **params):
    with pytest.raises(ProjectFileError) as e:
        open_project(data)
    assert e.value.code == code, (e.value.code, e.value.params)
    for k, v in params.items():
        assert e.value.params[k] == v, (k, e.value.params)
    return e.value


# ---- writing and reading back -----------------------------------------------------------------------------------
def test_a_project_comes_back_exactly_as_it_was_saved(made):
    proj, files, info, data = made
    back = open_project(data)
    assert back.project == proj and back.name == "my project" and back.info == info and back.files == files
    assert [l.id for l in back.project.boards[0].layers] == [l.id for l in proj.boards[0].layers]          # the order the user chose
    assert next(l for l in back.project.boards[0].layers if l.role.value == "copper").color == "#12ab34"   # the colour too


def test_the_archive_holds_only_the_project_and_each_distinct_file_once(made):
    proj, files, info, data = made
    board = proj.boards[0]
    twin = board.model_copy(update={"id": "b2", "name": "twin"})                 # a copy of the board: it shares every file
    two = proj.model_copy(update={"boards": (board, twin)})
    names = list(entries(save_project(two, files)))
    assert names == [pf.PROJECT_JSON] + [f"files/{s}" for s in sorted(pf.referenced_files(proj))]               # sorted, nothing else
    assert len(names) == 1 + len(files)


def test_the_same_project_gives_the_same_bytes(made):
    proj, files, info, data = made
    assert save_project(proj, files, name="my project", info=info) == data
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert {i.date_time for i in z.infolist()} == {(1980, 1, 1, 0, 0, 0)}                                  # not the clock


def test_the_file_is_plain_json_with_the_version_the_name_and_the_notes(made):
    proj, files, info, data = made
    doc = json.loads(entries(data)[pf.PROJECT_JSON])
    assert doc["format"] == "gerberslap" and doc["schema_version"] == 2 and doc["name"] == "my project"
    assert doc["info"]["b1"]["cad"] == "kicad" and doc["polarity"] == "negative" and doc["min_outline_mm"] == 0.45
    assert doc["boards"][0]["placement"] == {"x": 61.5, "y": 42.25, "angle": 33.5, "mirror": True}


def test_an_empty_project_can_be_saved_and_opened():
    empty = Project()
    back = open_project(save_project(empty, {}))
    assert back.project == empty and back.name is None and back.info == {} and back.files == {}


def test_what_is_exposed_is_the_same_after_saving_and_opening(made):
    proj, files, info, data = made
    back = open_project(data)
    a = render(proj, files, GRID, Polarity.NEGATIVE, supersample=8)
    b = render(back.project, back.files, GRID, Polarity.NEGATIVE, supersample=8)
    assert np.array_equal(a.mask, b.mask) and a.lit_pixels > 0


@pytest.mark.parametrize("zip_name", ["kicad_uni_mosfet_key.zip", "altium_flight_controller.zip", "eagle9_torazza.zip"])
def test_a_real_board_goes_through_the_file_and_exposes_the_same(zip_name):
    path = EXT / zip_name
    if not path.exists():
        pytest.skip(f"{zip_name} is not in experiments/fase2/external/")
    imp = import_zip(path, board_id="b1", source_name=zip_name)
    layers = tuple(l.model_copy(update={"on": l.role.value in ("copper", "mask") and l.side.value == "top" and l.status.level != "error"}) for l in imp.board.layers)
    proj = Project(boards=(imp.board.model_copy(update={"layers": layers}),))
    back = open_project(save_project(proj, imp.files, info={"b1": BoardInfo(cad=imp.cad, notes=imp.issues)}))
    assert back.project == proj and back.files == {s: imp.files[s] for s in pf.referenced_files(proj)}     # the ignored files are kept too
    assert np.array_equal(render(proj, imp.files, GRID, Polarity.NEGATIVE, supersample=8).mask,
                          render(back.project, back.files, GRID, Polarity.NEGATIVE, supersample=8).mask)


# ---- what saving refuses -----------------------------------------------------------------------------------------
def test_a_file_the_store_no_longer_has_is_named(made):
    proj, files, info, data = made
    sha_, fname = next(iter(pf.referenced_files(proj).items()))
    with pytest.raises(ProjectFileError) as e:
        save_project(proj, {k: v for k, v in files.items() if k != sha_})
    assert e.value.code == "file_missing" and e.value.params == {"file": fname, "sha256": sha_}


def test_a_file_that_is_not_what_its_hash_says_is_not_saved(made):
    proj, files, info, data = made
    sha_ = next(iter(pf.referenced_files(proj)))
    with pytest.raises(ProjectFileError) as e:
        save_project(proj, {**files, sha_: b"something else"})
    assert e.value.code == "bad_hash" and e.value.params["entry"] == f"files/{sha_}"


def test_notes_for_a_board_that_is_not_in_the_project_are_refused(made):
    proj, files, info, data = made
    with pytest.raises(ProjectFileError) as e:
        save_project(proj, files, info={"nobody": BoardInfo()})
    assert e.value.code == "invalid_project" and e.value.params["boards"] == ["nobody"]


def test_what_is_written_is_read_back_before_it_is_handed_over(made, monkeypatch):
    proj, files, info, data = made
    other = save_project(Project(), {})                                                         # a valid file, but not this project
    monkeypatch.setattr(pf, "_write", lambda *a, **k: other)
    with pytest.raises(ProjectFileError) as e:
        save_project(proj, files, name="my project", info=info)
    assert e.value.code == "verification_failed"


# ---- hostile and damaged archives --------------------------------------------------------------------------------
def test_something_that_is_not_a_zip_is_refused():
    refuses(b"PK\x03\x04 but not really", "bad_zip")
    refuses(b"", "bad_zip")
    refuses(b'{"format": "gerberslap"}', "bad_zip")


def test_an_archive_without_a_project_is_refused(made):
    refuses(zipped([("readme.txt", b"hi")]), "bad_entry", entry="readme.txt")
    refuses(zipped([]), "not_a_project")
    refuses(altered(made[3], drop=[pf.PROJECT_JSON]), "not_a_project")


@pytest.mark.parametrize("name", ["../evil", "/etc/passwd", "files/../project.json", "files/" + "A" * 64, "files/" + "a" * 63, "files/" + "a" * 64 + "/x",
                                  "files/" + "a" * 64 + ".gbr", "other.txt", "project.json/x", "files\\" + "a" * 64, "__MACOSX/._project.json",
                                  ".DS_Store", "files/" + "a" * 64 + "\n"])
def test_an_entry_that_is_not_the_project_or_a_file_by_hash_is_refused(made, name):
    refuses(altered(made[3], add=[(name, b"x")]), "bad_entry")


def test_the_name_of_a_refused_entry_is_shown_safely(made):
    hostile = "bad\x1b[31m\nline" + "n" * 300                                                      # (zipfile itself cuts a name at a NUL)
    e = refuses(altered(made[3], add=[(hostile, b"x")]), "bad_entry")
    assert len(e.params["entry"]) == 120 and not any(ord(c) < 32 for c in e.params["entry"]) and e.params["entry"].startswith("bad?[31m?line")


def test_the_same_entry_twice_is_refused(made):
    first = pf.PROJECT_JSON
    refuses(altered(made[3], add=[(first, b"{}")]), "duplicate_entry", entry=first)
    sha_ = next(iter(pf.referenced_files(made[0])))
    refuses(altered(made[3], add=[(f"files/{sha_}", b"x")]), "duplicate_entry")


def test_too_many_entries_and_too_much_data_are_refused(made, monkeypatch):
    monkeypatch.setattr(pf, "MAX_MEMBERS", 3)
    refuses(made[3], "too_large")
    monkeypatch.setattr(pf, "MAX_MEMBERS", 500)
    monkeypatch.setattr(pf, "MAX_MEMBER_BYTES", 100)                                                           # a file bigger than this
    refuses(made[3], "too_large")
    monkeypatch.setattr(pf, "MAX_MEMBER_BYTES", 2**20)
    monkeypatch.setattr(pf, "MAX_TOTAL_BYTES", 500)                                                            # all of them together
    refuses(made[3], "too_large")
    monkeypatch.setattr(pf, "MAX_TOTAL_BYTES", 2**30)
    monkeypatch.setattr(pf, "MAX_JSON_BYTES", 50)                                                              # project.json itself
    refuses(made[3], "too_large", entry=pf.PROJECT_JSON)


def test_an_entry_that_declares_a_small_size_and_inflates_is_stopped(made, monkeypatch):
    """A bomb: a few KB of zeros that inflate to far more than the limit. Only what is read counts, not what the header says."""
    sha_ = next(iter(pf.referenced_files(made[0])))
    bomb = altered(made[3], replace={f"files/{sha_}": bytes(5_000_000)})
    monkeypatch.setattr(pf, "MAX_MEMBER_BYTES", 1_000_000)
    assert len(bomb) < 100_000
    refuses(bomb, "too_large")


def test_a_damaged_entry_is_refused(made):
    raw = bytearray(made[3])
    raw[len(raw) // 2] ^= 0xFF                                                                                 # a bit flipped in the middle of the data
    with pytest.raises(ProjectFileError) as e:
        open_project(bytes(raw))
    assert e.value.code in ("bad_zip", "bad_hash", "bad_json", "invalid_project")                             # wherever it lands, never opened


def test_an_encrypted_entry_is_refused(made):
    raw = bytearray(made[3])
    at = raw.find(b"PK\x01\x02")
    assert at >= 0
    while at >= 0:                                                                                 # mark every entry of the central directory encrypted
        raw[at + 8] |= 0x01
        at = raw.find(b"PK\x01\x02", at + 4)
    refuses(bytes(raw), "bad_zip")


def test_a_link_in_place_of_a_file_is_refused(made):
    """An entry that is a symbolic link holds the path it points to; its content cannot be the hash it is named after."""
    sha_ = next(iter(pf.referenced_files(made[0])))
    link = altered(made[3], replace={f"files/{sha_}": b"/etc/passwd"})
    refuses(link, "bad_hash", entry=f"files/{sha_}")


@pytest.mark.parametrize("payload", [b"not json", b"[]", b"3", b'"x"', b"null", b'{"format": "gerberslap", "schema_version": NaN}', b"\xff\xfe", b"{" * 100000])
def test_a_project_json_that_is_not_an_object_of_json_is_refused(payload):
    refuses(zipped([(pf.PROJECT_JSON, payload)]), "bad_json")


def test_nan_and_infinity_are_refused_wherever_they_are(made):
    refuses(altered(made[3], replace={pf.PROJECT_JSON: entries(made[3])[pf.PROJECT_JSON].replace(b'"min_outline_mm": 0.45', b'"min_outline_mm": NaN')}), "bad_json")
    refuses(altered(made[3], replace={pf.PROJECT_JSON: entries(made[3])[pf.PROJECT_JSON].replace(b'"min_outline_mm": 0.45', b'"min_outline_mm": 1e999')}), "invalid_project")


@pytest.mark.parametrize("fmt", ["gerberslap2", "", None, 3, "GerberSLAp"])
def test_a_document_that_is_not_a_gerberslap_project_is_refused(made, fmt):
    refuses(altered(made[3], doc=lambda d: d.update(format=fmt)), "not_a_project")
    refuses(altered(made[3], doc=lambda d: d.pop("format")), "not_a_project")


@pytest.mark.parametrize("version", [0, -1, "1", True, 1.0, None, [1]])
def test_a_version_that_is_not_a_whole_number_from_one_is_refused(made, version):
    refuses(altered(made[3], doc=lambda d: d.update(schema_version=version)), "bad_version")
    refuses(altered(made[3], doc=lambda d: d.pop("schema_version")), "bad_version")


def test_a_newer_version_is_refused_and_says_which(made):
    refuses(altered(made[3], doc=lambda d: d.update(schema_version=3)), "newer_version", found=3, supported=2)


@pytest.mark.parametrize("edit", [
    lambda d: d.update(surprise=1),                                       # a field nobody knows
    lambda d: d.update(profile_id=None),                                  # a version 2 file has no profile: it names a recipe
    lambda d: d.update(recipe_name="two\nlines"),
    lambda d: d.update(recipe_id="../x"),
    lambda d: d.update(dosage_id="a b"),
    lambda d: d.update(polarity="sideways"),
    lambda d: d.update(min_outline_mm=-1),
    lambda d: d["boards"][0].update(id="../x"),
    lambda d: d["boards"][0].update(name="two\nlines"),
    lambda d: d["boards"][0]["layers"][0]["files"][0].update(name="a/b.gbr"),
    lambda d: d["boards"][0]["layers"][0]["files"][0].update(sha256="xyz"),
    lambda d: d["boards"][0]["layers"][0].update(role="nonsense"),
    lambda d: d["boards"][0]["placement"].update(x=1e9),
    lambda d: d["boards"][0].update(layers=[]),
    lambda d: d.update(name="x" * 500),
    lambda d: d["info"]["b1"].update(cad="Not A Code!"),
    lambda d: d["info"]["b1"].update(surprise=True),
    lambda d: d["info"].update(ghost={"cad": None, "notes": []}),         # notes for a board that is not there
    lambda d: d.update(boards=d["boards"] * 2),                           # two boards with the same id
])
def test_a_project_that_does_not_describe_a_valid_project_is_refused_with_a_short_list_of_why(made, edit):
    e = refuses(altered(made[3], doc=edit), "invalid_project")
    assert e.params["reason"] in ("invalid", "unknown_board")
    assert len(e.params.get("fields", [])) <= 10 and all(len(f["loc"]) <= 6 for f in e.params.get("fields", []))


def test_a_file_missing_from_the_archive_refuses_the_whole_project_naming_it(made):
    proj = made[0]
    sha_, fname = sorted(pf.referenced_files(proj).items())[0]
    refuses(altered(made[3], drop=[f"files/{sha_}"]), "project_file_missing", file=fname, sha256=sha_)


def test_a_file_that_was_changed_is_refused(made):
    sha_ = next(iter(pf.referenced_files(made[0])))
    refuses(altered(made[3], replace={f"files/{sha_}": entries(made[3])[f"files/{sha_}"] + b" "}), "bad_hash", entry=f"files/{sha_}")


def test_a_file_that_no_layer_uses_is_refused(made):
    extra = b"hidden payload"
    refuses(altered(made[3], add=[(f"files/{sha(extra)}", extra)]), "unreferenced_file", entry=f"files/{sha(extra)}")


def test_a_project_that_is_refused_leaves_nothing_behind(made):
    """Opening reads only into memory: a refused archive has no effect that outlives the call."""
    before = sorted(p.name for p in REPO.iterdir())
    refuses(altered(made[3], add=[("../../../evil", b"x")]), "bad_entry")
    assert sorted(p.name for p in REPO.iterdir()) == before


def test_a_version_1_project_is_read_as_a_version_2_one_with_no_recipe(made):
    """Version 1 had a profile (always empty in practice): the file is the same without it."""
    for profile in (None, "pos35"):
        v1 = altered(made[3], doc=lambda d: (d.update(schema_version=1, profile_id=profile), d.pop("recipe_id", None), d.pop("recipe_name", None), d.pop("dosage_id", None)))
        opened = pf.open_project(v1)
        assert opened.project.schema_version == 2 and (opened.project.recipe_id, opened.project.recipe_name, opened.project.dosage_id) == (None, None, None)
        assert opened.project.boards == pf.open_project(made[3]).project.boards and opened.files == pf.open_project(made[3]).files


def test_a_project_that_names_a_recipe_and_a_dosage_comes_back_with_them(made):
    project = pf.open_project(made[3]).project
    named = project.model_copy(update={"recipe_id": "7b1e0c3a", "recipe_name": "Dry film negativo", "dosage_id": "a8d3e6f1", "polarity": Polarity.NEGATIVE})
    out = pf.save_project(named, made[1], name="x", info=made[2])
    back = pf.open_project(out).project
    assert (back.recipe_id, back.recipe_name, back.dosage_id, back.polarity.value) == ("7b1e0c3a", "Dry film negativo", "a8d3e6f1", "negative")
    assert json.loads(entries(out)[pf.PROJECT_JSON])["schema_version"] == 2 and "profile_id" not in json.loads(entries(out)[pf.PROJECT_JSON])


# ---- migration between versions ------------------------------------------------------------------------------------
def test_an_older_document_is_brought_up_to_date_one_version_at_a_time(monkeypatch):
    seen = []
    monkeypatch.setattr(pf, "SCHEMA_VERSION", 4)
    monkeypatch.setattr(pf, "MIGRATIONS", {1: lambda d: (seen.append(1), {**d, "a": 1})[1], 2: lambda d: (seen.append(2), {**d, "b": d.get("a", 0) + 1})[1],
                                           3: lambda d: (seen.append(3), {**d, "c": d.get("b", 0) + 1})[1]})
    out = pf.migrate({"format": "gerberslap", "schema_version": 1})
    assert seen == [1, 2, 3] and out == {"format": "gerberslap", "schema_version": 4, "a": 1, "b": 2, "c": 3}
    assert pf.migrate({"schema_version": 3}) == {"schema_version": 4, "c": 1} and seen == [1, 2, 3, 3]          # starts where the document is
    assert pf.migrate({"schema_version": 4}) == {"schema_version": 4}                                          # a current one is not touched


def test_a_version_with_no_way_forward_is_refused_not_guessed(monkeypatch):
    monkeypatch.setattr(pf, "SCHEMA_VERSION", 3)
    monkeypatch.setattr(pf, "MIGRATIONS", {2: lambda d: d})                                                    # nothing turns a 1 into a 2
    with pytest.raises(ProjectFileError) as e:
        pf.migrate({"schema_version": 1})
    assert e.value.code == "bad_version" and e.value.params["found"] == 1


def test_migration_does_not_change_the_document_it_is_given(monkeypatch):
    monkeypatch.setattr(pf, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(pf, "MIGRATIONS", {1: lambda d: d.update(touched=True) or d})
    original = {"schema_version": 1}
    assert pf.migrate(original)["touched"] is True and original == {"schema_version": 1}
