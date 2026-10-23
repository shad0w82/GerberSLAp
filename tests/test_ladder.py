"""The calibration ladder's file: its layout is the page's (a test runs `js/ladder.js` with Node and compares), every step lights the strips from its own on, what the values can
be for a printer, the pixels of the strips, the time written on them, and the file the real printer's driver writes (skipped without the user's template)."""
import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from fakeprinters import building_driver, registry_of, template_driver
from fastapi.testclient import TestClient

from gerberslap.core import Grid, ladder as core
from gerberslap.model import C, ExposureLimits, LadderSpec, Plane
from gerberslap.printers import get_driver
from gerberslap.printers.ld002h import ctbio
from gerberslap.services.checks import blocking
from gerberslap.services.installation import install_template
from gerberslap.services.ladder import ladder_file_name, ladder_issues
from gerberslap.services.store import DataStore
from gerberslap.web import create_app

REPO = Path(__file__).resolve().parent.parent
LADDER_JS = REPO / "gerberslap" / "web" / "static" / "js" / "ladder.js"
TEMPLATE = REPO / "samples" / "speedCube.ctb"
needs_template = pytest.mark.skipif(not TEMPLATE.exists(), reason="samples/speedCube.ctb is not here (it is not in the repository)")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
LIMITS = ExposureLimits(min_flash_s=1.0, max_proven_flash_s=20.0)
PLANE = Plane(width_mm=130.56, height_mm=82.62)
FINE = Grid(2560, 1620, 0.051)
COARSE = Grid(500, 300, 0.2)                                          # a 100 x 60 mm plane, quick to draw
SPEC = dict(step=10, bands=3, pulses=2, rest=4, width=13, height=40)


def node_json(script):
    r = subprocess.run(["node", "--input-type=module", "-e", f"import * as L from {LADDER_JS.as_uri()!r};\n{script}"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def same(a, b, path=""):
    """Two structures of numbers, strings and lists are the same: the numbers to a nanometre."""
    if isinstance(a, dict):
        assert set(a) == set(b), (path, sorted(a), sorted(b))
        for k in a:
            same(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b), (path, len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            same(x, y, f"{path}[{i}]")
    elif isinstance(a, (int, float)) and not isinstance(a, bool):
        assert math.isclose(a, b, abs_tol=1e-9), (path, a, b)
    else:
        assert a == b, (path, a, b)


def masks_of(grid=COARSE, polarity="positive", mirror=False, plane=None, **kw):
    spec = {**SPEC, **kw}
    plane = plane or Plane(width_mm=grid.width * grid.pitch, height_mm=grid.height * grid.pitch)
    layout = core.ladder_layout(spec["bands"], spec["width"], spec["height"], spec["step"], plane.width_mm, plane.height_mm, spec.get("tests", core.TESTS))
    return layout, core.ladder_step_masks(layout, grid, polarity=polarity, mirror=mirror)


def px(grid, x_mm, y_mm):
    """The (row, column) of a point of the picture (mm, x from the left, y from the back)."""
    return int(y_mm / grid.pitch), int(x_mm / grid.pitch)


# ---- the layout is the page's ---------------------------------------------------------------------------------------------
@needs_node
def test_the_strip_drawing_is_the_one_of_the_page_for_every_size_and_choice_of_tests():
    cases = [(13, 76, list(core.TESTS)), (13, 46, list(core.TESTS)), (6, 76, list(core.TESTS)), (40, 150, list(core.TESTS)), (20, 30, list(core.TESTS)), (13, 76, ["soic8", "rings"]),
             (13, 76, []), (9, 20, ["lines_v", "fine"]), (7.5, 33.3, ["passives", "gaps", "lines_h"]), (25, 60, ["rings", "rings", "fine"][:2])]
    js = node_json(f"const cases = {json.dumps(cases)}; console.log(JSON.stringify(cases.map(([w, h, t]) => L.stripDrawing(w, h, t))));")
    for (w, h, tests), expected in zip(cases, js):
        same(core.strip_drawing(w, h, tests), expected, f"{w}x{h} {tests}")


@needs_node
def test_the_layout_of_the_strips_the_time_written_on_them_and_the_constants_are_the_pages():
    plane = {"w": 130.56, "h": 82.62}
    specs = [dict(step=10, bands=8, pulses=2, rest=4, width=13, height=76, tests=list(core.TESTS)), dict(step=7.5, bands=3, pulses=1, rest=0, width=6, height=15, tests=["fine"]),
             dict(step=600, bands=20, pulses=20, rest=60, width=40, height=150, tests=[]), dict(step=1, bands=2, pulses=1, rest=0, width=20, height=82.62, tests=["rings"])]
    js = node_json(f"""const plane = {json.dumps(plane)}, specs = {json.dumps(specs)}, texts = ['1 s', '10 s', '7.5 s', '1200 s', '12.5 s', '600 s'];
      console.log(JSON.stringify({{ layouts: specs.map((v) => L.ladderLayout(v, plane)), sizes: texts.flatMap((t) => [6, 13, 40].map((w) => L.labelSize(t, w))),
        constants: {{ HEAD: L.HEAD, FOOT: L.FOOT, MARGIN: L.MARGIN, GAP_X: L.GAP_X, GAP_Y: L.GAP_Y, LABEL_Y: L.LABEL_Y, gap: L.STRIP.gap, tests: L.TESTS }} }}));""")
    for spec, expected in zip(specs, js["layouts"]):
        got = core.ladder_layout(spec["bands"], spec["width"], spec["height"], spec["step"], plane["w"], plane["h"], spec["tests"])
        same(got, expected, str(spec))
    texts = ["1 s", "10 s", "7.5 s", "1200 s", "12.5 s", "600 s"]
    same([core.label_size(t, w) for t in texts for w in (6, 13, 40)], js["sizes"])
    same({"HEAD": core.HEAD, "FOOT": core.FOOT, "MARGIN": core.MARGIN, "GAP_X": core.GAP_X, "GAP_Y": list(core.GAP_Y), "LABEL_Y": core.LABEL_Y, "gap": core.STRIP_GAP, "tests": list(core.TESTS)}, js["constants"])


@needs_node
def test_what_is_wrong_with_the_values_is_what_the_page_says():
    """The same rules on both sides: the page's `ladderIssues` and `canGenerate` against the server's issues, for values on both sides of every limit."""
    values = [dict(step=s, bands=b, pulses=p, rest=4, width=w, height=h, tests=t) for s in (1, 10, 25) for b in (2, 8, 20) for p in (1, 2, 20) for w, h in ((13, 76), (6, 20), (40, 82.62), (30, 150))
              for t in (list(core.TESTS), [], ["rings", "soic8"])][::7]
    lim = {"min_flash_s": 1.0, "max_proven_flash_s": 20.0}
    js = node_json(f"""const values = {json.dumps(values)}, plane = {{ w: {PLANE.width_mm}, h: {PLANE.height_mm} }}, lim = {json.dumps(lim)};
      console.log(JSON.stringify(values.map((v) => ({{ kinds: L.ladderIssues(v, plane, lim).map((i) => i.kind), can: L.canGenerate(v, plane, lim) }}))));""")
    kind = {C.FLASH_BELOW_MINIMUM: "flash_below", C.FLASH_BEYOND_PROVEN: "flash_beyond", C.LADDER_TOO_BIG: "too_big", C.LADDER_NO_TESTS: "no_tests", C.LADDER_TESTS_DROPPED: "dropped"}
    assert len(values) > 20
    for v, expected in zip(values, js):
        issues = ladder_issues(LadderSpec(**v), PLANE, LIMITS)
        assert [kind[i.code] for i in issues] == expected["kinds"], v
        assert (not blocking(issues)) == expected["can"], v


# ---- the values and what is wrong with them -------------------------------------------------------------------------------
@pytest.mark.parametrize("edit", [dict(step=0.5), dict(step=601), dict(bands=1), dict(bands=21), dict(bands=2.5), dict(pulses=0), dict(pulses=21), dict(rest=-1), dict(rest=61),
                                  dict(width=5.9), dict(width=40.1), dict(height=14.9), dict(height=150.1), dict(tests=["nope"]), dict(tests=["fine", "fine"]), dict(polarity="sideways"),
                                  dict(extra=1)])
def test_values_outside_the_limits_of_the_page_are_refused(edit):
    with pytest.raises(Exception):
        LadderSpec(**{**SPEC, **edit})


def test_the_limits_themselves_are_good_and_the_defaults_are_the_pages():
    LadderSpec(step=1, bands=2, pulses=1, rest=0, width=6, height=15)
    LadderSpec(step=600, bands=20, pulses=20, rest=60, width=40, height=150, tests=[])
    assert LadderSpec(**SPEC).tests == core.TESTS and LadderSpec(**SPEC).polarity.value == "positive" and LadderSpec(**SPEC).mirror is False


def test_a_ladder_that_does_not_fit_the_plane_blocks_and_one_that_fits_does_not():
    wide = LadderSpec(**{**SPEC, "bands": 12, "width": 12})                                                   # 12 strips of 12 mm and 11 gaps: 155 mm
    (issue,) = [i for i in ladder_issues(wide, PLANE, LIMITS) if i.code == C.LADDER_TOO_BIG]
    assert issue.blocking and issue.params["width_mm"] == pytest.approx(155) and issue.params["plane_w_mm"] == 130.56
    assert not [i for i in ladder_issues(LadderSpec(**SPEC), PLANE, LIMITS) if i.code == C.LADDER_TOO_BIG]
    tall = LadderSpec(**{**SPEC, "height": 83})
    assert any(i.code == C.LADDER_TOO_BIG for i in ladder_issues(tall, PLANE, LIMITS))


def test_the_flash_is_checked_against_the_limits_of_the_printer():
    short = ladder_issues(LadderSpec(**{**SPEC, "step": 8, "pulses": 10}), PLANE, LIMITS)
    (b,) = [i for i in short if i.code == C.FLASH_BELOW_MINIMUM]
    assert b.blocking and b.params["flash_s"] == pytest.approx(0.8) and b.params["min_s"] == 1.0
    long = ladder_issues(LadderSpec(**{**SPEC, "step": 100, "pulses": 1}), PLANE, LIMITS)
    (w,) = [i for i in long if i.code == C.FLASH_BEYOND_PROVEN]
    assert not w.blocking and w.params["max_s"] == 20.0
    assert not [i for i in ladder_issues(LadderSpec(**{**SPEC, "step": 100, "pulses": 1}), PLANE, ExposureLimits()) if i.code == C.FLASH_BEYOND_PROVEN]     # a printer that says nothing of a flash: nothing to say


def test_no_tests_and_tests_without_room_only_inform():
    assert [i.code for i in ladder_issues(LadderSpec(**{**SPEC, "tests": []}), PLANE, LIMITS)] == [C.LADDER_NO_TESTS]
    narrow = ladder_issues(LadderSpec(**{**SPEC, "width": 6, "height": 76}), PLANE, LIMITS)
    (d,) = narrow
    assert d.code == C.LADDER_TESTS_DROPPED and not d.blocking and d.params["ids"] == ["soic8", "fine", "rings"]


@pytest.mark.parametrize("step,bands,name", [(10, 8, "scala_10s_x8"), (7.5, 3, "scala_7_5s_x3"), (600, 20, "scala_600s_x20"), (1, 2, "scala_1s_x2")])
def test_the_file_is_named_after_its_first_step_and_its_steps(step, bands, name):
    assert ladder_file_name(LadderSpec(**{**SPEC, "step": step, "bands": bands})) == name


# ---- the pixels ---------------------------------------------------------------------------------------------------------------
def test_every_step_lights_the_strips_from_its_own_on_and_nothing_else():
    layout, masks = masks_of()
    assert len(masks) == 3 and all(m.shape == (300, 500) and m.dtype == bool for m in masks)
    for i, mask in enumerate(masks):
        for j, s in enumerate(layout["strips"]):
            foot = mask[px(COARSE, s["x"] + s["w"] / 2, s["y"] + s["h"] - 0.5)]                              # the bottom of the strip: no test, no time
            assert foot == (j >= i), (i, j)                                                              # the strip j is lit by the steps 0..j
        gap = layout["strips"][0]["x"] + layout["strips"][0]["w"] + 0.5                                      # between two strips: dark in every step
        assert not mask[px(COARSE, gap, layout["strips"][0]["y"] + 20)] and not mask[0, 0] and not mask[-1, -1]
    assert masks[0].sum() > masks[1].sum() > masks[2].sum() > 0                                                # each step lights less of the plane than the one before


def test_the_time_a_strip_is_lit_is_its_number_of_steps_times_the_time_of_one():
    layout, masks = masks_of(step=7.5, bands=4)
    for j, s in enumerate(layout["strips"]):
        lit_in = sum(1 for m in masks if m[px(COARSE, s["x"] + s["w"] / 2, s["y"] + s["h"] - 0.5)])
        assert lit_in == j + 1 and s["total_s"] == pytest.approx((j + 1) * 7.5)


def test_with_a_positive_resist_the_copper_is_dark_and_with_a_negative_one_it_is_all_that_is_lit():
    layout, pos = masks_of(grid=FINE, bands=2, height=76, polarity="positive")
    _, neg = masks_of(grid=FINE, bands=2, height=76, polarity="negative")
    s = layout["strips"][0]
    first = layout["drawing"]["shapes"][0]["r"]                                                             # the first line of the first test
    row, col = px(FINE, s["x"] + first[0] + first[2] / 2, s["y"] + first[1] + first[3] / 2)
    assert not pos[0][row, col] and neg[0][row, col]                                                       # the copper: dark when positive, lit when negative
    row, col = px(FINE, s["x"] + s["w"] / 2, s["y"] + s["h"] - 0.5)
    assert pos[0][row, col] and not neg[0][row, col]                                                       # the rest of the strip: the other way round
    for step in (0, 1):
        assert not (pos[step] & neg[step]).any()                                                           # nothing is lit in both
    window = (slice(0, None), slice(0, None))
    area = 2 * 13 * 76 / FINE.pitch ** 2
    assert abs(int((pos[0] | neg[0]).sum()) - area) / area < 0.01                                          # together they are the strips, to the pixel at their edges


def test_the_ladder_turned_over_is_the_same_flipped_left_to_right_the_time_too():
    _, plain = masks_of(grid=FINE, bands=2, width=13, height=40)
    _, over = masks_of(grid=FINE, bands=2, width=13, height=40, mirror=True)
    for a, b in zip(plain, over):
        assert np.array_equal(a[:, ::-1], b) and b.flags.c_contiguous
    assert not np.array_equal(plain[0], over[0])                                                            # (the tests and the time are not symmetric: it is a different picture)


def test_the_time_is_written_at_the_top_of_the_strip_and_inside_it():
    """Drawn with a negative resist, where only the copper (and the time) is lit, the time is all there is in the strip."""
    layout, neg = masks_of(grid=FINE, bands=2, width=13, height=40, tests=[], polarity="negative")
    s = layout["strips"][1]                                                                                  # "20 s"
    top, bottom = int(s["y"] / FINE.pitch), int((s["y"] + s["h"]) / FINE.pitch)
    left, right = int(s["x"] / FINE.pitch), int((s["x"] + s["w"]) / FINE.pitch)
    rows, cols = np.where(neg[0][top:bottom, left - 5:right + 5])
    assert len(rows) > 100
    x0, x1 = (cols.min() + left - 5) * FINE.pitch, (cols.max() + 1 + left - 5) * FINE.pitch
    y0, y1 = (rows.min() + top) * FINE.pitch, (rows.max() + 1 + top) * FINE.pitch
    assert s["x"] + 0.5 < x0 and x1 < s["x"] + s["w"] - 0.5                                                  # inside the strip, with room at both sides
    assert abs((x0 + x1) / 2 - (s["x"] + s["w"] / 2)) < 0.4                                                  # centred
    assert abs(y1 - (s["y"] + core.LABEL_Y)) < 0.2 and y0 > s["y"] + 1.5                                    # the baseline at LABEL_Y, under the top of the strip
    assert (y1 - y0) == pytest.approx(core.label_size("20 s", 13) * 0.73, abs=0.4)                           # a digit is about three quarters of the size of the text


def test_a_longer_time_is_written_smaller_so_that_it_stays_inside_a_narrow_strip():
    layout, neg = masks_of(grid=FINE, bands=2, width=6, height=30, tests=[], step=600, polarity="negative")
    s = layout["strips"][1]                                                                                  # "1200 s" in 6 mm
    top, bottom = int(s["y"] / FINE.pitch), int((s["y"] + s["h"]) / FINE.pitch)
    left, right = int(s["x"] / FINE.pitch), int((s["x"] + s["w"]) / FINE.pitch)
    assert core.label_size("1200 s", 6) == pytest.approx(5.5 / 3.6) and core.label_size("1200 s", 6) < core.label_size("20 s", 6)
    around = neg[0][top:bottom, left - 8:right + 8]                                                          # lit pixels are the time alone: none outside the strip's columns
    cols = np.where(around.any(axis=0))[0] + left - 8
    assert len(cols) > 20 and cols.min() >= left and cols.max() < right


def test_a_strip_is_drawn_with_the_pixels_it_has_on_the_whole_plane():
    """The strips are drawn in small windows of the grid (quick); a window has to give the pixels the whole grid gives."""
    import shapely
    from shapely.geometry import box

    from gerberslap.core import binarize, coverage
    layout, pos = masks_of(grid=FINE, bands=3, width=13, height=40, tests=[])
    top = FINE.height * FINE.pitch
    for s in layout["strips"]:
        whole = binarize(coverage(shapely.transform(box(s["x"], s["y"], s["x"] + s["w"], s["y"] + s["h"]), lambda c: np.column_stack([c[:, 0], top - c[:, 1]])), FINE, 16))
        rows = slice(int((s["y"] + 7.0) / FINE.pitch), int((s["y"] + s["h"] + 1) / FINE.pitch))             # under the time: nothing but the strip
        cols = slice(int(s["x"] / FINE.pitch) - 2, int((s["x"] + s["w"]) / FINE.pitch) + 2)                 # the strip and a little more (the next one is 20 pixels away)
        assert np.array_equal(pos[0][rows, cols], whole[rows, cols]) and whole[rows, cols].any()


def test_every_ring_and_round_pad_is_drawn_round_and_hollow_where_it_should():
    layout, neg = masks_of(grid=FINE, bands=2, width=13, height=76, polarity="negative", tests=["rings"])
    s = layout["strips"][0]
    rings = [sh["ring"] for sh in layout["drawing"]["shapes"] if "ring" in sh]
    dots = [sh["dot"] for sh in layout["drawing"]["shapes"] if "dot" in sh]
    assert len(rings) == 3 and len(dots) == 1
    for cx, cy, outer, inner in rings:
        assert neg[0][px(FINE, s["x"] + cx + (outer + inner) / 4, s["y"] + cy)]                              # on the copper ring
        assert not neg[0][px(FINE, s["x"] + cx, s["y"] + cy)]                                               # the hole is dark
    cx, cy, r = dots[0]
    assert neg[0][px(FINE, s["x"] + cx, s["y"] + cy)]


def test_a_strip_that_is_all_outside_the_plane_is_not_drawn_and_does_not_break_the_others():
    narrow = Grid(100, 300, 0.2)                                                                             # 20 mm wide: four strips of 13 mm do not fit
    layout = core.ladder_layout(4, 13, 40, 10, 20, 60, core.TESTS)
    assert not layout["fits"] and layout["strips"][0]["x"] + 13 < 0 and layout["strips"][3]["x"] > 20       # the first and the last are wholly outside
    masks = core.ladder_step_masks(layout, narrow, polarity="positive", mirror=False)
    assert len(masks) == 4 and masks[0].any() and masks[1].any() and not masks[3].any()                      # (the last step lights only the last strip)


def test_the_masks_of_the_steps_are_independent_arrays():
    _, masks = masks_of()
    before = masks[2].copy()
    masks[0][:] = False
    assert np.array_equal(masks[2], before) and masks[1].any()


# ---- the route ---------------------------------------------------------------------------------------------------------------
BODY = {"ladder": {**SPEC, "height": 50}}


def served(driver, store=None):
    app = create_app(printers=registry_of(driver), allowed_hosts=["testserver"], store=store)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def made():
    drv = building_driver()
    drv.calls.clear()
    return served(drv), drv


def test_the_file_of_the_ladder_is_made_of_one_mask_per_step_with_the_flashes_of_a_step_each(made):
    client, drv = made
    r = client.post("/api/generate/ladder", json={**BODY, "printer_id": "build"})
    assert r.status_code == 200 and r.content == b"SEQ\x03\x02" and r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"] == 'attachment; filename="scala_10s_x3.fake"'
    (call,) = drv.calls
    assert len(call["masks"]) == 3 and call["flashes"] == 2 and call["flash_s"] == 5.0 and call["rest_s"] == 4.0                         # 10 s in 2 flashes of 5 s, 4 s of rest
    assert call["masks"][0].shape == (300, 500) and call["masks"][0].sum() > call["masks"][1].sum() > call["masks"][2].sum() > 0
    summary = json.loads(r.headers["x-build-summary"])
    assert summary["layers"] == 6 and summary["flash_s"] == 5.0 and summary["total_light_s"] == 30.0                                       # (three steps of two flashes)


def test_the_resist_and_the_mirror_of_the_request_are_in_the_masks(made):
    client, drv = made
    for extra in ({}, {"polarity": "negative"}, {"mirror": True}):
        assert client.post("/api/generate/ladder", json={"ladder": {**BODY["ladder"], **extra}}).status_code == 200
    plain, negative, mirrored = (c["masks"] for c in drv.calls)
    assert not (plain[0] & negative[0]).any() and negative[0].sum() < plain[0].sum()
    assert all(np.array_equal(a[:, ::-1], b) for a, b in zip(plain, mirrored))


def test_a_ladder_that_cannot_be_made_is_refused_with_every_issue_and_the_driver_is_never_asked(made):
    client, drv = made
    r = client.post("/api/generate/ladder", json={"ladder": {**BODY["ladder"], "bands": 12, "width": 12, "step": 8, "pulses": 10}})        # too wide, and flashes of 0.8 s
    assert r.status_code == 422 and r.json()["error"]["code"] == "generation_blocked"
    issues = r.json()["error"]["params"]["issues"]
    assert {i["code"] for i in issues if i["blocking"]} == {"flash_below_minimum", "ladder_too_big"}
    assert drv.calls == []


def test_the_issues_that_only_inform_do_not_stop_the_file(made):
    client, drv = made
    assert client.post("/api/generate/ladder", json={"ladder": {**BODY["ladder"], "tests": []}}).status_code == 200                       # no tests: empty strips with their time
    assert client.post("/api/generate/ladder", json={"ladder": {**BODY["ladder"], "step": 100, "pulses": 1}}).status_code == 200            # a flash over the longest tried
    assert len(drv.calls) == 2


@pytest.mark.parametrize("edit", [lambda b: b.pop("ladder"), lambda b: b["ladder"].update(bands=1), lambda b: b["ladder"].update(tests=["x"]), lambda b: b.update(extra=1),
                                  lambda b: b.update(supersample=4), lambda b: b["ladder"].update(polarity="sideways")])
def test_a_request_that_is_not_good_is_refused_before_anything_is_made(made, edit):
    client, drv = made
    body = json.loads(json.dumps(BODY))
    edit(body)
    r = client.post("/api/generate/ladder", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request" and drv.calls == []


def test_a_printer_that_writes_no_such_file_says_so_and_an_unknown_one_is_named(made):
    client, _ = made
    assert client.post("/api/generate/ladder", json={**BODY, "printer_id": "nobody"}).json()["error"] == {"code": "unknown_printer", "params": {"printer_id": "nobody"}}
    plain = served(template_driver("tpl"), store=None)
    r = plain.post("/api/generate/ladder", json={**BODY, "printer_id": "tpl"})
    assert r.status_code == 422 and "template_missing" in [i["code"] for i in r.json()["error"]["params"]["issues"]]


def test_a_driver_that_cannot_write_several_masks_says_so():
    from gerberslap.printers.base import DriverDescriptor, PrinterDriver
    drv = building_driver("plain")
    drv.build_sequence = lambda *a, **k: PrinterDriver.build_sequence(drv, *a, **k)                       # the default of a driver that does not do it
    r = served(drv).post("/api/generate/ladder", json=BODY)
    assert r.status_code == 422 and r.json() == {"error": {"code": "sequence_unsupported", "params": {}}}


def test_the_route_refuses_another_site_like_every_route_that_changes_something(made):
    client, drv = made
    for headers in ({"Origin": "http://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
        r = client.post("/api/generate/ladder", headers=headers, json=BODY)
        assert r.status_code == 403 and r.json()["error"]["code"] == "cross_site"
    assert drv.calls == []


def test_nothing_of_the_ladder_is_left_behind(made):
    client, drv = made
    client.post("/api/generate/ladder", json=BODY)
    out = drv.calls[0]["out"]
    assert out.name == "out.fake" and not out.exists() and not out.parent.exists()


# ---- the real printer ------------------------------------------------------------------------------------------------------------
@needs_template
def test_the_real_printer_writes_every_step_for_its_flashes_and_the_file_reads_back_as_the_masks(tmp_path):
    drv = get_driver("ld002h")
    store = DataStore(tmp_path / "data")
    install_template(store, drv, TEMPLATE)
    client = TestClient(create_app(store=store, allowed_hosts=["testserver"]), raise_server_exceptions=False)
    ladder = {**SPEC, "step": 8, "bands": 3, "pulses": 2, "rest": 3, "width": 13, "height": 76, "mirror": True, "polarity": "negative"}
    r = client.post("/api/generate/ladder", json={"ladder": ladder, "supersample": 8})
    assert r.status_code == 200 and r.headers["content-disposition"] == 'attachment; filename="scala_8s_x3.ctb"'
    out = tmp_path / "ladder.ctb"
    out.write_bytes(r.content)
    c = ctbio.CTB(str(out))
    assert c.crc_ok and c.layer_count == 6
    layout = core.ladder_layout(3, 13, 76, 8, drv.descriptor.plane.width_mm, drv.descriptor.plane.height_mm, core.TESTS)
    masks = core.ladder_step_masks(layout, drv.descriptor.grid, polarity="negative", mirror=True, supersample=8)
    for i in range(6):
        assert np.array_equal(c.layer_image(i) > 0, drv.to_printer_image(masks[i // 2])), i                # layers 0 and 1 are the first step, 2 and 3 the second...
    assert np.count_nonzero(c.layer_image(0)) > np.count_nonzero(c.layer_image(2)) > np.count_nonzero(c.layer_image(4)) > 0
    import struct
    assert struct.unpack_from("<f", c.d, ctbio.H_EXP)[0] == 4.0                                                # the flash: 8 s in 2 flashes
    summary = json.loads(r.headers["x-build-summary"])
    assert summary["layers"] == 6 and summary["flash_s"] == 4.0 and summary["rest_s"] == 3.0 and summary["file_bytes"] == len(r.content)


@needs_template
def test_the_real_printer_refuses_a_flash_under_its_minimum_and_a_ladder_that_does_not_fit(tmp_path):
    drv = get_driver("ld002h")
    store = DataStore(tmp_path / "data")
    install_template(store, drv, TEMPLATE)
    client = TestClient(create_app(store=store, allowed_hosts=["testserver"]), raise_server_exceptions=False)
    for ladder, code in (({**SPEC, "step": 8, "pulses": 10}, "flash_below_minimum"), ({**SPEC, "bands": 12, "width": 12, "step": 10, "pulses": 2}, "ladder_too_big")):
        r = client.post("/api/generate/ladder", json={"ladder": ladder})
        assert r.status_code == 422 and code in [i["code"] for i in r.json()["error"]["params"]["issues"] if i["blocking"]]


@needs_template
def test_the_real_printer_refuses_a_file_in_which_a_step_would_light_nothing(tmp_path):
    from gerberslap.model import PrinterConfig
    drv = get_driver("ld002h")
    lit = np.zeros((1620, 2560), bool)
    lit[100:200, 100:200] = True
    cfg = PrinterConfig(id="ld002h", name="x", driver="ld002h")
    for masks in ([lit, np.zeros_like(lit)], [np.zeros_like(lit), lit]):
        with pytest.raises(Exception) as info:
            drv.build_sequence(masks, 2, 4.0, 1.0, cfg, TEMPLATE, tmp_path / "x.ctb")
        assert getattr(info.value, "code", None) == "mask_all_dark" and not (tmp_path / "x.ctb").exists()


def test_a_pillow_that_cannot_cut_its_font_says_so_and_asks_the_driver_for_nothing(made, monkeypatch):
    client, drv = made
    monkeypatch.setattr(core, "label_font_available", lambda: False)
    r = client.post("/api/generate/ladder", json=BODY)
    assert r.status_code == 422 and r.json()["error"]["code"] == "font_missing" and drv.calls == []
    monkeypatch.undo()
    assert core.label_font_available()                                                                   # (this one can: the font is inside Pillow, there is no file to lose)
