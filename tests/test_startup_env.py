"""Where the server listens and which names it accepts can be said by the environment as well as by the options (a container is configured that way);
the option on the command line wins over the variable."""
import sys

import pytest
import uvicorn
from fastapi.testclient import TestClient

from gerberslap.web.__main__ import main

VARIABLES = ("GERBERSLAP_HOST", "GERBERSLAP_PORT", "GERBERSLAP_ALLOWED_HOSTS", "GERBERSLAP_NO_LIBRARY", "GERBERSLAP_DATA")


def start(monkeypatch, tmp_path, *args, env=None):
    """What `python -m gerberslap.web` would hand to uvicorn (the keyword arguments, with the app)."""
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(app=app, **kw))
    monkeypatch.setattr(sys, "argv", ["gerberslap.web", "--data", str(tmp_path / "d"), *args])
    for key in VARIABLES:
        monkeypatch.delenv(key, raising=False)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    main()
    return seen


def test_without_variables_or_options_it_listens_on_this_computer_only_on_8800(monkeypatch, tmp_path):
    seen = start(monkeypatch, tmp_path)
    assert (seen["host"], seen["port"]) == ("127.0.0.1", 8800)


def test_the_environment_says_the_address_and_the_port(monkeypatch, tmp_path):
    seen = start(monkeypatch, tmp_path, env={"GERBERSLAP_HOST": "0.0.0.0", "GERBERSLAP_PORT": "9100"})
    assert (seen["host"], seen["port"]) == ("0.0.0.0", 9100)


def test_an_option_wins_over_the_variable(monkeypatch, tmp_path):
    seen = start(monkeypatch, tmp_path, "--host", "127.0.0.2", "--port", "9200", env={"GERBERSLAP_HOST": "0.0.0.0", "GERBERSLAP_PORT": "9100"})
    assert (seen["host"], seen["port"]) == ("127.0.0.2", 9200)


@pytest.mark.parametrize("empty", ["", "   "])
def test_an_empty_variable_is_the_same_as_none(monkeypatch, tmp_path, empty):
    seen = start(monkeypatch, tmp_path, env={"GERBERSLAP_HOST": empty, "GERBERSLAP_PORT": empty, "GERBERSLAP_ALLOWED_HOSTS": empty})
    assert (seen["host"], seen["port"]) == ("127.0.0.1", 8800)


@pytest.mark.parametrize("bad", ["abc", "0", "70000", "-1", "88.5"])
def test_a_port_that_is_not_one_stops_the_start_with_a_message(monkeypatch, tmp_path, capsys, bad):
    with pytest.raises(SystemExit) as stop:
        start(monkeypatch, tmp_path, env={"GERBERSLAP_PORT": bad})
    assert stop.value.code == 2 and "GERBERSLAP_PORT" in capsys.readouterr().err


def test_the_names_the_variable_gives_are_accepted_together_with_those_of_the_option(monkeypatch, tmp_path):
    seen = start(monkeypatch, tmp_path, "--allowed-host", "nas.local", env={"GERBERSLAP_ALLOWED_HOSTS": "gerber.lan, 192.168.1.20 ,,other.example"})
    client = TestClient(seen["app"], raise_server_exceptions=False)
    for name in ("nas.local", "gerber.lan", "192.168.1.20", "other.example", "localhost"):
        assert client.get("/api/info", headers={"host": f"{name}:8800"}).status_code == 200, name
    assert client.get("/api/info", headers={"host": "evil.example"}).status_code == 403                  # any other name is still refused
    assert client.get("/api/info", headers={"host": "testserver"}).status_code == 403


def test_without_the_variable_only_the_local_names_are_accepted(monkeypatch, tmp_path):
    client = TestClient(start(monkeypatch, tmp_path)["app"], raise_server_exceptions=False)
    assert client.get("/api/info", headers={"host": "localhost:8800"}).status_code == 200
    assert client.get("/api/info", headers={"host": "nas.local"}).status_code == 403
