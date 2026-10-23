import io
import zipfile

import pytest

import testdata
from gerberslap.core import GerberError, gerber_io, read_file, sniff_kind, zip_members

ALL = list(testdata.TESTS) + list(testdata.DRILLS)


@pytest.mark.parametrize("name", ALL)
def test_synthetic_files_are_read(data_dir, name):
    r = read_file(name, (data_dir / name).read_bytes())
    assert r.kind == ("excellon" if name.endswith(".drl") else "gerber")
    assert len(r.file.objects) > 0


def test_crlf_line_endings_are_accepted(data_dir):
    raw = (data_dir / "f03_lines.gbr").read_bytes()
    assert len(read_file("crlf.gbr", raw.replace(b"\n", b"\r\n")).file.objects) == \
        len(read_file("lf.gbr", raw).file.objects)


def test_utf8_bom_is_accepted(data_dir):
    raw = (data_dir / "f01_rect_region.gbr").read_bytes()
    assert len(read_file("bom.gbr", b"\xef\xbb\xbf" + raw).file.objects) == 1


def test_macro_used_but_never_defined_is_an_error_naming_the_file(data_dir):
    with pytest.raises(GerberError) as e:
        read_file("r01_missing_macro.gbr", (data_dir / "r01_missing_macro.gbr").read_bytes())
    assert "r01_missing_macro.gbr" in str(e.value)
    assert e.value.code == "unreadable"


def test_excellon_without_any_number_format_is_an_error(data_dir):
    with pytest.raises(GerberError) as e:
        read_file("r02_excellon_no_format.drl", (data_dir / "r02_excellon_no_format.drl").read_bytes())
    assert "r02_excellon_no_format.drl" in str(e.value)


def test_parser_warnings_are_returned_not_lost():
    text = "%FSLAX25Y25*%\n%MOIN*%\nG70*\n%ADD10C,0.1*%\nD10*\nX10000Y10000D03*\nM02*\n"
    r = read_file("old.gbr", text.encode())
    assert any("G70" in w for w in r.warnings)


def test_gerbonara_debug_output_does_not_reach_stdout(data_dir, capsys):
    read_file("f11_macro_prims.gbr", (data_dir / "f11_macro_prims.gbr").read_bytes())
    from gerberslap.core import layer_geometry
    layer_geometry(read_file("f11_macro_prims.gbr", (data_dir / "f11_macro_prims.gbr").read_bytes()).file)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("data,kind", [
    (b"M48\nMETRIC\n", "excellon"),
    (b";comment\n;another\nM48\nMETRIC,TZ\n", "excellon"),
    (b"%FSLAX46Y46*%\n%MOMM*%\n", "gerber"),
    (b"G04 header*\nG75*\n", "gerber"),
])
def test_sniff_kind(data, kind):
    assert sniff_kind(data) == kind


# --- zip archives -------------------------------------------------------------------------
def test_zip_skips_macos_resource_forks_and_hidden_files(data_dir):
    zc = zip_members(data_dir / "synth_macos.zip")
    assert sorted(zc.members) == sorted(f"synth-{k}" for k in
                                        ("F_Cu.gbr", "Edge_Cuts.gbr", "F_Mask.gbr", "F_Silkscreen.gbr", "PTH.drl",
                                         "NPTH.drl"))
    assert set(zc.skipped) == {"__MACOSX/._synth-F_Cu.gbr", "__MACOSX/._synth-PTH.drl", ".DS_Store"}


def _zip_bytes(names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, "x")
    return buf.getvalue()


def test_zip_ignores_unsafe_and_hidden_paths():
    zc = zip_members(_zip_bytes(["../evil.gbr", "/abs.gbr", "a/b/ok.gbr", "sub/.hidden.gbr", "Thumbs.db"]))
    assert list(zc.members) == ["a/b/ok.gbr"]
    assert len(zc.skipped) == 4


def test_not_a_zip_is_an_error():
    with pytest.raises(GerberError) as e:
        zip_members(b"this is not a zip")
    assert e.value.code == "bad_zip"


def test_too_many_members_is_an_error(data_dir, monkeypatch):
    monkeypatch.setattr(gerber_io, "MAX_MEMBERS", 2)
    with pytest.raises(GerberError) as e:
        zip_members(data_dir / "synth_kicad.zip")
    assert e.value.code == "too_large"


def test_member_larger_than_the_limit_is_an_error(data_dir, monkeypatch):
    monkeypatch.setattr(gerber_io, "MAX_MEMBER_BYTES", 10)
    with pytest.raises(GerberError) as e:
        zip_members(data_dir / "synth_kicad.zip")
    assert e.value.code == "too_large"
