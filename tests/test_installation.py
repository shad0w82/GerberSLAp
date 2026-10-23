"""What the person who installs the app puts in the data folder: a printer works with the driver's defaults, needs its template, and the
template is judged by the driver before anything is written. The command that installs it and what `/api/info` tells the page about it."""
import json
from pathlib import Path

import pytest
from fakeprinters import registry_of, template_driver
from fastapi.testclient import TestClient

from gerberslap.model import C, PrinterConfig
from gerberslap.printers import registry
from gerberslap.services.installation import install_template, printer_config, printer_issues, template_path
from gerberslap.services.store import DataStore, Invalid, NotFound, Refused
from gerberslap.web import create_app
from gerberslap.web.__main__ import install, main
from gerberslap.web.devprinters import DEMO_SMALL

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "samples" / "speedCube.ctb"
needs_template = pytest.mark.skipif(not TEMPLATE.exists(), reason="samples/speedCube.ctb is not here (it is not in the repository)")
DRV = template_driver()
GOOD = b"TPL-a-template"


@pytest.fixture
def store(tmp_path):
    return DataStore(tmp_path / "data")


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "from-the-user.tpl"
    path.write_bytes(GOOD)
    return path


def codes(issues):
    return [i.code for i in issues]


def write_settings(store, settings):
    path = store.root / "printers" / "tpl" / "printer.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"format": "gerberslap-printer", "schema_version": 1, "printer": {"settings": settings}}))


# ---- the configuration of a printer ------------------------------------------------------------------------------
def test_a_printer_nobody_configured_has_the_drivers_own_defaults(store):
    assert printer_config(store, DRV) == PrinterConfig(id="tpl", name="Template test printer", driver="tpl")
    assert printer_config(None, DRV) == printer_config(store, DRV)                          # no data folder at all: the same
    assert not (store.root / "printers").exists()                                          # looking never writes


def test_the_settings_somebody_wrote_in_the_data_folder_are_added_to_the_defaults(store):
    write_settings(store, {"a": 1})
    assert printer_config(store, DRV) == PrinterConfig(id="tpl", name="Template test printer", driver="tpl", settings={"a": 1})


def test_a_settings_file_that_cannot_be_read_is_an_error_and_not_the_defaults(store):
    (store.root / "printers" / "tpl").mkdir(parents=True)
    (store.root / "printers" / "tpl" / "printer.json").write_text("{ not json")
    with pytest.raises(Invalid):
        printer_config(store, DRV)


# ---- is the printer ready ----------------------------------------------------------------------------------------
def test_without_a_template_the_printer_is_not_ready(store):
    assert codes(printer_issues(store, DRV)) == [C.TEMPLATE_MISSING]
    assert codes(printer_issues(None, DRV)) == [C.TEMPLATE_MISSING]                          # no data folder: no template


def test_a_printer_that_needs_no_template_is_always_ready(store):
    assert printer_issues(store, DEMO_SMALL) == [] and printer_issues(None, DEMO_SMALL) == []


def test_with_the_template_it_is_ready(store, source):
    install_template(store, DRV, source)
    assert printer_issues(store, DRV) == []


def test_a_template_that_was_removed_or_spoilt_after_the_installation_is_reported(store, source):
    path = install_template(store, DRV, source)
    path.write_bytes(b"garbage")
    issue, = printer_issues(store, DRV)
    assert (issue.code, issue.blocking, issue.params["reason"]) == (C.TEMPLATE_INVALID, True, "not_a_template")
    path.unlink()
    assert codes(printer_issues(store, DRV)) == [C.TEMPLATE_MISSING]


def test_a_settings_file_that_cannot_be_read_blocks_and_says_which_kind_of_trouble(store):
    (store.root / "printers" / "tpl").mkdir(parents=True)
    (store.root / "printers" / "tpl" / "printer.json").write_text("{ not json")
    issue, = printer_issues(store, DRV)
    assert (issue.code, issue.blocking, issue.params) == (C.PRINTER_CONFIG_INVALID, True, {"printer_id": "tpl", "reason": "bad_json"})


# ---- installing a template ---------------------------------------------------------------------------------------
def test_installing_puts_the_template_where_the_driver_says_whatever_the_file_was_called(store, source, tmp_path):
    path = install_template(store, DRV, source)
    assert path == store.root / "printers" / "tpl" / "template.tpl" and path.read_bytes() == GOOD
    assert template_path(store, DRV) == path
    odd = tmp_path / "speed cube (final).bin"
    odd.write_bytes(GOOD + b"-2")
    assert install_template(store, DRV, odd) == path and path.read_bytes() == GOOD + b"-2"            # the name comes from the driver, not from the file


def test_installing_writes_nothing_but_the_template(store, source):
    install_template(store, DRV, source)
    assert sorted(p.name for p in (store.root / "printers" / "tpl").iterdir()) == ["template.tpl"]       # no printer.json is made


def test_installing_keeps_the_settings_somebody_wrote(store, source):
    write_settings(store, {"a": 1})
    before = (store.root / "printers" / "tpl" / "printer.json").read_bytes()
    install_template(store, DRV, source)
    assert (store.root / "printers" / "tpl" / "printer.json").read_bytes() == before
    assert printer_config(store, DRV).settings == {"a": 1}


def test_there_is_no_template_path_without_a_data_folder_or_for_a_printer_that_needs_none(store, source):
    assert template_path(None, DRV) is None and template_path(store, DRV) is None and template_path(store, DEMO_SMALL) is None
    install_template(store, DRV, source)
    assert template_path(None, DRV) is None and template_path(store, DEMO_SMALL) is None


def test_installing_again_replaces_the_template(store, source, tmp_path):
    install_template(store, DRV, source)
    newer = tmp_path / "newer.tpl"
    newer.write_bytes(GOOD + b"-newer")
    install_template(store, DRV, newer)
    assert store.printer_file("tpl", "template.tpl").read_bytes() == GOOD + b"-newer"
    assert sorted(p.name for p in (store.root / "printers" / "tpl").iterdir()) == ["template.tpl"]


def test_a_template_the_driver_refuses_leaves_no_trace_in_the_data_folder(store, tmp_path):
    bad = tmp_path / "bad.tpl"
    bad.write_bytes(b"nope")
    with pytest.raises(Invalid) as e:
        install_template(store, DRV, bad)
    assert e.value.code == "template_rejected" and "not_a_template" in e.value.detail
    assert not store.root.exists()                                                            # not even the folder


def test_a_refused_template_does_not_touch_the_one_that_was_working(store, source, tmp_path):
    install_template(store, DRV, source)
    bad = tmp_path / "bad.tpl"
    bad.write_bytes(b"nope")
    with pytest.raises(Invalid):
        install_template(store, DRV, bad)
    assert store.printer_file("tpl", "template.tpl").read_bytes() == GOOD and printer_issues(store, DRV) == []


def test_a_file_that_is_not_there_or_is_too_big_is_named_not_guessed(store, tmp_path, monkeypatch):
    with pytest.raises(NotFound):
        install_template(store, DRV, tmp_path / "missing.tpl")
    big = tmp_path / "big.tpl"
    big.write_bytes(GOOD)
    monkeypatch.setattr("gerberslap.services.installation.MAX_TEMPLATE_BYTES", 4)
    with pytest.raises(Invalid) as e:
        install_template(store, DRV, big)
    assert e.value.code == "template_too_large" and not store.root.exists()


def test_a_printer_that_needs_no_template_refuses_one(store, source):
    with pytest.raises(Refused) as e:
        install_template(store, DEMO_SMALL, source)
    assert e.value.code == "no_template_needed" and not store.root.exists()


# ---- the command ---------------------------------------------------------------------------------------------------
class Out:
    def __init__(self):
        self.text = ""

    def write(self, s):
        self.text += s

    def flush(self):
        pass


def run_install(store, printer_id, path, drivers=registry_of(DRV)):
    out, err = Out(), Out()
    return install(store, printer_id, path, drivers, out=out, err=err), out.text, err.text


def test_the_command_installs_and_says_where(store, source):
    status, out, err = run_install(store, "tpl", source)
    assert (status, err) == (0, "") and str(store.printer_file("tpl", "template.tpl")) in out and printer_issues(store, DRV) == []


def test_the_command_refuses_with_a_status_and_a_reason_and_leaves_nothing(store, tmp_path):
    bad = tmp_path / "bad.tpl"
    bad.write_bytes(b"nope")
    status, out, err = run_install(store, "tpl", bad)
    assert (status, out) == (1, "") and "not_a_template" in err and not store.root.exists()
    status, out, err = run_install(store, "tpl", tmp_path / "missing.tpl")
    assert status == 1 and "no such file" in err


def test_the_command_names_the_printers_it_has_when_asked_for_one_it_has_not(store, source):
    status, out, err = run_install(store, "nope", source)
    assert status == 2 and "'nope'" in err and "tpl" in err and not store.root.exists()


def test_the_command_does_not_start_a_server(tmp_path, source, monkeypatch):
    import uvicorn
    ran = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: ran.append(1))
    monkeypatch.setattr("gerberslap.web.__main__.registry", lambda: registry_of(DRV))
    with pytest.raises(SystemExit) as e:
        main(["--data", str(tmp_path / "d"), "--install-template", "tpl", str(source)])
    assert e.value.code == 0 and ran == [] and (tmp_path / "d" / "printers" / "tpl" / "template.tpl").is_file()


def test_the_server_is_given_the_data_folder_it_was_started_with(tmp_path, source, monkeypatch):
    import uvicorn
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(app=app))
    monkeypatch.setattr("gerberslap.web.__main__.registry", lambda: registry_of(DRV))
    install_template(DataStore(tmp_path / "d"), DRV, source)
    main(["--allowed-host", "testserver", "--data", str(tmp_path / "d")])
    info = TestClient(seen["app"]).get("/api/info").json()
    assert [(p["id"], p["ready"], p["issues"]) for p in info["printers"]] == [("tpl", True, [])]


# ---- what the page is told -----------------------------------------------------------------------------------------
def client_for(store, *drivers):
    return TestClient(create_app(printers=registry_of(*drivers), allowed_hosts=["testserver"], store=store), raise_server_exceptions=False)


def test_info_says_for_every_printer_whether_it_is_ready_and_why_not(store, source):
    c = client_for(store, DRV, DEMO_SMALL)
    printers = {p["id"]: p for p in c.get("/api/info").json()["printers"]}
    assert printers["tpl"]["ready"] is False and [i["code"] for i in printers["tpl"]["issues"]] == ["template_missing"]
    assert printers["tpl"]["issues"][0]["blocking"] is True and printers["tpl"]["issues"][0]["params"] == {"printer_id": "tpl"}
    assert printers["demo_small"] == {**printers["demo_small"], "ready": True, "issues": []}
    install_template(store, DRV, source)                                                     # no restart needed: the answer is read each time
    again = {p["id"]: p for p in c.get("/api/info").json()["printers"]}
    assert again["tpl"]["ready"] is True and again["tpl"]["issues"] == []


def test_without_a_data_folder_a_printer_that_needs_a_template_is_not_ready():
    c = TestClient(create_app(printers=registry_of(DRV), allowed_hosts=["testserver"]), raise_server_exceptions=False)
    p, = c.get("/api/info").json()["printers"]
    assert p["ready"] is False and p["issues"][0]["code"] == "template_missing"


def test_a_damaged_configuration_does_not_stop_the_page_from_loading(store):
    (store.root / "printers" / "tpl").mkdir(parents=True)
    (store.root / "printers" / "tpl" / "printer.json").write_text(json.dumps({"format": "wrong"}))
    r = client_for(store, DRV, DEMO_SMALL).get("/api/info")
    assert r.status_code == 200
    printers = {p["id"]: p for p in r.json()["printers"]}
    assert printers["tpl"]["ready"] is False and printers["tpl"]["issues"][0]["code"] == "printer_config_invalid"
    assert printers["demo_small"]["ready"] is True                                           # the other printers are not affected


# ---- with the real driver and the user's own template ------------------------------------------------------------
@needs_template
def test_the_real_printer_is_not_ready_until_the_template_is_installed_and_then_it_is(store):
    real = registry().get("ld002h")
    assert codes(printer_issues(store, real)) == [C.TEMPLATE_MISSING]
    path = install_template(store, real, TEMPLATE)
    assert path.name == "template.ctb" and printer_issues(store, real) == []
    assert path.read_bytes() == TEMPLATE.read_bytes()


@needs_template
def test_the_real_driver_refuses_a_damaged_template_and_names_why(store, tmp_path):
    real = registry().get("ld002h")
    good = TEMPLATE.read_bytes()
    broken = tmp_path / "broken.ctb"
    broken.write_bytes(good[:-1] + bytes([good[-1] ^ 0xFF]))
    with pytest.raises(Invalid) as e:
        install_template(store, real, broken)
    assert "bad_crc" in e.value.detail and not store.root.exists()
    status, out, err = run_install(store, "ld002h", broken, drivers=registry())
    assert status == 1 and "bad_crc" in err
