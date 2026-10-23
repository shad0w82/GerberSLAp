"""The page, without a browser: the files it refers to exist, the scripts are valid, the Italian and English catalogues have the same keys,
every text the page asks for exists, and every code the backend can send (an error, an issue, a layer status) has a sentence."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from gerberslap.model import C, LC

STATIC = Path(__file__).resolve().parent.parent / "gerberslap" / "web" / "static"
SRC = STATIC.parent.parent
HTML = (STATIC / "index.html").read_text()
JS = {p.name: p.read_text() for p in (STATIC / "js").glob("*.js")}


def catalogues():
    text = JS["i18n.js"]
    it, en = text.split("  it: {", 1)[1].split("\n  en: {", 1)
    key = re.compile(r"(?:^|[\s,{])([a-z][a-z0-9_]*): '")
    return set(key.findall(it)), set(key.findall(en))


IT, EN = catalogues()


# ---- files and scripts -------------------------------------------------------------------------------------------
def test_everything_the_page_loads_is_there():
    for ref in re.findall(r'(?:src|href)="([^"#]+)"', HTML):
        if ref.startswith("https://"):                                                                               # (the one link out is checked below)
            continue
        assert (STATIC / ref).is_file(), ref
    for name, text in JS.items():
        for ref in re.findall(r"from '\./([\w.-]+)'", text):
            assert ref in JS, f"{name} imports {ref}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("name", sorted(JS))
def test_the_scripts_are_valid_modules(name):
    # as a module, from stdin: "node --check file.js" takes a .js file for a script and accepts almost anything in it
    r = subprocess.run(["node", "--input-type=module", "--check"], input=JS[name], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ---- the order of the layers: the functions that move them, run for real with node -------------------------------------
def node_json(script):
    r = subprocess.run(["node", "--input-type=module", "-e", f"import * as m from {(STATIC / 'js' / 'model.js').as_uri()!r};\n{script}"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return __import__("json").loads(r.stdout)


LAYERS = ("const L = (id, role, status = 'ok') => ({ id, role, status: { level: status } }); "
          "const ids = (a) => a && a.map((l) => l.id); ")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_layer_moves_within_the_stack_and_the_others_stay_where_they_are():
    got = node_json(LAYERS + """
      const a = [L('silk', 'silk'), L('mask', 'mask'), L('copper', 'copper'), L('outline', 'outline'), L('drill', 'drill')];
      const b = [L('outline', 'outline'), L('silk', 'silk'), L('mask', 'mask'), L('drill', 'drill'), L('copper', 'copper')];   // the apart ones in between
      const before = JSON.stringify(a);
      console.log(JSON.stringify({
        top: ids(m.moveLayer(a, 'copper', 0)), down: ids(m.moveLayer(a, 'silk', 2)), clamp: ids(m.moveLayer(a, 'silk', 99)), under: ids(m.moveLayer(a, 'copper', -5)),
        same: m.moveLayer(a, 'mask', 1), unknown: m.moveLayer(a, 'nope', 0), outline: m.moveLayer(a, 'outline', 0), drill: m.moveLayer(a, 'drill', 0),
        between: ids(m.moveLayer(b, 'copper', 0)), untouched: JSON.stringify(a) === before }));""")
    assert got["top"] == ["copper", "silk", "mask", "outline", "drill"] and got["down"] == ["mask", "copper", "silk", "outline", "drill"]
    assert got["clamp"] == got["down"] and got["under"] == got["top"]                  # past the ends is the end
    assert got["same"] is None and got["unknown"] is None and got["outline"] is None and got["drill"] is None      # nothing to do
    assert got["between"] == ["outline", "copper", "silk", "drill", "mask"]            # the outline and the holes keep their places
    assert got["untouched"]                                                            # the list it was given is not changed


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_layer_steps_one_place_up_or_down_and_stops_at_the_ends():
    got = node_json(LAYERS + """
      const a = [L('silk', 'silk'), L('mask', 'mask'), L('copper', 'copper'), L('outline', 'outline')];
      console.log(JSON.stringify({ up: ids(m.stepLayer(a, 'copper', -1)), down: ids(m.stepLayer(a, 'silk', 1)), topUp: m.stepLayer(a, 'silk', -1),
        bottomDown: m.stepLayer(a, 'copper', 1), outline: m.stepLayer(a, 'outline', -1), unknown: m.stepLayer(a, 'x', 1) }));""")
    assert got["up"] == ["silk", "copper", "mask", "outline"] and got["down"] == ["mask", "silk", "copper", "outline"]
    assert got["topUp"] is None and got["bottomDown"] is None and got["outline"] is None and got["unknown"] is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_area_outline_is_the_smallest_id_without_an_error_in_whatever_order():
    got = node_json(LAYERS + """
      const w = [L('b_out', 'outline'), L('a_out', 'outline'), L('0_bad', 'outline', 'error'), L('copper', 'copper')];
      const pick = (layers) => (m.areaOutline({ layers }) || {}).id;
      console.log(JSON.stringify({ one: pick(w), reversed: pick([...w].reverse()), none: pick([L('copper', 'copper')]) ?? null }));""")
    assert got == {"one": "a_out", "reversed": "a_out", "none": None}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_mirrored_board_is_drawn_with_its_stack_turned_over():
    """The list runs from the top side down and the plane is seen from above. Turned over, the bottom side is the nearest to the viewer."""
    got = node_json(LAYERS + """
      const layers = [L('silk_top', 'silk'), L('mask_top', 'mask'), L('cu_top', 'copper'), L('cu_bot', 'copper'), L('mask_bot', 'mask'), L('silk_bot', 'silk'),
                      L('outline', 'outline'), L('drill', 'drill')];
      const on = (ls) => ls.map((l) => ({ ...l, on: true }));
      const board = (mirror, ls = on(layers)) => ({ mirror, layers: ls });
      const off = on(layers).map((l) => (l.id === 'mask_top' || l.id === 'drill' ? { ...l, on: false } : l));
      console.log(JSON.stringify({ plain: ids(m.drawOrder(board(false))), mirrored: ids(m.drawOrder(board(true))),
        someOff: ids(m.drawOrder(board(true, off))), unchanged: JSON.stringify(board(false).layers.map((l) => l.id)) }));""")
    assert got["plain"] == ["silk_bot", "mask_bot", "cu_bot", "cu_top", "mask_top", "silk_top", "outline"]      # the top of the list is drawn last
    assert got["mirrored"] == ["silk_top", "mask_top", "cu_top", "cu_bot", "mask_bot", "silk_bot", "outline"]   # the bottom side on top, the outline always last
    assert got["someOff"] == ["silk_top", "cu_top", "cu_bot", "mask_bot", "silk_bot", "outline"]                  # only what is on; the holes draw nothing
    assert got["unchanged"] == '["silk_top","mask_top","cu_top","cu_bot","mask_bot","silk_bot","outline","drill"]'   # the list itself is not touched


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_board_added_after_opening_a_project_never_takes_an_id_the_project_has():
    got = node_json("""
      const B = (...ids) => ids.map((id) => ({ id }));
      console.log(JSON.stringify([m.nextBoardNumber([]), m.nextBoardNumber(B('b1', 'b2')), m.nextBoardNumber(B('b3', 'b12', 'b7')), m.nextBoardNumber(B('b-9f3a2c1d', 'x5')),
                                  m.nextBoardNumber(B('b0')), m.nextBoardNumber(B('b99999999999')), m.nextBoardNumber(B('B4', 'b4x', 'ab4'))]));""")
    assert got == [1, 3, 13, 1, 1, 100000000000, 1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_name_of_a_project_is_its_file_name_without_the_extension():
    got = node_json("""console.log(JSON.stringify(['board.gslp', 'My Board.GSLP', 'x.gslp.gslp', 'no-extension', 'tab\\tname.gslp',
                                                   '.gslp', 'a.gslp.zip', '  padded  .gslp', 'caffè è.gslp'].map(m.projectStem)));""")
    assert got == ["board", "My Board", "x.gslp", "no-extension", "tab name", "", "a.gslp.zip", "padded", "caffè è"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_only_gslp_files_are_project_files_and_the_old_extension_is_not():
    got = node_json("""console.log(JSON.stringify(['a.gslp', 'A.GSLP', 'x.gerberslap', 'X.GerberSLAp', 'a.gslp.zip', 'a.zip', 'gslp', 'a.gslp.gerberslap', '.gslp'].map(m.isProjectFile)));""")
    assert got == [True, True, False, False, False, False, False, False, True]
    index = (STATIC / "index.html").read_text()
    assert 'id="file-open" accept=".gslp"' in index                                                                                      # the dialog offers only the new extension
    app = (STATIC / "js" / "app.js").read_text()
    assert "if (isProjectFile(f.name)) openProjectFile(f); else toast(t('toast_unsupported'));" in app                                    # the dialog can be switched to "all files": the picker checks the extension too, like the drop does
    assert "projects = files.filter((f) => isProjectFile(f.name))" in app
    assert ".gerberslap" not in app and ".gerberslap" not in index                                                                       # the old extension is written nowhere in the page


# ---- what the user decided about showing unsaved changes and the project name ------------------------------------------------
def section(start, end):
    return HTML[HTML.index(start):HTML.index(end, HTML.index(start))]


def test_the_save_state_is_a_pill_that_is_always_there_and_the_save_button_only_saves():
    pill = re.search(r'<(span|button)[^>]*id="st-save"[^>]*>', HTML)
    assert pill and pill.group(1) == "span" and "hidden" not in pill.group(0)                                         # a notice, not a button, never hidden
    app = JS["app.js"]
    assert "'#st-save').onclick" not in app and "#st-save').addEventListener" not in app                              # nothing is bound to it
    assert "classList.toggle('dirty'" not in app and ".dirty" not in (STATIC / "css" / "style.css").read_text()       # the Save button never changes
    assert "btn-save').title" not in app and "save.title" not in app


def test_the_cadtitlebar_has_undo_and_redo_on_the_left_the_views_in_the_middle_and_the_pills_on_the_right():
    bar = section('<div class="cadtitlebar"', '<div class="canvas-wrap')
    order = [bar.index(x) for x in ('id="btn-undo"', 'id="btn-redo"', 'data-mode="material"', 'data-mode="exact"', 'id="st-save"', 'id="st-warn"')]
    assert order == sorted(order)                                                                                    # in this order, left to right
    assert bar.index('class="tb-left"') < bar.index('id="btn-undo"') < bar.index('class="seg"') < bar.index('class="tb-right"') < bar.index('id="st-save"')
    assert "btn-help" not in HTML                                                                                    # the "?" button is gone (the Help tab replaces it)


def test_the_status_bar_holds_only_what_is_about_the_drawing():
    bar = section('<footer class="statusbar">', "</footer>")
    for wanted in ("st-cursor", "st-sel", "btn-grid", "btn-snap", "btn-zoom-in", "btn-zoom-out", "btn-fit", "st-zoom", "st-busy"):
        assert f'id="{wanted}"' in bar, wanted
    for gone in ("st-save", "st-warn", "st-live", "lay-live"):
        assert gone not in bar, gone                                                                                 # the pills moved to the CadTitleBar


def test_help_has_the_licence_and_the_only_link_out_of_the_page_is_the_one_to_the_source_code():
    help_view = section('<main id="view-help"', "</main>")
    card = section('<section class="card" id="help-license">', "</section>")
    assert card in help_view and 'data-i18n="help_license_title"' in card and 'data-i18n="help_license_text"' in card
    link = re.search(r"<a [^>]*>", card).group(0)
    url = re.search(r'href="([^"]+)"', link).group(1)
    assert 'id="source-link"' in link and 'target="_blank"' in link and 'rel="noopener noreferrer"' in link and 'data-i18n="help_source_link"' in link
    assert re.findall(r'(?:src|href|action)="(?:https?:)?//[^"]*"', HTML) == [f'href="{url}"']                          # nothing else is loaded from, or sent to, another site
    assert "AGPL" in re.search(r"help_license_text: '([^']*)'", JS["i18n.js"]).group(1)
    readme = (SRC.parent / "README.md").read_text()
    assert re.search(r"git clone (\S+)", readme).group(1) == url + ".git"                                              # the page and the README point to the same repository


def test_help_is_a_tab_that_holds_the_shortcuts_and_there_is_no_shortcuts_dialog_any_more():
    tabs = section('<nav class="tabs"', "</nav>")
    assert re.findall(r'data-view="([a-z]+)"', tabs) == ["plane", "ladder", "settings", "help"]
    help_view = section('<main id="view-help"', "</main>")
    assert 'id="keys-table"' in help_view and 'data-i18n="help_title"' in help_view
    assert "dlg-help" not in HTML and "dlg-help" not in JS["app.js"]
    assert "const VIEWS = ['plane', 'ladder', 'settings', 'help']" in JS["app.js"]
    assert "setView('help')" in JS["app.js"]                                                                         # and "?" opens it, from any tab


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_warnings_pill_is_only_an_icon():
    got = node_json("""
      const t = (k) => k;
      const W = (...lv) => lv.map((l) => ({ lv: l }));
      console.log(JSON.stringify({ none: m.warningStatus([], t), some: m.warningStatus(W('warn', 'warn', 'warn'), t), bad: m.warningStatus(W('warn', 'bad'), t) }));""")
    assert got["none"] == {"text": "✓", "cls": "chip ok", "label": "no_warnings"}                                      # a tick and nothing else: no words
    assert got["some"] == {"text": "⚠ 3", "cls": "chip warn", "label": "warnings: 3"}                                # a sign and how many
    assert got["bad"] == {"text": "⚠ 2", "cls": "chip bad", "label": "warnings: 2"}                                  # red when one of them is an error


ICON_BUTTONS = ["btn-new", "btn-open", "btn-save", "btn-download", "btn-undo", "btn-redo", "btn-add", "btn-expand-all", "btn-collapse-all", "btn-fit",
                "btn-ld-zoom-out", "btn-ld-zoom-in", "btn-ld-fit"]                  # (the buttons of the Placement section have a short text beside the icon: see the test of that section)


@pytest.mark.parametrize("button_id", ICON_BUTTONS)
def test_the_buttons_that_act_have_an_icon_and_no_text_and_their_text_is_the_tooltip(button_id):
    m = re.search(r'<button[^>]*\bid="%s"([^>]*)>(.*?)</button>' % button_id, HTML, re.S)
    assert m, button_id
    attrs, inner = m.group(1), m.group(2)
    assert "<svg" in inner and re.sub(r"<[^>]+>", "", inner).strip() == "", button_id                                 # an icon and no words
    assert "data-i18n=" not in attrs and "data-i18n-title=" in attrs and "data-i18n-aria=" in attrs, button_id      # the words are the tooltip and the screen reader name


def test_there_is_no_duplicate_button_in_the_boards_panel_nor_the_old_notes_under_the_layers():
    css = (STATIC / "css" / "style.css").read_text()
    for gone in ("btn-dup", "list-tools", "holes-note", "no_holes_file"):
        assert gone not in HTML and gone not in JS["app.js"] and gone not in css, gone
    assert 'data-act="dup"' in JS["app.js"]                                                                          # each card still has its own


def test_the_card_has_one_name_and_a_subtitle_without_the_file_name_and_the_notes_are_tooltips():
    app = JS["app.js"]
    assert "esc(b.source" not in app and "b.source ||" not in app                                                  # the zip name is not repeated in the subtitle
    assert "boardTitle(b)" in app and "ignored_files_tip" in app
    assert app.count("holes_on") >= 2 and app.count("holes_off") >= 2                                              # the holes explanation: the row's tooltip


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_board_is_called_by_its_name_with_the_extension_of_its_file():
    got = node_json("""
      const t = (name, source) => m.boardTitle({ name, source });
      console.log(JSON.stringify([t('altium_flight_controller', 'altium_flight_controller.zip'), t('x (2)', 'x.zip'), t('board', null), t('board', undefined), t('board', 'board'),
        t('My Board', 'My Board.ZIP'), t('x.zip', 'x.zip'), t('a', 'a.b.c.zip'), t('a', 'a.toolongextension'), t('', '.zip')]));""")
    assert got == ["altium_flight_controller.zip", "x (2).zip", "board", "board", "board", "My Board.ZIP", "x.zip", "a.zip", "a", ".zip"]


PRINTERS_JS = """
  const P = (id, name, w, h, cols, rows, pitch) => ({ id, name, plane: { width_mm: w, height_mm: h }, grid: { width: cols, height: rows, pitch } });
  const small = P('small', 'Small', 100, 60, 500, 300, 0.2), large = P('large', 'Large', 200, 120, 1000, 600, 0.2);
  const fmt = (n, d) => n.toFixed(d).replace('.', ',');
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_plane_of_the_page_is_the_one_of_the_printer_and_the_pill_says_name_size_and_pixels():
    got = node_json(PRINTERS_JS + """
      console.log(JSON.stringify({ plane: m.planeOf(small), size: m.printerSize(small, fmt), line: m.printerLine(large, fmt) }));""")
    assert got["plane"] == {"w": 100, "h": 60, "px": [500, 300], "pitch": 0.2, "name": "Small"}
    assert got["size"] == "100,00 × 60,00 mm · 500 × 300 px" and got["line"] == "Large · 200,00 × 120,00 mm · 1000 × 600 px"       # the resolution is in the pill


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_size_of_a_pixel_is_written_whole_when_it_is_whole_and_to_the_tenth_when_it_is_not():
    got = node_json(PRINTERS_JS + """
      console.log(JSON.stringify([0.051, 0.08, 0.1, 0.0475, 0.0635, 0.05105, 0.0508, 0.025].map((x) => m.pitchLabel(x, fmt))));""")
    assert got == ["51 µm", "80 µm", "100 µm", "47,5 µm", "63,5 µm", "51 µm", "50,8 µm", "25 µm"]


def test_the_name_of_the_exact_view_carries_the_pixel_of_the_printer_in_use_and_there_is_no_other_button_for_it():
    tag = re.search(r'data-mode="exact"[^>]*>', HTML)
    assert tag and "data-i18n" not in tag.group(0)                                                                           # written by the page from the printer
    assert len(re.findall(r"\bmode_exact: '[^']*\{res\}[^']*'", JS["i18n.js"])) == 2                                        # Italian and English, both with the size
    assert "mode_exact', { res }" in JS["app.js"] and "pitchLabel(p.grid.pitch, fmt)" in JS["app.js"]
    # the Exposure panel had a button «Exact preview»: it was the same as the view of that name (decided on 14 October, done on 18 October)
    assert "btn-exact" not in HTML + JS["app.js"] and "exact_preview" not in JS["i18n.js"] + JS["app.js"]
    for text in (HTML, (STATIC / "css" / "style.css").read_text(), *JS.values()):
        assert not re.search(r"\b\d+(?:[.,]\d+)?\s*µm", text), re.search(r"\b\d+(?:[.,]\d+)?\s*µm", text).group(0)         # no size of a pixel written by hand


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_project_gets_its_printer_if_the_app_has_it_and_otherwise_the_one_in_use_and_it_is_said():
    got = node_json(PRINTERS_JS + """
      const L = [small, large], pick = (req, cur = 'large', def = 'small') => m.pickPrinter(req, L, cur, def);
      console.log(JSON.stringify({ known: pick('small'), none: pick(null), none2: pick(undefined, 'small'), unknown: pick('mars'), unknownNoCurrent: pick('mars', null),
        currentGone: pick(null, 'gone'), noPrinters: m.pickPrinter(null, [], null, undefined) }));""")
    assert got["known"] == {"id": "small", "unknown": None}
    assert got["none"] == {"id": "large", "unknown": None} and got["none2"] == {"id": "small", "unknown": None}              # none asked for: the one in use
    assert got["unknown"] == {"id": "large", "unknown": "mars"} and got["unknownNoCurrent"] == {"id": "small", "unknown": "mars"}    # replaced, and named
    assert got["currentGone"] == {"id": "small", "unknown": None} and got["noPrinters"]["unknown"] is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_issues_of_a_printers_installation_are_those_of_the_printer_in_use_and_only_those():
    got = node_json("""
      const issue = (code) => ({ code, severity: 'error', blocking: true, params: {} });
      const L = [{ id: 'a', issues: [issue('template_missing')] }, { id: 'b', issues: [] }, { id: 'c' }];
      console.log(JSON.stringify({ a: m.printerIssues(L, 'a').map((i) => i.code), b: m.printerIssues(L, 'b'), noList: m.printerIssues(L, 'c'),
        unknown: m.printerIssues(L, 'z'), none: m.printerIssues([], null) }));""")
    assert got == {"a": ["template_missing"], "b": [], "noList": [], "unknown": [], "none": []}
    assert "printerIssues(state.printers, state.printerId)" in JS["app.js"]                           # and the warnings list takes them from there


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_project_sent_to_the_server_names_the_printer():
    got = node_json("""
      const board = { id: 'b1', name: 'x', source: null, w: 1, h: 1, cx: 0, cy: 0, x: 0, y: 0, angle: 0, mirror: false, layers: [] };
      console.log(JSON.stringify([m.toApiProject([board], 'positive', 0.3, 'small').printer_id, m.toApiProject([board], 'positive', 0.3).printer_id]));""")
    assert got == ["small", None]


def test_the_printer_pill_is_in_the_cadwindow_and_the_page_knows_no_printer_by_name_or_size():
    window = section('<div class="canvas-wrap cadwindow"', '<div id="empty-state"') if '<div id="empty-state"' in HTML else HTML
    assert 'id="printer-pill"' in window and 'id="printer-menu"' in window and 'role="listbox"' in window
    css = (STATIC / "css" / "style.css").read_text()
    for text in (HTML, css, *JS.values()):
        for constant in ("LD-002", "Creality", "130.56", "82.62", "2560", "1620", "0.051"):
            assert constant not in text, constant                                                                            # all of it comes from /api/info
    app = JS["app.js"]
    for call in re.findall(r"toApiProject\([^)]*\)", app):
        assert "state.printerId" in call, call                                                                              # every project the page sends names its printer
    assert "api.openZip(f, id, false, state.printerId)" in app                                                              # a zip is placed on the plane of that printer
    assert "state.info.printers" in app and "state.info.driver" not in app


def test_the_state_of_the_page_is_declared_with_all_its_keys_outside_of_the_comments():
    """A comment added at the end of a line of the declaration once commented out the rest of that line, and the syntax stayed valid."""
    decl = JS["app.js"][JS["app.js"].index("const state = {"):]
    decl = decl[:decl.index("};") + 2]
    code = "\n".join(re.sub(r"//.*$", "", line) for line in decl.splitlines())
    for key in ("plane", "info", "printers", "printerId", "defaultPrinter", "printerNote", "polarity", "boards", "selectedId", "view", "mode", "grid", "snap",
                "minOutline", "nextId", "history", "hi", "anchor", "open", "issues", "checkFailed", "pending", "name", "saved", "savedAt",
                "recipeId", "dosageId", "working", "library"):
        assert re.search(r"\b%s\b\s*:" % key, code), key


def test_the_menubar_has_save_and_download_and_neither_can_be_used_without_a_board():
    header = HTML[HTML.index('<header class="menubar">'):HTML.index("</header>")]
    for button in ("btn-new", "btn-open", "btn-save", "btn-download"):
        assert f'id="{button}"' in header
    assert "$('#btn-save').disabled = $('#btn-download').disabled = !state.boards.length" in JS["app.js"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_save_pill_says_when_it_was_saved_and_adds_unsaved_when_there_are_changes():
    got = node_json("""
      import * as w from %r;
      const t = (k, v = {}) => k + (Object.keys(v).length ? JSON.stringify(v) : '');
      const at = Date.UTC(2026, 9, 13, 14, 32, 5), now = Date.UTC(2026, 9, 13, 18, 0, 0), tomorrow = Date.UTC(2026, 9, 14, 9, 0, 0);
      const s = (dirty, savedAt, n = now) => w.saveStatus({ dirty, savedAt, now: n, locale: 'en-GB', t, timeZone: 'UTC' });
      console.log(JSON.stringify({ never: s(false, null), neverDirty: s(true, null), clean: s(false, at), dirty: s(true, at), otherDay: s(false, at, tomorrow) }));""" % (STATIC / "js" / "workcopy.js").as_uri())
    assert got["never"] == {"main": "st_never", "extra": "", "text": "st_never", "title": "st_title_never", "warn": False}
    assert got["neverDirty"] == {"main": "● st_unsaved", "extra": "", "text": "● st_unsaved", "title": "st_title_never", "warn": True}   # nothing to say about the last save
    assert got["clean"]["text"].startswith('st_saved{"time":"') and not got["clean"]["warn"] and "st_unsaved" not in got["clean"]["text"]
    assert got["dirty"]["text"].startswith("● st_unsaved · st_last{") and got["dirty"]["warn"]                           # both: unsaved, and when the last save was
    assert got["dirty"]["main"] == "● st_unsaved" and got["dirty"]["extra"].startswith("st_last{")                      # the part that can be dropped where there is no room
    assert got["clean"]["extra"] == ""
    assert '"time":"14:32"' in got["clean"]["text"] and '"time":"13 Oct, 14:32"' in got["otherDay"]["text"]
    assert got["clean"]["title"].startswith('st_title{"when":"') and "14:32:05" in got["clean"]["title"]


def test_the_project_name_is_in_the_menubar():
    header = HTML[HTML.index('<header class="menubar">'):HTML.index("</header>")]
    assert 'id="project-name"' in header
    assert "project_untitled" in JS["app.js"] and {"project_untitled"} <= IT


def test_the_page_names_no_mock_leftovers():
    for text in (HTML, *JS.values()):
        assert "mockup" not in text.lower()


# ---- the catalogues ----------------------------------------------------------------------------------------------
def test_italian_and_english_have_the_same_keys():
    assert IT == EN, (sorted(IT - EN), sorted(EN - IT))
    assert len(IT) > 150


def test_every_text_the_html_asks_for_exists():
    keys = set(re.findall(r'data-i18n(?:-title|-aria)?="([a-z0-9_]+)"', HTML))
    assert keys and keys <= IT, sorted(keys - IT)


def test_every_literal_text_the_scripts_ask_for_exists():
    keys = set()
    for text in JS.values():
        keys |= set(re.findall(r"\bt\('([a-z][a-z0-9_]*)'", text))
        keys |= set(re.findall(r"\bhas\('([a-z][a-z0-9_]*)'", text))
        keys |= set(re.findall(r"\[\s*'(m_[a-z]+)'", text))                      # the margin labels are listed in an array
        keys |= set(re.findall(r"\bk_[a-z_]+", text))                              # the shortcuts table
    keys = {k for k in keys if not k.endswith("_")}                              # "cad_" + value: a prefix, checked below
    assert keys and keys <= IT, sorted(keys - IT)


def test_the_keys_built_from_a_prefix_exist_for_every_value():
    for role in ("copper", "outline", "mask", "silk", "drill", "ignore"):
        assert f"role_{role}" in IT
    for side in ("top", "bottom", "inner"):
        assert f"side_{side}" in IT
    for cad in ("kicad", "altium", "eagle", "generic"):
        assert f"cad_{cad}" in IT
    for mb in ("default", "graphite", "navy", "indigo", "teal", "bordeaux", "slate"):
        assert f"mb_{mb}" in IT


# ---- what the backend can send, as sentences ---------------------------------------------------------------------
# what reaches the page: the importer, the pipeline, the shapes and the API (the data folder and the drivers are not wired in yet)
SENDERS = [*sorted((SRC / "cad").glob("*.py")), *sorted((SRC / "core").glob("*.py")), SRC / "web" / "app.py",
           SRC / "services" / "importer.py", SRC / "services" / "pipeline.py", SRC / "services" / "vector.py", SRC / "services" / "projectfile.py",
           SRC / "services" / "library.py"]


def harvested(pattern, *_ignored):
    out = set()
    for f in SENDERS:
        out |= set(re.findall(pattern, f.read_text()))
    return out


def test_every_layer_status_has_a_sentence():
    codes = {v for k, v in vars(LC).items() if k.isupper()}
    assert codes and {f"ls_{c}" for c in codes} <= IT, sorted({f"ls_{c}" for c in codes} - IT)


def test_no_sentence_is_left_for_a_code_that_does_not_exist_any_more():
    layer_codes = {v for k, v in vars(LC).items() if k.isupper()}
    assert {k for k in IT if k.startswith("ls_")} <= {f"ls_{c}" for c in layer_codes}, sorted(k for k in IT if k.startswith("ls_"))
    issue_codes = {v for k, v in vars(C).items() if k.isupper()}
    stale = [k for k in IT if k.startswith("i_") and not any(k == f"i_{c}" or k.startswith(f"i_{c}_") for c in issue_codes)]
    assert not stale, stale


def test_every_issue_has_a_sentence_or_a_known_special_form():
    special = {"board_outside_plane": "w_out", "boards_overlap": "w_overlap", "board_layer_sum": "w_sum", "layer_types_mixed": "w_mixed",
               "layer_issue": "w_layer"}
    # what the page can receive: the layout checks, the findings made when a zip is opened and what a printer's installation lacks (the exposure
    # codes come later)
    shown = {"no_layer_on", "board_no_layer_on", "layer_error_on", "layer_issue", "board_outside_plane", "boards_overlap", "board_layer_sum",
             "layer_types_mixed", "no_outline", "no_drill", "job_size_mismatch", "files_unrecognised", "board_clipped", "board_area_estimated",
             "template_missing", "template_invalid", "template_lift_large", "printer_settings_invalid", "printer_config_invalid"}
    known = {v for k, v in vars(C).items() if k.isupper()}
    assert shown <= known
    for code in shown:
        assert f"i_{code}" in IT or special.get(code) in IT, code


def test_every_reason_a_template_can_be_refused_for_has_a_sentence():
    driver = (SRC / "printers" / "ld002h" / "driver.py").read_text()
    reasons = set(re.findall(r'refuse\("([a-z_]+)"', driver))
    assert {"missing", "not_a_ctb", "bad_crc", "bad_version", "lift_distance_zero"} <= reasons
    assert {f"i_template_invalid_{r}" for r in reasons} <= IT, sorted({f"i_template_invalid_{r}" for r in reasons} - IT)
    assert "i_template_invalid" in IT                                          # for a reason the page does not know


def test_the_texts_about_a_printers_installation_name_no_printer_and_no_file_format():
    lines = [line for line in JS["i18n.js"].splitlines() if re.search(r"\bi_(?:template|printer)_\w+:", line)]
    text = re.sub(r"\bi_\w+:", "", "\n".join(lines))                          # the keys carry the driver's reason codes; the sentences must not name anything
    assert text.strip() and not re.search(r"ctb|ld-?002|creality|chitubox", text, re.IGNORECASE), re.search(r"ctb|ld-?002|creality|chitubox", text, re.IGNORECASE).group(0)


def test_every_error_code_the_api_can_send_has_a_sentence():
    codes = harvested(r'code="([a-z_]+)"') | harvested(r'(?m)^\s+code = "([a-z_]+)"')
    codes |= harvested(r'ApiError\(\d+, "([a-z_]+)"')
    codes |= harvested(r'_error\(\d+, "([a-z_]+)"')
    codes |= harvested(r'PipelineError\(\s*"([a-z_]+)"')
    codes |= harvested(r'ProjectFileError\(\s*"([a-z_]+)"')
    codes -= {"import_refused"}                                                              # the base class: only its subclasses are sent
    assert {"bad_zip", "no_copper", "incompatible_export", "file_missing", "internal", "empty_file", "too_large", "store_full"} <= codes
    assert {"not_a_project", "bad_entry", "duplicate_entry", "bad_json", "bad_version", "newer_version", "invalid_project", "bad_hash",
            "unreferenced_file", "project_file_missing", "verification_failed"} <= codes                                  # what a project file can say
    missing = sorted(c for c in codes if f"err_{c}" not in IT)
    assert not missing, missing


def test_every_error_the_library_can_send_has_a_sentence():
    """The library's refusals reach the page as codes (the app maps a `StoreError` to a status and keeps its code): each one has a sentence."""
    sent = {"recipe_not_found", "dosage_not_found", "recipe_exists", "polarity_locked", "too_many_recipes", "too_many_dosages", "bad_content",
            "bad_id", "data_damaged", "unknown_printer", "not_found"}
    in_code = set(re.findall(r'code="([a-z_]+)"', (SRC / "services" / "store.py").read_text() + (SRC / "services" / "library.py").read_text()))
    in_code |= set(re.findall(r'_error\(\d+, "([a-z_]+)"', (SRC / "web" / "app.py").read_text()))
    assert {"recipe_not_found", "dosage_not_found", "recipe_exists", "polarity_locked", "too_many_recipes", "too_many_dosages", "bad_content", "bad_id", "data_damaged"} <= in_code
    assert not {f"err_{c}" for c in sent} - IT, sorted({f"err_{c}" for c in sent} - IT)


def test_every_reason_the_board_area_can_be_estimated_for_has_a_sentence():
    reasons = harvested(r'(?:BoardArea\(None, |return rect, )"([a-z_]+)"')
    assert {"no_outline", "not_closed", "extent_mismatch"} <= reasons
    assert {f"i_board_area_estimated_{r}" for r in reasons} <= IT, sorted({f"i_board_area_estimated_{r}" for r in reasons} - IT)
    assert "i_board_area_estimated" in IT                                      # for a reason the page does not know


def test_the_reasons_of_an_incompatible_export_each_have_a_sentence():
    reasons = harvested(r'"reason": "([a-z_]+)"')
    assert {"old_cam_processor", "old_cam_header"} <= reasons
    assert {f"err_incompat_{r}" for r in reasons} <= IT, sorted({f"err_incompat_{r}" for r in reasons} - IT)


# ---- recipes and dosages in the page: the logic without the DOM (exposure.js), run for real with node -------------------------------------------
def node_exposure(script):
    r = subprocess.run(["node", "--input-type=module", "-e", f"import * as e from {(STATIC / 'js' / 'exposure.js').as_uri()!r};\nimport * as m from {(STATIC / 'js' / 'model.js').as_uri()!r};\n{script}"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return __import__("json").loads(r.stdout)


DOSAGES_JS = """
  const d = (id, printer, updated, extra = {}) => ({ id, printer_id: printer, updated, total_s: 80, pulses: 4, rest_s: 5, name: '', note: '', ...extra });
  const recipe = { id: 'r', name: 'Dry film', polarity: 'negative', dosages: [
    d('old', 'ld', '2026-10-03T20:15:40Z'), d('other', 'fab', '2026-11-01T00:00:00Z'), d('new', 'ld', '2026-10-12T14:30:05Z'),
    d('tie-1', 'ld', '2026-10-05T10:00:00Z'), d('tie-2', 'ld', '2026-10-05T10:00:00Z')] };
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_dosages_of_a_recipe_for_a_printer_are_the_last_changed_first_and_the_chosen_one_is_preselected():
    got = node_exposure(DOSAGES_JS + """
      const ids = (l) => l.map((x) => x.id), pick = (p, id) => e.preselected(recipe, p, id)?.id ?? null;
      console.log(JSON.stringify({ ld: ids(e.dosagesFor(recipe, 'ld')), fab: ids(e.dosagesFor(recipe, 'fab')), none: ids(e.dosagesFor(recipe, 'x')), noRecipe: ids(e.dosagesFor(null, 'ld')),
        auto: pick('ld', null), chosen: pick('ld', 'old'), chosenForAnotherPrinter: pick('ld', 'other'), unknownChoice: pick('ld', 'gone'), noneForPrinter: pick('x', null) }));""")
    assert got["ld"] == ["new", "tie-2", "tie-1", "old"] and got["fab"] == ["other"] and got["none"] == [] and got["noRecipe"] == []     # of two at the same moment, the later in the list
    assert got["auto"] == "new" and got["chosen"] == "old"                                                                           # what the project chose, else the last changed
    assert got["chosenForAnotherPrinter"] == "new" and got["unknownChoice"] == "new" and got["noneForPrinter"] is None                # never a dosage of another printer


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_values_are_good_enough_to_save_only_within_the_servers_limits_and_a_long_flash_is_noted():
    got = node_exposure("""
      const v = (total_s, pulses, rest_s) => ({ total_s, pulses, rest_s }), lim = { min_flash_s: 1, max_proven_flash_s: 20 };
      console.log(JSON.stringify({ ok: e.isComplete(v(200, 5, 4)), edges: [e.isComplete(v(36000, 1000, 3600)), e.isComplete(v(0.5, 1, 0))], bad: [v(0, 1, 0), v(36001, 1, 0), v(10, 0, 0), v(10, 1.5, 0), v(10, 1001, 0), v(10, 1, -1), v(10, 1, 3601),
        v(null, 4, 5), v(10, null, 5), v(10, 4, null), v(NaN, 4, 5), null].map(e.isComplete),
        same: [e.sameValues(v(1, 2, 3), v(1, 2, 3)), e.sameValues(v(1, 2, 3), v(1, 2, 4)), e.sameValues(null, v(1, 2, 3))], values: e.valuesOf({ id: 'x', total_s: 9, pulses: 3, rest_s: 1, name: 'n' }), noValues: e.valuesOf(null),
        notes: [e.flashNote(v(200, 5, 4), lim), e.flashNote(v(100, 5, 4), lim), e.flashNote(v(4, 8, 4), lim), e.flashNote(v(200, 5, 4), { min_flash_s: null, max_proven_flash_s: null }), e.flashNote(v(null, 5, 4), lim), e.flashNote(v(200, 5, 4), null)] }));""")
    assert got["ok"] is True and got["edges"] == [True, True] and got["bad"] == [False] * 12
    assert got["same"] == [True, False, False] and got["values"] == {"total_s": 9, "pulses": 3, "rest_s": 1} and got["noValues"] is None
    assert got["notes"][0] == {"kind": "beyond", "flash": 40, "max": 20} and got["notes"][1] is None and got["notes"][2] == {"kind": "below", "flash": 0.5, "min": 1}
    assert got["notes"][3:] == [None, None, None]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_age_of_values_is_said_in_days_and_then_in_months():
    got = node_exposure("""
      const day = 864e5, now = Date.parse('2026-10-14T12:00:00Z'), ago = (days) => e.ageOf(new Date(now - days * day).toISOString(), now);
      console.log(JSON.stringify([ago(0), ago(0.4), ago(1), ago(59), ago(60), ago(330), e.ageOf('2027-01-01T00:00:00Z', now)]));""")
    assert got == [{"unit": "today", "n": 0}, {"unit": "today", "n": 0}, {"unit": "days", "n": 1}, {"unit": "days", "n": 59}, {"unit": "months", "n": 2}, {"unit": "months", "n": 11},
                   {"unit": "today", "n": 0}]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_values_typed_by_hand_come_back_only_if_they_are_numbers():
    got = node_exposure("""
      const p = e.parseRemembered;
      console.log(JSON.stringify([p('{"total_s":200,"pulses":5,"rest_s":4}'), p('{"total_s":200}'), p('{"total_s":"200","pulses":null,"rest_s":4}'), p('{}'), p('null'), p('[1,2]'), p('3'), p('"x"'),
        p('not json'), p(''), p(null), p('{"total_s":1e999}')]));""")
    assert got == [{"total_s": 200, "pulses": 5, "rest_s": 4}, {"total_s": 200, "pulses": None, "rest_s": None}, {"total_s": None, "pulses": None, "rest_s": 4}, None, None, None, None, None,
                   None, None, None, None]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_project_is_reconciled_with_the_library_and_the_recipes_polarity_wins_and_is_said():
    got = node_exposure("""
      const lib = { on: true, recipes: [{ id: 'r1', name: 'Dry film', polarity: 'negative', dosages: [] }, { id: 'r2', name: 'Positivo', polarity: 'positive', dosages: [] }] };
      const rec = (project, library = lib) => e.reconcileRecipe(project, library);
      console.log(JSON.stringify({
        same: rec({ recipe_id: 'r1', recipe_name: 'Dry film', dosage_id: 'd1', polarity: 'negative' }),
        differs: rec({ recipe_id: 'r1', recipe_name: 'Old name', dosage_id: 'd1', polarity: 'positive' }),
        noSavedPolarity: rec({ recipe_id: 'r2', recipe_name: 'Positivo', polarity: null }),
        missing: rec({ recipe_id: 'gone', recipe_name: 'Lost', dosage_id: 'd', polarity: 'negative' }),
        missingNoName: rec({ recipe_id: 'gone', polarity: 'negative' }),
        noRecipe: rec({ recipe_id: null, polarity: 'negative' }),
        badPolarity: rec({ recipe_id: null, polarity: 'sideways' }),
        noLibrary: rec({ recipe_id: 'r1', recipe_name: 'Dry film', dosage_id: 'd1', polarity: 'negative' }, { on: false, recipes: [] }) }));""")
    assert got["same"] == {"recipeId": "r1", "dosageId": "d1", "polarity": "negative", "notice": None}
    assert got["differs"] == {"recipeId": "r1", "dosageId": "d1", "polarity": "negative", "notice": {"kind": "polarity_changed", "name": "Dry film", "was": "positive", "now": "negative"}}
    assert got["noSavedPolarity"] == {"recipeId": "r2", "dosageId": None, "polarity": "positive", "notice": None}                    # nothing saved, nothing to flag
    assert got["missing"] == {"recipeId": None, "dosageId": None, "polarity": "negative", "notice": {"kind": "recipe_missing", "name": "Lost"}}     # the saved polarity is kept
    assert got["missingNoName"]["notice"] == {"kind": "recipe_missing", "name": ""} and got["missingNoName"]["polarity"] == "negative"
    assert got["noRecipe"] == {"recipeId": None, "dosageId": None, "polarity": "negative", "notice": None}
    assert got["badPolarity"]["polarity"] == "positive"
    assert got["noLibrary"] == {"recipeId": None, "dosageId": None, "polarity": "negative", "notice": None}                           # without a library only the polarity counts


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_library_copy_in_the_page_is_kept_by_name_and_changed_one_recipe_at_a_time():
    got = node_exposure("""
      const r = (id, name) => ({ id, name, polarity: 'positive', dosages: [] }), list = [r('b', 'beta'), r('a', 'Alpha'), r('c', 'gamma')];
      const sorted = e.sortRecipes(list), put = e.putRecipe(sorted, { ...r('b', 'Zeta'), dosages: [1] }), added = e.putRecipe(sorted, r('d', 'alpha two'));
      console.log(JSON.stringify({ sorted: sorted.map((x) => x.name), replaced: put.map((x) => [x.name, x.dosages.length]), added: added.map((x) => x.name), dropped: e.dropRecipe(sorted, 'a').map((x) => x.id),
        untouched: list.map((x) => x.id), droppedAbsent: e.dropRecipe(sorted, 'zz').length }));""")
    assert got["sorted"] == ["Alpha", "beta", "gamma"] and got["replaced"] == [["Alpha", 0], ["gamma", 0], ["Zeta", 1]] and got["added"] == ["Alpha", "alpha two", "beta", "gamma"]
    assert got["dropped"] == ["b", "c"] and got["untouched"] == ["b", "a", "c"] and got["droppedAbsent"] == 3


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_project_sent_to_the_server_names_the_recipe_and_the_dosage_and_never_the_values():
    got = node_exposure("""
      const board = { id: 'b1', name: 'x', source: null, w: 1, h: 1, cx: 0, cy: 0, x: 0, y: 0, angle: 0, mirror: false, layers: [] };
      const withRecipe = m.toApiProject([board], 'negative', 0.3, 'ld', { id: 'r1', name: 'Dry film', dosageId: 'd1' }), without = m.toApiProject([board], 'positive', 0.3, 'ld');
      const noChoice = m.toApiProject([board], 'negative', 0.3, 'ld', { id: 'r1', name: 'Dry film', dosageId: null });
      console.log(JSON.stringify({ withRecipe, without, noChoice }));""")
    p = got["withRecipe"]
    assert (p["schema_version"], p["printer_id"], p["recipe_id"], p["recipe_name"], p["dosage_id"], p["polarity"]) == (2, "ld", "r1", "Dry film", "d1", "negative")
    assert "profile_id" not in p and "total_s" not in json.dumps(p) and "pulses" not in json.dumps(p)                                   # a reference, never the values
    assert (got["without"]["recipe_id"], got["without"]["recipe_name"], got["without"]["dosage_id"]) == (None, None, None) and got["noChoice"]["dosage_id"] is None


def test_every_id_the_page_looks_up_is_in_the_html():
    ids = set(re.findall(r'id="([^"]+)"', HTML))
    used = set(re.findall(r"\$\('#([A-Za-z][\w-]*)'\)", JS["app.js"]))
    assert used and not (used - ids), sorted(used - ids)


def test_in_a_dialog_with_fields_the_enter_key_confirms_and_never_cancels():
    """Pressing Enter in a field submits the form with its first submit button: it must be the one that confirms."""
    seen = 0
    for dialog in re.findall(r"<dialog .*?</dialog>", HTML, re.S):
        if "<input" not in dialog and "<textarea" not in dialog:
            continue
        seen += 1
        first = re.search(r'<button[^>]*value="([^"]+)"', dialog).group(1)
        assert first == "ok", re.search(r'id="([^"]+)"', dialog).group(1)
    assert seen >= 4                                                           # the duplicate, recipe, dosage and Settings dosage dialogs at least


def test_the_settings_dosage_dialog_is_wired_to_every_field_it_has():
    app = JS["app.js"]
    for field in ("sd-printer", "sd-total", "sd-pulses", "sd-rest", "sd-name", "sd-note", "sd-ok", "sd-flash"):
        assert f'id="{field}"' in HTML and f"#{field}" in app, field
    assert "api.editDosage(recipeId, dosageId" in app and "api.addDosage(recipeId, { printer_id: $('#sd-printer').value" in app     # one dialog adds and edits
    assert "$('#sd-printer').disabled = !!d" in app                                                                                 # the printer is fixed when editing


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_short_form_of_a_recipe_is_its_resist_development_and_notes_on_one_line_with_a_dot_between():
    got = node_exposure("""
      const b = (r) => e.recipeBrief(r);
      console.log(JSON.stringify({ all: b({ resist: 'Dry film 25 µm', development: 'Soda 1%, 60 s', notes: 'Stendere senza bolle' }), some: b({ resist: 'Dry film', development: '', notes: 'solo note' }),
        lines: b({ resist: 'a', development: 'b', notes: 'prima riga\\n\\nseconda   riga\\t.' }), blanks: b({ resist: '  ', development: '', notes: '' }), missing: b({}) }));""")
    assert got["all"] == "Dry film 25 µm · Soda 1%, 60 s · Stendere senza bolle" and got["some"] == "Dry film · solo note"
    assert got["lines"] == "a · b · prima riga seconda riga ." and got["blanks"] == "" and got["missing"] == ""


def test_a_recipe_row_of_settings_lights_up_under_the_mouse_and_has_its_count_apart_from_the_buttons():
    css, app = (STATIC / "css" / "style.css").read_text(), JS["app.js"]
    assert "details.recipe > summary:hover" in css and "details.recipe > summary:focus-visible" in css
    assert re.search(r"\.rc-count \{[^}]*width: 94px[^}]*text-align: right", css)                                   # a fixed column, right-aligned (with room for its divider)
    assert re.search(r"\.rc-brief \{[^}]*flex: 1 1 0", css)                                                       # a closed row with no text still holds the space that keeps its count at the right
    assert app.index("rc-brief") < app.index("rc-count") < app.index('class="rc-actions"')                         # the text, then the count, then the buttons


def test_an_open_recipe_row_shows_its_texts_with_their_labels_and_loses_its_count():
    css, app = (STATIC / "css" / "style.css").read_text(), JS["app.js"]
    assert "details.recipe[open] > summary .rc-count, details.recipe[open] > summary .rc-brief { display: none; }" in css          # the short text and the count are for the closed row
    assert "<b>${esc(t(k))}:</b>" in app and app.index("${meta(r)}${table(r)}") > 0 and re.search(r"\.rc-meta \{[^}]*margin: [^;}]*17px", css)   # the labelled lines, under the name
    assert app.index('<div class="rc-dosages">') < app.index('<div class="rc-dosages-head">') < app.index('<table class="t data-table">', app.index('<div class="rc-dosages">'))      # the title and the plus come before the table, outside it


def test_the_dosage_table_is_its_own_frame_with_the_curvature_of_the_recipe_and_the_title_and_the_plus_are_outside_it():
    css, app = (STATIC / "css" / "style.css").read_text(), JS["app.js"]
    assert re.search(r"table\.data-table \{[^}]*border: 1px solid var\(--border\)[^}]*border-radius: var\(--rc-radius\)[^}]*overflow: hidden", css)       # the frame is the table, and clips its corners
    assert re.search(r"^:root \{[^}]*--rc-radius: 8px;", css, re.M | re.S) and re.search(r"details\.recipe \{[^}]*border-radius: var\(--rc-radius\)", css)       # the same curvature as the recipe's: one value for both
    assert css.count("--rc-radius:") == 1 and not re.search(r"^details\.recipe[^\n]*border-radius: \d+px", css, re.M)               # (no recipe rule has a curvature of its own)
    assert re.search(r"table\.data-table \{[^}]*border-collapse: separate", css)                                                 # (rounded corners need separate borders)
    rule = re.search(r"\.rc-dosages \{([^}]*)\}", css).group(1)
    assert "border" not in rule and "background" not in rule and "padding" not in rule                                        # the block around the title and the table has no frame of its own


def test_a_recipe_row_is_name_short_text_count_then_the_pill_at_the_right_then_a_divider_and_the_buttons():
    css, app = (STATIC / "css" / "style.css").read_text(), JS["app.js"]
    row = app[app.index('<summary><strong class="rc-title"'):app.index("</summary>")]
    order = [row.index(k) for k in ('class="rc-title"', 'class="rc-brief"', 'rc-count">', '${polChip(r.polarity)}', 'class="rc-actions"')]
    assert order == sorted(order)                                                                                             # the name, the short text, the count, the pill, the buttons
    assert re.search(r"details\.recipe \.rc-actions \{[^}]*padding-left: 12px[^}]*border-left: 1px solid", css)               # the divider is between the pill and the buttons
    assert re.search(r"\.rc-brief \{[^}]*flex: 1 1 0", css) and re.search(r"details\.recipe > summary \.chip \{ flex: none; width: 8rem;", css)   # the short text takes the room, so the pill (fixed width) is at the right
    assert "details.recipe[open] > summary .chip { margin-left: auto; }" in css                                              # open, the short text is gone: the pill still goes right
    assert "border-left-color: transparent" not in css and "margin-left: auto; border-left: 0; padding-left: 0" not in css      # the solid divider before the buttons is there open too, as it is closed
    assert not re.search(r"details\.recipe\[(data-)?open\][^{]*\.rc-actions", css)                                          # (no open rule touches it)


def test_the_dosage_table_has_a_centred_upper_case_title_a_name_column_and_dashed_columns():
    css, app = (STATIC / "css" / "style.css").read_text(), JS["app.js"]
    assert re.search(r"\.rc-dosages-head \{[^}]*grid-template-columns: 1fr auto 1fr", css) and re.search(r"\.rc-dtitle \{[^}]*text-transform: uppercase[^}]*text-align: center", css)
    assert "['name', 'ex_name', 'l']" in app and "'ex_dosage'" not in app[app.index("const COLS"):app.index("const table")]          # the column is called Name
    assert re.search(r"table\.data-table th, table\.data-table td \{ text-align: center;", css) and re.search(r"table\.data-table td \+ td \{[^}]*border-left: 1px dashed", css)


def test_in_the_dosage_table_printer_name_and_notes_are_left_aligned_and_cut_and_the_numbers_have_the_narrowest_columns():
    css, app = (STATIC / "css" / "style.css").read_text(), JS["app.js"]
    assert re.search(r"table\.data-table \{[^}]*table-layout: auto[^}]*width: 100%", css)                                       # the columns of numbers are as wide as their content needs, whichever the language
    for col in ("updated", "total", "pulses", "rest"):
        assert re.search(rf"table\.data-table \.c-{col} \{{ width: 1%; \}}", css), col                                         # 1%: no more than the name and the values need
    for col in ("printer", "name", "note", "acts"):
        assert re.search(rf"table\.data-table \.c-{col} \{{ width: ", css), col                                                # the texts have a share, the notes what is left, the icons their width
    assert "<colgroup>${COLS.map(([key]) => `<col class=\"c-${key}\">`).join('')}<col class=\"c-acts\"></colgroup>" in app
    left = re.findall(r"\['(\w+)', '\w+', 'l'\]", app[app.index("const COLS"):app.index("const head")])
    assert left == ["printer", "name", "note"]                                                                                # only these three to the left, the others centred
    assert "table.data-table th.l, table.data-table td.l { text-align: left; }" in css
    assert re.search(r"\.rc-cut \{[^}]*width: 0; min-width: 100%[^}]*text-overflow: ellipsis[^}]*white-space: nowrap", css)     # cut, and never widening its column
    assert 'class="rc-cut" title="${esc(text)}"' in app and app.count("${cut(") == 3                                          # whole under the mouse; printer, name and note


def test_the_names_of_closed_and_open_rows_have_one_fixed_width_so_that_the_pills_line_up():
    css = (STATIC / "css" / "style.css").read_text()
    assert re.search(r"\.rc-title \{ flex: none; width: 10rem;[^}]*text-overflow: ellipsis", css)                           # a longest name, cut
    assert re.search(r"details\.recipe > summary \.chip \{ flex: none; width: 8rem;[^}]*white-space: nowrap", css)          # and the pills as wide as the wider one, never wrapped
    assert '<strong class="rc-title" title="${esc(r.name)}">' in JS["app.js"]                                                 # the whole name under the mouse


def test_the_labels_of_an_open_row_are_muted_and_their_text_is_not():
    css = (STATIC / "css" / "style.css").read_text()
    assert re.search(r"\.rc-meta b \{[^}]*color: var\(--muted\)", css) and not re.search(r"\.rc-meta \{[^}]*color:", css)


def test_a_column_of_the_dosage_table_is_sorted_by_clicking_its_name_and_the_page_keeps_where_it_was():
    css, app, i18n = (STATIC / "css" / "style.css").read_text(), JS["app.js"], JS["i18n.js"]
    assert 'class="th-sort" data-sort="${key}"' in app and "aria-sort=" in app                                              # a real button, and the state said to the screen readers
    assert "nextSort(dosageSort.get(id), th.dataset.sort)" in app and "sortDosages(r.dosages, dosageSort.get(r.id), printerName)" in app
    assert "const dosageSort = new Map()" in app and ".focus()" in app[app.index("nextSort(dosageSort"):app.index("nextSort(dosageSort") + 600]     # per recipe; the keyboard stays on the column
    assert 'class="sort-i"' in app and "${SORT_ICON}</button>" in app                                                       # the sort icon is in every column's button, whether sorted or not
    assert i18n.count("s_sort_by:") == 2


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_sorting_the_dosages_by_a_column_ascending_descending_and_back_to_the_default_with_empty_values_always_last():
    got = node_exposure("""
      const d = (id, printer, updated, total, extra = {}) => ({ id, printer_id: printer, updated, total_s: total, pulses: 4, rest_s: 5, name: '', note: '', ...extra });
      const list = [d('a', 'p2', '2026-10-10T10:00:00Z', 40, { name: 'Zeta', note: 'b' }), d('b', 'p1', '2026-10-01T10:00:00Z', 90, { name: 'alfa', note: 'Z' }),
                    d('c', 'p1', '2026-10-12T10:00:00Z', 12.5), d('d', 'p2', '2026-10-12T10:00:00Z', 100, { name: 'Beta', note: 'a' }),
                    d('e', 'p1', '2026-10-12T09:00:00Z', 9, { name: 'Gamma', pulses: 10, rest_s: 0 })];       // e: the same day as c and d, but earlier
      const printers = { p1: 'Zebra', p2: 'Alpha' };
      const ids = (s, names = printers) => e.sortDosages(list, s, (id) => names[id]).map((x) => x.id).join('');
      const by = (key, dir) => ids({ key, dir });
      let s = null; const steps = [];
      for (let i = 0; i < 4; i++) { s = e.nextSort(s, 'name'); steps.push(s); }
      console.log(JSON.stringify({
        none: ids(null), unknown: by('nope', 'asc'), noNames: e.sortDosages(list, null).map((x) => x.id).join(''),
        printerAsc: by('printer', 'asc'), printerDesc: by('printer', 'desc'), numbers: ids(null, { p1: 'Printer 2', p2: 'Printer 10' }),
        nameAsc: by('name', 'asc'), nameDesc: by('name', 'desc'), updatedAsc: by('updated', 'asc'), updatedDesc: by('updated', 'desc'),
        totalAsc: by('total', 'asc'), totalDesc: by('total', 'desc'), pulsesDesc: by('pulses', 'desc'), restAsc: by('rest', 'asc'),
        noteAsc: by('note', 'asc'), noteDesc: by('note', 'desc'),
        other: e.nextSort({ key: 'name', dir: 'desc' }, 'total'), steps, same: list.map((x) => x.id).join('') }));""")
    # the default: by the printer as it is read (Alpha, then Zebra), then the last changed first (c, then e)
    assert got["none"] == "daceb" and got["unknown"] == "daceb" and got["printerAsc"] == "daceb"
    assert got["noNames"] == "cebda"                                                                                           # without names the ids are read: p1 before p2
    assert got["printerDesc"] == "cebda"                                                                                       # the ties keep the default order, they are not turned over
    assert got["numbers"] == "cebda"                                                                                           # "Printer 2" comes before "Printer 10" (numbers inside a text are numbers)
    assert got["nameAsc"] == "bdeac" and got["nameDesc"] == "aedbc"                                                            # case does not matter; the dosage without a name is last in both
    assert got["updatedAsc"] == "baedc" and got["updatedDesc"] == "dceab"                                                      # by the moment (the time of the day counts), not by the text of the date
    assert got["totalAsc"] == "ecabd" and got["totalDesc"] == "dbace"                                                          # numbers as numbers: 9 < 12.5 < 40 < 90 < 100
    assert got["pulsesDesc"] == "edacb" and got["restAsc"] == "edacb"
    assert got["noteAsc"] == "dabce" and got["noteDesc"] == "badce"                                                            # the empty notes are last in both
    assert got["other"] == {"key": "total", "dir": "asc"}                                                                      # another column starts ascending
    assert got["steps"] == [{"key": "name", "dir": "asc"}, {"key": "name", "dir": "desc"}, None, {"key": "name", "dir": "asc"}]   # ascending, descending, the default, again
    assert got["same"] == "abcde"                                                                                              # the list given is never changed


def test_the_names_of_the_columns_are_on_one_line_with_a_smaller_unit_and_the_sort_icon_always_at_the_right():
    css, app = (STATIC / "css" / "style.css").read_text(), JS["app.js"]
    assert re.search(r"table\.data-table th \.lbl \{[^}]*white-space: nowrap", css)                                            # one line, never in a pill
    assert not re.search(r"\.th-sort \{[^}]*(border: 1px|border-radius: 6px|background)", css)                               # a name is plain text, not a pill
    assert re.search(r"table\.data-table th \.u \{[^}]*font-size: 10px[^}]*text-transform: none", css)                       # the unit smaller than the name, and never in capitals: (s)
    assert re.search(r"table\.data-table th \.lbl \{[^}]*font-size: 11px[^}]*text-transform: uppercase", css)                 # the names in capitals, a little smaller than the title
    assert re.search(r"\.rc-dtitle \{[^}]*font-size: 12px", css)                                                            # (the title is 12px)
    assert re.search(r"\.th-sort \{[^}]*color: var\(--muted\)", css) and re.search(r"\.th-sort:hover[^{]*\{ color: var\(--text\); \}", css)   # muted at rest, normal under the mouse, as the icon
    assert "text-decoration" not in css[css.index(".th-sort"):css.index(".sort-i")]                                          # never underlined
    assert "splitUnit(t(label))" in app and '<span class="u">${esc(unit)}</span>' in app
    assert re.search(r"\.th-sort \{[^}]*grid-template-columns: minmax\(max-content, 1fr\) 10px", css)                        # the whole name, then the icon, at the right
    assert re.search(r"table\.data-table th:not\(\.l\) \.th-sort \{ grid-template-columns: 10px minmax\(max-content, 1fr\) 10px; \}", css) and "th:not(.l) .th-sort::before" in css   # a centred name: a spacer as wide as the icon at the left
    assert re.search(r"\.sort-i \{[^}]*width: 10px", css) and 'th[aria-sort="ascending"] .sort-i .up' in css and 'th[aria-sort="descending"] .sort-i .down' in css     # the sorted half is lit
    assert not re.search(r"display: none[^}]*sort-i|sort-i[^}]*display: none|sort-i[^}]*visibility: hidden", css)             # and the icon is never hidden


def test_in_the_header_the_columns_are_told_apart_by_a_gap_in_the_colour_of_what_is_behind_and_not_by_a_dashed_line():
    css = (STATIC / "css" / "style.css").read_text()
    assert re.search(r"table\.data-table thead th \+ th \{ border-left: 2px solid var\(--table-gap, var\(--panel-2\)\); \}", css)   # the gap: a recipe's background unless said otherwise
    assert re.search(r"details\.recipe \{[^}]*background: var\(--panel-2\)", css)                                             # ... which is the colour behind the dosages: the open recipe
    assert not re.search(r"table\.data-table th \+ th", css) and not re.search(r"thead[^{]*\{[^}]*dashed", css)               # the dashed lines are the body's only
    assert re.search(r"table\.data-table td \+ td \{[^}]*border-left: 1px dashed", css)


def test_the_total_column_is_called_total_and_a_value_says_its_unit_in_full_under_the_mouse():
    app, i18n = JS["app.js"], JS["i18n.js"]
    assert "['total', 's_col_total', '']" in app and "'ex_total'" not in app[app.index("const COLS"):app.index("const head")]
    assert "s_col_total: 'Totale (s)'" in i18n and "s_col_total: 'Total (s)'" in i18n                                         # without "time", in both languages
    for text in ("u_seconds_one: '1 secondo'", "u_seconds_many: '{n} secondi'", "u_flashes_one: '1 flash'", "u_flashes_many: '{n} flash'",
                 "u_seconds_one: '1 second'", "u_seconds_many: '{n} seconds'", "u_flashes_one: '1 flash'", "u_flashes_many: '{n} flashes'"):
        assert text in i18n, text
    for kind, value in (("u_seconds", "d.total_s"), ("u_flashes", "d.pulses"), ("u_seconds", "d.rest_s")):                 # total, flashes and rest; the date and the texts have their own tooltips
        assert f"quantity(t, '{kind}', {value}" in app, (kind, value)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_quantity_is_written_with_its_unit_in_the_singular_only_for_exactly_one():
    got = node_exposure("""
      const t = (key, v) => key + ':' + JSON.stringify(v), q = e.quantity;
      console.log(JSON.stringify([q(t, 'u_seconds', 1, '1'), q(t, 'u_seconds', 20, '20'), q(t, 'u_seconds', 0, '0'), q(t, 'u_seconds', 1.5, '1,5'), q(t, 'u_flashes', 4), q(t, 'u_flashes', 1)]));""")
    assert got == ['u_seconds_one:{"n":"1"}', 'u_seconds_many:{"n":"20"}', 'u_seconds_many:{"n":"0"}', 'u_seconds_many:{"n":"1,5"}', 'u_flashes_many:{"n":4}', 'u_flashes_one:{"n":1}']


def test_the_dosage_table_has_a_header_that_stands_out_from_rows_in_alternate_shades():
    css, app = (STATIC / "css" / "style.css").read_text(), JS["app.js"]
    assert "<thead><tr>${head(r)}<th></th></tr></thead><tbody>" in app and "</tbody></table>" in app                          # the header and the body are what they are, so that the shades can alternate
    head = re.search(r"table\.data-table thead th \{[^}]*background: color-mix\(in srgb, var\(--accent\) (\d+)%", css)
    zebra = re.search(r"table\.data-table tbody tr:nth-child\(even\) td \{[^}]*background: color-mix\(in srgb, var\(--text\) (\d+)%", css)
    assert head and zebra and int(head.group(1)) >= 3 * int(zebra.group(1))                                                   # the header's shade is far stronger than the rows'


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_column_name_is_split_from_its_unit_in_brackets():
    got = node_exposure("""
      const s = e.splitUnit;
      console.log(JSON.stringify([s('Tempo totale (s)'), s('Riposo (s)'), s('Flash'), s('Total time (s)'), s('Nome (facoltativo) (s)'), s('(s)'), s(''), s(undefined), s('A ( )')]));""")
    assert got[0] == {"label": "Tempo totale", "unit": "(s)"} and got[1] == {"label": "Riposo", "unit": "(s)"} and got[3] == {"label": "Total time", "unit": "(s)"}
    assert got[2] == {"label": "Flash", "unit": ""}                                                                            # no unit: the name is left whole
    assert got[4] == {"label": "Nome (facoltativo)", "unit": "(s)"}                                                              # only the last bracket is the unit
    assert got[5] == {"label": "(s)", "unit": ""} and got[6] == {"label": "", "unit": ""} and got[7] == {"label": "", "unit": ""}   # nothing left for a name: leave it
    assert got[8] == {"label": "A", "unit": "( )"}


def test_the_count_and_the_pill_are_told_apart_by_a_dashed_short_divider_unlike_the_solid_one_before_the_buttons():
    css = (STATIC / "css" / "style.css").read_text()
    count = re.search(r"\.rc-count \{([^}]*)\}", css).group(1)
    actions = re.search(r"details\.recipe \.rc-actions \{([^}]*)\}", css).group(1)
    assert re.search(r"border-right: 1px dashed", count) and "padding: 2px 10px 2px 0" in count                              # on the count's right: dashed, and only as tall as the text
    assert re.search(r"border-left: 1px solid", actions) and "dashed" not in actions                                         # the other one: solid, as tall as the buttons
    assert "details.recipe[open] > summary .rc-count, details.recipe[open] > summary .rc-brief { display: none; }" in css    # open, the count and with it its divider are gone


def test_the_recipes_of_settings_are_an_accordion_and_the_open_one_is_a_single_id():
    app = JS["app.js"]
    assert "let openRecipe = null;" in app and "openRecipes" not in app                                                      # no longer a set: one at most
    assert "${openRecipe === r.id ? 'open data-open' : ''}" in app                                                           # a redraw keeps it open (both marks), without animation
    toggle = app[app.index("function toggleRecipe(d)"):]
    toggle = toggle[:toggle.index("\n}\n")]
    assert "openRecipe = openAfterToggle(openRecipe, d.dataset.recipe, open)" in toggle
    assert "details.recipe[data-open]" in toggle and "setRecipeOpen(other, false)" in toggle and "other !== d" in toggle      # the others are closed, never the one that opened
    click = app[app.index("$('#tbl-recipes').addEventListener('click'"):]
    assert "const sum = e.target.closest('summary')" in click and "e.preventDefault(); toggleRecipe(sum.closest('details'))" in click   # the row is opened by this code, with its animation
    assert click.index("const b = e.target.closest('[data-act]')") < click.index("const sum = e.target.closest('summary')")  # (a button of the row is not a click on the row)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_opening_a_recipe_closes_the_other_and_the_late_report_of_the_one_that_closed_does_not_close_the_new_one():
    got = node_exposure("""
      const f = e.openAfterToggle;
      let cur = null; const seen = [];
      cur = f(cur, 'a', true); seen.push(cur);          // a opens
      cur = f(cur, 'b', true); seen.push(cur);          // b opens...
      cur = f(cur, 'a', false); seen.push(cur);         // ...and a's closing is reported after it: b stays
      cur = f(cur, 'b', false); seen.push(cur);         // b closed by the person
      cur = f(cur, 'a', false); seen.push(cur);         // a closed when nothing is open
      cur = f('c', 'c', true); seen.push(cur);
      console.log(JSON.stringify(seen));""")
    assert got == ["a", "b", "b", None, None, "c"]


def test_the_accordion_is_animated_in_javascript_because_firefox_cannot_do_it_in_css():
    css, app = (STATIC / "css" / "style.css").read_text(), JS["app.js"]
    assert "interpolate-size" not in css and "::details-content" not in css                                                  # (Firefox has the pseudo-element but no `interpolate-size`: the height jumped)
    fn = app[app.index("function setRecipeOpen(d, open)"):app.index("function toggleRecipe(d)")]
    assert "body.animate(heightFrames(from, to), { duration: RECIPE_MS, easing: 'ease', fill: 'forwards' })" in fn and "const RECIPE_MS = 280" in app
    assert "d._anim?.cancel(); d._anim = null;" in fn and "getBoundingClientRect().height" in fn                             # clicked in the middle: it goes on from where it is
    assert "if (open) d.open = true;" in fn and "if (!open) d.open = false;" in fn                                           # the content is there before it grows and gone after it has shrunk
    assert "d.toggleAttribute('data-open', open)" in fn and fn.index("d.toggleAttribute('data-open', open)") < fn.index("body.animate")   # what is seen changes at once
    assert "body.style.overflow = 'hidden'" in fn and "body.style.overflow = ''" in fn                                       # no scroll bar while it grows
    assert "matchMedia('(prefers-reduced-motion: reduce)')" in app and "if (reducedMotion() || from === to)" in fn            # no motion for those who do not want it
    assert "scrollIntoView({ block: 'nearest' })" in fn                                                                       # the open row is in view once it has grown
    assert re.search(r"details\.recipe > summary::before \{[^}]*transition: transform \.28s", css) and re.search(r"details\.recipe > summary \{[^}]*transition: border-radius \.28s", css)   # the arrow and the corners follow
    assert "details.recipe[data-open] > summary::before { transform: rotate(90deg); }" in css and "details.recipe[data-open] > summary { border-radius:" in css     # the arrow and the corners follow at once: `data-open`
    assert "details.recipe[open] > summary .rc-brief" in css and "details.recipe[open] > summary { box-shadow:" in css       # the short text stays away, and the line under the row stays, until the content has gone: the native `open`
    toggle = app[app.index("$('#tbl-recipes').addEventListener('toggle'"):]
    assert "d._anim || d.open === d.hasAttribute('data-open')" in toggle[:toggle.index("}, true);")]                          # the browser's own opening (find in page) is followed; ours is not taken twice


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_row_opening_or_closing_has_two_key_frames_with_the_height_and_a_fading_content():
    got = node_exposure("""
      const f = e.heightFrames;
      console.log(JSON.stringify([f(0, 200), f(200, 0), f(80, 200), f(150, 0), f(0, 0)]));""")
    assert got[0] == [{"height": "0px", "opacity": 0}, {"height": "200px", "opacity": 1}]                                    # opening: from nothing to everything
    assert got[1] == [{"height": "200px", "opacity": 1}, {"height": "0px", "opacity": 0}]                                    # closing
    assert got[2] == [{"height": "80px", "opacity": 0.4}, {"height": "200px", "opacity": 1}]                                 # taken over in the middle: it fades in from how much was there
    assert got[3] == [{"height": "150px", "opacity": 1}, {"height": "0px", "opacity": 0}]
    assert got[4] == [{"height": "0px", "opacity": 0}, {"height": "0px", "opacity": 0}]                                      # nothing to move: no division by zero


def test_a_row_that_is_closing_keeps_its_open_look_so_that_the_short_text_comes_back_only_when_it_is_closed():
    css, app = (STATIC / "css" / "style.css").read_text(), JS["app.js"]
    fn = app[app.index("function setRecipeOpen(d, open)"):app.index("function toggleRecipe(d)")]
    assert re.search(r"details\.recipe\[open\] > summary \.rc-count, details\.recipe\[open\] > summary \.rc-brief \{ display: none; \}", css)   # hidden as long as the content is there
    assert fn.rindex("if (!open) d.open = false;") > fn.index("anim.onfinish")                                                 # ... and `open` goes only when the animation has finished (the first one is when there is nothing to animate)
    assert "details.recipe[data-open] > summary .rc-brief" not in css                                                          # (never tied to the state that changes at once)


def test_a_line_under_the_row_of_an_open_recipe_takes_no_room_so_the_row_keeps_its_closed_size():
    css = (STATIC / "css" / "style.css").read_text()
    rule = re.search(r"details\.recipe\[open\] > summary \{([^}]*)\}", css).group(1)
    assert re.search(r"box-shadow: inset 0 -1px 0 ", rule) and "border" not in rule and "padding" not in rule                 # an inner shadow: no border, no padding, so no height more than when closed
    assert re.search(r"details\.recipe > summary \{[^}]*transition: [^;}]*box-shadow \.15s", css)                          # and it comes and goes softly


def test_the_printers_are_cards_with_a_picture_the_model_a_state_pill_and_the_plane_the_pixels_and_the_pitch():
    css, app, i18n, html = (STATIC / "css" / "style.css").read_text(), JS["app.js"], JS["i18n.js"], HTML
    assert '<div id="printer-cards"></div>' in html and "tbl-printers" not in html + app                                        # a place for the cards; the table is gone
    assert "$('#printer-cards').innerHTML = printerCards(state.printers, { t, fmt, esc });" in app and "const pcols" not in app   # drawn by printercards.js
    assert "import { printerCards, printerPicture } from './printercards.js';" in app
    assert not re.search(r"table\.data-table\.printers|\.c-model|\.c-plane|\.c-pixels|\.c-pitch|\.c-state|data-table \.w ", css)    # nothing of the table's styles is left
    for key, it, en in (("s_pr_model", "Modello", "Model"), ("s_pr_plane", "Piano", "Plane"), ("s_pr_pixels", "Pixel", "Pixels"), ("s_pr_pitch", "Passo", "Pitch")):
        assert f"{key}: '{it}'" in i18n and f"{key}: '{en}'" in i18n, key                                                      # the labels: first letter capital
    assert not any(k in i18n for k in ("s_col_model", "s_col_plane", "s_col_pixels", "s_col_pitch", "s_state:"))                 # the names of the table's columns went with the table (the dosage table keeps its own)
    assert re.search(r"\.printer-grid \{[^}]*--pc-w: 410px[^}]*grid-template-columns: repeat\(auto-fill, var\(--pc-w\)\)", css)   # every card as wide as the longest name needs
    assert re.search(r"\.printer-grid \{[^}]*justify-content: center; gap: 20px;", css)                                         # the cards as a group in the middle of the row (the same room at both sides), with a space between them
    assert re.search(r"\.printer-grid \{[^}]*margin: 12px 0;", css)                                                            # 12px under the title (as a recipe) and over the note
    assert re.search(r"\.printer-card \{[^}]*border-radius: var\(--rc-radius\)[^}]*background: var\(--panel-2\)", css)           # the curvature and the colour of a recipe
    notready = re.search(r"\.printer-card\.notready :is\(([^)]*)\) \{ opacity: \.5; \}[^\n]*\.printer-card\.notready \.pc-strip :is\(svg, img\) \{ filter: grayscale\(1\); \}", css)
    assert notready and notready.group(1) == ".pc-strip, .pc-k, .pc-name, .pc-v" and ".pc-state" not in notready.group(1)     # not ready: dimmed as if disabled (picture, labels, name and values), the pill keeps its colour
    assert not re.search(r"\.printer-card\.notready \{[^}]*border", css)                                                         # and no coloured border any more
    assert re.search(r"\.pc-k \{ font-size: 10\.5px;[^}]*color: var\(--muted\); \}", css) and "text-transform" not in re.search(r"\.pc-k \{[^}]*\}", css).group(0)   # labels: small, muted, not in capitals
    assert re.search(r"\.pc-meta \{[^}]*font-size: 12px", css) and re.search(r"\.pc-name \{[^}]*font-size: 16px; font-weight: 700", css)   # the facts at 12px, the name 16px bold
    strip = re.search(r"\.pc-strip \{([^}]*)\}", css).group(1)
    assert "background" not in strip and "border" not in strip                                                                   # the picture is on the card's own colour: no strip of another colour, no line
    assert re.search(r"\.pc-state \{[^}]*min-width: 34px", css)                                                                    # the pill as the StatusPill (`#st-warn`)
    assert "width: calc(var(--pc-img-w) + 2 * var(--pc-gap) - 1px);" in strip and "padding" not in strip                          # the same space (--pc-gap) from the edge of the card (its 1px border counts) to the picture and from the picture to the text; the strip takes only that width
    assert re.search(r"\.pc-main \{[^}]*padding: var\(--pc-pad-y\) 12px var\(--pc-pad-y\) 0;", css)                                # the text decides the height of the card: its own padding above and below
    card = re.search(r"\.printer-card \{([^}]*)\}", css).group(1)
    assert re.search(r"box-shadow: 0 1px 2px rgba\(0, 0, 0, \.5\), 0 6px 14px rgba\(0, 0, 0, \.4\)", card) and "inset" not in card.split("box-shadow")[1]   # raised: a shadow underneath, and no light line inside the top border (the border is one pixel)
    assert re.search(r"--pc-img-w: 55px; --pc-gap: 20px; --pc-pad-y: 16px; --pc-trim-top: 3px; --pc-trim-bottom: 4px;", css)
    picture = re.search(r"(?m)^\.pc-strip :is\(svg, img\) \{([^}]*)\}", css).group(1)
    assert "position: absolute" in picture and "object-fit: contain" in picture and "width: var(--pc-img-w)" in picture              # it takes no room of its own: the text decides the height of the card...
    assert "top: calc(var(--pc-pad-y) + var(--pc-trim-top))" in picture and "height: calc(100% - 2 * var(--pc-pad-y) - var(--pc-trim-top) - var(--pc-trim-bottom))" in picture   # ... and the picture goes from the top of the letters of «Modello» to the baseline of «Passo»   # the photo and the drawing in the same box
    assert "pp-mark" not in css and re.search(r"\.pp-hood \{[^}]*\}", css) and re.search(r"\.pp-base \{[^}]*\}", css)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_printer_card_says_model_state_plane_pixels_and_pitch_in_that_order_and_nothing_unescaped():
    got = node_json("""
      const c = await import(%r);
      const fmt = (n, d = 1) => Number(n).toLocaleString('it-IT', { minimumFractionDigits: d, maximumFractionDigits: d });
      const t = (k) => ({ s_pr_model: 'Modello', s_pr_plane: 'Piano', s_pr_pixels: 'Pixel', s_pr_pitch: 'Passo', s_ready: 'Pronta', s_notready: 'Non pronta' }[k] ?? k);
      const esc = (s) => String(s).replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
      const ok = { id: 'ld', name: 'Creality LD-002H', ready: true, picture: '/api/printers/ld/picture', plane: { width_mm: 130.56, height_mm: 82.62 }, grid: { width: 2560, height: 1620, pitch: 0.051 } };
      const bad = { id: 'x"y', name: '<b>Odd</b> & co', ready: false, picture: 'javascript:alert(1)', plane: { width_mm: 100, height_mm: 62.5 }, grid: { width: 1600, height: 1000, pitch: 0.0625 } };
      const far = { ...ok, id: 'far', picture: 'https://example.org/x.png' }, none = { ...ok, id: 'none', picture: null }, odd = { ...ok, id: 'odd', picture: '/api/printers/../x/picture' };
      const html = c.printerCards([ok, bad], { t, fmt, esc });
      const others = c.printerCards([far, none, odd], { t, fmt, esc });
      const text = (h) => h.replace(/<svg[\\s\\S]*?<\\/svg>/g, '').replace(/<[^>]+>/g, '|').replace(/\\|+/g, '|');
      console.log(JSON.stringify({ html, first: text(html.split('<li ')[1]), second: text(html.split('<li ')[2]), others, facts: c.printerFacts(ok, fmt) }));""" % (STATIC / "js" / "printercards.js").as_uri())
    assert got["facts"] == [["s_pr_plane", "130,56 × 82,62 mm"], ["s_pr_pixels", "2560 × 1620 px"], ["s_pr_pitch", "51 µm"]]                    # units in the values, the pitch in µm
    assert got["first"].startswith("class=\"printer-card\" data-printer=\"ld\">|Modello|Creality LD-002H|✓|Piano|130,56 × 82,62 mm|Pixel|2560 × 1620 px|Passo|51 µm|"), got["first"]
    assert got["html"].count('class="printer-card') == 2 and got["html"].count('class="printer-card notready"') == 1                         # a card per printer; the not ready one says so
    assert 'class="chip ok pc-state" role="img" title="Pronta" aria-label="Pronta">✓' in got["html"]                                           # the StatusPill's: tick, green
    assert 'class="chip bad pc-state" role="img" title="Non pronta" aria-label="Non pronta">⚠' in got["html"]                                  # warning sign, red
    assert "<b>" not in got["html"] and "&lt;b&gt;Odd&lt;/b&gt; &amp; co" in got["html"] and 'data-printer="x&quot;y"' in got["html"]         # a name or an id cannot break out of the markup
    first, second = got["html"].split("<li ")[1:]
    assert '<img class="pc-photo" src="/api/printers/ld/picture" alt="" decoding="async">' in first and "<svg" not in first                  # the printer that has a photo shows it (an empty alt: it is decoration, the name is beside it)
    assert "<svg" in second and "<img" not in second and "javascript:" not in second                                                           # one that has none, the drawing; and an address that is not the app's own is never put in a page
    assert got["others"].count("<svg") == 3 and "<img" not in got["others"] and "example.org" not in got["others"] and "../" not in got["others"]    # other addresses, none, a path with .. : the drawing
    assert second.count('aria-hidden="true"') == 1                                                                                           # the drawing is not read by a screen reader


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_plane_the_pixels_and_the_pitch_of_a_printer_are_written_apart_and_without_units_for_the_columns():
    got = node_exposure("""
      const fmt = (n, d = 1) => Number(n).toLocaleString('it-IT', { minimumFractionDigits: d, maximumFractionDigits: d });
      const p = { plane: { width_mm: 130.56, height_mm: 82.62 }, grid: { width: 2560, height: 1620, pitch: 0.051 } };
      console.log(JSON.stringify({ plane: m.planeSize(p, fmt), pixels: m.pixelSize(p), pitch: m.pitchValue(0.051, fmt), pitch2: m.pitchValue(0.0625, fmt), label: m.pitchLabel(0.051, fmt), size: m.printerSize(p, fmt) }));""")
    assert got == {"plane": "130,56 × 82,62", "pixels": "2560 × 1620", "pitch": "51", "pitch2": "62,5", "label": "51 µm", "size": "130,56 × 82,62 mm · 2560 × 1620 px"}   # the line of the pill is as it was


def test_the_printer_cards_start_as_far_under_their_title_as_the_first_recipe_does_under_its_own():
    css, html = (STATIC / "css" / "style.css").read_text(), (STATIC / "index.html").read_text()
    # under RECIPES: the title is centred in a row as tall as its plus button (26px) and the title is 18px high, so 4px; then the 8px margin of a recipe = 12px
    assert re.search(r"details\.recipe \{[^}]*margin: 8px 0", css)                                                           # the 8px of a recipe (the rest, 4px, is the title centred in the taller row of the plus button)
    assert re.search(r"\.printer-grid \{[^}]*margin: 12px 0;", css)                                                          # under PRINTERS: the same 12px
    assert '<section class="card"><h2 data-i18n="s_printers"></h2><div id="printer-cards"></div>' in html                      # (the cards follow the title with nothing between but this)


def test_the_stylesheet_has_as_many_closing_braces_as_opening_ones():
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "css" / "style.css").read_text(), flags=re.S)
    assert css.count("{") == css.count("}")                                                                                   # a stray one makes the browser drop the rule that follows it


def test_the_sign_of_a_resist_pill_is_drawn_and_its_text_is_centred_on_the_lowercase_letters():
    css = (STATIC / "css" / "style.css").read_text()
    assert re.search(r"\.chip\.pos::before, \.chip\.neg::before \{ content: \"\"; flex: none; width: 6px; height: 6px; \}", css)   # a box of whole pixels, centred by the flex row
    assert re.search(r"\.chip\.pos::before \{ background: linear-gradient\(currentColor, currentColor\) center / 100% 2px no-repeat, linear-gradient\(currentColor, currentColor\) center / 2px 100% no-repeat; \}", css)
    assert re.search(r"\.chip\.neg::before \{ background: linear-gradient\(currentColor, currentColor\) center / 100% 2px no-repeat; \}", css)
    assert "\\2212" not in re.sub(r"/\*.*?\*/", "", css, flags=re.S) and 'content: "+"' not in css                              # no font glyph: it sits on the font's own axis, below the middle of the pill
    block = css[css.index("@supports (text-box: trim-both ex alphabetic) {"):]
    block = block[:block.index("\n}\n") + 3]
    assert ".chip.pos > span, .chip.neg > span, .pol-switch .chip > span { text-box: trim-both ex alphabetic; }" in block   # the text is cut to the band of the lowercase letters
    assert ".chip.pos, .chip.neg, .pol-switch .chip { min-height: 24px; }" in block and ".picker .chip.pos, .picker .chip.neg { min-height: 20px; }" in block   # the height comes from an even minimum
    app = JS["app.js"]
    assert "const polChip = (polarity, title = '') =>" in app and "<span>${esc(t('pol_' + polarity))}</span></span>`;" in app   # the text of a pill is in a span of its own


def test_the_resist_by_hand_is_two_pills_with_a_switch_between_them_and_the_chosen_pill_takes_its_uv_look():
    html, css, app = (STATIC / "index.html").read_text(), (STATIC / "css" / "style.css").read_text(), JS["app.js"]
    group = html[html.index('<div class="pol-switch" id="manual-pol"'):html.index('<div class="callout info small" id="pol-hint"')]
    assert 'role="radiogroup"' in group and 'data-i18n-aria="resist"' in group                                               # a group of two choices, named for the screen readers
    assert group.index('class="chip pos"') < group.index('id="pol-toggle"') < group.index('class="chip neg"')                # pill, switch, pill: positive at the left
    assert re.findall(r'<input type="radio" name="polarity" value="(\w+)">', group) == ["positive", "negative"]             # the pills are the radios: arrows and screen readers
    assert 'tabindex="-1" aria-hidden="true"' in group and 'class="pol-track"' in group and 'class="switch"' not in group    # the switch is only graphic, and does not take the name of the settings' switch
    assert 'id="sel-polarity"' not in html and 'id="chip-polarity"' not in html                                              # the select is gone, and so is the pill under the recipe's information: the recipe's pill is in its menu
    assert re.search(r"\.pol-switch \.chip \{[^}]*color: var\(--muted\)[^}]*background: transparent[^}]*box-shadow: none", css)  # muted and flat at rest
    # the chosen pill looks as the UV-light view does: the positive white with a black ring of 2 px (border + 1 px inside) and a white line of 1 px outside, the negative the same with the colours swapped
    assert re.search(r"\.pol-switch \.chip\.pos:has\(input:checked\) \{ color: #000; border-color: #000; background: #fff; box-shadow: inset 0 0 0 1px #000, 0 0 0 1px #fff; \}", css)
    assert re.search(r"\.pol-switch \.chip\.neg:has\(input:checked\) \{ color: #fff; border-color: #fff; background: #000; box-shadow: inset 0 0 0 1px #fff, 0 0 0 1px #000; \}", css)
    # the pill of a recipe (in its menu and in the lists) has the same look, so a recipe's resist is read the same everywhere; no blue or violet is left on it
    assert re.search(r"\.chip\.pos \{ color: #000; border-color: #000; background: #fff; box-shadow: inset 0 0 0 1px #000, 0 0 0 1px #fff; \}", css)
    assert re.search(r"\.chip\.neg \{ color: #fff; border-color: #fff; background: #000; box-shadow: inset 0 0 0 1px #fff, 0 0 0 1px #000; \}", css)
    assert not re.search(r"\.chip\.(pos|neg)[^{]*\{[^}]*(--accent|--sec-expo)", css)
    assert re.search(r"\.pol-switch:has\(input\[value=\"negative\"\]:checked\) \.pol-track \.pol-knob \{[^}]*translateX\(16px\)[^}]*background: #000[^}]*inset 0 0 0 1px #fff", css)   # the knob goes right and is black with a white ring
    assert re.search(r"\.pol-switch:has\(\.chip\.pos\) \.pol-track \.pol-knob \{ background: #fff; \}", css)       # ... and is white on the left (only for the resist: the mirror's keeps the accent)
    assert re.search(r"\.pol-track \.pol-knob \{[^}]*background: var\(--accent\)", css)
    assert re.search(r"\.pol-switch \.chip:has\(input:focus-visible\) \{ outline: 2px solid var\(--accent\)", css)         # the keyboard focus is seen on the pill
    assert re.search(r"\.pol-switch \.chip input \{[^}]*opacity: 0", css) and "display: none" not in re.search(r"\.pol-switch \.chip input \{[^}]*\}", css).group(0)   # hidden, but focusable
    fn = app[app.index("function setManualPolarity(value)"):app.index("$('#pol-toggle').onclick")]
    assert "if (recipe() || state.polarity === value) return;" in fn                                                         # a recipe's polarity is the recipe's; nothing to do when it is the same
    assert "state.polarity = value; renderExposure(); plane.invalidate(); plane.draw(); updateDirty();" in fn              # as the select did
    assert "radio.onchange = (e) => setManualPolarity(e.target.value)" in app and "setManualPolarity(state.polarity === 'positive' ? 'negative' : 'positive')" in app
    render = app[app.index("$('#pol-row').hidden = !!r;"):app.index("if (lib && r) {", app.index("$('#pol-row').hidden = !!r;"))]
    assert "$('#pol-row').hidden = !!r;" in render and "radio.checked = radio.value === state.polarity" in render   # by hand: the row of the switch; with a recipe: its pill, in the recipe's menu


def test_the_yellow_pill_is_only_the_version_again_and_the_flags_are_in_the_side_status_bar():
    html, css = (STATIC / "index.html").read_text(), (STATIC / "css" / "style.css").read_text()
    brand = html[html.index('<div class="brand">'):html.index('<nav class="tabs"')]
    assert '<span class="badge mock" data-i18n="alpha_badge"></span></div>' in brand and "flags" not in brand and "badge-mode" not in html      # the pill says what it said
    assert "badge-flags" not in css and "badge-flags" not in html and ".brand .badge > " not in css                                    # nothing left of the flags in it
    assert "@media (max-width: 1300px)" not in css                                                                                      # (the tighter tabs were only for the flags)
    assert re.search(r"\.brand \.badge \{ min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; \}", css)       # it gives way first when the bar is short of room


def test_the_side_status_bar_is_at_the_bottom_of_the_side_panel_whichever_section_is_in_it():
    html, css, app, i18n = (STATIC / "index.html").read_text(), (STATIC / "css" / "style.css").read_text(), JS["app.js"], JS["i18n.js"]
    panels = html[html.index('<div class="panels">'):html.index('<div class="splitter"')]
    scroll = panels[panels.index('<div class="panels-scroll">'):panels.index('<footer class="side-statusbar"')]
    assert scroll.count("<section ") == 3 and scroll.rstrip().endswith("</div>")                                                         # the three sections scroll together, in their own part
    assert panels.count('<footer class="side-statusbar" id="side-status" role="status">') == 1 and panels.index("<footer") > panels.index("</section>", panels.rindex("<section "))   # the bar after the last section, outside all of them: always there
    assert '<span class="ssb-label" data-i18n="ssb_start"></span><span class="ssb-flags" id="ssb-flags"></span>' in panels
    assert re.search(r"\.panels \{[^}]*display: flex; flex-direction: column; overflow: hidden", css)                                    # the SidePanel: the sections above, the bar below
    assert re.search(r"\.panels-scroll \{ flex: 1 1 auto; min-height: 0; overflow-y: auto;", css)                                       # only the sections scroll
    bar = re.search(r"\.side-statusbar \{([^}]*)\}", css).group(1)
    status = re.search(r"\.statusbar \{([^}]*)\}", css).group(1)
    assert "flex: none" in bar and "min-height: 40px" in bar and "min-height: 40px" in status                                              # as tall as the StatusBar: they make one line
    assert "display: flex; flex-direction: column" in bar and "font-size: 10.5px" in bar                                                 # two lines (the words, then the flags) in a small font
    assert re.search(r"\.ssb-flags \{[^}]*font-size: 10px", css) and re.search(r"\.ssb-label \{[^}]*color: var\(--muted\)", css)         # the flags a little smaller still; the words muted
    assert "ssb_start: 'App avviata con flags:'" in i18n and "ssb_start: 'App started with flags:'" in i18n                               # the words of the first line, in both languages
    assert "ssb_start_plain: 'nessuno'" in i18n and "ssb_start_plain: 'none'" in i18n                                                     # and what stands for no flags on the second
    assert "border-top: 1px solid var(--border)" in bar and "border-top: 1px solid var(--border)" in status and "padding: 4px 12px" in bar and "padding: 4px 12px" in status
    assert re.search(r"\.ssb-flags \{[^}]*monospace", css) and re.search(r"\.ssb-flags\.plain \{[^}]*color: var\(--muted\)", css)         # the flags in monospace; "no options" in words, muted
    fn = app[app.index("function renderSideStatus()"):app.index("function renderPrinter()")]
    assert "state.info?.flags ?? []" in fn and "flagsText(flags)" in fn and "flagsTitle(flags, t, has)" in fn and "t('ssb_start_plain')" in fn and "t('flags_none_title')" in fn
    assert "renderSideStatus();" in app[app.index("function applyLang(l)"):app.index("function renderKeys()")]                          # in the language of the page
    assert "renderSideStatus();" in app[app.index("state.info = await api.getInfo();"):app.index("await loadLibrary();")]                   # as soon as the page knows
    for key in ("flags_title", "flags_none_title", "flag_no_library", "flag_dev_printers", "flag_dev_samples", "ssb_start", "ssb_start_plain"):
        assert i18n.count(f"{key}:") == 2, key


def test_the_tab_menu_stays_at_the_left_after_the_pill_with_more_room_that_grows_with_the_window():
    html, css = (STATIC / "index.html").read_text(), (STATIC / "css" / "style.css").read_text()
    bar = html[html.index('<header class="menubar">'):html.index("</header>")]
    assert bar.index('class="brand"') < bar.index('<nav class="tabs"') < bar.index('</nav>') < bar.index('<div class="spacer"></div>') < bar.index('id="project-name"')   # the sections right after the name and the pill; the room after them
    assert bar.count('<div class="spacer"></div>') == 1                                                                       # (not one before them too: they are not pushed to the right)
    rule = re.search(r"^\.tabs \{([^}]*)\}", css, re.M).group(1)
    assert "margin: 0 0 0 clamp(18px, calc(18px + (100vw - 1280px) * .4), 38px)" in rule                                      # 18px at the narrowest the page goes, 38px from 1330px up (and 14px of gap besides)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_flags_are_written_one_after_the_other_and_explained_in_the_language_of_the_page():
    got = node_exposure("""
      const texts = { flags_title: 'Started with: {list}.', flag_no_library: '--no-library: no library', flag_dev_printers: '--dev-printers: made-up printers' };
      const t = (k, v = {}) => (texts[k] ?? k).replace(/\\{(\\w+)\\}/g, (_, n) => v[n] ?? ''), has = (k) => k in texts;
      console.log(JSON.stringify({ none: m.flagsText([]), missing: m.flagsText(undefined), flags: m.flagsText(['--no-library', '--dev-printers']),
        noTitle: m.flagsTitle([], t, has), noTitle2: m.flagsTitle(undefined, t, has), title: m.flagsTitle(['--no-library', '--dev-printers'], t, has),
        unknown: m.flagsTitle(['--no-library', '--new-thing'], t, has) }));""")
    assert got["none"] == "" and got["missing"] == "" and got["flags"] == "--no-library --dev-printers"                          # nothing to say: nothing is written
    assert got["noTitle"] == "" and got["noTitle2"] == ""
    assert got["title"] == "Started with: --no-library: no library · --dev-printers: made-up printers."                          # what each one means, separated
    assert got["unknown"] == "Started with: --no-library: no library · --new-thing."                                            # a flag of a newer server is written as it is


def test_a_divider_separates_the_file_menu_from_the_language_selector_as_the_one_after_the_project_name():
    html, css = (STATIC / "index.html").read_text(), (STATIC / "css" / "style.css").read_text()
    bar = html[html.index('<header class="menubar">'):html.index("</header>")]
    assert bar.index('class="menu"') < bar.index('<span class="mb-divider" aria-hidden="true"></span>') < bar.index('id="lang-btn"')       # FileMenu, divider, LanguageSelector
    assert bar.count('class="mb-divider"') == 1 and bar.index('id="project-name"') < bar.index('class="menu"')                          # (one only; the one after the ProjectName is that element's own border)
    divider = re.search(r"\.mb-divider \{([^}]*)\}", css).group(1)
    assert "width: 1px" in divider and "height: 18px" in divider and "background: var(--border)" in divider and "align-self: center" in divider and "margin: 0 4px" in divider
    project = re.search(r"^\.projname \{([^}]*)\}", css, re.M).group(1)
    assert "border-right: 1px solid var(--border)" in project and "margin-right: 4px" in project                                         # the same colour and the same 4px of margin: the two lines match


def test_the_project_name_is_edited_with_a_double_click_and_is_what_the_downloaded_file_is_called():
    html, css, app, i18n = (STATIC / "index.html").read_text(), (STATIC / "css" / "style.css").read_text(), JS["app.js"], JS["i18n.js"]
    assert '<span class="projname" id="project-name" tabindex="0"></span>' in html                                                      # it takes the keyboard focus: Enter or F2 edit it too
    assert "$('#project-name').addEventListener('dblclick', editProjectName);" in app
    assert "(e.key === 'Enter' || e.key === 'F2')" in app and "e.target === e.currentTarget" in app                                      # (on the name itself, not on the field that replaces it)
    edit = app[app.index("function editProjectName()"):app.index("$('#project-name').addEventListener('dblclick'")]
    assert "input.maxLength = 200" in edit and "input.value = state.name" in edit and "input.placeholder = t('project_untitled')" in edit  # the name it has (empty: the placeholder says "New Project"), 200 characters at most
    assert "if (e.key === 'Enter') { e.preventDefault(); finish(true, true); }" in edit                                                  # Enter keeps the new name and the focus stays on the name
    assert "e.stopPropagation(); finish(false, true);" in edit and "input.onblur = () => finish(true, false);" in edit                   # Esc keeps the old one; leaving the field keeps the new one and does not take the focus
    assert "if (done) return; done = true;" in edit                                                                                     # the field going away does not finish it twice
    render = app[app.index("function renderProjectName()"):app.index("function setProjectName(raw)")]
    assert "if (el.querySelector('input')) return;" in render                                                                           # a redraw does not take the field away while it is typed in
    setter = app[app.index("function setProjectName(raw)"):app.index("function editProjectName()")]
    assert "cleanProjectName(raw)" in setter and "if (name === state.name) return;" in setter and "updateDirty();" in setter            # cleaned; nothing to do when it is the same; the project is unsaved
    assert "state.recipeId, state.dosageId, state.name]);" in app                                                                       # the name is part of what Save keeps: changing it is a change
    assert "name: projectName()" in app and "(state.name || state.boards[0]?.name || 'progetto')" in app                                # the file is named after it (the first board's name is only for a project with no name)
    download = app[app.index("async function downloadProject()"):app.index("const confirmDiscard")]
    assert "if (!state.name) {" in download and "state.name = projectStem(filename)" in download                                         # the name of the file is taken only when the project had none: a name that was typed is never replaced by its safe form
    assert "if (!was) state.saved = fingerprint();" in download                                                                         # ... and that is not a change to save
    assert "state.name = cleanProjectName(r.name || '') || projectStem(fileName) || ''" in app                                          # opened: the project's own name first, the file's second
    assert "state.name = entry.name || ''; state.saved = fingerprint();" in app                                                         # a restored copy is as saved as it was
    assert re.search(r"\.projname-input \{[^}]*border: 1px solid var\(--accent\)", css) and re.search(r"\.projname \{ cursor: text;", css)
    for key in ("project_rename_hint", "project_name_label"):
        assert i18n.count(f"{key}:") == 2, key


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_typed_project_name_loses_its_control_characters_its_extension_and_its_blanks_and_stops_at_200():
    got = node_exposure("""
      const c = m.cleanProjectName;
      console.log(JSON.stringify([c('  Scheda LED v2  '), c('Scheda\\n\\tLED'), c('progetto.gslp'), c('PROGETTO.GsLp'), c(''), c(undefined), c(null), c('   '), c('x'.repeat(300)).length, c(' ' + 'y'.repeat(199) + ' z'),
        c('Città è così'), c('a.gslp.b')]));""")
    assert got[0] == "Scheda LED v2" and got[1] == "Scheda LED"                                                                         # blanks at the edges go; a control character becomes one space
    assert got[2] == "progetto" and got[3] == "PROGETTO"                                                                                # a project is not called "x.gslp": the extension is the file's
    assert got[4] == "" and got[5] == "" and got[6] == "" and got[7] == ""                                                              # nothing: no name (the placeholder says "New Project")
    assert got[8] == 200 and len(got[9]) == 199 and not got[9].endswith(" ")                                                           # at most 200; a cut that ends in a blank loses it (199 here)
    assert got[10] == "Città è così" and got[11] == "a.gslp.b"                                                                    # accents and spaces are kept in the name (only the file's name is made safe by the server)


def test_grid_and_snap_are_toggle_buttons_with_only_an_icon_at_the_right_of_the_status_bar_apart_from_the_zoom_ones():
    html, css, app = (STATIC / "index.html").read_text(), (STATIC / "css" / "style.css").read_text(), JS["app.js"]
    bar = section('<footer class="statusbar">', "</footer>")                                                                            # (the first </footer> in the page is the SideStatusBar's)
    assert "chk-grid" not in html and "chk-snap" not in html and 'type="checkbox"' not in bar and "sb-center" not in bar               # no checkboxes any more
    right = bar[bar.index('<div class="sb-right">'):]
    assert right.count('class="sb-divider"') == 2                                                                                           # a divider before Grid and Snap, and one between them and the zoom buttons
    first, second = right.index('class="sb-divider"'), right.rindex('class="sb-divider"')
    order = [right.index('id="st-busy"'), first, right.index('id="btn-grid"'), right.index('id="btn-snap"'), second, right.index('id="btn-zoom-out"'), right.index('id="btn-zoom-in"'), right.index('id="btn-fit"'), right.index('id="st-zoom"')]
    assert order == sorted(order) and first != second                                                                                       # (text) | Grid, Snap | − + Fit, zoom
    for ident, key in (("btn-grid", "grid"), ("btn-snap", "snap")):
        button = re.search(rf'<button class="btn sm icon" id="{ident}"[^>]*>.*?</button>', right, re.S).group(0)
        assert 'aria-pressed="true"' in button and f'data-i18n-title="{key}"' in button and f'data-i18n-aria="{key}"' in button       # pressed at the start; the name in the title and the label
        assert "<svg" in button and re.sub(r"<svg.*?</svg>", "", button, flags=re.S).count("data-i18n=") == 0                         # only an icon: no text in it
    assert right.count('<span class="sb-divider" aria-hidden="true"></span>') == 2
    assert re.search(r"\.statusbar \{[^}]*grid-template-columns: 1fr auto;", css)                                                      # the text on the left takes all the room that is left
    pressed = re.search(r'\.btn\[aria-pressed="true"\] \{([^}]*)\}', css).group(1)
    assert "border-color: var(--accent)" in pressed and "color:" not in pressed.replace("border-color:", "").replace("background:", "")      # a pressed button looks pressed by its fill and its border, never by the colour of its icon
    assert int(re.search(r"background: color-mix\(in srgb, var\(--accent\) (\d+)%", pressed).group(1)) >= 45                                # and the fill is well contrasted with the one of a button that is not pressed
    assert "#btn-grid, #btn-snap { color: #fff; }" in css and "accent-h" not in re.search(r"#btn-grid, #btn-snap \{[^}]*\}", css).group(0)  # the icons are white, pressed or not
    assert re.search(r"\.statusbar \.grp \.btn\.icon \{ width: 30px; height: 28px;", css)                                           # the five buttons are the same square
    assert re.search(r"\.sb-divider \{[^}]*width: 1px; height: 18px", css) and ".chk {" not in css and ".sb-center" not in css
    assert "19px" not in css[css.index(".statusbar .grp .btn.icon {"):css.index(".sb-divider")] and re.search(r"^svg\.i \{ width: 16px; height: 16px;", css, re.M)   # the symbols of the five buttons are the 16px of every icon, with no size of their own
    for ident, key, path in (("btn-zoom-out", "zoom_out", 'd="M4 12h16"'), ("btn-zoom-in", "zoom_in", 'd="M4 12h16M12 4v16"')):
        zoom = re.search(rf'id="{ident}".*?</button>', right, re.S).group(0)
        assert f'data-i18n-title="{key}" data-i18n-aria="{key}"' in zoom and path in zoom and "<svg" in zoom                                 # − and + are drawings, not characters of a font; the name is in the title and the label
        assert re.sub(r"<svg.*?</svg>", "", zoom, flags=re.S).count("−") == 0 and "aria-label=" not in zoom
    fit = re.search(r'id="btn-fit".*?</button>', right, re.S).group(0)
    assert 'd="M4 9V5h4M20 9V5h-4M4 15v4h4M20 15v4h-4"' in fit                                                                         # (Fit is drawn on the same 4-20 square)
    snap = re.search(r'id="btn-snap".*?</button>', right, re.S).group(0)
    assert 'd="M5 19v-7a7 7 0 0 1 14 0v7h-4v-7a3 3 0 0 0-6 0v7z"' in snap                                                              # the magnet is an arch with its legs down, not a U
    assert 'd="M5 16h4v3H5zM15 16h4v3h-4z" fill="#fff"' in snap                                                                         # and the ends of its legs are solid white, short (3 units of the 24: they were 5)
    assert "$('#btn-grid').onclick = () => { state.grid = !state.grid; renderToggles(); plane.draw(); };" in app
    assert "$('#btn-snap').onclick = () => { state.snap = !state.snap; renderToggles(); };" in app
    assert "$('#btn-grid').setAttribute('aria-pressed', String(state.grid))" in app and "$('#btn-snap').setAttribute('aria-pressed', String(state.snap))" in app   # the state says it, aria-pressed shows it
    assert "if (k === 'g' || k === 'G') { state.grid = !state.grid; renderToggles(); plane.draw(); return; }" in app                         # the G key too
    assert "renderToggles(); setSection(" in app                                                                                         # the first look comes from the state


def test_the_cursor_in_the_status_bar_is_mm_then_px_both_as_x_y_between_brackets_with_a_dot_between_them():
    app = JS["app.js"]
    fn = app[app.index("  onCursor(c) {"):app.index("\n  }", app.index("  onCursor(c) {"))]
    assert "$('#st-cursor').textContent = cursorText(c, state.plane, fmt);" in fn and "· px" not in fn and "x ${fmt" not in fn            # one function says it, in one way
    assert "'—'" in fn                                                                                                                  # (and a dash when the cursor is off the plane)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_cursor_text_has_the_same_form_for_mm_and_px_and_the_pixels_count_from_the_top_left_inside_the_grid():
    got = node_exposure("""
      const it = (n, d = 1) => Number(n).toLocaleString('it-IT', { minimumFractionDigits: d, maximumFractionDigits: d });
      const en = (n, d = 1) => Number(n).toLocaleString('en-GB', { minimumFractionDigits: d, maximumFractionDigits: d });
      const ld = { w: 130.56, h: 82.62, px: [2560, 1620], pitch: 0.051 }, small = { w: 96, h: 64, px: [1200, 800], pitch: 0.08 };
      const c = m.cursorText;
      console.log(JSON.stringify({ it: c([28.36, 51.6], ld, it), en: c([28.36, 51.6], ld, en), origin: c([0, 0], ld, it), far: c([130.56, 82.62], ld, it), outside: c([200, -5], ld, it),
        small: c([10.04, 10.04], small, it), topLeft: c([0, 82.62], ld, it) }));""")
    assert got["it"] == "mm(28,36; 51,60) · px(556; 608)"                                                                              # x and y in mm, then column and row, in the same form; the decimals are the page's language's
    assert got["en"] == "mm(28.36; 51.60) · px(556; 608)"
    assert got["origin"] == "mm(0,00; 0,00) · px(0; 1619)"                                                                              # bottom-left: column 0, the last row (the pixels count from the top)
    assert got["topLeft"] == "mm(0,00; 82,62) · px(0; 0)"                                                                               # top-left: pixel (0; 0)
    assert got["far"] == "mm(130,56; 82,62) · px(2559; 0)"                                                                              # the far edge is the last column, never one beyond the grid
    assert got["outside"] == "mm(200,00; -5,00) · px(2559; 1619)"                                                                       # (nothing is drawn outside; the pixels still stay inside the grid)
    assert got["small"] == "mm(10,04; 10,04) · px(125; 674)"                                                                            # another printer: its own pitch and grid, the same direction


def test_a_mirrored_board_is_said_in_a_word_in_the_status_bar_and_not_with_a_symbol():
    app, i18n = JS["app.js"], JS["i18n.js"]
    assert "⇋" not in app and "⇋" not in JS["model.js"]                                                                                 # the symbol that nobody could read is gone
    assert "$('#st-sel').textContent = b ? selectionText(b, fmt, t) : t('no_selection');" in app
    assert "st_mirrored: 'specchiata'" in i18n and "st_mirrored: 'mirrored'" in i18n


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_selection_text_gives_name_size_rotation_and_the_word_mirrored_only_when_it_is():
    got = node_exposure("""
      const fmt = (n, d = 1) => Number(n).toLocaleString('it-IT', { minimumFractionDigits: d, maximumFractionDigits: d });
      const t = (k) => ({ st_mirrored: 'specchiata' }[k] ?? k);
      const b = { name: 'x.zip', w: 30, h: 30, angle: 0, mirror: false, layers: [] };
      console.log(JSON.stringify({ plain: m.selectionText(b, fmt, t), mirrored: m.selectionText({ ...b, mirror: true }, fmt, t), turned: m.selectionText({ ...b, angle: -90, mirror: true }, fmt, t), full: m.selectionText({ ...b, angle: 450 }, fmt, t) }));""")
    assert got["plain"].endswith("30,0 × 30,0 mm · 0°") and "specchiata" not in got["plain"]                                          # not mirrored: nothing added
    assert got["mirrored"].endswith("30,0 × 30,0 mm · 0° · specchiata")                                                              # mirrored: the word, with the same dot as the others
    assert got["turned"].endswith("· 270° · specchiata") and got["full"].endswith("· 90°")                                            # the angle is always between 0 and 359


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_turning_counterclockwise_adds_to_the_angle_and_that_is_counterclockwise_on_the_plane():
    got = node_exposure("""
      const b = { x: 0, y: 0, angle: 0, mirror: false };
      const after = (delta) => { const t = { ...b, angle: (b.angle + delta + 360) % 360 }; return m.localToWorld(t, 1, 0).map((v) => Math.round(v * 1e9) / 1e9 + 0); };
      console.log(JSON.stringify({ turn: m.TURN, ccw: after(m.TURN.ccw), cw: after(m.TURN.cw) }));""")
    assert got["turn"] == {"ccw": 90, "cw": -90}                                                                                         # counterclockwise adds, clockwise takes away
    assert got["ccw"] == [0, 1]                                                                                                          # a point on the right of the board (1, 0) goes UP (the plane's y is up): counterclockwise
    assert got["cw"] == [0, -1]                                                                                                          # clockwise: it goes down


def test_each_way_of_turning_a_board_uses_its_own_sign_in_the_buttons_and_in_the_keys():
    app, html, i18n = JS["app.js"], (STATIC / "index.html").read_text(), JS["i18n.js"]
    assert "$('#btn-rot-ccw').onclick = () => { const b = selected(); if (b) rotate(b, TURN.ccw); };" in app                               # the button that says counterclockwise turns counterclockwise
    assert "$('#btn-rot-cw').onclick = () => { const b = selected(); if (b) rotate(b, TURN.cw); };" in app
    assert "if (k === 'r') rotate(b, TURN.ccw); else if (k === 'R') rotate(b, TURN.cw);" in app                                          # R counterclockwise, Shift+R clockwise (what the help says)
    assert not re.search(r"rotate\(b, -?90\)", app)                                                                                      # no bare number to get wrong again
    assert "['R · Shift+R', 'k_rot']" in app and "k_rot: 'Ruota di 90° (antiorario · orario)'" in i18n and "k_rot: 'Rotate 90° (counterclockwise · clockwise)'" in i18n
    assert "rot_ccw: 'Ruota di 90° in senso antiorario'" in i18n and "rot_cw: 'Ruota di 90° in senso orario'" in i18n
    assert 'id="btn-rot-ccw" data-i18n-title="rot_ccw"' in html and 'id="btn-rot-cw" data-i18n-title="rot_cw"' in html                 # (each button keeps its own tooltip)


def test_the_new_recipe_dialog_has_the_name_on_its_own_row_the_resist_switch_and_a_frame_called_info():
    dlg = section('<dialog id="dlg-recipe"', '</dialog>')
    name_row, rest = dlg.split('<label class="field rc-name-field">')[1].split('</label>', 1)
    assert 'id="rc-name"' in name_row and 'grid2' not in dlg                                                              # the name is alone on its row: the whole width, no two-column grid
    switch = dlg[dlg.index('<div class="pol-switch" id="rc-pol"'):dlg.index('<fieldset')]
    assert 'role="radiogroup"' in switch and switch.count('type="radio" name="rc-polarity"') == 2 and 'name="polarity"' not in dlg   # the same switch as the resist by hand, with radios of its own (the panel's are `polarity`)
    assert 'id="rc-pol-toggle"' in switch and 'tabindex="-1" aria-hidden="true"' in switch and 'class="chip pos"' in switch and 'class="chip neg"' in switch and "<select" not in dlg
    frame = dlg[dlg.index('<fieldset'):dlg.index('</fieldset>')]
    assert 'class="frame rc-infos"' in frame and '<legend data-i18n="ex_infos">' in frame                                   # a frame with its title
    assert all(f'id="{i}"' in frame for i in ("rc-resist", "rc-dev", "rc-notes")) and 'id="rc-name"' not in frame and 'rc-pol' not in frame   # the three text boxes inside; the name and the polarity outside
    css = (STATIC / "css" / "style.css").read_text()
    assert re.search(r"\.frame \{[^}]*border: 1px solid var\(--border\)[^}]*border-radius", css) and re.search(r"\.pol-switch\.locked \{ opacity", css)
    assert re.search(r"\.frame \{[^}]*margin: 22px 0 0", css) and re.search(r"\.frame > legend \{[^}]*margin-inline: auto", css)   # room above the frame (it is not stuck to the pills) and its title centred
    assert '<textarea id="rc-notes" rows="2"' in frame and re.search(r"#rc-notes \{ min-height: calc\(2lh \+ 14px\); \}", css)      # the notes start at two lines, and two lines (with padding and border) is also the least it can be resized to
    app = JS["app.js"]
    assert "$('#rc-pol').value" not in app and app.count("recipePolarity()") == 3                                           # the polarity is read from the switch (new, duplicate and the toggle)
    assert "setRecipePolarity(r ? r.polarity : 'positive'); setRecipePolarityLocked(mode === 'edit');" in app             # editing shows it but does not let it change
    assert "$('.rc-infos').disabled = mode === 'dup';" in app                                                                # a copy keeps the text of the original
    i18n = JS["i18n.js"]
    assert i18n.count("ex_infos: 'Info'") == 2                                                                                # in both languages


def test_in_the_exposure_panel_without_library_the_note_is_the_colour_of_the_warning_pill_with_room_below_and_the_resist_hint_is_an_info_frame_with_an_icon():
    css, html = (STATIC / "css" / "style.css").read_text(), HTML
    assert '<div id="nolib-note" class="callout warn small" hidden data-i18n="ex_nolib"></div>' in html                          # the note of the mode without library: the warning variant
    assert re.search(r"\.callout\.warn \{ border-color: var\(--warn\); \}", css) and re.search(r"\.chip\.warn \{[^}]*border-color: var\(--warn\)", css)   # the same colour as the warning pill
    assert re.search(r"#pol-hint \{ margin-bottom: 18px; \}", css)                                                               # room between the info frame and the values
    assert re.search(r"#sec-expo \{ display: flex; flex-direction: column; min-height: 100%; padding-bottom: 0; \}", css)         # the panel fills the height of its section...
    assert re.search(r"#sec-expo > \.expo-body \{ flex: none; margin-bottom: 18px; \}", css) and re.search(r"#nolib-note \{ margin: auto 0 0; \}", css)   # ... and the note takes the room left: at the very bottom, at least 18px under the rest
    expo = html[html.index('<section class="panel sec-expo"'):html.index("</section>", html.index('<section class="panel sec-expo"'))]
    assert expo.rstrip().endswith('<div id="nolib-note" class="callout warn small" hidden data-i18n="ex_nolib"></div>') and expo.count("nolib-note") == 1   # the note of the mode without library is the last thing of the section...
    assert expo.index('<div class="expo-body">') < expo.index('id="recipe-block"') and expo.index("</div>\n      <div id=\"nolib-note\"") > expo.index('id="gen-result"')   # ... after the body of the panel, which is one block (so that the margins inside it work as they did)
    hint = html[html.index('<div class="callout info small" id="pol-hint"'):]
    hint = hint[:hint.index("</div>") + 6]
    assert 'hidden' not in hint.split(">")[0] and '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/>' in hint   # a frame of the info kind, with an icon (a circle with an i), always there
    assert '<p data-i18n="resist_hint"></p>' in hint and "<p class" not in html[html.index('id="pol-hint"'):html.index('id="dosage-block"')]
    info = re.search(r"\.callout\.info \{([^}]*)\}", css).group(1)
    assert "display: flex" in info and "var(--accent)" in info and "color-mix" in info                                             # the accent's blue, the icon beside the text
    assert re.search(r"\.callout\.info > svg\.i \{[^}]*color: var\(--accent-h\)", css) and re.search(r"\.callout\.info > p \{[^}]*margin: 0;", css)
    assert "$('#pol-hint').hidden" not in JS["app.js"] and "$('#pol-row').hidden = !!r;" in JS["app.js"]                         # the frame is shown with a recipe too (it says what the polarity does, not what the switch does); only the switch is by hand


def test_the_three_values_of_an_exposure_are_small_cards_with_minus_and_plus_beside_the_icon_and_the_unit_after_the_number():
    css, html, app, i18n = (STATIC / "css" / "style.css").read_text(), HTML, JS["app.js"], JS["i18n.js"]
    block = html[html.index('<div id="values" class="values">'):html.index('<p class="small flash-note"')]
    cards = re.findall(r'<label class="vcard" for="(in-\w+)" data-i18n-title="(\w+)">(.*?)</label>', block, re.S)
    assert [(i, k) for i, k, _ in cards] == [("in-total", "ex_total"), ("in-pulses", "ex_pulses"), ("in-rest", "ex_rest")]          # total time, flashes, rest; `for` names the number (the buttons come first in the card)
    for (input_id, key, body), icon_start in zip(cards, ('<circle cx="12" cy="13.5" r="7.5"/>', '<path d="M13 2.5L5.5 13.5H11l-1 8 7.5-11H12z"/>', '<rect x="6.5" y="5" width="3.6" height="14" rx="1"/>')):
        name = input_id[3:]
        top = body[body.index('<span class="vc-top">'):body.index('<span class="vc-row">')]
        assert top.index('data-step="-1"') < top.index('<svg class="i" viewBox="0 0 24 24" aria-hidden="true">' + icon_start) < top.index('data-step="1"'), key      # minus, the icon (a stopwatch, a bolt, a pause), plus: on one row
        for step in ("-1", "1"):
            assert f'data-for="{input_id}" data-step="{step}"' in top and f'data-i18n-aria="ex_{"down" if step == "-1" else "up"}_{name}"' in top, (key, step)   # each button knows its number and has its own name
        assert f'data-i18n-aria="{key}"' in body and 'type="number"' in body and 'placeholder="–"' in body                              # the number keeps its name for the screen readers
    assert [("vc-unit" in b) for _, _, b in cards] == [True, False, True] and block.count(">s</span>") == 2                              # seconds for the total and the rest; the flashes are a count
    assert 'class="field"' not in block and "<span data-i18n=" not in block                                                              # no text labels over the boxes
    for key in ("up_total", "down_total", "up_pulses", "down_pulses", "up_rest", "down_rest"):
        assert i18n.count(f"ex_{key}: '") == 2, key                                                                                      # in both languages
    assert re.search(r"\.values \{[^}]*grid-template-columns: repeat\(3, 1fr\)", css) and re.search(r"\.vcard \{[^}]*border-radius: var\(--rc-radius\)[^}]*background: var\(--panel-2\)", css)
    assert re.search(r"\.vc-top \{ display: flex; align-items: center; justify-content: space-between; width: 100%; \}", css)
    assert re.search(r"\.vstep \{ all: unset;[^}]*width: 20px; height: 20px;", css) and re.search(r"\.vstep:disabled \{ opacity: \.3;", css) and re.search(r"\.vstep:focus-visible \{ outline: 2px solid var\(--accent\)", css)
    assert re.search(r"\.vcard:focus-within \{[^}]*border-color: var\(--accent\)", css) and re.search(r'\.vcard input\[type="number"\]:focus-visible \{ outline: none; \}', css)   # the card shows the focus
    assert "-webkit-appearance: none" in css and re.search(r"\.vc-unit \{[^}]*position: absolute; left: 100%", css)                    # no native spin buttons; the unit hangs after the number
    # the behaviour: a step of the input at each click, never under its minimum, no repetition, dispatched as if typed
    step = app[app.index("function stepValue(input, dir) {"):app.index("function syncSteppers()")]
    assert "+input.step || 1" in step and "input.min === '' ? 0 : +input.min" in step and "Math.max(min, Math.round((cur + dir * step) * 100) / 100)" in step
    assert "input.dispatchEvent(new Event('input', { bubbles: true }));" in step                                                          # the state, the memory of the last values and the summary follow
    assert "b.disabled = v !== null && v <= " in app and "syncSteppers();" in app                                                       # the minus is off at the minimum
    assert "$('#values').addEventListener('click'," in app and "mousedown" not in app[app.index("function stepValue"):app.index("for (const [id, key] of [['in-total'")] and "setInterval" not in step   # one step per click: nothing repeats while the button is held
    assert "function fitValue(el)" in app and "fitValue(el); }" in app and "fitValue(e.target); const x =" in app                        # the number is as wide as its digits


def node_placement(script):
    r = subprocess.run(["node", "--input-type=module", "-e", f"import * as p from {(STATIC / 'js' / 'placement.js').as_uri()!r};\nimport * as m from {(STATIC / 'js' / 'model.js').as_uri()!r};\n{script}"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return __import__("json").loads(r.stdout)


def test_the_placement_section_is_made_of_the_same_pieces_as_the_exposure_panel():
    html, css, app, i18n = HTML, (STATIC / "css" / "style.css").read_text(), JS["app.js"], JS["i18n.js"]
    place = section('<section class="panel sec-place"', '<section class="panel sec-expo"')
    empty = re.search(r'<div id="place-empty" class="callout info small"><svg[^>]*>.*?</svg><p data-i18n="select_board_hint"></p></div>', place, re.S)
    assert empty                                                                                                                         # nothing selected: an information, with its icon
    assert 'data-i18n="pl_centre"' in place and "pl-label" in place and "board name" not in place.lower()                                # a capital label over the three cards; no line with the board's name
    cards = re.findall(r'<label class="vcard" for="(in-\w+)" data-i18n-title="(\w+)">(.*?)</label>', place, re.S)
    assert [(i, k) for i, k, _ in cards] == [("in-x", "pos_x"), ("in-y", "pos_y"), ("in-angle", "angle"), ("in-ax", "offset_x"), ("in-ay", "offset_y")]
    for (input_id, key, body), (letter, unit) in zip(cards, [("X", "mm"), ("Y", "mm"), (None, "°"), ("X", "mm"), ("Y", "mm")]):
        top = body[body.index('<span class="vc-top">'):body.index('<span class="vc-row">')]
        assert top.index('data-step="-1"') < top.index('vc-letter' if letter else '<svg class="i"') < top.index('data-step="1"'), input_id        # minus, the letter (or the angle's icon), plus
        assert (f'<span class="vc-letter" aria-hidden="true">{letter}</span>' in top) == bool(letter), input_id
        assert f'data-for="{input_id}" data-step="-1"' in top and f'data-for="{input_id}" data-step="1"' in top and f'>{unit}</span>' in body, input_id
        assert 'data-jump="1"' in body and 'type="number"' in body and "min=" not in body and f'data-i18n-aria="{key}"' in body, input_id     # one click moves by 1 (mm or degree); a board may leave the plane, so no minimum
    assert [k for k in re.findall(r'data-i18n-title="(pl_\w+)"', place)] == ["pl_x_down", "pl_x_up", "pl_y_down", "pl_y_up", "pl_a_down", "pl_a_up", "pl_ax_down", "pl_ax_up", "pl_ay_down", "pl_ay_up"]
    for key in ("pl_x_down", "pl_x_up", "pl_y_down", "pl_y_up", "pl_a_down", "pl_a_up", "pl_ax_down", "pl_ax_up", "pl_ay_down", "pl_ay_up", "pl_centre", "m_title", "apply", "mirror_off", "mirror_on"):
        assert i18n.count(f" {key}: '") == 2 or i18n.count(f"{key}: '") == 2, key                                                       # in both languages
    # X and Y on one row; under it the two turns of 90° with the card of the angle between them (each button an icon over a short text: an exception to the icon-only rule; the full name is the tooltip)
    assert '<div class="values two" role="group" aria-labelledby="pl-centre">' in place and place.index('for="in-x"') < place.index('for="in-y"') < place.index('<div class="pl-turn">') < place.index('for="in-angle"')
    turn = re.search(r'<div class="pl-turn">(.*?)\n          </div>', place, re.S).group(1)
    assert turn.index('id="btn-rot-ccw"') < turn.index('<label class="vcard" for="in-angle"') < turn.index('id="btn-rot-cw"')                # counterclockwise, the angle, clockwise
    buttons = re.findall(r'<button class="btn sm" id="(btn-[\w-]+)" data-i18n-title="(\w+)" data-i18n-aria="(\w+)">(<svg.*?</svg>)<span>90°</span></button>', turn, re.S)
    assert [(i, k, a) for i, k, a, _ in buttons] == [("btn-rot-ccw", "rot_ccw", "rot_ccw"), ("btn-rot-cw", "rot_cw", "rot_cw")]
    assert "btn-center" not in html and "center_hint" not in html + app + i18n and "$('#btn-center')" not in app                      # no Centra button: the centre of the anchor does it
    assert re.search(r"\.pl-turn \{ display: grid; grid-template-columns: minmax\(0, 1fr\) minmax\(0, 1\.5fr\) minmax\(0, 1fr\);", css) and re.search(r"\.pl-turn \.btn \{[^}]*flex-direction: column;[^}]*border-radius: var\(--rc-radius\)", css)
    # the mirror: the two-pill switch of the resist, with its own words and the accent on both sides
    mirror = place[place.index('id="mirror-switch"'):place.index('id="mirror-hint"')]
    assert 'role="radiogroup"' in mirror and mirror.count('name="mirror"') == 2 and 'value="off"' in mirror and 'value="on"' in mirror and mirror.count('class="chip opt"') == 2
    assert 'tabindex="-1" aria-hidden="true"' in mirror and 'class="pol-track" id="mirror-toggle"' in mirror and "chk-mirror" not in place    # the switch is only graphic; the checkbox is gone
    assert re.search(r'\.pol-switch \.chip\.opt:has\(input:checked\) \{[^}]*var\(--accent\)', css) and re.search(r'\.pol-switch:has\(input\[value="on"\]:checked\) \.pol-track \.pol-knob \{ transform: translateX\(16px\); \}', css)
    hint = re.search(r'<div class="callout info small" id="mirror-hint"><svg.*?</svg><p data-i18n="mirror_hint"></p></div>', place, re.S)
    assert hint                                                                                                                          # the sentence about mirror and rotation is an information frame
    # the margins and the anchor: two frames with their titles
    assert '<fieldset class="frame margins-frame"><legend data-i18n="m_title"></legend><div id="margins" aria-live="polite"></div></fieldset>' in place
    assert '<fieldset class="frame anchor-frame" id="anchor-box"><legend data-i18n="anchor"></legend>' in place and "<details" not in place and "<summary" not in place   # always open, like the margins: nothing to collapse
    corners = re.findall(r'<button type="button" role="radio" aria-checked="(\w+)" data-corner="(\w+)" data-i18n-title="(\w+)" data-i18n-aria="\w+"></button>', place)
    assert corners == [("true", "TL", "c_tl"), ("false", "TR", "c_tr"), ("false", "C", "c_c"), ("false", "BL", "c_bl"), ("false", "BR", "c_br")]   # the top left corner is the one chosen at first
    assert 'id="in-ax"' in place and 'id="in-ay"' in place and place.count(' value="0"') == 2                                         # the offsets start at 0
    apply = re.search(r'<button class="btn sm primary" id="btn-anchor" data-i18n-title="apply_hint" data-i18n-aria="apply_hint"><svg.*?</svg><span data-i18n="apply"></span></button>', place, re.S)
    assert apply
    for gone in ("details.frame", ".frame-body", ".pl-actions", ".anchor-grid", ".margins {", ".margins b", ".margins div", ".align-end", "grid-template-columns: repeat(4, 1fr); gap: 6px; margin: 6px 0;"):
        assert gone not in css, gone                                                                                                     # the old tiles and the grid of arrows are gone
    assert "anchor-grid" not in app and "$('#chk-mirror')" not in app
    # the behaviour
    step = app[app.index("function stepPlacement(input, dir) {"):app.index("$('#place-body').addEventListener('click'")]
    assert "(+input.dataset.jump || 1)" in step and "Math.min" not in step and "Math.max" not in step                                  # by `data-jump`, with no limit
    assert "input.dispatchEvent(new Event('input', { bubbles: true }));" in step and "$('#place-body').addEventListener('click', (e) => { const b = e.target.closest('.vstep');" in app
    assert "radio.checked = (radio.value === 'on') === b.mirror" in app and "b.mirror = e.target.value === 'on'" in app and "$('#mirror-toggle').onclick = () => { const b = selected(); if (b) { b.mirror = !b.mirror; app.changed(true); } };" in app
    assert "$('#margins').innerHTML = marginsMap(b, state.plane, { t, fmt });" in app and "import { anchorSize, marginsMap } from './placement.js';" in app
    assert "$$('#anchor-pick button')" in app and "fitValue($('#in-ax')); fitValue($('#in-ay'));" in app


def test_the_cards_of_the_placement_section_have_the_number_centred_and_the_unit_after_it_as_the_exposure_cards_do():
    css = (STATIC / "css" / "style.css").read_text()
    assert "#place-body .vc-row" not in css and "#place-body .vc-unit" not in css and '#place-body .vcard input[type="number"]' not in css   # no style of their own for the number and its unit: they are the exposure cards'
    assert re.search(r"\.vc-unit \{[^}]*position: absolute; left: 100%", css) and re.search(r'\.vcard input\[type="number"\] \{[^}]*font-size: 17px;[^}]*text-align: center;', css)   # the number is centred in the card, the unit hangs after it
    assert re.search(r"\.vcard \.vc-letter \{[^}]*font-weight: 700;", css) and re.search(r"\.values\.two \{ grid-template-columns: repeat\(2, 1fr\);", css)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_margins_are_drawn_as_the_plane_with_the_board_in_it_and_four_distances_around_it():
    got = node_placement("""
      const t = (k) => k, fmt = (n, d) => n.toFixed(d).replace('.', ',');
      const plane = { w: 130, h: 80 };
      const board = (x, y, angle = 0, w = 30, h = 20) => ({ x, y, angle, mirror: false, w, h, cx: 0, cy: 0 });
      const inside = p.marginsMap(board(65, 40), plane, { t, fmt }), outside = p.marginsMap(board(10, 40), plane, { t, fmt }), turned = p.marginsMap(board(65, 40, 90), plane, { t, fmt });
      const cells = (h) => [...h.matchAll(/<div class="mg (\\w+)( neg)?"><small>(\\w+)<\\/small><b>([^<]*)<\\/b>/g)].map((x) => [x[1], !!x[2], x[3], x[4]]);
      const attr = (h, re) => (h.match(re) || [])[1];
      console.log(JSON.stringify({ inside: cells(inside), outside: cells(outside), turned: cells(turned),
        insideBoard: attr(inside, /<rect class="(mm-board[^"]*)"/), outsideBoard: attr(outside, /<rect class="(mm-board[^"]*)"/),
        rect: inside.match(/<rect class="mm-board" x="([\\d.-]+)" y="([\\d.-]+)" width="([\\d.-]+)" height="([\\d.-]+)"/).slice(1).map(Number),
        dim: attr(inside, /<path class="mm-dim" d="([^"]*)"/), view: attr(inside, /viewBox="([^"]*)"/),
        turnedRect: turned.match(/<rect class="mm-board" x="([\\d.-]+)" y="([\\d.-]+)" width="([\\d.-]+)" height="([\\d.-]+)"/).slice(1).map(Number),
        sizes: [p.anchorSize({ w: 130.56, h: 82.62 }), p.anchorSize({ w: 82.62, h: 130.56 }), p.anchorSize({ w: 100, h: 100 }), p.anchorSize({ w: 130, h: 80 }, { w: 65, h: 80 })] }));""")
    # the order of the cells is the order of the picture: the back above, the left and the right beside it, the front under it
    assert [c[0] for c in got["inside"]] == ["t", "l", "r", "b"] and [c[2] for c in got["inside"]] == ["m_back", "m_left", "m_right", "m_front"]
    assert [c[3] for c in got["inside"]] == ["30,0", "50,0", "50,0", "30,0"] and not any(c[1] for c in got["inside"])                      # 80 − 40 − 10 = 30 above and under, 65 − 15 = 50 on the sides; none is negative
    assert got["inside"][0][3] == got["inside"][3][3] == "30,0"
    assert [c[3] for c in got["outside"]] == ["30,0", "-5,0", "105,0", "30,0"] and [c[1] for c in got["outside"]] == [False, True, False, False]   # 10 − 15 = −5 on the left (red), 130 − 25 = 105 on the right
    assert got["insideBoard"] == "mm-board" and got["outsideBoard"] == "mm-board out"                                                    # the board outside the plane has the colour of the errors
    assert got["rect"] == [50, 30, 30, 20] and got["view"] == "-2 -2 134 84"                                                              # the extent in the plane (y from the back: 80 − 50 = 30), 2 mm of pad around
    assert got["dim"] == "M0 40H50M130 40H80M65 0V30M65 80V50"                                                                             # a dashed line from each side of the board to the edge of the plane
    assert [c[3] for c in got["turned"]] == ["25,0", "55,0", "55,0", "25,0"] and got["turnedRect"] == [55, 25, 20, 30]                   # turned by 90° the extent is 20 × 30
    assert got["sizes"] == [{"w": 150, "h": 95}, {"w": 61, "h": 96}, {"w": 96, "h": 96}, {"w": 65, "h": 40}]                              # the plane's own proportions, as large as the box lets it be


def node_ladder(script):
    r = subprocess.run(["node", "--input-type=module", "-e", f"import * as l from {(STATIC / 'js' / 'ladder.js').as_uri()!r};\n{script}"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return __import__("json").loads(r.stdout)


def test_the_calibration_ladder_page_has_the_printer_the_resist_the_values_the_mirror_a_preview_the_strip_and_no_recipe():
    html, css, app, i18n = HTML, (STATIC / "css" / "style.css").read_text(), JS["app.js"], JS["i18n.js"]
    page = section('<main id="view-ladder"', '<!-- ===== view: settings ===== -->')
    assert "soon_title" not in html + app + i18n and "ladder_soon" not in html + app + i18n                                              # the placeholder is gone
    assert "recipe" not in page and "ex_recipe" not in page and "dosage" not in page.replace("dosage:", "")                              # no recipe is chosen here (the resist is: two pills)
    printer = section_of(page, '<div class="picker" id="ld-printer-picker">', 'id="ld-resist-label"')
    assert 'id="ld-printer-btn"' in printer and 'aria-haspopup="listbox"' in printer and 'id="ld-printer-menu" role="listbox"' in printer         # the printer in use, changed with a list
    assert page.index('id="ld-printer-label"') < page.index('id="ld-resist-label"') < page.index('id="ld-steps-label"') < page.index('id="ld-mirror-label"') < page.index('id="ld-summary"') < page.index('id="btn-ld-generate"')
    pol = section_of(page, 'id="ld-pol"', 'id="ld-steps-label"')
    assert pol.count('name="ld-polarity"') == 2 and 'value="positive"' in pol and 'value="negative"' in pol and 'class="pol-track" id="ld-pol-toggle" tabindex="-1" aria-hidden="true"' in pol
    assert 'data-i18n="pol_positive"' in pol and 'data-i18n="pol_negative"' in pol                                                         # the same pills as the resist of the exposure
    cards = re.findall(r'<label class="vcard" for="(ld-\w+)" data-i18n-title="(\w+)">(.*?)</label>', page, re.S)
    assert [(i, k) for i, k, _ in cards] == [("ld-step", "ld_step"), ("ld-bands", "ld_bands"), ("ld-pulses", "ld_pulses"), ("ld-rest", "ld_rest"), ("ld-width", "ld_width"), ("ld-height", "ld_height")]
    for (input_id, key, body), (lo, hi, unit) in zip(cards, [(1, 600, "s"), (2, 20, ""), (1, 20, ""), (0, 60, "s"), (6, 40, "mm"), (15, 150, "mm")]):
        assert f'min="{lo}" max="{hi}"' in body and f'data-for="{input_id}" data-step="-1" data-i18n-title="{key}_down" data-i18n-aria="{key}_down"' in body and f'data-for="{input_id}" data-step="1" data-i18n-title="{key}_up"' in body
        assert ("vc-unit" in body and f">{unit}</span>" in body) == bool(unit), input_id
        assert i18n.count(f" {key}: '") == 2 and i18n.count(f" {key}_up: '") == 2 and i18n.count(f" {key}_down: '") == 2                         # in both languages
    mirror = section_of(page, 'id="ld-mirror"', 'id="ld-notes"')
    assert mirror.count('name="ld-mirror"') == 2 and mirror.count('class="chip opt"') == 2 and 'id="ld-mirror-toggle"' in mirror
    assert '<div id="ld-notes" aria-live="polite"></div>' in page and 'id="ld-note"' not in page                                              # what is wrong, one sentence each
    # the strip: its size and, one switch for each, the tests (the style of the layers' switches), under the preview and in the same column
    strip = section_of(page, '<section class="lad-sec lad-strip off"', "</section>")
    assert page.index('class="lad-side"') < page.index('id="lad-tabs"') < page.index('<section class="lad-sec lad-params"') < page.index('<section class="lad-sec lad-strip off"') < page.index('class="lad-foot"') < page.index('class="lad-main"') < page.index('<section class="card lad-preview">')   # on the left the tabs, the two sections and the footer; on the right the preview
    foot = section_of(page, 'class="lad-foot"', 'class="lad-main"')
    assert 'id="ld-notes"' in foot and 'id="ld-summary"' in foot and 'id="btn-ld-generate"' in foot and 'id="ld-notes"' not in page[:page.index('class="lad-foot"')]   # what is wrong, what the file will be and the button are under both tabs, never in one of them
    head = section_of(strip, 'class="lad-tests-head', 'id="ld-tests"')
    assert 'id="ld-tests-label"' in head and 'id="btn-ld-all" data-i18n="ld_all" data-i18n-title="ld_all_title" data-i18n-aria="ld_all_title"' in head and 'id="btn-ld-none" data-i18n="ld_none"' in head   # all and none, over the switches
    for key in ("ld_all", "ld_none", "ld_all_title", "ld_none_title"):
        assert i18n.count(f" {key}: '") == 2, key
    # the two tabs: the SideBar turned on its side
    tabs = section_of(page, 'id="lad-tabs"', 'class="lad-panel"')
    assert 'role="tablist" aria-orientation="horizontal" data-i18n-aria="ld_sections"' in tabs and i18n.count(" ld_sections: '") == 2
    found = re.findall(r'<button type="button" role="tab" id="ld-tab-(\w+)" data-ldtab="(\w+)" aria-selected="(\w+)"(?: tabindex="-1")? aria-controls="ld-sec-(\w+)" data-i18n-title="(ld_\w+)"><svg.*?</svg><span data-i18n="(ld_\w+)"></span></button>', tabs, re.S)
    assert found == [("params", "params", "true", "params", "ld_params", "ld_params"), ("strip", "strip", "false", "strip", "ld_strip", "ld_strip")]
    assert 'id="ld-sec-params" role="tabpanel" aria-labelledby="ld-tab-params"' in page and 'id="ld-sec-strip" role="tabpanel" aria-labelledby="ld-tab-strip" inert' in page    # the other tab's section cannot be reached
    assert "sec.classList.toggle('off', !on); sec.inert = !on;" in app and "ArrowRight: (cur + 1) % LD_TABS.length, ArrowLeft: (cur + LD_TABS.length - 1) % LD_TABS.length, Home: 0, End: LD_TABS.length - 1" in app   # arrows, Home and End move between the tabs
    assert "store.set('gs-ldtab', id)" in app and "placeLadTabs" not in app                                                    # the tab is remembered; nothing slides, nothing to place
    # the look: tabs of the same width, the grey of the bar is the grey of the border, a notch a pixel smaller than the chosen tab leaves a grey line round it (so the border of the panel goes up round
    # the chosen tab only), slides (by CSS), has rounded corners above and a concave curve at its foot only between the two tabs, and casts a shadow on the other tab; the shadow of the cards goes round all of it
    bar = css[css.index(".lad-side { flex: none; width: 330px;"):css.index(".lad-secs { display: grid; }")]
    assert ".lad-side { flex: none; width: 330px; display: flex; flex-direction: column; border-radius: 10px; box-shadow: var(--shadow); }" in bar                 # the shadow of the cards (Settings') goes round the tabs and the panel together
    assert ".lad-tabs { --tab-off: var(--border); position: relative; z-index: 1; display: grid; grid-template-columns: 1fr 1fr; height: 43px; overflow: hidden; border-radius: 10px 10px 0 0; background: var(--tab-off); }" in bar   # two tabs of the same width on a bar of the border's grey; it clips the notch (and its shadow)
    notch = bar[bar.index(".lad-tabs::after {"):bar.index(".lad-tabs button {")]
    assert "left: -10px; width: calc(50% + 20px);" in notch and notch.count("radial-gradient(circle at") == 4 and "transform: translateX(calc(100% - 20px));" in notch   # wider than a tab by the curve of each foot: the one at the outer side falls out of the bar
    assert "left 11px top 1px / 9px 9px" in notch and "left 11px top 9px / calc(100% - 22px) calc(100% - 9px)" in notch and "transparent 10.5px, var(--panel) 11px" in notch      # a pixel in on the top and at the walls (and the curve a pixel wider): the grey line of the border shows round it
    assert "filter: drop-shadow(5px 4px 9px rgba(0, 0, 0, .7)); clip-path: inset(1px -40px -40px 11px);" in notch and "transition: transform .22s ease-in-out, filter .22s ease-in-out, clip-path .22s ease-in-out;" in notch   # the shadow goes towards the other tab (to the right when the notch is at the left), kept off the grey line round the notch, and turns with the slide
    assert '.lad-tabs[data-active="strip"]::after { transform: translateX(calc(100% - 20px)); filter: drop-shadow(-5px 4px 9px rgba(0, 0, 0, .7)); clip-path: inset(1px 11px -40px -40px); }' in notch   # ... and to the left when it is at the right
    assert "border" not in notch and "border:" not in bar[:bar.index(".lad-panel")].replace("border: 0;", "")                                                                             # the bar and the notch have no border of their own
    assert ".lad-panel { position: relative; padding: 16px; background: var(--panel); border: 1px solid var(--border); border-top: 0; border-radius: 0 0 10px 10px; }" in bar   # the border of the panel: not at the top (the bar's grey is there)
    assert "var(--mb)" not in bar and bar.count("box-shadow") == 1                                                                    # no teal; a single shadow of the section
    assert "color: color-mix(in srgb, var(--text) 68%, var(--tab-off));" in bar and '.lad-tabs button[aria-selected="true"] { color: var(--sec); }' in bar and ".lad-tabs button:hover { color: var(--text); }" in bar   # the other tab: not too dim; the chosen one has its section's colour
    assert 'id="lad-tabs" data-active="params"' in html and "$('#lad-tabs').dataset.active = id;" in app                                                  # the notch follows the attribute
    assert ".lad-secs { display: grid; } .lad-sec { grid-area: 1 / 1; min-width: 0; } .lad-sec.off { visibility: hidden; }" in css                                      # both sections in the same place: the panel does not change its height with the tab
    assert "$('#btn-ld-all').onclick = () => { state.ladder.tests = [...TESTS]; ldChanged(); };" in app and "$('#btn-ld-none').onclick = () => { state.ladder.tests = []; ldChanged(); };" in app
    assert "$('#btn-ld-all').disabled = L.tests.length === TESTS.length; $('#btn-ld-none').disabled = !L.tests.length;" in app                                   # each is off when there is nothing to do
    assert strip.index('id="ld-width"') < strip.index('id="ld-height"') < strip.index('id="ld-tests"')
    tests = re.findall(r'<label class="switch-row"><input type="checkbox" role="switch" data-test="(\w+)"><span class="switch" aria-hidden="true"></span><span data-i18n="(ld_t_\w+)"></span></label>', strip)
    assert [t for t, _ in tests] == ["lines_v", "lines_h", "gaps", "soic8", "fine", "passives", "rings"] and all(k == f"ld_t_{t}" for t, k in tests)   # the order they are laid out in
    for _, k in tests:
        assert i18n.count(f" {k}: '") == 2, k
    for key in ("ld_strip", "ld_size", "ld_tests", "ld_no_tests", "ld_dropped_one", "ld_dropped_many"):
        assert i18n.count(f" {key}: '") == 2, key
    assert "$$('#ld-tests input')" in app and "state.ladder.tests = TESTS.filter(" in app                                                    # the switches are the list of the tests
    assert 'id="btn-ld-generate" data-i18n="ld_generate" disabled' in page and 'ex_generate_soon' not in page                             # the button is off until nothing blocks (the page turns it on)
    assert page.index('id="btn-ld-generate"') < page.index('id="ld-gen-reason"') < page.index('id="ld-gen-done"')                          # under it: why it is off, and what the last file did
    seg = section_of(page, 'id="ld-seg"', 'id="btn-ld-zoom-out"')
    assert seg.count("data-ldview=") == 2 and 'data-ldview="material" aria-checked="true" data-i18n="mode_material"' in seg and 'data-ldview="uv" aria-checked="false" data-i18n="mode_light"' in seg
    assert 'class="lad-view" id="ld-view" tabindex="0" role="img" data-i18n-aria="ld_view_label"' in page                                    # the preview can be reached from the keyboard
    assert "$$('.cadtitlebar .seg button')" in app and "$$('.seg button')" not in app                                                     # the views of the plane are not the ladder's
    assert "const ldSave = () => store.set('gs-ladder', JSON.stringify(state.ladder));" in app and "parseLadder(store.get('gs-ladder'))" in app   # the browser remembers the last values
    assert "makePicker('ld-printer', {" in app and "pick: (id) => selectPrinter(id)" in app                                              # the same choice as the PrinterPill's
    assert "renderLadder(); renderWarnings();" in app                                                                                    # drawn again with the rest of the page (a printer or a language change)
    assert re.search(r"\.lad-grid \{ display: flex; justify-content: center; align-items: flex-start; gap: 14px;", css)                              # the values and the preview side by side, in the middle of the page
    assert ".ld-uv.pos .ld-field { fill: #fff; }" in css and ".ld-uv.neg .ld-field { fill: none; }" in css and ".ld-uv .ld-bg { fill: #000; }" in css      # white where the light passes, as in the CadWindow
    assert ".ld-material .ld-text { fill: var(--copper); } .ld-material use { color: var(--copper); }" in css and ".ld-plane.out .ld-edge { stroke: var(--danger);" in css   # the drawing takes the colour of its <use>
    assert ".ld-uv.pos use { color: #000; }" in css and ".ld-uv.neg use { color: #fff; }" in css and ".lad-tests { display: grid; gap: 10px; }" in css
    assert "#view-ladder .page-inner { width: auto; max-width: 96%;" in css and ".lad-side { flex: none; width: 330px;" in css                 # the page is as wide as its content
    main = css[css.index(".lad-main {"):css.index("\n", css.index(".lad-main {"))]
    assert "width: calc(var(--ld-fw, 600px) + 34px)" in main and "position: sticky; top: 14px;" in main and "min(calc((100vh" not in css                       # the card is as wide as its picture (17 px of card at each side) and stays in view; the width comes from JS, not from the window's height
    size = app[app.index("function sizeLadPreview() {"):app.index("new ResizeObserver(sizeLadPreview)")]
    assert "const extra = $$('#ld-notes p, #ld-gen-reason, #ld-gen-done').reduce((a, p) => (p.offsetHeight ? a + p.offsetHeight + parseFloat(getComputedStyle(p).marginTop) : a), 0);" in size   # what the warnings and the lines under the button add to the panel is not counted
    assert "const chrome = card.offsetHeight - view.offsetHeight, fw = Math.min((side.offsetHeight - extra - chrome) * (fit.w / fit.h), page.clientWidth * 0.96 - 330 - 14 - 34);" in size   # the picture takes what is left of the panel's height (without the warnings), keeping the proportions of the plane (a narrow window makes the card lower, not the picture bent)
    assert "$('.lad-main').style.setProperty('--ld-fw'," in size and "new ResizeObserver(sizeLadPreview).observe($('.lad-side'));" in app and "window.addEventListener('resize', sizeLadPreview);" in app   # drawn again when the panel changes its height or the window its size
    assert "if (v === 'ladder') sizeLadPreview();" in app and "--ld-ar" not in css + app
    assert ".lad-view { position: relative; width: 100%;" in css
    # no sentence under the title and no frame of "how to use it": the title is the same as in Settings and Help, and the size of the ladder is under the picture, at the right
    assert "lad-how" not in css + html + app and "ladder_intro" not in html + app + i18n and not re.search(r" ld_how(_\d)?: '", i18n) and "ld_how" not in html     # (the strings are gone too)
    assert '<h1 data-i18n="ladder_title"></h1>\n      <div class="lad-grid">' in page or '<h1 data-i18n="ladder_title"></h1>\n      <div class="lad-grid">' in html
    assert "#view-ladder h1" not in css and "#view-ladder .page-inner > p" not in css and "padding-bottom: 14px; }" in css[css.index("#view-ladder .page-inner"):css.index("#view-ladder .page-inner") + 260]   # the title is the page's own (22 px, 24 px under the MenuBar): only the bottom is short
    cap = section_of(page, '<div class="lad-view" id="ld-view"', "</section>")
    assert '<div class="lad-cap"><span id="ld-dims"></span></div>' in cap and 'id="ld-dims"' not in page[:page.index('<div class="lad-view" id="ld-view"')]   # the size of the ladder: under the picture
    assert ".lad-cap { display: flex; justify-content: flex-end; margin-top: 8px; font-size: 12px; color: var(--muted); }" in css and ".lad-head .dims" not in css     # ... at the right
    assert "ld_dims: 'Dimensioni totali scala calibrazione: {w} × {h} mm'" in i18n and "ld_dims: 'Calibration ladder total space: {w} × {h} mm'" in i18n   # what it says, in both languages
    assert "ld-caption" not in app and "view.title = t(L.view === 'uv' ? 'ld_cap_light' : 'ld_cap_material');" in app   # the sentence about what the view shows is the tip of the picture


def section_of(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


def test_the_steppers_stop_at_the_maximum_of_a_field_that_has_one():
    app = JS["app.js"]
    step = app[app.index("function stepValue(input, dir) {"):app.index("function syncSteppers()")]
    assert "max = input.max === '' ? Infinity : +input.max" in step and "Math.min(max, Math.max(min, Math.round((cur + dir * step) * 100) / 100))" in step   # the exposure's fields have no maximum
    sync = app[app.index("function syncSteppers()"):app.index("$('#values').addEventListener('click'")]
    assert "b.disabled = v !== null && input.max !== '' && v >= +input.max" in sync and "#view-ladder .vstep[data-step=\"1\"]" in sync    # the plus is off at the top
    assert "$('#view-ladder').addEventListener('click'," in app                                                                                # (all the cards of the ladder page)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_what_the_ladder_remembers_says_and_finds_wrong_with_its_values():
    got = node_ladder("""
      const P = { w: 130, h: 80 }, lim = { min_flash_s: 1, max_proven_flash_s: 20 };
      const v = (o = {}) => ({ ...l.DEFAULTS, ...o });
      console.log(JSON.stringify({
        defaults: l.parseLadder(null), damaged: l.parseLadder('{oops'), array: l.parseLadder('[1]'),
        partial: l.parseLadder(JSON.stringify({ step: 15, bands: 3.5, pulses: 99, rest: -1, width: 3, height: 200, polarity: 'negative', mirror: 'yes', view: 'uv' })),
        full: l.parseLadder(JSON.stringify({ step: 12.5, bands: 6, pulses: 3, rest: 0, width: 20, height: 50.5, tests: ['soic8', 'nope', 'lines_v'], polarity: 'negative', mirror: true, view: 'uv' })),
        noTests: l.parseLadder(JSON.stringify({ tests: [] })).tests, badTests: l.parseLadder(JSON.stringify({ tests: 'soic8' })).tests,
        valid: [l.isValid(v()), l.isValid(v({ step: null })), l.isValid(v({ bands: 1 })), l.isValid(v({ bands: 2.5 })), l.isValid(v({ rest: 0 })), l.isValid(v({ pulses: 21 })), l.isValid(null),
                l.isValid(v({ width: 5 })), l.isValid(v({ width: 40 })), l.isValid(v({ height: 14 })), l.isValid(v({ height: 150.5 })), l.isValid(v({ height: null }))],
        spec: l.ladderSpec(v()), spec2: l.ladderSpec(v({ step: 12, bands: 3, pulses: 4 })),
        issues: [l.ladderIssues(v(), P, lim), l.ladderIssues(v({ step: 1, pulses: 2 }), P, lim), l.ladderIssues(v({ step: 60, pulses: 2 }), P, lim), l.ladderIssues(v({ bands: 9 }), P, lim),
                 l.ladderIssues(v({ bands: 10 }), P, lim), l.ladderIssues(v(), { w: 96, h: 64 }, lim), l.ladderIssues(v({ step: null }), P, lim), l.ladderIssues(v({ step: 1, pulses: 2 }), P, null),
                 l.ladderIssues(v({ tests: [] }), P, lim), l.ladderIssues(v({ width: 6 }), P, lim), l.ladderIssues(v({ bands: 10, width: 11 }), P, lim), l.ladderIssues(v({ height: 60, bands: 5 }), { w: 96, h: 64 }, lim)],
        can: [l.canGenerate(v(), P, lim), l.canGenerate(v({ step: 60 }), P, lim), l.canGenerate(v({ step: 1 }), P, lim), l.canGenerate(v({ bands: 10 }), P, lim), l.canGenerate(v({ step: null }), P, lim),
              l.canGenerate(v({ tests: [] }), P, lim), l.canGenerate(v({ width: 6 }), P, lim), l.canGenerate(v({ height: 60, bands: 5 }), { w: 96, h: 64 }, lim)],
        layout: l.ladderLayout(v({ bands: 3 }), P), wide: l.ladderLayout(v({ bands: 3, width: 20, height: 50 }), P),
      }));""")
    d = got["defaults"]
    every = ["lines_v", "lines_h", "gaps", "soic8", "fine", "passives", "rings"]
    assert d == {"step": 10, "bands": 8, "pulses": 2, "rest": 4, "width": 13, "height": 76, "tests": every, "polarity": "positive", "mirror": False, "view": "material"} and got["damaged"] == d == got["array"]   # nothing, or damage: the ladder tried on a printer
    assert got["partial"] == {**d, "step": 15, "polarity": "negative", "view": "uv"}                                                                           # each value on its own: the good ones stay, the others are the default
    assert got["full"] == {"step": 12.5, "bands": 6, "pulses": 3, "rest": 0, "width": 20, "height": 50.5, "tests": ["lines_v", "soic8"], "polarity": "negative", "mirror": True, "view": "uv"}   # the tests it knows, in their order
    assert got["noTests"] == [] and got["badTests"] == every                                                                                                   # no test is a choice; a list that is not a list is not
    assert got["valid"] == [True, False, False, False, True, False, False, False, True, False, False, False]
    assert got["spec"] == {"bands": 8, "flash": 5, "layers": 16, "totals": [10, 20, 30, 40, 50, 60, 70, 80], "first": 10, "last": 80}                         # the strip k is lit for k times the first; 8 steps in 2 flashes: 16 layers
    assert got["spec2"] == {"bands": 3, "flash": 3, "layers": 12, "totals": [12, 24, 36], "first": 12, "last": 36}
    flash_ok, below, beyond, nine, ten, small, empty, nolimits, none, narrow, eleven, low = got["issues"]
    assert flash_ok == [] and below == [{"kind": "flash_below", "flash": 0.5, "min": 1}] and beyond == [{"kind": "flash_beyond", "flash": 30, "max": 20}]   # 1 s in 2 flashes is under the minimum; 60 s in 2, over the longest tried
    assert nine == [] and ten == [{"kind": "too_big", "w": 9 * 14 + 13, "h": 76, "pw": 130, "ph": 80, "sw": 13, "maxn": 9, "maxh": 80}]                          # 9 strips are 125 mm: they fit 130; 10 do not (and the plane takes at most 9 of 13 mm, 80 high)
    assert small[0]["kind"] == "too_big" and small[0]["pw"] == 96 and small[0]["maxh"] == 64 and empty == [] and nolimits == []                              # a plane of 96 × 64 cannot hold a strip of 76; a half-typed field says nothing
    assert none == [{"kind": "no_tests"}] and narrow == [{"kind": "dropped", "ids": ["soic8", "fine", "rings"]}] and eleven == []   # no test: said; a strip of 6 mm has no room for the wide ones; 10 strips of 11 mm (129 mm) fit, with every pattern in them
    assert low == []                                                                                                                                           # 5 strips of 60 mm high fit a plane of 96 × 64
    assert got["can"] == [True, True, False, False, False, True, True, True]                                                                                  # beyond the longest, no test or no room for tests only warn; under the minimum, too big or not valid do not generate
    lay = got["layout"]
    assert lay["width"] == 2 * 14 + 13 and lay["x0"] == (130 - 41) / 2 and lay["y0"] == 2 and lay["fits"] is True and [s["x"] for s in lay["strips"]] == [44.5, 58.5, 72.5]   # centred both ways
    assert [s["total_s"] for s in lay["strips"]] == [10, 20, 30] and lay["pitch"] == 14 and lay["drawing"]["dropped"] == []
    wide = got["wide"]                                                                                                                                         # a wider, lower strip: the pitch follows (1 mm of dark between)
    assert wide["pitch"] == 21 and wide["width"] == 2 * 21 + 20 and wide["y0"] == 15 and [s["x"] for s in wide["strips"]] == [34, 55, 76] and wide["strips"][0]["w"] == 20 and wide["strips"][0]["h"] == 50


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_tests_of_a_strip_are_laid_out_in_rows_inside_it_and_adapt_to_its_size():
    got = node_ladder("""
      const all = l.TESTS, box = (s) => s.r ? [s.r[0], s.r[1], s.r[0] + s.r[2], s.r[1] + s.r[3]]
        : s.ring ? [s.ring[0] - s.ring[2] / 2, s.ring[1] - s.ring[2] / 2, s.ring[0] + s.ring[2] / 2, s.ring[1] + s.ring[2] / 2]
        : s.dot ? [s.dot[0] - s.dot[2], s.dot[1] - s.dot[2], s.dot[0] + s.dot[2], s.dot[1] + s.dot[2]]
        : [Math.min(s.line[0], s.line[2]) - s.line[4] / 2, Math.min(s.line[1], s.line[3]) - s.line[4] / 2, Math.max(s.line[0], s.line[2]) + s.line[4] / 2, Math.max(s.line[1], s.line[3]) + s.line[4] / 2];
      const ext = (d) => { const b = d.shapes.map(box); return b.length ? { minx: Math.min(...b.map((x) => x[0])), maxx: Math.max(...b.map((x) => x[2])), miny: Math.min(...b.map((x) => x[1])), maxy: Math.max(...b.map((x) => x[3])) } : null; };
      const d = l.stripDrawing(13, 76, all), widths = [...new Set(d.shapes.filter((s) => s.r).map((s) => +s.r[2].toFixed(2)))].sort((a, b) => a - b);
      const gaps = d.rows.slice(1).map((r, i) => +(r.y - d.rows[i].y - d.rows[i].h).toFixed(3));
      const sizes = (w, h, t = all) => { const x = l.stripDrawing(w, h, t); return { dropped: x.dropped, rows: x.rows.map((r) => r.ids.join('+')), ext: ext(x) }; };
      console.log(JSON.stringify({ pieces: Object.fromEntries(all.map((id) => [id, l.BLOCK[id].pieces.length])), n: d.shapes.length, dropped: d.dropped, rows: d.rows.map((r) => r.ids.join('+')), ext: ext(d), gaps, y0: d.rows[0].y,
        kinds: { ring: d.shapes.filter((s) => s.ring).length, dot: d.shapes.filter((s) => s.dot).length }, thin: widths.filter((w) => w < 0.45),
        w11: sizes(11, 76), w6: sizes(6, 76), h46: sizes(13, 46), h15: sizes(13, 15), none: sizes(13, 76, []), pair: sizes(20, 76, ['fine', 'soic8']), order: sizes(13, 76, ['rings', 'soic8']),
        wide: sizes(40, 76), label: [l.labelSize('10 s'), l.labelSize('1000 s'), l.labelSize('12000 s'), l.labelSize('10 s', 6), l.labelSize('10 s', 40)], labelY: l.LABEL_Y, head: l.HEAD, foot: l.FOOT, margin: l.MARGIN, gapY: l.GAP_Y }));""")
    assert got["pieces"] == {"lines_v": 5, "lines_h": 5, "gaps": 4, "soic8": 1, "fine": 1, "passives": 3, "rings": 4}   # what a test is made of (the pieces wrap onto more rows when the strip is narrow)
    assert got["dropped"] == [] and got["rows"] == ["lines_v", "lines_h", "gaps", "soic8", "fine", "passives", "rings"]        # in a strip of 13 × 76 every pattern has its row
    e = got["ext"]
    assert e["minx"] >= got["margin"] - 1e-9 and e["maxx"] <= 13 - got["margin"] + 1e-9 and e["miny"] >= got["head"] and e["maxy"] <= 76 - got["foot"] + 1e-9   # inside the strip, under the time, with its margins
    assert got["y0"] == got["head"] and all(got["gapY"][0] - 1e-9 <= g <= got["gapY"][1] + 1e-9 for g in got["gaps"]) and max(got["gaps"]) - min(got["gaps"]) < 1e-6   # the rows are spread over the height, evenly
    assert got["kinds"]["ring"] == 3 and got["kinds"]["dot"] == 1                                           # pads with a hole, and a round pad
    for w in (0.1, 0.15, 0.2, 0.28, 0.3, 0.35, 0.4):
        assert w in got["thin"], w                                                                                                                          # lines of different widths (not all the same), down to two pixels
    assert got["w11"]["dropped"] == [] and got["w11"]["rows"][:3] == ["lines_v", "lines_v", "lines_h"]                                                 # a narrower strip: the pieces wrap onto more rows and the last tests may lose their room
    assert "soic8" in got["w6"]["dropped"] and "fine" in got["w6"]["dropped"] and "soic8" not in "".join(got["w6"]["rows"])                                  # a piece wider than the strip is left out (the SOIC-8 is 6.9 mm wide)
    assert got["h46"]["dropped"] == ["rings"] and got["h46"]["ext"]["maxy"] <= 46 - got["foot"] + 1e-9                          # a lower strip keeps the first rows that fit and says what is left out
    assert got["h15"]["rows"] == [] and got["h15"]["ext"] is None and got["h15"]["dropped"] == ["lines_v", "lines_h", "gaps", "soic8", "fine", "passives", "rings"]   # 15 mm: nothing fits under the time
    assert got["none"] == {"dropped": [], "rows": [], "ext": None}                                                                                             # no test: only the time
    assert got["pair"]["rows"] == ["soic8+fine"] and got["order"]["rows"] == ["soic8", "rings"]                                                                # in the order of the list whatever the order they were asked in; two share a row when they fit it (6.9 + 5.8 mm in a strip of 20), not when they do not (6.9 + 8 mm in one of 13)
    assert got["wide"]["dropped"] == [] and got["wide"]["rows"] == ["lines_v+lines_h+gaps", "soic8+fine+passives+rings"]            # a wide strip puts more tests on a row
    assert got["label"][0] == 4.4 and got["label"][1] < got["label"][0] and got["label"][2] < got["label"][1] and got["label"][2] * 6 * 0.6 <= 13           # the time shrinks to stay inside the strip...
    assert got["label"][3] < got["label"][0] and got["label"][4] == 4.4 and got["labelY"] < got["head"]                                                       # ... narrower, smaller; it is above the first row


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_ladder_preview_is_the_plane_with_the_strips_and_turns_with_the_resist_the_view_and_the_mirror():
    got = node_ladder("""
      const P = { w: 130, h: 80 }, sec = (n) => String(n), v = { ...l.DEFAULTS, bands: 3 }, lay = l.ladderLayout(v, P), box = l.fitBox(P);
      const svg = (o) => l.ladderSvg(lay, { plane: P, view: 'material', polarity: 'positive', mirror: false, box, sec, ...o });
      const plain = svg({}), uv = svg({ view: 'uv', polarity: 'negative' }), flip = svg({ mirror: true }), big = l.ladderSvg(l.ladderLayout({ ...v, bands: 10 }, P), { plane: P, view: 'material', polarity: 'positive', mirror: false, box, sec });
      console.log(JSON.stringify({ cls: [plain, uv, big].map((s) => /<svg [^>]*class="([^"]*)"/.exec(s)[1]), vb: /viewBox="([^"]*)"/.exec(plain)[1], strips: (plain.match(/class="ld-field"/g) || []).length, texts: [...plain.matchAll(/<text [^>]*>([^<]*)<\\/text>/g)].map((m) => m[1]),
        flipped: [plain.includes('scale(-1 1)'), flip.includes('transform="translate(130 0) scale(-1 1)"')], at: [...plain.matchAll(/<g transform="translate\\(([\\d.]+) ([\\d.]+)\\)"><rect class="ld-field"/g)].map((m) => [+m[1], +m[2]]),
        pattern: plain.includes('<pattern id="ld-grid"'), uses: (plain.match(/<use href="#ld-draw"\\/>/g) || []).length, draw: /<g id="ld-draw">(.*?)<\\/g><\\/defs>/s.exec(plain)[1], size: plain.length, noscript: !/<script|on\\w+=/.test(plain),
        fit: l.fitBox(P), zoom: [l.zoomOf(box, box)] }));""")
    assert got["cls"] == ["ld-plane ld-material pos", "ld-plane ld-uv neg", "ld-plane ld-material pos out"]                                                  # the view and the resist are classes (the stylesheet colours them); one that does not fit is `out`
    assert got["vb"] == "-1 -1 132 82" and got["strips"] == 3 and got["texts"] == ["10 s", "20 s", "30 s"]
    assert got["flipped"] == [False, True] and got["at"] == [[44.5, 2], [58.5, 2], [72.5, 2]] and got["pattern"] and got["noscript"]
    assert got["uses"] == 3 and got["draw"].count("<rect") > 100 and 'class="ld-ink' not in got["draw"] and 'fill="currentColor"' in got["draw"] and 'stroke="currentColor"' in got["draw"]   # the drawing is made once (135 shapes) and used by every strip, in the colour of its <use>


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_zoom_of_the_ladder_preview_keeps_the_point_under_the_pointer_and_never_leaves_the_plane():
    got = node_ladder("""
      const P = { w: 130, h: 80 }, fit = l.fitBox(P), r = (b) => ({ x: +b.x.toFixed(3), y: +b.y.toFixed(3), w: +b.w.toFixed(3), h: +b.h.toFixed(3) });
      const z = l.zoomBox(fit, 2, 65, 40, fit), at = l.zoomBox(fit, 2, 10, 10, fit), more = l.zoomBox(z, 1000, 65, 40, fit), out = l.zoomBox(z, 1 / 1000, 65, 40, fit);
      const edge = l.zoomBox(fit, 4, 0, 0, fit), moved = l.panBox(z, -1000, 1000, fit), pt = l.boxPoint(z, { left: 100, top: 50, width: 200, height: 100 }, 200, 100);
      console.log(JSON.stringify({ fit, z: r(z), at: r(at), more: r(more), moreZoom: l.zoomOf(more, fit), out: r(out), edge: r(edge), moved: r(moved), pt, ratio: [z.w / z.h, fit.w / fit.h], max: l.MAX_ZOOM,
        under: [(65 - z.x) / z.w, (40 - z.y) / z.h], underAt: [(10 - at.x) / at.w, (10 - at.y) / at.h, (10 - fit.x) / fit.w, (10 - fit.y) / fit.h] }));""")
    assert got["fit"] == {"x": -1, "y": -1, "w": 132, "h": 82} and got["z"] == {"x": 32, "y": 19.5, "w": 66, "h": 41}                                           # twice as close, about the middle of the plane
    assert got["under"] == [0.5, 0.5] and abs(got["underAt"][0] - got["underAt"][2]) < 1e-9 and abs(got["underAt"][1] - got["underAt"][3]) < 1e-9          # the point under the pointer stays where it was
    assert got["moreZoom"] == got["max"] == 20 and got["out"] == got["fit"] and abs(got["ratio"][0] - got["ratio"][1]) < 1e-9                                # at most 20 times, at least the whole; always the proportions of the whole
    assert got["edge"]["x"] == -0.25 and got["edge"]["y"] == -0.25 and got["moved"]["w"] == 66 and got["moved"]["h"] == 41                                # zoomed about the corner of the plane: that point stays where it was in the frame
    assert got["moved"]["x"] == -1 and got["moved"]["y"] == 40                                                                                               # panning stops at the edge of the plane (x: -1; y: 81 - 41)
    assert got["pt"] == [65, 40]                                                                                                                              # the middle of the frame is the middle of the box shown (the plane's point, y down as on the screen)


def test_what_the_cadwindow_says_when_there_is_no_board_is_centred_in_what_the_rulers_leave():
    css, plane = (STATIC / "css" / "style.css").read_text(), JS["plane.js"]
    ruler = re.search(r"const RULER = \{ l: (\d+), t: (\d+) \};", plane)
    left, top = ruler.groups()
    assert f"--ruler-l', `${{RULER.l}}px`" in plane and f"--ruler-t', `${{RULER.t}}px`" in plane                                  # the plane tells the stylesheet how much room its Rulers take (one source)
    assert re.search(rf"\.empty \{{ position: absolute; inset: var\(--ruler-t, {top}px\) 0 0 var\(--ruler-l, {left}px\);", css)   # the message starts where the Rulers end, so its centre is the plane's


def test_the_summary_of_an_exposure_is_a_plain_sentence_with_bold_numbers_and_not_a_box_that_looks_like_a_field():
    css, html, app, i18n = (STATIC / "css" / "style.css").read_text(), HTML, JS["app.js"], JS["i18n.js"]
    rule = re.search(r"(?m)^\.summary \{([^}]*)\}", css).group(1)
    assert not re.search(r"background|border|padding|monospace|pre-wrap", rule) and "color: var(--muted)" in rule             # no box, no fixed-width letters: it does not look like a field to type in
    assert "margin: 12px 0 48px;" in rule                                                                                       # room between the sentence and the button that generates (at least twice what it was)
    assert re.search(r"(?m)^\.summary b \{ color: var\(--text\); font-weight: 600; \}", css)                                 # the numbers in the normal colour and bold
    assert '<p class="summary" id="summary" aria-live="polite"></p>' in html                                                     # still announced when it changes
    # the sentence: «Luce totale x in y flash da z, riposo w», with the numbers in bold (and no break between a number and its s)
    assert "ex_summary: 'Luce totale <b>{total}&nbsp;s</b> in <b>{flashes}</b> da <b>{flash}&nbsp;s</b>, riposo <b>{rest}&nbsp;s</b>'," in i18n
    assert "ex_summary: 'Total light <b>{total}&nbsp;s</b> in <b>{flashes}</b> of <b>{flash}&nbsp;s</b>, rest <b>{rest}&nbsp;s</b>'," in i18n
    line = app[app.index("if (ok) $('#summary').innerHTML"):app.index("else $('#summary').textContent")]
    assert line.count("esc(") >= 4 and "t(v.pulses === 1 ? 'u_flashes_one' : 'u_flashes_many', { n: v.pulses })" in line         # every value escaped; «1 flash» in the singular
    assert "else $('#summary').textContent = t('ex_summary_none');" in app                                                      # the hint when something is missing is plain text


def test_recipes_are_made_and_changed_in_settings_only_and_the_exposure_panel_only_chooses_one():
    html, css, app = HTML, (STATIC / "css" / "style.css").read_text(), JS["app.js"]
    expo = html[html.index('<section class="panel sec-expo"'):html.index("</section>", html.index('<section class="panel sec-expo"'))]
    assert "btn-recipe-new" not in expo and "ex_recipe_new" not in expo and "ex_recipe_edit" not in expo                          # no «new recipe» (or «edit recipe») in the Exposure panel
    block = expo[expo.index('<div id="recipe-block">'):expo.index('<div id="recipe-info"')]
    assert block.count("<button") == 1 and 'id="recipe-btn"' in block and "<select" not in block                                # the row of the recipe has its menu (a button that opens a list) and nothing else
    assert html.count('id="btn-recipe-new2"') == 1 and html.index('id="btn-recipe-new2"') > html.index('id="view-settings"')        # the plus of the recipes is in Settings
    assert "$('#btn-recipe-new2').onclick = () => openRecipeDialog('new');" in app and "btn-recipe-new'" not in app
    # what stays: the frame of the changed values, with its two buttons taking all the room of the frame
    frame = expo[expo.index('<div class="callout small" id="dos-save-row" hidden>'):]
    frame = frame[:frame.index("</div>\n      </div>") + 6]
    assert '<p data-i18n="ex_modified"></p>' in frame and '<div class="row gap fill">' in frame                                    # the two buttons on one row (no `wrap`)
    assert frame.count('data-i18n-title=') == 2 and 'data-i18n-title="ex_update"' in frame and 'data-i18n-title="ex_saveas"' in frame   # the whole text in the tooltip, for a panel so narrow that it is cut
    assert "ex_modified: 'Valori modificati, non salvati. Si può generare lo stesso: il riepilogo li segna «modificati».'" in JS["i18n.js"]
    assert re.search(r"\.row\.fill \{ flex-wrap: nowrap; \} \.row\.fill > \.btn \{ flex: 1 1 auto; min-width: 0; justify-content: center; padding-left: 6px; padding-right: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; \}", css)   # on one line, each button as wide as its text and the room left shared
    # dosages: the panel does not add, change or delete them (Settings does); what it keeps is the frame above, with «update» and «save as new»
    for gone in ("btn-dos-new", "btn-dos-edit", "btn-dos-del", "btn-dos-copy", "dlg-copy", "cp-source"):
        assert gone not in html + app, gone
    assert "openCopyDialog" not in app and "dosageDlg" not in app and "const deleteDosage =" not in app and "copyDosage" not in JS["api.js"]   # nor the code of those buttons
    for key in ("ex_dosage_edit", "ex_dosage_title_edit", "ex_dosage_hint_edit", "ex_copy_from", "ex_copy_hint", "ex_copy_do", "ex_copy_note", "ex_toast_copy_none"):
        assert f"{key}:" not in JS["i18n.js"], key                                                                                 # nor their words
    row = expo[expo.index('id="dosage-block"'):expo.index('<div id="dos-missing"')]
    assert row.count("<button") == 1 and 'id="dosage-btn"' in row and "<select" not in row                                         # the row of the dosage has its menu (a button that opens a list) and nothing else
    assert all(f'id="{b}"' in expo for b in ("btn-dos-manual", "btn-dos-ladder", "btn-dos-update", "btn-dos-saveas"))              # what stays: enter by hand, the ladder, update, save as new
    assert "async function deleteDosageOf(recipeId, d)" in app and "function openSettingsDosage(recipeId, dosageId)" in app          # Settings keeps all of it


def test_the_frame_of_a_missing_dosage_has_a_warning_icon_two_buttons_on_one_row_and_the_menu_only_shows_a_dash():
    css, html, app = (STATIC / "css" / "style.css").read_text(), HTML, JS["app.js"]
    frame = html[html.index('<div id="dos-missing"'):html.index('<div id="values"')]
    assert frame.startswith('<div id="dos-missing" class="callout warn iconed" hidden>')                                           # the frame of the warning, with an icon
    assert '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5L21.5 20h-19z"/><path d="M12 10v4.5M12 17.2v.01"/></svg>' in frame   # a triangle with an exclamation mark
    assert frame.index("<svg") < frame.index('<div class="cb">') < frame.index('<strong data-i18n="ex_missing_title">')               # icon at the left, the content in a block
    assert '<div class="row gap fill">' in frame and "wrap" not in frame.split("<button")[0].split('<div class="row')[1][:20]      # the two buttons on one row, filling it
    assert frame.count("<button") == 2 and 'id="btn-dos-manual"' in frame and 'id="btn-dos-ladder"' in frame                     # enter by hand, the ladder (nothing to copy from another printer)
    assert 'data-i18n-title="ex_manual"' in frame and 'data-i18n-title="ex_ladder"' in frame                                       # the whole text in the tooltip, if a narrow panel cuts it
    assert re.search(r"\.callout\.iconed \{ display: flex; gap: 8px; align-items: flex-start; \}", css) and re.search(r"\.callout\.warn\.iconed > svg\.i \{ color: var\(--warn\); \}", css)   # the icon in the colour of the frame
    # the menu of the dosages says nothing when there are none (the frame says it): a dash
    assert "'<span class=\"pk-name none\">–</span>'" in app and "t('ex_missing_title'))}</option>" not in app
    # by hand: the cursor goes to the total time and nothing is filled in; the ladder takes to its own section
    assert "$('#btn-dos-manual').onclick = () => $('#in-total').focus();" in app and "total_s: 40" not in app
    assert "$('#btn-dos-ladder').onclick = () => setView('ladder');" in app


def test_the_labels_of_the_two_menus_of_the_exposure_panel_are_in_capitals_by_the_stylesheet_and_what_the_recipe_says_is_not():
    css, html, app, i18n = (STATIC / "css" / "style.css").read_text(), HTML, JS["app.js"], JS["i18n.js"]
    rule = re.search(r"(?m)^#sec-expo \.field > span, \.pl-label \{([^}]*)\}", css)                                  # the capital labels of the Placement section share the rule
    assert rule and "text-transform: uppercase" in rule.group(1) and "font-size: 11px" in rule.group(1) and "letter-spacing: .05em" in rule.group(1)
    assert "recipe-info b" not in re.search(r"(?m)^[^\n]*text-transform: uppercase[^\n]*$", css[css.index("#sec-expo .field > span"):]).group(0)   # only the labels of the menus
    expo = html[html.index('<section class="panel sec-expo"'):html.index("</section>", html.index('<section class="panel sec-expo"'))]
    assert '<div class="field grow"><span id="recipe-label" data-i18n="ex_recipe">' in expo and '<div class="field grow"><span id="dosage-label" data-i18n="ex_dosage">' in expo   # the labels of the two menus are the spans the rule names
    assert re.search(r"(?m)^\.recipe-info \{[^\n]*\.recipe-info b \{ color: var\(--text\); font-weight: 600; \}$", css)           # what the recipe says (resist, development, notes): as it was, bold and as the text
    for key in ("ex_recipe", "ex_dosage"):
        assert f"{key}: '" in i18n and f"{key}: '{key.upper()}" not in i18n                                                      # the words are written as usual: the capitals come from the stylesheet (a screen reader reads words)


def test_the_recipe_and_dosage_menus_of_the_exposure_panel_are_made_by_the_page_and_the_pill_under_the_recipe_is_gone():
    css, html, app = (STATIC / "css" / "style.css").read_text(), HTML, JS["app.js"]
    for name in ("recipe", "dosage"):
        picker = html[html.index(f'<div class="picker" id="{name}-picker">'):html.index("</div>\n          </div>", html.index(f'id="{name}-picker"'))]
        assert f'id="{name}-btn" aria-haspopup="listbox" aria-expanded="false" aria-controls="{name}-menu" aria-labelledby="{name}-label {name}-btn"' in picker   # a button that opens a list, named by its label and by what it shows
        assert f'id="{name}-menu" role="listbox" aria-labelledby="{name}-label" hidden' in picker
    assert "sel-recipe" not in html + app and "sel-dosage" not in html + app and "chip-polarity" not in html + app + css            # no <select>s any more, and no pill under the recipe's information
    # one factory for the two
    factory = app[app.index("function makePicker(name, { items, pick }) {"):app.index("// the recipes: closed")]
    for key in ("ArrowDown", "ArrowUp", "Escape", "Home", "End"):
        assert f"e.key === '{key}'" in factory, key                                                                                  # keyboard, as the printer's menu
    assert "document.addEventListener('pointerdown', (e) => { if (!e.target.closest(`#${name}-picker`)) close(false); });" in factory   # a click outside closes
    assert 'role="option" data-id=' in factory and "<small>${esc(x.sub)}</small>" in factory and "if (btn.disabled) return;" in factory    # entries with a line under them; a disabled menu does not open
    # the recipes: closed, the name and the pill of the resist; open, name and pill and, under them, what the recipe says
    assert "const recipePill = (r) => polChip(r.polarity, t('ex_pol_locked'));" in app   # the tip of the pill says the polarity is the recipe's
    assert "<span class=\"chip ${polarity === 'positive' ? 'pos' : 'neg'}\"${title ? ` title=\"${esc(title)}\"` : ''}><span>${esc(t('pol_' + polarity))}</span></span>" in app   # the text of a pill has its own span: the box that is cut to the lowercase letters
    assert "${polChip(r.polarity)}" in app
    closed = app[app.index("function renderRecipePicker(r) {"):app.index("makePicker('recipe'")]
    assert "recipePill(r)" in closed and "pk-name" in closed and "recipeBrief" in closed
    recipes = app[app.index("makePicker('recipe'"):app.index("// the dosages of the recipe")]
    assert "main: noRecipe(), selected: !state.recipeId" in recipes and "sub: recipeBrief(x)" in recipes and "recipePill(x)" in recipes and "pick: (id) => setRecipe(id)" in recipes
    # the dosages: closed, its name (or its values) and, if it is the last changed, a pill that says so; open, the same and under them the date and the note
    dosages = app[app.index("const dosageTitle = "):app.index("function setRecipe(id) {")]
    assert "d.name || `${sec(d.total_s)} s · ${d.pulses} ×`" in dosages and "[d.name ? `${sec(d.total_s)} s · ${d.pulses} × · ${sec(d.rest_s)} s` : '', fmtDate(d.updated), d.note].filter(Boolean).join(' · ')" in dosages
    assert "latestPill" in dosages and "i === 0 ? latestPill()" in dosages and "selected: d.id === dosage()?.id" in dosages and "btn.disabled = !list.length;" in dosages and "pick: (id) => { state.dosageId = id; syncWorking(); refreshAll(true); updateDirty(); }" in dosages
    assert re.search(r"\.picker \{ --pk-r: 15px; --pk-pad: 14px; position: relative; \}", css)                                      # the radius of the menus: 15px
    assert re.search(r"\.picker-btn \{[^}]*padding: 6px 12px 6px var\(--pk-pad\);[^}]*border-radius: var\(--pk-r\); background: var\(--panel-2\)", css) and re.search(r"\.picker-btn:disabled \{ cursor: default; opacity: \.7; \}", css)
    # open, the list is the continuation of the button: no lower corners for the button, no upper ones for the list, the same colour and outline, a deep shadow
    assert re.search(r"\.picker\.open \.picker-btn \{ border-color: var\(--accent\); border-bottom-color: transparent; border-radius: var\(--pk-r\) var\(--pk-r\) 0 0; \}", css)
    menu = re.search(r"(?m)^\.picker-menu \{([^}]*)\}", css).group(1)
    assert "top: calc(100% - 1px)" in menu and "background: var(--panel-2)" in menu and "border: 1px solid var(--accent); border-top-color: var(--border)" in menu and "border-radius: 0 0 var(--pk-r) var(--pk-r)" in menu
    assert re.search(r"box-shadow: 0 22px 34px -6px rgba\(0, 0, 0, \.8\), 0 10px 16px rgba\(0, 0, 0, \.55\)", menu)                    # much deeper than a card's: it must come off what is under it
    assert "@keyframes pk-open" in css and "@keyframes pk-close" in css and "prefers-reduced-motion: no-preference" in css           # it unrolls from the button and rolls up again (not for who asked for less movement)
    assert re.search(r"\.picker\.closing \.picker-menu \{ animation: pk-close \.16s ease-in forwards; \}", css) and re.search(r"\.picker\.open \.pk-chev \{ transform: rotate\(180deg\); \}", css)
    # closing: the list stays (and the button keeps its shape) while it rolls up, then it is hidden; not at all for who asked for less movement
    assert "picker.classList.add('closing'); rolling = setTimeout(finish, 170);" in factory and "menu.hidden = true; picker.classList.remove('open', 'closing');" in factory
    assert "matchMedia('(prefers-reduced-motion: reduce)').matches" in factory and "picker.classList.add('open'); menu.hidden = false;" in factory and "if (rolling) finish();" in factory
    entry = re.search(r"(?m)^\.picker-menu button \{([^}]*)\}", css).group(1)
    assert "min-height: 52px" in entry and "justify-content: center" in entry and "border-radius: calc(var(--pk-r) - 4px)" in entry       # every entry as tall as those with two lines
    assert re.search(r"\.picker-menu small \{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap;", css) and re.search(r"\.picker-menu button\[aria-selected=\"true\"\] \{ background: color-mix", css)
    assert re.search(r"\.recipe-info \{[^}]*padding-left: calc\(1px \+ 14px\);", css)                                              # the information under the menu of the recipe in line with the text inside it
    assert 'id="dosage-age"' not in html and "dosage-age" not in app and "ex_dosage_age" not in JS["i18n.js"] and "ex_ago_" not in JS["i18n.js"]   # the line «Values of … · 3 days ago» is gone


def test_the_menu_of_the_printer_in_use_has_the_thumbnail_of_each_printer_beside_its_name_and_size():
    css, app = (STATIC / "css" / "style.css").read_text(), JS["app.js"]
    menu = app[app.index("function openPrinterMenu() {"):app.index("$('#printer-pill').onclick")]
    assert '<span class="pm-thumb">${printerPicture(p, esc)}</span><span class="pm-name">${esc(p.name)}</span><small>${esc(printerSize(p, fmt))}</small>' in menu   # the same picture as the card (its photo, or the drawing)
    assert re.search(r"\.printer-menu button \{ display: grid; grid-template-columns: 30px minmax\(0, 1fr\);", css)
    assert re.search(r"\.printer-menu \.pm-thumb \{ grid-row: 1 / span 2; width: 30px; height: 50px; \}", css) and re.search(r"\.printer-menu \.pm-thumb > :is\(img, svg\) \{[^}]*object-fit: contain;", css)
    assert re.search(r"\.printer-menu \.pm-name, \.printer-menu small \{ grid-column: 2; \}", css)                                 # name and size at the right of the thumbnail


# ---- the file of the board: what the page tells the server, why "Generate" is off, and what it says afterwards ---------------------------
@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_requests_to_the_server_carry_the_values_and_the_recipe_chosen():
    got = node_exposure("""
      const v = { total_s: 40, pulses: 4, rest_s: 2 }, recipe = { id: 'r1', name: 'Dry film', polarity: 'negative', dosages: [{ id: 'd' }], resist: 'x' };
      console.log(JSON.stringify({
        check: e.checkRequest({ p: 1 }, v, recipe), checkNoValues: e.checkRequest({ p: 1 }, null, null), checkHalf: e.checkRequest({ p: 1 }, { total_s: 40, pulses: null, rest_s: 2 }, null),
        keys: Object.keys(e.checkRequest({ p: 1 }, null, null)), gen: e.generateRequest({ p: 1 }, 'negative', v, recipe, 'My board'), genByHand: e.generateRequest({ p: 1 }, 'positive', v, null, ''),
      }));""")
    assert got["check"] == {"project": {"p": 1}, "exposure": {"total_s": 40, "pulses": 4, "rest_s": 2}, "recipe": {"id": "r1", "name": "Dry film", "polarity": "negative"}}   # only what a check reads of the recipe
    assert got["checkNoValues"] == {"project": {"p": 1}, "exposure": None, "recipe": None} and got["keys"] == ["project", "exposure", "recipe"]        # the key is there even with no values: without it the server only checks the layout
    assert got["checkHalf"]["exposure"] is None                                                                                  # half-typed values are no values
    assert got["gen"] == {"project": {"p": 1}, "polarity": "negative", "exposure": {"total_s": 40, "pulses": 4, "rest_s": 2},
                          "recipe": {"id": "r1", "name": "Dry film", "polarity": "negative"}, "name": "My board", "supersample": 16}
    assert got["genByHand"]["recipe"] is None and got["genByHand"]["name"] is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_generate_button_says_why_it_is_off_in_this_order():
    got = node_exposure("""
      const bad = { code: 'x', blocking: true }, warn = { code: 'w', blocking: false }, okay = { boards: true, printerIssues: [], issues: [], checkFailed: false, checking: false };
      const b = (o) => e.generateBlock({ ...okay, ...o });
      console.log(JSON.stringify([b({}), b({ boards: false, printerIssues: [bad] }), b({ printerIssues: [warn, bad], issues: [bad], checkFailed: true }),
        b({ checkFailed: true, checking: true, issues: [bad] }), b({ checking: true, issues: [bad] }), b({ issues: [warn, { code: 'first', blocking: true }, bad] }), b({ issues: [warn] })]));""")
    assert got == [None,                                                     # nothing blocks: the button is on
                   {"kind": "no_board"},                                     # first of all: nothing to make
                   {"kind": "issue", "issue": {"code": "x", "blocking": True}},                     # the printer's own problem before the project's
                   {"kind": "check_failed"},                                 # a check that failed says so, whatever the old issues were
                   {"kind": "checking"},                                     # the checks still on their way: wait
                   {"kind": "issue", "issue": {"code": "first", "blocking": True}},                  # the first that blocks, not the first one
                   None]                                                     # warnings only inform


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_time_is_said_as_people_say_it_and_the_summary_of_the_server_is_read_with_care():
    got = node_exposure("""
      const s = { layers: 4, flash_s: 10, rest_s: 2, total_light_s: 40, estimated_s: 48, lit_area_mm2: 10168.5, details: {} };
      const d = { id: 'd', printer_id: 'p', updated: '2026-10-12T14:30:05Z', total_s: 40, pulses: 4, rest_s: 2, name: 'fine' };
      console.log(JSON.stringify({ t: [0, 48, 59.6, 60, 80, 725, 3600, 7500, 7260].map(e.durationText), ok: e.parseSummary(JSON.stringify(s)).layers, bad: [e.parseSummary(''), e.parseSummary('{'), e.parseSummary('[]'), e.parseSummary('{}')],
        byHand: e.resultOf(s, { recipe: null, dosage: null, values: { total_s: 40, pulses: 4, rest_s: 2 } }), typed: e.resultOf(s, { recipe: { name: 'R' }, dosage: null, values: null }).how,
        same: e.resultOf(s, { recipe: { name: 'R' }, dosage: d, values: { total_s: 40, pulses: 4, rest_s: 2 } }).how.edited, edited: e.resultOf(s, { recipe: { name: 'R' }, dosage: d, values: { total_s: 41, pulses: 4, rest_s: 2 } }).how.edited }));""")
    assert got["t"] == ["0 s", "48 s", "1 min", "1 min", "1 min 20 s", "12 min 5 s", "1 h", "2 h 05 min", "2 h 01 min"]
    assert got["ok"] == 4 and got["bad"] == [None, None, None, None]
    assert got["byHand"] == {"layers": 4, "flash": 10, "rest": 2, "total": 40, "estimated": 48, "area_cm2": 101.685, "how": {"kind": "manual"}}
    assert got["typed"] == {"kind": "typed", "recipe": "R"} and got["same"] is False and got["edited"] is True


def test_the_exposure_panel_makes_the_file_and_says_what_it_made():
    html, css, app, i18n, api = HTML, (STATIC / "css" / "style.css").read_text(), JS["app.js"], JS["i18n.js"], JS["api.js"]
    expo = section('<section class="panel sec-expo"', '<footer class="side-statusbar"')
    assert expo.index('id="summary"') < expo.index('id="btn-generate"') < expo.index('id="gen-reason"') < expo.index('id="gen-result"') < expo.index('id="nolib-note"')   # the summary, the button, why it is off, what the file did
    assert 'id="btn-generate" data-i18n="ex_generate" disabled' in expo and 'ex_generate_soon' not in expo and 'aria-live="polite"' in expo.split('id="gen-reason"')[0][-60:] + 'aria-live="polite"'
    assert re.search(r'<div class="callout ok small gen-result" id="gen-result" role="group" aria-labelledby="gen-res-title" hidden>', expo)   # a div: a section would end the panel for the tests that cut it
    assert re.search(r"\.callout\.ok \{ border-color: var\(--ok\); \}", css) and re.search(r"\.gen-reason:empty \{ display: none; \}", css)
    assert "const checkRequest" not in app and "checkRequest(apiProject(), state.working, recipe())" in app                                      # the checks carry the values and the recipe
    assert re.search(r"else \$\('#summary'\)\.textContent = t\('ex_summary_none'\);\n  scheduleCheck\(\);", app)                                 # whenever the panel is drawn the checks are asked again
    assert "generateRequest(apiProject(), state.polarity, values, r, projectName())" in app and "$('#btn-generate').onclick = generateFile;" in app
    fn = app[app.index("async function generateFile()"):app.index("$('#btn-generate').onclick")]
    assert fn.index("const sig = genSignature(), values = state.working, r = recipe(), d = dosage();") < fn.index("api.generateFile(")        # what is made of is what was in the panel when it was clicked
    assert "download(out.blob, filename);" in fn and "catch (e) { if (generationFailed(e)) scheduleCheck(); }" in fn
    assert "finally { state.gen.busy = false; setLoading(false); renderGenerate(); }" in fn                                                      # never left busy
    refused = app[app.index("function generationFailed(e)"):app.index("function renderGenerate()") if app.index("function renderGenerate()") > app.index("function generationFailed(e)") else None]
    assert "e.code === 'generation_blocked'" in refused and "e.code === 'verification_failed' ? t('err_gen_verification_failed')" in refused   # one place says what a refusal is
    render = app[app.index("function renderGenerate()"):app.index("function resultRows(")]
    assert "g.last.sig === genSignature()" in render and "$('#btn-generate').disabled = !!block || g.busy;" in render                            # the frame stays only while nothing it came from changed
    assert "block.issue.code === 'flash_below_minimum' ? t('ex_gen_fix_flash')" in render and i18n.count("ex_gen_fix_flash:") == 2              # the red note over the summary already says it: not twice
    assert "renderGenerate();\n}" in app[app.index("function renderWarnings()"):app.index("function renderStatusSel()")]                           # the warnings and the printer's state decide the button too
    assert "export const generateFile = (request) => withRecovery(() => download('/api/generate', request));" in api                             # a missing file is given again, once
    assert "export const checkProject = (request) => call('/api/check', json(request));" in api


def test_every_check_of_the_exposure_has_a_sentence_in_both_languages():
    app, i18n = JS["app.js"], JS["i18n.js"]
    sent = {"exposure_invalid": "i_exposure_invalid", "recipe_missing": "i_recipe_missing", "dosage_missing": "i_dosage_missing", "polarity_mismatch": "i_polarity_mismatch",
            "printer_missing": "i_printer_missing", "flash_below_minimum": "ex_flash_below", "flash_beyond_proven": "ex_flash_beyond"}
    codes = set(re.findall(r'^    ([A-Z_]+) = "([a-z_]+)"', (SRC / "model" / "issues.py").read_text(), re.M))
    for name in sent:
        assert any(code == name for _, code in codes), name                                                   # these are codes the server has
    issue_text = app[app.index("function issueText(i)"):app.index("// tooltip for the warning icons")]
    for code, key in sent.items():
        assert (f"case '{code}':" in issue_text) or f"i_{code}" == key and f"has('i_' + i.code)" in issue_text, code      # a case, or the generic `i_<code>`
        assert i18n.count(f"{key}:") == 2, key                                                                # in Italian and in English
    for code in ("mask_all_dark", "write_failed", "gen_verification_failed", "flash_below_minimum", "template_missing", "mask_shape", "generation_blocked"):
        assert i18n.count(f"err_{code}:") == 2, code


# ---- the file of the calibration ladder ---------------------------------------------------------------------------------------------
@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_ladder_request_carries_the_values_the_tests_in_order_and_the_same_key_means_the_same_file():
    r = subprocess.run(["node", "--input-type=module", "-e", f"import * as L from {(STATIC / 'js' / 'ladder.js').as_uri()!r};\n" + """
      const v = { step: 10, bands: 8, pulses: 2, rest: 4, width: 13, height: 76, tests: ['rings', 'lines_v', 'fine'], polarity: 'negative', mirror: true, view: 'uv' };
      const plane = { w: 130.56, h: 82.62 }, lim = { min_flash_s: 1, max_proven_flash_s: 20 }, bad = { code: 'x', blocking: true };
      console.log(JSON.stringify({ req: L.ladderRequest(v, 'ld002h'), none: L.ladderRequest(v, null).printer_id,
        sameView: L.ladderKey(v, 'p') === L.ladderKey({ ...v, view: 'material' }, 'p'), otherTests: L.ladderKey(v, 'p') === L.ladderKey({ ...v, tests: ['lines_v'] }, 'p'),
        otherPrinter: L.ladderKey(v, 'p') === L.ladderKey(v, 'q'), reorder: L.ladderKey(v, 'p') === L.ladderKey({ ...v, tests: ['fine', 'lines_v', 'rings'] }, 'p'),
        block: [L.ladderBlock(v, plane, lim, []), L.ladderBlock(v, plane, lim, [bad]), L.ladderBlock({ ...v, step: null }, plane, lim, []), L.ladderBlock({ ...v, step: 8, pulses: 10 }, plane, lim, []),
                L.ladderBlock({ ...v, bands: 12, width: 12 }, plane, lim, []), L.ladderBlock({ ...v, step: 100, pulses: 1 }, plane, lim, []), L.ladderBlock({ ...v, bands: 12, width: 12 }, plane, lim, [bad])
                ].map((b) => b && b.kind) }));"""], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got["req"] == {"printer_id": "ld002h", "supersample": 16, "ladder": {"step": 10, "bands": 8, "pulses": 2, "rest": 4, "width": 13, "height": 76, "tests": ["lines_v", "fine", "rings"],
                                                                            "polarity": "negative", "mirror": True}}        # the view is a way to look, not part of the file; the tests are in the order they are laid out
    assert got["none"] is None and got["sameView"] is True and got["reorder"] is True and got["otherTests"] is False and got["otherPrinter"] is False
    assert got["block"] == [None, "printer", "values", "ladder", "ladder", None, "printer"]                                 # a flash over the longest tried only warns; the printer comes first


def test_the_ladder_page_makes_its_file_and_keeps_the_picture_its_size():
    app, api, css = JS["app.js"], JS["api.js"], (STATIC / "css" / "style.css").read_text()
    assert "export const generateLadder = (request) => download('/api/generate/ladder', request);" in api
    fn = app[app.index("async function generateLadderFile()"):app.index("$('#btn-ld-generate').onclick")]
    assert fn.index("const L = state.ladder, key = ladderKey(L, state.printerId), request = ladderRequest(L, state.printerId);") < fn.index("api.generateLadder(request)")   # what the page held when it was clicked
    assert "download(out.blob, filename);" in fn and "catch (e) { generationFailed(e); }" in fn and "finally { state.ldGen.busy = false; setLoading(false); renderLadderGen(); }" in fn
    render = app[app.index("function renderLadderGen()"):app.index("async function generateLadderFile()")]
    assert "ladderBlock(L, state.plane, p?.limits, printerIssues(state.printers, state.printerId))" in render and "g.last.key === ladderKey(L, state.printerId)" in render
    assert "why.textContent = block?.kind === 'printer' ? text : ''" in render                                              # only the printer's own problem is said again (the notes say the rest)
    assert "renderLadderGen(); ldDraw();" in app and "$('#btn-ld-generate').onclick = generateLadderFile;" in app
    assert re.search(r"\.gen-done::before \{ content: \"\\2713\"; margin-right: 6px; color: var\(--ok\)", css)
    i18n = JS["i18n.js"]
    for key in ("ld_res_line", "i_ladder_too_big", "i_ladder_no_tests", "i_ladder_tests_dropped", "err_sequence_unsupported"):
        assert i18n.count(f" {key}: '") == 2, key
    assert "case 'ladder_too_big':" in app


def test_without_a_library_the_values_last_typed_come_back_when_the_page_opens():
    """`--no-library`: the browser remembers the last values (`gs-manual`); the page reads them as soon as it knows it has no library, not only when a project is opened."""
    app = JS["app.js"]
    fn = app[app.index("async function loadLibrary()"):app.index("async function libCall(")]
    assert "if (!state.info?.library) { state.library = { on: false, recipes: [], problems: [], loaded: true }; syncWorking(); return; }" in fn.split("\n", 2)[1]       # the first thing it does
