// GerberSLAp: wiring of the UI to the backend. The browser holds the layout (boards, placements, which layers are on); the backend reads
// the Gerber files, sends the shapes to draw, computes the exact mask and the layout checks. Nothing about a board is invented here.
import { t, setLang, getLang, applyI18n, fmt, has } from './i18n.js';
import { fromApi, toApiProject, cloneBoard, cursorText, selectionText, cleanProjectName, extent, flagsTitle, isProjectFile, margins, overlaps, anchorTo, flagsText, areaOutline, boardTitle, isStacked, moveLayer, nextBoardNumber, pickPrinter, pitchLabel, planeOf, planeSize, printerIssues, printerLine, printerSize, projectStem, stepLayer, TURN, warningStatus } from './model.js';
import { checkRequest, dosagesFor, dropRecipe, durationText, flashNote, flashOf, generateBlock, generateRequest, heightFrames, isComplete, nextSort, openAfterToggle, parseRemembered, parseSummary, preselected, quantity, recipeBrief, putRecipe, reconcileRecipe, resultOf, sameValues, sortDosages, splitUnit, valuesOf } from './exposure.js';
import { createPlane } from './plane.js';
import { MAX_ZOOM, TESTS, boxPoint, fitBox, isValid, ladderBlock, ladderIssues, ladderKey, ladderLayout, ladderRequest, ladderSvg, panBox, zoomBox, zoomOf, parseLadder } from './ladder.js';
import { anchorSize, marginsMap } from './placement.js';
import { printerCards, printerPicture } from './printercards.js';
import { createWorkCopy, formatWhen, indexedDbStore, saveStatus, webLocks } from './workcopy.js';
import { LANGS } from './flags.js';
import * as api from './api.js';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } } };
const ROLE_VAR = { copper: '--copper', outline: '--outline', mask: '--mask', silk: '--silk' };
const ROLE_COLOR = { copper: 'var(--copper)', outline: 'var(--outline)', mask: 'var(--mask)', silk: 'var(--silk)' };

// the plane (a placeholder here) comes from the printer, as soon as the backend answers with `/api/info`; `printerNote` is a printer a project asked for and this version has not
const state = { plane: { w: 100, h: 100, px: [1000, 1000], pitch: 0.1, name: '' }, info: null, printers: [], printerId: null, defaultPrinter: null, printerNote: null,
                polarity: 'positive', boards: [], selectedId: null,
                recipeId: null, dosageId: null,           // the recipe the project uses (none: polarity and values by hand) and the dosage it chose (none: the last changed one is preselected)
                working: null,                            // the three values in the panel: the dosage's, or typed; not saved until the person saves them
                library: { on: false, recipes: [], problems: [], loaded: false },     // the server's recipe library, as the page last read it
                view: 'plane', mode: 'material', grid: true, snap: true, minOutline: 0.3, nextId: 1, history: [], hi: -1, anchor: 'TL',
                open: new Set(),                          // expanded cards: UI state, deliberately outside undo/redo
                issues: [], checkFailed: false, pending: 0,
                ldGen: { busy: false, last: null },                       // the file of the calibration ladder: being made, and the last one made (its line stays while the values are the same)
                gen: { busy: false, checking: false, last: null },       // the file of the board: being made, the checks still on their way, and the last one made (its frame stays while nothing it came from changes)
                ladder: parseLadder(store.get('gs-ladder')), ldBox: null, ldKey: '', ldGood: null,        // the Calibration ladder's values (remembered by the browser), the part of the plane shown, which plane that was, and the last good values
                name: '', saved: '', savedAt: null };     // the project's name (from the file it came from), the fingerprint of what was last saved and when

const selected = () => state.boards.find((b) => b.id === state.selectedId) || null;
const outside = (b) => { const m = margins(b, state.plane); return m.left < -1e-6 || m.right < -1e-6 || m.front < -1e-6 || m.back < -1e-6; };
const boardName = (id) => { const b = state.boards.find((q) => q.id === id); return b ? boardTitle(b) : ''; };
const drawn = (l) => l.role !== 'drill' && l.role !== 'ignore';                 // layers that draw something

// ---------------------------------------------------------------------------------------------------------------
// layer colours: default = theme colour of the role; a layer can override it
function cssHex(varName) {
  const el = document.createElement('span'); el.style.color = `var(${varName})`; document.body.append(el);
  const m = getComputedStyle(el).color.match(/[\d.]+/g) || [0, 0, 0]; el.remove();
  return '#' + [0, 1, 2].map((i) => Math.round(+m[i]).toString(16).padStart(2, '0')).join('');
}
const layerHex = (l) => l.color || cssHex(ROLE_VAR[l.role]);
const layerOf = (el) => state.boards.find((b) => b.id === el.dataset.board)?.layers.find((l) => l.id === el.dataset.layer);

// ---------------------------------------------------------------------------------------------------------------
// what the backend says, as sentences
const simple = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => typeof v === 'string' || typeof v === 'number'));   // the parameters a sentence can show
function errorText(e, name = '') {
  let text;
  if (!(e instanceof api.ApiError)) text = t('err_unknown');
  else if (e.code === 'incompatible_export' && has('err_incompat_' + (e.params.reason || ''))) text = t('err_incompat_' + e.params.reason);
  else if (has('err_' + e.code)) text = t('err_' + e.code, { ...simple(e.params), mb: Math.round((e.params.max_bytes || 0) / 1048576), name: e.params.name || '' });
  else text = `${t('err_unknown')} (${e.code})`;
  return name ? `${name}: ${text}` : text;
}
const layerStatusText = (status) => (has('ls_' + status.code) ? t('ls_' + status.code, status.params || {}) : String(status.code));
function issueText(i) {
  const b = state.boards.find((q) => q.id === i.board_id), name = b ? boardTitle(b) : '', p = i.params || {};
  const layer = b?.layers.find((l) => l.id === i.layer_id)?.name || '';
  switch (i.code) {
    case 'board_outside_plane': return t('w_out', { name });
    case 'boards_overlap': return t('w_overlap', { a: boardName(p.board_a), b: boardName(p.board_b) });
    case 'board_layer_sum': return t('w_sum', { name });
    case 'layer_types_mixed': return t('w_mixed');
    case 'layer_issue': return t('w_layer', { name, layer, msg: layerStatusText({ code: p.status_code, params: p }) });
    case 'job_size_mismatch': return t('i_job_size_mismatch', { name, job: p.job_mm.map((v) => fmt(v, 2)).join(' × '), outline: p.outline_mm.map((v) => fmt(v, 2)).join(' × ') });
    case 'files_unrecognised': return t('i_files_unrecognised', { name, names: (p.names || []).join(', ') });
    case 'board_area_estimated': return t(has('i_board_area_estimated_' + p.reason) ? 'i_board_area_estimated_' + p.reason : 'i_board_area_estimated', { name });
    case 'template_missing': case 'template_invalid': case 'template_lift_large': case 'printer_settings_invalid': case 'printer_config_invalid': {
      const pr = currentPrinter();                                                 // these come with the printer in use, so they are about it
      const reason = i.code === 'template_invalid' && has('i_template_invalid_' + p.reason) ? t('i_template_invalid_' + p.reason) : String(p.reason ?? '');
      return t('i_' + i.code, { printer: pr?.name || '', id: pr?.id || '', reason, lift: fmt(p.lift_mm ?? 0, 3), field: p.field || '', message: p.message || '' });
    }
    case 'ladder_too_big': return t('i_ladder_too_big', { w: sec(+p.width_mm.toFixed(1)), h: sec(+p.height_mm.toFixed(1)), pw: fmt(p.plane_w_mm, 2), ph: fmt(p.plane_h_mm, 2) });
    case 'flash_below_minimum': return t('ex_flash_below', { flash: sec(p.flash_s), min: sec(p.min_s) });
    case 'flash_beyond_proven': return t('ex_flash_beyond', { flash: sec(p.flash_s), max: sec(p.max_s) });
    case 'dosage_missing': return t('i_dosage_missing', { printer: printerName(p.printer_id) });
    case 'polarity_mismatch': return t('i_polarity_mismatch', { project: t('pol_' + p.project), recipe: t('pol_' + p.recipe) });
    default: return has('i_' + i.code) ? t('i_' + i.code, { name, layer }) : String(i.code);
  }
}

// tooltip for the warning icons: on hover or focus, and pinned by a click
const tipEl = $('#tip'); let tipPin = null;
function showTip(btn, pin) {
  tipEl.textContent = btn.dataset.tip; tipEl.hidden = false; tipEl.classList.toggle('pinned', !!pin);
  const r = btn.getBoundingClientRect(); tipEl.style.left = Math.max(8, Math.min(innerWidth - 316, r.left - 150)) + 'px'; tipEl.style.top = (r.bottom + 8) + 'px';
}
function hideTip() { tipEl.hidden = true; tipPin = null; }

// ---------------------------------------------------------------------------------------------------------------
// toast, busy, loading
let toastTimer = 0;
function placeToast(el) {                          // centred on the CadWindow, not on the whole screen
  const r = (state.view === 'plane' ? $('#canvas-wrap') : $(`#view-${state.view}`)).getBoundingClientRect();
  el.style.left = Math.round(r.left + r.width / 2) + 'px'; el.style.bottom = Math.round(innerHeight - r.bottom + 18) + 'px'; el.style.maxWidth = Math.max(260, Math.round(r.width - 40)) + 'px';
}
function toast(msg, actionLabel, action) {
  const el = $('#toast'); el.innerHTML = `<span>${esc(msg)}</span>`; el.hidden = false; placeToast(el);
  if (actionLabel) { const b = document.createElement('button'); b.textContent = actionLabel; b.onclick = () => { action(); el.hidden = true; }; el.append(b); }
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.hidden = true; }, actionLabel ? 6000 : 6500);
}
function setLoading(on, key = 'loading') { $('#loading span').textContent = t(key); $('#loading').hidden = !on; }
let exactBusy = false;
function renderBusy() { $('#st-busy').textContent = state.pending ? t('loading_shapes') : exactBusy ? t('computing') : ''; }

// ---------------------------------------------------------------------------------------------------------------
// history (undo / redo): boards are plain data, so a snapshot is their JSON
const snapshot = () => JSON.stringify({ boards: state.boards, selectedId: state.selectedId });
function commit() { updateDirty(); state.history = state.history.slice(0, state.hi + 1); state.history.push(snapshot()); if (state.history.length > 80) state.history.shift(); state.hi = state.history.length - 1; updateUndo(); }
function restore(s) { const o = JSON.parse(s); state.boards = o.boards; state.selectedId = o.selectedId; refreshAll(); }
function undo() { if (state.hi > 0) { state.hi--; restore(state.history[state.hi]); updateUndo(); } }
function redo() { if (state.hi < state.history.length - 1) { state.hi++; restore(state.history[state.hi]); updateUndo(); } }
function updateUndo() { $('#btn-undo').disabled = state.hi <= 0; $('#btn-redo').disabled = state.hi >= state.history.length - 1; }
let commitTimer = 0;
function commitSoon() { clearTimeout(commitTimer); commitTimer = setTimeout(commit, 450); }

// ---------------------------------------------------------------------------------------------------------------
// the shapes the plane draws: one request per layer (and per set of holes and outline width), kept for the session
const shapeCache = new Map();
function toPath(polygons) {
  const p = new Path2D();
  for (const rings of polygons) for (const ring of rings) { p.moveTo(ring[0], ring[1]); for (let i = 2; i < ring.length; i += 2) p.lineTo(ring[i], ring[i + 1]); p.closePath(); }
  return p;
}
const holesOf = (b) => b.layers.find((l) => l.role === 'drill' && l.on)?.files ?? [];
// a mask is the board's area minus its openings: it depends on the outline file and on the board's size as well
const areaOf = (b) => ({ outline: areaOutline(b)?.files[0] ?? null, size: { width_mm: b.w, height_mm: b.h } });
const areaKey = (b) => { const a = areaOf(b); return `${a.outline?.sha256 ?? ''}:${b.w}x${b.h}`; };
const shapeKey = (b, l) => [l.role, l.files.map((f) => f.sha256).join('+'), holesOf(b).map((f) => f.sha256).join('+'), l.role === 'outline' ? state.minOutline : '', l.role === 'mask' ? areaKey(b) : '', b.cx, b.cy].join('|');
async function loadShapes(e, b, l) {
  state.pending++; renderBusy();
  try {
    const r = await api.getGeometry({ role: l.role, files: l.files, holes: holesOf(b), center: [b.cx, b.cy], min_outline_mm: state.minOutline, ...(l.role === 'mask' ? { area: areaOf(b) } : {}) });
    e.paths = [toPath(r.polygons)];
  } catch (err) { e.paths = []; toast(errorText(err, l.name)); }
  finally { state.pending--; renderBusy(); plane.draw(); }
}
const geo = {
  paths(b, l) {                                           // null while loading; the plane draws the board again when they arrive
    if (!drawn(l)) return null;
    const key = shapeKey(b, l); let e = shapeCache.get(key);
    if (!e) {
      e = { paths: null }; shapeCache.set(key, e); loadShapes(e, b, l);
      if (shapeCache.size > 300) shapeCache.delete(shapeCache.keys().next().value);
    }
    return e.paths;
  },
};

// the exact view: the mask the backend computes from the full geometry at the printer's resolution (never a resampled picture)
let exactController = null;
async function exactImage() {
  if (!state.boards.some((b) => b.layers.some((l) => l.on && drawn(l)))) return null;
  exactController?.abort(); exactController = new AbortController();
  try {
    const r = await api.renderMask(apiProject(), state.polarity, exactController.signal);
    return await new Promise((resolve, reject) => { const img = new Image(); img.onload = () => resolve(img); img.onerror = reject; img.src = 'data:image/png;base64,' + r.png; });
  } catch (e) {
    if (e.name === 'AbortError') throw e;
    toast(t('err_exact', { msg: errorText(e) })); return null;
  }
}

// ---------------------------------------------------------------------------------------------------------------
// boards
function freeSpot(w, h) {
  const p = state.plane;
  for (let y = h / 2 + 2; y <= p.h - h / 2 - 2; y += 4) for (let x = w / 2 + 2; x <= p.w - w / 2 - 2; x += 4) {
    const probe = { x, y, w, h, angle: 0, mirror: false };
    if (!state.boards.some((b) => overlaps(probe, b))) return [x, y];
  }
  return [p.w / 2, p.h / 2];
}
async function addFiles(files) {
  const zips = files.filter((f) => /\.zip$/i.test(f.name)), projects = files.filter((f) => isProjectFile(f.name));
  if (projects.length > 1) { toast(t('err_one_project')); return; }
  if (projects.length && !(await openProjectFile(projects[0]))) return;           // a project replaces the work; zips dropped with it are added after
  if (!zips.length) { if (!projects.length) toast(t('toast_unsupported')); return; }
  setLoading(true, 'uploading'); let n = 0;
  try {
    for (const f of zips) {
      const id = 'b' + state.nextId++;
      try {
        const r = await api.openZip(f, id, false, state.printerId);
        const b = fromApi(r.board, r.issues, r.cad);
        if (state.boards.length) { [b.x, b.y] = freeSpot(b.w, b.h); }
        state.boards.push(b); state.open.add(b.id); state.selectedId = b.id; n++;
      } catch (e) { toast(errorText(e, f.name)); }
    }
  } finally { setLoading(false); }
  if (n) { const first = state.boards.length === n; commit(); refreshAll(); if (first) plane.fit(); toast(n === 1 ? t('toast_added_one') : t('toast_added', { n })); }
}
function removeBoard(id) {
  const before = snapshot(), b = state.boards.find((q) => q.id === id); if (!b) return;
  state.boards = state.boards.filter((q) => q.id !== id); if (state.selectedId === id) state.selectedId = null;
  commit(); refreshAll(); toast(t('toast_removed', { name: boardTitle(b) }), t('undo_action'), () => { restore(before); commit(); });
}
function toggleLayer(bid, lid, on) {
  const b = state.boards.find((q) => q.id === bid), l = b.layers.find((q) => q.id === lid);
  if (!on && drawn(l) && b.layers.filter((q) => q.on && drawn(q) && q.id !== lid).length === 0) {
    const holesOn = b.layers.some((q) => q.role === 'drill' && q.on);   // only the holes would be left, or nothing at all
    toast(t(holesOn ? 'toast_only_holes' : 'toast_all_off')); refreshAll(); return;
  }
  l.on = on; commit(); refreshAll();
}

// ---------------------------------------------------------------------------------------------------------------
// the order of the layers of the stack: drag the grip, or Alt + up/down on a layer (up/down alone on the grip). The first of the list is the top layer,
// drawn last in the Material view; the exposure is the sum of the layers on, so the order never changes what is exposed.
function reorderLayer(bid, lid, next, focusGrip) {
  const b = state.boards.find((q) => q.id === bid), l = b?.layers.find((q) => q.id === lid);
  if (!next) return false;
  b.layers = next; commit(); refreshAll(true);
  const stack = b.layers.filter(isStacked);
  $('#lay-live').textContent = t('layer_moved', { name: l.name, pos: stack.indexOf(l) + 1, n: stack.length });
  if (focusGrip) document.querySelector(`.grip[data-board="${bid}"][data-layer="${lid}"]`)?.focus();
  return true;
}
let drag = null;
const dragSlot = (d, e) => {                               // the gap between rows the pointer is in (0 = above the first), and where the layer would end up
  let slot = 0;
  for (const r of d.rows) { const q = r.getBoundingClientRect(); if (e.clientY > q.top + q.height / 2) slot++; }
  return { slot, to: slot > d.from ? slot - 1 : slot };
};
function endDrag(drop, e) {
  if (!drag) return;
  const d = drag; drag = null;
  d.rows.forEach((r) => r.classList.remove('dragging', 'drop-above', 'drop-below'));
  const b = state.boards.find((q) => q.id === d.board);
  if (drop && b) reorderLayer(d.board, d.layer, moveLayer(b.layers, d.layer, dragSlot(d, e).to), true);
}
$('#boards-list').addEventListener('pointerdown', (e) => {
  const grip = e.target.closest('.grip'); if (!grip || e.button !== 0) return;
  const row = grip.closest('.layer'), rows = [...row.parentElement.querySelectorAll('.layer.stacked')];
  drag = { board: grip.dataset.board, layer: grip.dataset.layer, rows, from: rows.indexOf(row), pointer: e.pointerId };
  grip.setPointerCapture(e.pointerId); row.classList.add('dragging'); e.preventDefault();
});
$('#boards-list').addEventListener('pointermove', (e) => {
  if (!drag || e.pointerId !== drag.pointer) return;
  const { slot, to } = dragSlot(drag, e);
  drag.rows.forEach((r) => r.classList.remove('drop-above', 'drop-below'));
  if (to !== drag.from) drag.rows[Math.min(slot, drag.rows.length - 1)].classList.add(slot < drag.rows.length ? 'drop-above' : 'drop-below');
});
$('#boards-list').addEventListener('pointerup', (e) => { if (drag && e.pointerId === drag.pointer) endDrag(true, e); });
$('#boards-list').addEventListener('pointercancel', () => endDrag(false));
$('#boards-list').addEventListener('keydown', (e) => {
  if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
  const grip = e.target.closest('.grip'), row = e.target.closest('.layer.stacked');
  if (!row || !(grip || e.altKey)) return;
  e.preventDefault(); e.stopPropagation();                                    // not the board's own arrow keys
  const b = state.boards.find((q) => q.id === row.dataset.board); if (!b) return;
  reorderLayer(b.id, row.dataset.layer, stepLayer(b.layers, row.dataset.layer, e.key === 'ArrowUp' ? -1 : 1));
});
window.addEventListener('keydown', (e) => { if (drag && e.key === 'Escape') endDrag(false); }, true);

// ---------------------------------------------------------------------------------------------------------------
// the printer in use: it fixes the plane (the size of the LCD and its pixels) that is drawn and that the server computes on. The pill over the plane
// says which one it is and, when the app has more than one, opens the list; choosing another resizes the plane and leaves the boards where they are
// (those that no longer fit get the usual warning). Nothing here knows a printer: the list comes from the server.
const currentPrinter = () => state.printers.find((p) => p.id === state.printerId) || null;
function setPrinter(id) {                                                       // the state only: the plane the page draws
  const p = state.printers.find((q) => q.id === id); if (!p) return;
  state.printerId = id; state.plane = planeOf(p);
}
function selectPrinter(id) {
  if (id === state.printerId || !state.printers.some((p) => p.id === id)) return;
  setPrinter(id); state.printerNote = null; state.dosageId = null; syncWorking();       // the dosage is looked up again for this printer
  refreshAll(); plane.fit(); updateDirty();
}
const printerTip = (p) => t('printer_tip', { name: p.name, w: fmt(p.plane.width_mm, 2), h: fmt(p.plane.height_mm, 2), pw: p.grid.width, ph: p.grid.height, pitch: pitchLabel(p.grid.pitch, fmt) })
  + (state.printers.length > 1 ? ' ' + t('printer_tip_change') : '');
function renderSideStatus() {                                                 // the SideStatusBar: how the app was started (the flags, and what they mean under the mouse)
  const flags = state.info?.flags ?? [], el = $('#ssb-flags');
  el.textContent = flags.length ? flagsText(flags) : t('ssb_start_plain'); el.classList.toggle('plain', !flags.length);
  $('#side-status').title = flags.length ? flagsTitle(flags, t, has) : t('flags_none_title');
}
function renderPrinter() {
  const p = currentPrinter(), pill = $('#printer-pill'), multi = state.printers.length > 1;
  // the exact view is the plane at the printer's own resolution, so its name carries the size of that printer's pixel
  const res = p ? pitchLabel(p.grid.pitch, fmt) : '';
  $('[data-mode="exact"]').textContent = t('mode_exact', { res }).trim();
  pill.hidden = !p; if (!p) return;
  pill.textContent = printerLine(p, fmt) + (multi ? ' ▾' : '');
  pill.title = printerTip(p); pill.classList.toggle('single', !multi); pill.setAttribute('aria-disabled', String(!multi)); pill.tabIndex = multi ? 0 : -1;
  if (!multi) closePrinterMenu(false);
}
function closePrinterMenu(focus) {
  const menu = $('#printer-menu'); if (menu.hidden) return;
  menu.hidden = true; $('#printer-pill').setAttribute('aria-expanded', 'false'); if (focus) $('#printer-pill').focus();
}
function openPrinterMenu() {
  if (state.printers.length < 2) return;
  const menu = $('#printer-menu');
  menu.innerHTML = state.printers.map((p) => `<button type="button" role="option" data-printer="${esc(p.id)}" aria-selected="${p.id === state.printerId}"><span class="pm-thumb">${printerPicture(p, esc)}</span><span class="pm-name">${esc(p.name)}</span><small>${esc(printerSize(p, fmt))}</small></button>`).join('');
  menu.hidden = false; $('#printer-pill').setAttribute('aria-expanded', 'true');
  (menu.querySelector('[aria-selected="true"]') || menu.querySelector('button'))?.focus();
}
$('#printer-pill').onclick = () => { if ($('#printer-menu').hidden) openPrinterMenu(); else closePrinterMenu(true); };
$('#printer-menu').addEventListener('click', (e) => { const b = e.target.closest('[data-printer]'); if (!b) return; closePrinterMenu(true); selectPrinter(b.dataset.printer); });
$('#printer-menu').addEventListener('keydown', (e) => {
  const items = [...$('#printer-menu').querySelectorAll('button')], i = items.indexOf(document.activeElement);
  if (e.key === 'Escape') { e.preventDefault(); closePrinterMenu(true); }
  else if (e.key === 'ArrowDown') { e.preventDefault(); items[(i + 1) % items.length].focus(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); items[(i + items.length - 1) % items.length].focus(); }
});
document.addEventListener('pointerdown', (e) => { if (!e.target.closest('#printer-menu') && !e.target.closest('#printer-pill')) closePrinterMenu(false); });

// ---------------------------------------------------------------------------------------------------------------
// the project. Save keeps a working copy in this browser (workcopy.js) and Download makes the .gslp file, when it is wanted; Open (or dropping a
// file on the page) replaces the work with a file, which becomes the working copy too. The Gerber files travel inside the project; the server keeps nothing.
const tabStore = { get(k) { try { return sessionStorage.getItem(k); } catch { return null; } }, set(k, v) { try { sessionStorage.setItem(k, v); } catch { /* private mode */ } } };
const wc = createWorkCopy({ store: indexedDbStore(), locks: webLocks(), tabStorage: tabStore });
// What counts as "changed since the last save" is everything the file holds: the boards and what is set for the whole project.
const fingerprint = () => JSON.stringify([state.boards, state.polarity, state.minOutline, state.printerId, state.recipeId, state.dosageId, state.name]);
const isDirty = () => state.boards.length > 0 && fingerprint() !== state.saved;
// Unsaved changes show in two places and nowhere else: the title of the browser tab ("●") and the status bar, whose pill always says when the project
// was last saved and adds "Unsaved" when there are changes since. The pill is not a button and the Save button does not change: it only saves.
function updateDirty() {
  const dirty = isDirty(), chip = $('#st-save');
  document.title = (dirty ? '● ' : '') + 'GerberSLAp';
  const s = saveStatus({ dirty, savedAt: state.savedAt, now: Date.now(), locale: getLang() === 'it' ? 'it-IT' : 'en-GB', t });
  const main = $('#st-save-main'), extra = $('#st-save-extra');
  if (main.textContent !== s.main) main.textContent = s.main;
  const more = s.extra ? ` · ${s.extra}` : ''; if (extra.textContent !== more) extra.textContent = more;
  chip.title = s.title; chip.classList.toggle('warn', s.warn);
}
// The ProjectName in the MenuBar: the name the project has (the one in its file, else the file's own name), "New Project" until it has one. A double click (or
// Enter or F2 with the focus on it) turns it into a field: Enter, or leaving the field, keeps the new name; Esc keeps the old one. It is the name of the file that
// Download makes (the server only makes it safe for a file name), it goes into the file and into the working copy, and changing it makes the project "unsaved".
function renderProjectName() {
  const el = $('#project-name'); if (el.querySelector('input')) return;      // it is being edited: the field is not taken away
  const name = state.name || t('project_untitled'); el.textContent = name; el.title = name + '\n' + t('project_rename_hint');
  el.setAttribute('aria-label', name + '. ' + t('project_rename_hint'));
}
function setProjectName(raw) {
  const name = cleanProjectName(raw); if (name === state.name) return;
  state.name = name; renderProjectName(); updateDirty();
}
function editProjectName() {
  const el = $('#project-name'); if (el.querySelector('input')) return;
  const input = document.createElement('input');
  input.type = 'text'; input.className = 'projname-input'; input.maxLength = 200; input.value = state.name; input.placeholder = t('project_untitled');
  input.setAttribute('aria-label', t('project_name_label'));
  el.textContent = ''; el.append(input); input.focus(); input.select();
  let done = false;
  const finish = (keep, refocus) => {
    if (done) return; done = true; const value = input.value; el.textContent = '';
    if (keep) setProjectName(value);
    renderProjectName(); if (refocus) el.focus();                           // after Enter or Esc the keyboard stays on the name; after a click elsewhere the focus is where that click put it
  };
  input.onkeydown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); finish(true, true); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(false, true); }
  };
  input.onblur = () => finish(true, false);
}
$('#project-name').addEventListener('dblclick', editProjectName);
$('#project-name').addEventListener('keydown', (e) => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === 'F2')) { e.preventDefault(); editProjectName(); } });
const projectName = () => (state.name || state.boards[0]?.name || 'progetto').slice(0, 200);
function download(blob, filename) {
  const url = URL.createObjectURL(blob), a = document.createElement('a');
  a.href = url; a.download = filename; document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
const buildProject = () => api.saveProject({
  project: apiProject(), name: projectName(),
  info: Object.fromEntries(state.boards.map((b) => [b.id, { cad: b.cad || null, notes: b.notes || [] }])),
});
async function saveProject() {
  if (!state.boards.length) { toast(t('nothing_to_save')); return; }
  const fp = fingerprint(); setLoading(true, 'saving');                       // what is saved is the state now, not what it becomes while this runs
  try {
    const { blob } = await buildProject();
    state.savedAt = await wc.save({ name: state.name, boards: state.boards.length, bytes: await blob.arrayBuffer() });
    state.saved = fp; updateDirty();
    toast(t('toast_saved'));
  } catch (e) { toast(e instanceof api.ApiError ? errorText(e) : t('err_browser_storage')); } finally { setLoading(false); }
}
async function downloadProject() {
  if (!state.boards.length) { toast(t('nothing_to_save')); return; }
  setLoading(true, 'preparing');
  try {
    const { blob, filename } = await buildProject();
    download(blob, filename);
    if (!state.name) { const was = isDirty(); state.name = projectStem(filename); renderProjectName(); if (!was) state.saved = fingerprint(); updateDirty(); }     // a project with no name takes the one the file got; one that has a name keeps it
    toast(t('toast_downloaded', { name: filename }));
  } catch (e) { toast(errorText(e)); } finally { setLoading(false); }
}
const confirmDiscard = () => new Promise((resolve) => {
  const d = $('#dlg-discard'); d.returnValue = '';
  d.addEventListener('close', () => resolve(d.returnValue === 'ok'), { once: true }); d.showModal();
});
function loadProject(r, fileName, savedAt = null) {
  const boards = r.project.boards.map((b) => fromApi(b, r.info[b.id]?.notes || [], r.info[b.id]?.cad || ''));
  state.boards = boards; state.selectedId = boards[0]?.id ?? null; state.open = new Set(boards.map((b) => b.id));
  const rec = reconcileRecipe(r.project, state.library);                       // the recipe's polarity wins over the one saved, and a recipe that is gone is said
  state.polarity = rec.polarity; state.recipeId = rec.recipeId; state.dosageId = rec.dosageId;
  state.minOutline = r.project.min_outline_mm; $('#set-outline').value = state.minOutline;
  state.nextId = nextBoardNumber(boards);
  const pick = pickPrinter(r.project.printer_id, state.printers, state.printerId, state.defaultPrinter);
  setPrinter(pick.id); state.printerNote = pick.unknown;                       // a printer this version does not have is said, not replaced in silence
  syncWorking();
  state.name = cleanProjectName(r.name || '') || projectStem(fileName) || ''; state.history = []; state.hi = -1; commit();            // the project's own name first: the file's may have been renamed or made safe
  state.saved = fingerprint(); state.savedAt = savedAt; refreshAll(); plane.fit(); updateDirty();
  if (rec.notice) setTimeout(() => toast(noticeText(rec.notice)), 300);
}
async function openProjectFile(file) {
  if (isDirty() && !(await confirmDiscard())) return false;
  setLoading(true, 'opening_project');
  try {
    const r = await api.openProject(file);
    loadProject(r, file.name);
    try { state.savedAt = await wc.save({ name: state.name, boards: state.boards.length, bytes: await file.arrayBuffer() }); updateDirty(); } catch { /* no storage: it just is not kept */ }
    toast(t('toast_project_opened', { name: r.name || file.name }));
    return true;
  } catch (e) { toast(errorText(e, file.name)); return false; } finally { setLoading(false); }
}

// ---- getting the work back: after a reload, after a closed tab is reopened, and after the server forgot the files
const boardsText = (n) => (n === 1 ? t('board_count_one') : t('board_count', { n }));
async function restoreEntry(entry) {
  try {
    loadProject(await api.openProject(new File([entry.bytes], 'copy.gslp')), '', entry.savedAt);
    state.name = entry.name || ''; state.saved = fingerprint(); renderProjectName(); updateDirty();
    return true;
  } catch (e) {
    toast(errorText(e, entry.name || ''));
    if (e instanceof api.ApiError && e.status === 422) await wc.discard(entry).catch(() => {});     // a copy the server refuses would be offered for ever
    return false;
  }
}
const askRestore = (entry) => new Promise((resolve) => {
  const d = $('#dlg-restore'), when = formatWhen(entry.savedAt, Date.now(), getLang() === 'it' ? 'it-IT' : 'en-GB').full;
  $('#restore-text').textContent = t('restore_text', { name: entry.name || t('project_untitled'), boards: boardsText(entry.boards), when });
  d.returnValue = ''; d.addEventListener('close', () => resolve(d.returnValue), { once: true }); d.showModal();
});
async function recoverWork() {
  try {
    const own = await wc.load();                                               // this tab's own copy: it was reloaded, or brought back after being closed
    if (own) { if (await restoreEntry(own)) toast(t('toast_restored')); return; }
    const entry = await wc.offer();                                            // the copy of a tab that is gone, never that of one still open
    if (!entry) return;
    const choice = await askRestore(entry);
    if (choice === 'discard') await wc.discard(entry);
    else if (choice === 'restore') { await wc.adopt(entry); if (await restoreEntry({ ...entry, tabId: wc.tabId })) toast(t('toast_restored_other', { name: entry.name || t('project_untitled') })); }
  } catch { /* no IndexedDB, no Web Locks: the page simply starts empty */ }
}
let refilling = null;
api.onFilesMissing(() => (refilling ||= (async () => {                          // all the requests that fail together wait for one refill
  try { const e = await wc.load(); if (!e) return false; await api.openProject(new File([e.bytes], 'copy.gslp')); return true; }
  catch { return false; } finally { setTimeout(() => { refilling = null; }, 0); }
})()));

// ---------------------------------------------------------------------------------------------------------------
// warnings: what the backend finds in the layout, and what it found when it opened each zip
let checkTimer = 0, checkSeq = 0;
function scheduleCheck() { clearTimeout(checkTimer); state.gen.checking = true; renderGenerate(); checkTimer = setTimeout(runCheck, 120); }
async function runCheck() {
  const seq = ++checkSeq;
  if (!state.boards.length) { state.issues = []; state.checkFailed = false; state.gen.checking = false; renderWarnings(); return; }
  try {
    const r = await api.checkProject(checkRequest(apiProject(), state.working, recipe()));            // with the values and the recipe: all the checks, not only the layout
    if (seq === checkSeq) { state.issues = r.issues; state.checkFailed = false; state.gen.checking = false; renderWarnings(); }
  } catch { if (seq === checkSeq) { state.checkFailed = true; state.gen.checking = false; renderWarnings(); } }
}
function computeWarnings() {
  const notes = state.boards.flatMap((b) => b.notes || []);
  const list = [...printerIssues(state.printers, state.printerId), ...notes, ...state.issues].map((i) => ({ lv: i.severity === 'error' ? 'bad' : 'warn', text: issueText(i), id: i.board_id }));
  if (state.printerNote) list.unshift({ lv: 'warn', text: t('w_printer_unknown', { requested: state.printerNote, used: currentPrinter()?.name || '' }), id: null });   // said, not replaced in silence
  return list;
}

// ---------------------------------------------------------------------------------------------------------------
// rendering of the sidebar
// The layers of a board usually share a long prefix ("Flight_Controller_PCB_Copper_Signal_Top.gbr"): show what tells them apart.
function commonPrefix(names) {
  if (names.length < 2) return '';
  let p = names[0];
  for (const n of names) while (!n.startsWith(p)) p = p.slice(0, -1);
  const cut = Math.max(p.lastIndexOf('_'), p.lastIndexOf('-'), p.lastIndexOf(' '), p.lastIndexOf('.')) + 1;       // never inside a word
  return cut >= 3 ? p.slice(0, cut) : '';
}
const countProblems = (b) => b.layers.filter((l) => l.role !== 'ignore' && l.status.level !== 'ok');
// The list is drawn again after almost every action; the keyboard focus must stay on the same control (the switch, the grip, the colour) or a
// keyboard user would be thrown back to the top of the page each time.
function focusKey() {
  const a = document.activeElement; if (!a || !$('#boards-list').contains(a)) return null;
  const kind = a.matches('input[role="switch"]') ? 'input[role="switch"]' : a.matches('.grip') ? '.grip' : a.matches('.colorin') ? '.colorin' : null;
  return kind && a.dataset.board ? `${kind}[data-board="${a.dataset.board}"][data-layer="${a.dataset.layer}"]` : null;
}
function renderBoards() {
  hideTip();
  const keep = focusKey();
  $('#boards-list').innerHTML = state.boards.map((b) => {
    const ignoredFiles = b.layers.filter((l) => l.role === 'ignore').flatMap((l) => l.files.map((f) => f.name));   // for the tooltip of the subtitle
    const prefix = commonPrefix(b.layers.flatMap((l) => l.files.map((f) => f.name)));
    const shown = (l) => l.files.map((f) => f.name.slice(prefix.length)).join(' + ');
    const visible = b.layers.filter((l) => l.role !== 'ignore'), stack = visible.filter(isStacked), apart = visible.filter((l) => !isStacked(l));
    const row = (l, movable) => {
      const bad = l.status.level === 'error', msg = l.status.level !== 'ok' ? layerStatusText(l.status) : '';
      const icon = msg ? `<button class="lw ${bad ? 'bad' : 'warn'}" data-act="tip" data-tip="${esc(msg)}" aria-label="${esc(t(bad ? 'e_icon' : 'w_icon') + ': ' + msg)}">${bad ? '✖' : '⚠'}</button>` : '<span></span>';
      const where = isStacked(l) || l.side !== 'top' ? ` · ${t('side_' + l.side)}` : '';            // the side of a copper, mask or silkscreen layer, top included
      const grip = movable ? `<button class="grip" data-act="grip" data-board="${b.id}" data-layer="${l.id}" title="${esc(t('layer_move'))}" aria-label="${esc(t('layer_move_label', { name: l.name }))}">⋮⋮</button>` : '<span></span>';
      return `<div class="layer ${bad ? 'bad' : ''} ${l.role === 'drill' ? 'drill' : ''} ${isStacked(l) ? 'stacked' : ''}" data-board="${b.id}" data-layer="${l.id}"${l.role === 'drill' ? ` title="${esc(t(l.on ? 'holes_on' : 'holes_off'))}"` : ''}>
        ${grip}<label class="switch-row"><input type="checkbox" role="switch" data-board="${b.id}" data-layer="${l.id}" ${l.on ? 'checked' : ''} ${bad ? 'disabled' : ''} aria-label="${esc(l.name)}"><span class="switch" aria-hidden="true"></span></label>
        ${l.role === 'drill' ? '<span class="dotpick static" aria-hidden="true"><span class="dot ring"></span></span>' : `<label class="dotpick" title="${esc(t('pick_color'))}"><input type="color" class="colorin" data-board="${b.id}" data-layer="${l.id}" value="${layerHex(l)}" aria-label="${esc(t('pick_color') + ': ' + l.name)}"><span class="dot" style="background:${l.color || ROLE_COLOR[l.role]}"></span></label>`}
        <span class="name" title="${esc(l.role === 'drill' ? `${l.name}\n${t(l.on ? 'holes_on' : 'holes_off')}` : l.name)}">${esc(shown(l))}</span>
        ${l.color ? `<button class="mini" data-act="resetcolor" data-board="${b.id}" data-layer="${l.id}" title="${esc(t('reset_color'))}" aria-label="${esc(t('reset_color'))}">↺</button>` : '<span></span>'}
        ${icon}<span class="role">${t('role_' + l.role)}${where}</span></div>`;
    };
    // the stack, from its top layer down (the layers can be reordered), then the outline and the holes apart from it
    const rows = `<div class="stack">${stack.map((l) => row(l, stack.length > 1)).join('')}</div>${apart.length ? `<div class="apart">${apart.map((l) => row(l, false)).join('')}</div>` : ''}`;
    const problems = countProblems(b);
    return `<div class="board ${b.id === state.selectedId ? 'sel' : ''}" data-id="${b.id}">
      <div class="board-head"><button class="board-name" data-act="toggle" title="${esc(boardTitle(b))}" aria-expanded="${state.open.has(b.id)}"><span class="chev" aria-hidden="true">▶</span><span class="bn-text">${esc(boardTitle(b))}</span></button>
        <button class="btn sm icon" data-act="dup" title="${esc(t('duplicate'))}" aria-label="${esc(t('duplicate'))}">⧉</button>
        <button class="btn sm icon" data-act="remove" title="${esc(t('remove'))}" aria-label="${esc(t('remove'))}">✕</button></div>
      <div class="board-meta"${ignoredFiles.length ? ` title="${esc(t('ignored_files_tip', { names: ignoredFiles.join(', ') }))}"` : ''}>${fmt(b.w, 1)} × ${fmt(b.h, 1)} mm${b.cad ? ' · ' + esc(t('cad_' + b.cad)) : ''}</div>
      ${state.open.has(b.id)
        ? `<div class="layers">${rows}</div>`
        : `<div class="chips">${b.layers.filter((l) => l.on).map((l) => `<span class="chip sm">${t('role_' + l.role)}</span>`).join('')}${problems.length ? `<span class="chip sm ${problems.some((l) => l.status.level === 'error') ? 'bad' : 'warn'}">⚠ ${problems.length}</span>` : ''}</div>`}</div>`;
  }).join('');
  $('#empty-state').hidden = state.boards.length > 0; $('#btn-expand-all').hidden = $('#btn-collapse-all').hidden = state.boards.length < 2; $('#btn-save').disabled = $('#btn-download').disabled = !state.boards.length;
  if (keep) $(keep)?.focus();
}
function setVal(el, v) { if (document.activeElement !== el) el.value = v; fitValue(el); }
// the number of a value card is as wide as its digits (at least two): the unit hangs right after it and the number stays in the middle of the card
function fitValue(el) { if (el.closest('.vcard')) el.style.width = `${Math.max(2, String(el.value || '').length) + 0.4}ch`; }
function renderPlacement() {
  const b = selected(); $('#place-empty').hidden = !!b; $('#place-body').hidden = !b; if (!b) return;
  setVal($('#in-x'), +b.x.toFixed(2)); setVal($('#in-y'), +b.y.toFixed(2)); setVal($('#in-angle'), +(((b.angle % 360) + 360) % 360).toFixed(1));
  for (const radio of $$('input[name="mirror"]')) radio.checked = (radio.value === 'on') === b.mirror;
  $('#margins').innerHTML = marginsMap(b, state.plane, { t, fmt });
  const pick = anchorSize(state.plane); $('#anchor-pick').style.setProperty('--ap-w', pick.w + 'px'); $('#anchor-pick').style.setProperty('--ap-h', pick.h + 'px');
  fitValue($('#in-ax')); fitValue($('#in-ay'));
}

// ---------------------------------------------------------------------------------------------------------------
// exposure: the recipe, the polarity and the dosage
// The library (recipes, each with its dosages) lives in the server's data folder; the page keeps a copy (`state.library`), and every change goes through the API,
// which answers with the recipe as it is afterwards. A project uses one recipe (`state.recipeId`; none: the polarity and the values are set by hand) and may have
// chosen one of its dosages for the printer in use (`state.dosageId`; if it did not, the last changed one is preselected). With a recipe the polarity is the
// recipe's and cannot be changed. The three values in the panel (`state.working`) start as the dosage's and may be changed without saving: a file can be
// generated with them all the same. No recipe and no dosage are ever taken from another printer in silence. The logic that needs no DOM is in exposure.js.
const recipe = () => (state.library.on ? state.library.recipes.find((r) => r.id === state.recipeId) || null : null);
const dosage = () => preselected(recipe(), state.printerId, state.dosageId);
const manualValues = () => parseRemembered(store.get('gs-manual'));
const syncWorking = () => { state.working = recipe() ? valuesOf(dosage()) : manualValues(); };
const recipeRef = () => { const r = recipe(); return r ? { id: r.id, name: r.name, dosageId: state.dosageId } : null; };
const apiProject = () => toApiProject(state.boards, state.polarity, state.minOutline, state.printerId, recipeRef());
const sec = (n) => fmt(n, Number.isInteger(n) ? 0 : 1);
const fmtDate = (iso) => new Date(iso).toLocaleDateString(getLang() === 'it' ? 'it-IT' : 'en-GB');
const dosageLabel = (d) => `${d.name || `${sec(d.total_s)} s · ${d.pulses} ×`} · ${fmtDate(d.updated)}`;
const printerName = (id) => state.printers.find((p) => p.id === id)?.name || id;
const noticeText = (n) => (n.kind === 'recipe_missing' ? t('ex_toast_recipe_missing', { name: n.name, pol: t('pol_' + state.polarity) })
  : t('ex_toast_pol_changed', { name: n.name, was: t('pol_' + n.was), now: t('pol_' + n.now) }));
function renderExposure() {
  const lib = state.library.on, r = recipe(), cur = dosage(), v = state.working, printer = currentPrinter();
  $('#nolib-note').hidden = lib; $('#recipe-block').hidden = !lib; $('#dosage-block').hidden = !(lib && r);
  if (lib) {
    renderRecipePicker(r);
    $('#recipe-info').innerHTML = r ? [['resist', r.resist], ['ex_development', r.development], ['ex_notes', r.notes]].filter(([, x]) => x).map(([k, x]) => `<div><b>${esc(t(k))}:</b> ${esc(x)}</div>`).join('') : '';
  }
  $('#pol-row').hidden = !!r;                                                // by hand: the switch; with a recipe its pill is the one in the recipe's menu (locked: the tip says so). The frame under it, which says what the polarity does to the views, is always there
  for (const radio of document.querySelectorAll('input[name="polarity"]')) radio.checked = radio.value === state.polarity;
  if (lib && r) {
    renderDosagePicker(dosagesFor(r, state.printerId), cur);
  }
  const missing = lib && !!r && !cur && !v;                                    // a recipe with no dosage for this printer, and nothing typed yet
  $('#dos-missing').hidden = !missing; if (missing) $('#dos-missing-text').textContent = t('ex_missing_text', { recipe: r.name, printer: printer?.name || '' });
  setVal($('#in-total'), v?.total_s ?? ''); setVal($('#in-pulses'), v?.pulses ?? ''); setVal($('#in-rest'), v?.rest_s ?? ''); syncSteppers();
  const ok = isComplete(v), dirty = lib && !!r && !!v && (!cur || !sameValues(v, valuesOf(cur)));
  $('#dos-save-row').hidden = !dirty; $('#btn-dos-update').hidden = !cur; $('#btn-dos-update').disabled = $('#btn-dos-saveas').disabled = !ok;
  const note = flashNote(v, printer?.limits), nEl = $('#flash-note');
  nEl.hidden = !note; nEl.classList.toggle('bad', note?.kind === 'below');
  if (note) nEl.textContent = note.kind === 'below' ? t('ex_flash_below', { flash: sec(note.flash), min: sec(note.min) }) : t('ex_flash_beyond', { flash: sec(note.flash), max: sec(note.max) });
  // the sentence is plain text with its numbers in bold (the template has the <b>; the values are numbers we wrote, escaped all the same)
  if (ok) $('#summary').innerHTML = t('ex_summary', { total: esc(sec(v.total_s)), flashes: esc(t(v.pulses === 1 ? 'u_flashes_one' : 'u_flashes_many', { n: v.pulses })), flash: esc(sec(flashOf(v))), rest: esc(sec(v.rest_s)) });
  else $('#summary').textContent = t('ex_summary_none');
  scheduleCheck();                                                          // the values, the recipe and the polarity are part of what is checked (and decide the Generate button)
}

// The file of the board. The button is on when nothing blocks (`generateBlock`: no board, a printer that is not ready, the checks, in that order); when it is off, the reason is written under it.
// The frame under it says what the last file did and stays while nothing it was made from changes.
const genSignature = () => JSON.stringify([apiProject(), state.polarity, state.working, state.printerId]);
function renderGenerate() {
  const g = state.gen, block = generateBlock({ boards: state.boards.length > 0, printerIssues: printerIssues(state.printers, state.printerId), issues: state.issues,
                                               checkFailed: state.checkFailed, checking: g.checking });
  const text = !block ? '' : block.kind === 'no_board' ? t('ex_gen_no_board') : block.kind === 'check_failed' ? t('err_network') : block.kind === 'checking' ? ''
    : block.issue.code === 'flash_below_minimum' ? t('ex_gen_fix_flash') : issueText(block.issue);         // (the red note over the summary already says it: not twice)
  $('#btn-generate').disabled = !!block || g.busy; $('#btn-generate').title = text;
  const why = $('#gen-reason'); why.textContent = text; why.classList.toggle('bad', block?.kind === 'issue' || block?.kind === 'check_failed');
  const show = !!g.last && g.last.sig === genSignature();
  $('#gen-result').hidden = !show;
  if (show) $('#gen-res-list').innerHTML = resultRows(g.last);
}
function resultRows({ filename, result: r }) {
  const how = r.how.kind === 'manual' ? ['ex_res_values', t('ex_res_manual')]
    : r.how.kind === 'typed' ? ['ex_res_recipe', t('ex_res_typed', { recipe: r.how.recipe })]
    : ['ex_res_recipe', `${r.how.recipe} · ${dosageLabel(r.how.dosage)}${r.how.edited ? ' · ' + t('ex_res_edited') : ''}`];
  return [['ex_res_file', filename], ['ex_res_layers', t('ex_res_layers_v', { n: r.layers, flash: sec(r.flash), rest: sec(r.rest) })], ['ex_res_light', `${sec(r.total)} s`],
    ['ex_res_time', durationText(r.estimated)], ['ex_res_area', `${fmt(r.area_cm2, 1)} cm²`], how].map(([k, v]) => `<dt>${esc(t(k))}</dt><dd>${esc(v)}</dd>`).join('');
}
async function generateFile() {
  if ($('#btn-generate').disabled) return;
  const sig = genSignature(), values = state.working, r = recipe(), d = dosage();         // what the file is made of is what is in the panel now, not what it becomes while this runs
  state.gen.busy = true; renderGenerate(); setLoading(true, 'ex_generating');
  try {
    const out = await api.generateFile(generateRequest(apiProject(), state.polarity, values, r, projectName()));
    const summary = parseSummary(out.summary), filename = out.filename || 'print-file';
    download(out.blob, filename);
    state.gen.last = summary ? { sig, filename, result: resultOf(summary, { recipe: r, dosage: d, values }) } : null;
    toast(t('ex_toast_generated', { name: filename }));
  } catch (e) { if (generationFailed(e)) scheduleCheck(); }
  finally { state.gen.busy = false; setLoading(false); renderGenerate(); }
}
// what the person is told when the server does not make a file: a file that is blocked says the first thing that blocks it (and the caller asks the checks again: true), the verification of a
// file has its own sentence (the same code of a saved project has another), the rest is the sentence of its code
function generationFailed(e) {
  if (e instanceof api.ApiError && e.code === 'generation_blocked') { const first = (e.params.issues || []).find((i) => i.blocking); toast(first ? issueText(first) : errorText(e)); return true; }
  toast(e instanceof api.ApiError && e.code === 'verification_failed' ? t('err_gen_verification_failed') : errorText(e));
  return false;
}
$('#btn-generate').onclick = generateFile;

// the library: read from the server, and changed only through it
async function refreshLibrary() {
  if (!state.library.on) return;
  const before = JSON.stringify(valuesOf(dosage())), had = state.recipeId;
  try { const r = await api.listRecipes(); state.library.recipes = r.recipes; state.library.problems = r.problems; state.library.loaded = true; }
  catch { toast(t('ex_lib_error')); return; }
  if (state.recipeId && !recipe()) { state.recipeId = null; state.dosageId = null; toast(t('ex_toast_recipe_gone')); }
  if (had !== state.recipeId || before !== JSON.stringify(valuesOf(dosage()))) syncWorking();        // what was typed stays unless the saved values changed under it
  refreshAll(true); updateDirty();
}
async function loadLibrary() {
  if (!state.info?.library) { state.library = { on: false, recipes: [], problems: [], loaded: true }; syncWorking(); return; }        // (no library: the values are the last ones typed, which the browser remembers)
  state.library.on = true;
  try { const r = await api.listRecipes(); state.library = { on: true, recipes: r.recipes, problems: r.problems, loaded: true }; }
  catch { toast(t('ex_lib_error')); }
  const last = store.get('gs-recipe');                                         // the last recipe chosen, for a new project
  if (last && state.library.recipes.some((r) => r.id === last)) { state.recipeId = last; state.polarity = recipe().polarity; }
  syncWorking();
}
async function libCall(fn) {                                                   // a refusal is said; a recipe or dosage that is gone makes the page read the library again
  try { return await fn(); } catch (e) {
    toast(errorText(e));
    if (e instanceof api.ApiError && (e.code === 'recipe_not_found' || e.code === 'dosage_not_found')) await refreshLibrary();
    return null;
  }
}
const keep = (out) => { state.library.recipes = putRecipe(state.library.recipes, out); };      // the server's answer is the recipe as it is now
const lastDosage = (out) => out.dosages[out.dosages.length - 1];               // a new dosage goes at the end of the list
// The menus of the Exposure panel (the recipe and the dosage) are made here, not <select>s, in the style of the printer's menu: a button that shows the choice and a
// list of buttons under it (a listbox: arrows, Home and End to move, Esc to close, a click outside closes). `items()` gives the entries { id, main, sub, title, selected }
// (`main` is markup: the name and a pill; `sub` the line under it) and `pick(id)` is called with the one chosen.
const CHEVRON = '<svg class="pk-chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>';
function makePicker(name, { items, pick }) {
  const btn = $(`#${name}-btn`), menu = $(`#${name}-menu`), picker = $(`#${name}-picker`);
  let rolling = 0;                                                            // the timer of the list rolling up: the list is hidden when it has finished
  const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const finish = () => { clearTimeout(rolling); rolling = 0; menu.hidden = true; picker.classList.remove('open', 'closing'); };
  const close = (focus) => {
    if (focus) btn.focus();
    if (menu.hidden || picker.classList.contains('closing')) return;
    btn.setAttribute('aria-expanded', 'false');
    if (still()) { finish(); return; }
    picker.classList.add('closing'); rolling = setTimeout(finish, 170);       // (the animation lasts .16 s; `.open` stays until then, so the button keeps its shape)
  };
  const open = () => {
    if (btn.disabled) return;
    if (rolling) finish();
    menu.innerHTML = items().map((x) => `<button type="button" role="option" data-id="${esc(x.id)}" aria-selected="${!!x.selected}"${x.title ? ` title="${esc(x.title)}"` : ''}><span class="pk-main">${x.main}</span>${x.sub ? `<small>${esc(x.sub)}</small>` : ''}</button>`).join('');
    picker.classList.add('open'); menu.hidden = false; btn.setAttribute('aria-expanded', 'true');
    (menu.querySelector('[aria-selected="true"]') || menu.querySelector('button'))?.focus();
  };
  btn.onclick = () => { if (menu.hidden || picker.classList.contains('closing')) open(); else close(true); };
  btn.addEventListener('keydown', (e) => { if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && (menu.hidden || picker.classList.contains('closing'))) { e.preventDefault(); open(); } });
  menu.addEventListener('click', (e) => { const b = e.target.closest('[data-id]'); if (!b) return; close(true); pick(b.dataset.id); });
  menu.addEventListener('keydown', (e) => {
    const list = [...menu.querySelectorAll('button')], i = list.indexOf(document.activeElement);
    if (e.key === 'Escape') { e.preventDefault(); close(true); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); list[(i + 1) % list.length].focus(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); list[(i + list.length - 1) % list.length].focus(); }
    else if (e.key === 'Home') { e.preventDefault(); list[0].focus(); }
    else if (e.key === 'End') { e.preventDefault(); list.at(-1).focus(); }
    else if (e.key === 'Tab') close(false);
  });
  document.addEventListener('pointerdown', (e) => { if (!e.target.closest(`#${name}-picker`)) close(false); });
  return { close };
}
// the recipes: closed, the name and the pill of the resist (the pill's tip says the polarity is the recipe's); open, name and pill and, under them, what the recipe
// says (resist, development, notes, without labels, one line, divided by a dot); the first entry is «no recipe» (the values by hand)
// the pill of a resist: the sign comes from the stylesheet, the text sits in a span of its own (that is the box whose height is cut to the lowercase letters)
const polChip = (polarity, title = '') => `<span class="chip ${polarity === 'positive' ? 'pos' : 'neg'}"${title ? ` title="${esc(title)}"` : ''}><span>${esc(t('pol_' + polarity))}</span></span>`;
const recipePill = (r) => polChip(r.polarity, t('ex_pol_locked'));
const noRecipe = () => `<span class="pk-name none">${esc(t('ex_recipe_none'))}</span>`;
function renderRecipePicker(r) {
  const btn = $('#recipe-btn');
  btn.innerHTML = (r ? `<span class="pk-name">${esc(r.name)}</span>${recipePill(r)}` : noRecipe()) + CHEVRON;
  btn.title = r ? [r.name, recipeBrief(r)].filter(Boolean).join(' — ') : '';
}
makePicker('recipe', {
  items: () => [{ id: '', main: noRecipe(), selected: !state.recipeId },
    ...state.library.recipes.map((x) => ({ id: x.id, main: `<span class="pk-name">${esc(x.name)}</span>${recipePill(x)}`, sub: recipeBrief(x), title: [x.name, recipeBrief(x)].filter(Boolean).join(' — '), selected: x.id === state.recipeId }))],
  pick: (id) => setRecipe(id),
});
// the dosages of the recipe for the printer in use: closed, its name (or its values) and, if it is the last changed, a pill that says so; open, the same and,
// under them, the date and the note (and the values, when it has a name)
const dosageTitle = (d) => d.name || `${sec(d.total_s)} s · ${d.pulses} ×`;
const dosageSub = (d) => [d.name ? `${sec(d.total_s)} s · ${d.pulses} × · ${sec(d.rest_s)} s` : '', fmtDate(d.updated), d.note].filter(Boolean).join(' · ');
const latestPill = () => `<span class="chip">${esc(t('ex_dosage_latest'))}</span>`;
function renderDosagePicker(list, cur) {
  const btn = $('#dosage-btn'); btn.disabled = !list.length;
  btn.innerHTML = (cur ? `<span class="pk-name">${esc(dosageTitle(cur))}</span>${cur.id === list[0]?.id ? latestPill() : ''}` : '<span class="pk-name none">–</span>') + CHEVRON;
  btn.title = cur ? [dosageTitle(cur), dosageSub(cur)].filter(Boolean).join(' — ') : '';
}
makePicker('dosage', {
  items: () => dosagesFor(recipe(), state.printerId).map((d, i) => ({ id: d.id, main: `<span class="pk-name">${esc(dosageTitle(d))}</span>${i === 0 ? latestPill() : ''}`, sub: dosageSub(d), title: [dosageTitle(d), dosageSub(d)].join(' — '), selected: d.id === dosage()?.id })),                // (the one in use: the last changed while none was chosen)
  pick: (id) => { state.dosageId = id; syncWorking(); refreshAll(true); updateDirty(); },
});
function setRecipe(id) {
  state.recipeId = id || null; state.dosageId = null; store.set('gs-recipe', id || '');
  if (recipe()) state.polarity = recipe().polarity;                            // the recipe's polarity is the project's
  syncWorking(); refreshAll(); updateDirty();
}
const confirmDelete = (title, text) => new Promise((resolve) => {
  $('#confirm-title').textContent = title; $('#confirm-text').textContent = text;
  const d = $('#dlg-confirm'); d.returnValue = ''; d.addEventListener('close', () => resolve(d.returnValue === 'ok'), { once: true }); d.showModal();
});
// a dialog's "ok" runs `apply`; closing it any other way does nothing
function onDialogOk(id, apply) { const d = $(id); d.addEventListener('close', () => { const ok = d.returnValue === 'ok'; d.returnValue = ''; if (ok) apply(); }); }

// ---- dosages
// the dialog of the panel names the values that are saved as a new dosage; a dosage is changed or deleted in Settings only (the panel changes the values it holds, and updates or saves them)
function openDosageDialog() {
  const r = recipe(); if (!r) return;
  if (!isComplete(state.working)) { toast(t('ex_toast_values_first')); return; }
  $('#dosage-title').textContent = t('ex_dosage_title_new');
  $('#dosage-hint').textContent = t('ex_dosage_hint_new', { recipe: r.name, printer: currentPrinter()?.name || '' });
  $('#ds-name').value = ''; $('#ds-note').value = '';
  $('#dlg-dosage').showModal();
}
onDialogOk('#dlg-dosage', async () => {
  const r = recipe(), name = $('#ds-name').value.trim(), note = $('#ds-note').value.trim(); if (!r || !isComplete(state.working)) return;
  const out = await libCall(() => api.addDosage(r.id, { printer_id: state.printerId, ...state.working, name, note }));
  if (out) { keep(out); state.dosageId = lastDosage(out).id; syncWorking(); refreshAll(true); updateDirty(); toast(t('ex_toast_dosage_saved')); }
});
async function updateDosageValues() {                                          // the values change in place; their date becomes now
  const r = recipe(), cur = dosage(); if (!r || !cur || !isComplete(state.working)) return;
  const out = await libCall(() => api.editDosage(r.id, cur.id, { ...state.working }));
  if (out) { keep(out); state.dosageId = cur.id; syncWorking(); refreshAll(true); updateDirty(); toast(t('ex_toast_dosage_updated')); }
}
async function deleteDosageOf(recipeId, d) {                                   // from Settings (any dosage; the panel does not delete)
  if (!(await confirmDelete(t('ex_confirm_dosage_title'), t('ex_confirm_dosage_text', { name: dosageLabel(d) })))) return;
  const before = JSON.stringify(valuesOf(dosage()));
  const out = await libCall(() => api.deleteDosage(recipeId, d.id));
  if (!out) return;
  keep(out); if (state.dosageId === d.id) state.dosageId = null;
  if (before !== JSON.stringify(valuesOf(dosage()))) syncWorking();            // what was typed stays unless the dosage in use changed under it
  refreshAll(true); updateDirty(); toast(t('ex_toast_dosage_deleted'));
}

// the dosage dialog of Settings: all of a dosage (the printer too, when it is new), for any recipe; the panel's one only names the values it saves as a new dosage
let sDosage = null;                                                            // { recipeId, dosageId } (dosageId: none when adding)
const sdValues = () => ({ total_s: num($('#sd-total')), pulses: num($('#sd-pulses')), rest_s: num($('#sd-rest')) });
function renderSdCheck() {                                                     // the dialog can be confirmed only with values that can be saved; a long flash is noted
  const v = sdValues(), note = flashNote(v, state.printers.find((p) => p.id === $('#sd-printer').value)?.limits), el = $('#sd-flash');
  $('#sd-ok').disabled = !isComplete(v); el.hidden = !note; el.classList.toggle('bad', note?.kind === 'below');
  if (note) el.textContent = note.kind === 'below' ? t('ex_flash_below', { flash: sec(note.flash), min: sec(note.min) }) : t('ex_flash_beyond', { flash: sec(note.flash), max: sec(note.max) });
}
function openSettingsDosage(recipeId, dosageId) {
  const r = state.library.recipes.find((x) => x.id === recipeId), d = dosageId ? r?.dosages.find((x) => x.id === dosageId) : null;
  if (!r || (dosageId && !d)) return;
  sDosage = { recipeId, dosageId: dosageId || null };
  $('#sdos-title').textContent = t(d ? 's_dos_title_edit' : 's_dos_title_new', { recipe: r.name });
  $('#sdos-hint').textContent = t(d ? 's_dos_hint_edit' : 's_dos_hint_new');
  const ids = state.printers.map((p) => p.id), known = d && !ids.includes(d.printer_id) ? `<option value="${esc(d.printer_id)}">${esc(d.printer_id)}</option>` : '';
  $('#sd-printer').innerHTML = known + state.printers.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
  $('#sd-printer').value = d ? d.printer_id : state.printerId; $('#sd-printer').disabled = !!d;           // a dosage is for the printer it was found on
  $('#sd-total').value = d?.total_s ?? ''; $('#sd-pulses').value = d?.pulses ?? ''; $('#sd-rest').value = d?.rest_s ?? '';
  $('#sd-name').value = d?.name || ''; $('#sd-note').value = d?.note || '';
  renderSdCheck(); $('#dlg-sdosage').showModal(); $('#sd-total').focus();
}
onDialogOk('#dlg-sdosage', async () => {
  const v = sdValues(); if (!sDosage || !isComplete(v)) return;
  const { recipeId, dosageId } = sDosage, extra = { name: $('#sd-name').value.trim(), note: $('#sd-note').value.trim() }, before = JSON.stringify(valuesOf(dosage()));
  const out = await libCall(() => (dosageId ? api.editDosage(recipeId, dosageId, { ...v, ...extra }) : api.addDosage(recipeId, { printer_id: $('#sd-printer').value, ...v, ...extra })));
  if (!out) return;
  keep(out); if (before !== JSON.stringify(valuesOf(dosage()))) syncWorking();
  refreshAll(true); updateDirty(); toast(t('ex_toast_dosage_saved'));
});
for (const id of ['sd-total', 'sd-pulses', 'sd-rest']) $('#' + id).addEventListener('input', renderSdCheck);
$('#sd-printer').addEventListener('change', renderSdCheck);
// ---- recipes: new (the polarity is chosen now and never changes), edit (not the polarity), duplicate (the copy's polarity is chosen again), delete
let recipeDlg = null;
// the polarity in the dialog is the same switch as the resist by hand (pill - switch - pill); its own radios (`rc-polarity`) keep it apart from the panel's
const recipePolarity = () => document.querySelector('input[name="rc-polarity"]:checked').value;
function setRecipePolarity(value) { for (const radio of document.querySelectorAll('input[name="rc-polarity"]')) radio.checked = radio.value === value; }
function setRecipePolarityLocked(locked) {                                   // editing: the polarity is shown but cannot be changed
  const box = $('#rc-pol'); box.classList.toggle('locked', locked); box.title = locked ? t('ex_pol_locked') : '';
  for (const radio of box.querySelectorAll('input')) radio.disabled = locked;
  $('#rc-pol-toggle').disabled = locked;
}
$('#rc-pol-toggle').onclick = () => setRecipePolarity(recipePolarity() === 'positive' ? 'negative' : 'positive');
function openRecipeDialog(mode, id) {
  const r = state.library.recipes.find((x) => x.id === id); if (mode !== 'new' && !r) return;
  recipeDlg = { mode, id };
  $('#recipe-title').textContent = t(mode === 'edit' ? 'ex_recipe_edit' : mode === 'dup' ? 'ex_recipe_dup' : 'ex_recipe_new');
  $('#recipe-hint').textContent = mode === 'new' ? t('ex_hint_new') : mode === 'edit' ? t('ex_hint_edit') : t('ex_hint_dup', { name: r.name });
  setRecipePolarity(r ? r.polarity : 'positive'); setRecipePolarityLocked(mode === 'edit');
  $('#rc-name').value = mode === 'dup' ? `${r.name} (${t('ex_copy_suffix')})` : r?.name || '';
  $('#rc-resist').value = r?.resist || ''; $('#rc-dev').value = r?.development || ''; $('#rc-notes').value = r?.notes || '';
  $('.rc-infos').disabled = mode === 'dup';                                                           // a copy keeps the text; only the name and the polarity are asked
  $('#dlg-recipe').showModal(); $('#rc-name').focus();
}
onDialogOk('#dlg-recipe', async () => {
  const name = $('#rc-name').value.trim(); if (!recipeDlg || !name) return;
  const { mode, id } = recipeDlg, text = { resist: $('#rc-resist').value.trim(), development: $('#rc-dev').value.trim(), notes: $('#rc-notes').value };
  const out = await libCall(() => (mode === 'edit' ? api.editRecipe(id, { name, ...text }) : mode === 'dup' ? api.duplicateRecipe(id, { name, polarity: recipePolarity() })
    : api.createRecipe({ name, polarity: recipePolarity(), ...text })));
  if (!out) return;
  keep(out);
  if (mode === 'new') setRecipe(out.id); else { refreshAll(true); updateDirty(); }
  toast(t(mode === 'edit' ? 'ex_toast_recipe_saved' : 'ex_toast_recipe_created', { name: out.name }));
});
async function deleteRecipe(id) {
  const r = state.library.recipes.find((x) => x.id === id); if (!r) return;
  if (!(await confirmDelete(t('ex_confirm_recipe_title'), t('ex_confirm_recipe_text', { name: r.name, n: r.dosages.length })))) return;
  if (!(await libCall(() => api.deleteRecipe(id)))) return;
  state.library.recipes = dropRecipe(state.library.recipes, id);
  if (state.recipeId === id) { state.recipeId = null; state.dosageId = null; store.set('gs-recipe', ''); syncWorking(); }
  refreshAll(); updateDirty(); toast(t('ex_toast_recipe_deleted', { name: r.name }));
}

// ---- Settings: the printers (as the server describes them) and the recipes with their dosages
let openRecipe = null;                                                        // the recipe that is expanded (an accordion: one at most): UI state only
// A recipe opens and closes with an animation of its height. It is done here, with the Web Animations API, because CSS cannot do it in every browser (Firefox has no
// `interpolate-size`). What is seen is `data-open` (it changes at once, with the arrow and the layout of the row); the native `open` only says whether the content is
// there: it is set before the content grows and removed after it has shrunk.
const RECIPE_MS = 280;
const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
function setRecipeOpen(d, open) {
  const body = d.querySelector('.rc-body'), running = d._anim && d._anim.playState === 'running';
  const from = running ? body.getBoundingClientRect().height : (open ? 0 : body.offsetHeight);          // an animation still going is taken over where it is
  d._anim?.cancel(); d._anim = null;
  d.toggleAttribute('data-open', open);
  if (open) d.open = true;
  const to = open ? body.offsetHeight : 0;
  if (reducedMotion() || from === to) { if (!open) d.open = false; return; }
  body.style.overflow = 'hidden';
  const anim = d._anim = body.animate(heightFrames(from, to), { duration: RECIPE_MS, easing: 'ease', fill: 'forwards' });
  anim.onfinish = () => {
    body.style.overflow = ''; if (!open) d.open = false;
    anim.cancel(); if (d._anim === anim) d._anim = null;                                                    // (the last frame was held until the content was really gone)
    if (open) d.querySelector('summary').scrollIntoView({ block: 'nearest' });                              // the row that opened is in view, whatever moved above it
  };
}
function toggleRecipe(d) {
  const open = !d.hasAttribute('data-open');
  openRecipe = openAfterToggle(openRecipe, d.dataset.recipe, open);
  setRecipeOpen(d, open);
  if (open) for (const other of $('#tbl-recipes').querySelectorAll('details.recipe[data-open]')) if (other !== d) setRecipeOpen(other, false);          // an accordion: the one that was open closes
}
const dosageSort = new Map();                                                 // recipe id -> { key, dir } of its dosage table; none: the default order
function renderSettings() {
  $('#card-recipes').hidden = !state.library.on; $('#card-nolib').hidden = state.library.on;
  $('#printer-cards').innerHTML = printerCards(state.printers, { t, fmt, esc });                          // the printers, as cards (printercards.js)
  if (!state.library.on) return;
  const meta = (r) => { const f = [['resist', r.resist], ['ex_development', r.development], ['ex_notes', r.notes]].filter(([, x]) => x); return f.length ? `<div class="rc-meta">${f.map(([k, x]) => `<div><b>${esc(t(k))}:</b> ${esc(x)}</div>`).join('')}</div>` : ''; };
  const labelled = (r) => [['resist', r.resist], ['ex_development', r.development], ['ex_notes', r.notes]].filter(([, x]) => x).map(([k, x]) => `${t(k)}: ${String(x).replace(/\s+/g, ' ').trim()}`).join(' · ');          // for the tooltip
  const icon = (act, path, key) => `<button class="btn sm icon" data-act="${act}" title="${esc(t(key))}" aria-label="${esc(t(key))}"><svg class="i" viewBox="0 0 24 24" aria-hidden="true">${path}</svg></button>`;
  const PEN = '<path d="M4 20h4L19 9l-4-4L4 16v4zM13 7l4 4"/>', BIN = '<path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13"/>', PLUS = '<path d="M12 5v14M5 12h14"/>';
  // fixed, predefined columns (the widths are in the stylesheet); printer, name and notes are left-aligned and cut, with the whole text on hover
  const COLS = [['printer', 'printer', 'l'], ['name', 'ex_name', 'l'], ['updated', 's_updated', ''], ['total', 's_col_total', ''], ['pulses', 'ex_pulses', ''], ['rest', 'ex_rest', ''], ['note', 'ex_notes', 'l']];
  const SORT_ICON = '<svg class="sort-i" viewBox="0 0 10 14" aria-hidden="true"><path class="up" d="M5 1l4 5H1z"/><path class="down" d="M5 13L1 8h8z"/></svg>';          // always there, at the right of the name; the active half is lit
  const head = (r) => { const cur = dosageSort.get(r.id); return COLS.map(([key, label, cls]) => {
    const on = cur?.key === key, tip = esc(t('s_sort_by', { column: t(label) })), { label: name, unit } = splitUnit(t(label));
    return `<th class="${cls}" aria-sort="${on ? (cur.dir === 'asc' ? 'ascending' : 'descending') : 'none'}"><button class="th-sort" data-sort="${key}" title="${tip}"><span class="lbl">${esc(name)}${unit ? ` <span class="u">${esc(unit)}</span>` : ''}</span>${SORT_ICON}</button></th>`; }).join(''); };
  const cut = (text) => `<span class="rc-cut" title="${esc(text)}">${esc(text)}</span>`;
  const table = (r) => `<div class="rc-dosages"><div class="rc-dosages-head"><span></span><span class="rc-dtitle">${esc(t('s_dosages_title'))}</span>${icon('dos-new', PLUS, 'ex_dosage_new')}</div>` + (r.dosages.length
    ? `<table class="t data-table"><colgroup>${COLS.map(([key]) => `<col class="c-${key}">`).join('')}<col class="c-acts"></colgroup><thead><tr>${head(r)}<th></th></tr></thead><tbody>${
    sortDosages(r.dosages, dosageSort.get(r.id), printerName).map((d) =>
      `<tr data-dosage="${esc(d.id)}"><td class="l">${cut(printerName(d.printer_id))}</td><td class="l">${cut(d.name || '—')}</td><td>${esc(fmtDate(d.updated))}</td><td title="${esc(quantity(t, 'u_seconds', d.total_s, sec(d.total_s)))}">${sec(d.total_s)}</td><td title="${esc(quantity(t, 'u_flashes', d.pulses))}">${d.pulses}</td><td title="${esc(quantity(t, 'u_seconds', d.rest_s, sec(d.rest_s)))}">${sec(d.rest_s)}</td><td class="l muted">${cut(d.note || '')}</td>
      <td class="acts">${icon('dos-edit', PEN, 's_dos_edit')}${icon('dos-del', BIN, 'ex_dosage_delete')}</td></tr>`).join('')}</tbody></table>`
    : `<p class="muted small">${esc(t('s_no_dosages'))}</p>`) + '</div>';
  $('#tbl-recipes').innerHTML = state.library.recipes.map((r) => `<details class="recipe" data-recipe="${esc(r.id)}" ${openRecipe === r.id ? 'open data-open' : ''}><summary><strong class="rc-title" title="${esc(r.name)}">${esc(r.name)}</strong>
    <span class="rc-brief" title="${esc(labelled(r))}">${esc(recipeBrief(r))}</span>
    <span class="muted small rc-count">${esc(t(r.dosages.length === 1 ? 's_dos_one' : 's_dos_many', { n: r.dosages.length }))}</span>
    ${polChip(r.polarity)}
    <span class="rc-actions">${icon('edit', PEN, 'ex_recipe_edit')}${icon('dup', '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h8"/>', 'ex_recipe_dup')}${icon('del', BIN, 'ex_recipe_delete')}</span></summary>
    <div class="rc-body">${meta(r)}${table(r)}</div></details>`).join('');
  const pr = state.library.problems, pEl = $('#recipes-problems'); pEl.hidden = !pr.length; if (pr.length) pEl.textContent = t('s_problems', { files: pr.map((x) => x.file).join(', ') });
}
function renderWarnings() {
  const w = computeWarnings(), chip = $('#st-warn'), s = warningStatus(w, t);
  chip.textContent = s.text; chip.className = s.cls; chip.title = s.label; chip.setAttribute('aria-label', s.label); $('#st-live').textContent = s.label;
  $('#warn-pop').innerHTML = `<strong>${t('warnings')}</strong>` + (w.length ? `<ul>${w.map((x) => `<li><span class="lv ${x.lv}">${x.lv === 'bad' ? '✖' : '⚠'}</span>${esc(x.text)}</li>`).join('')}</ul>` : `<p class="muted">${t('no_warnings')}</p>`)
    + (state.checkFailed ? `<p class="muted small">${esc(t('err_network'))}</p>` : '');
  renderGenerate();
}
function renderStatusSel() {
  const b = selected(); $('#st-sel').textContent = b ? selectionText(b, fmt, t) : t('no_selection');
}
function renderBadges() {
  const nb = state.boards.length; $('#badge-boards').textContent = nb ? String(nb) : '';
  const out = selected() && outside(selected()); $('#badge-place').hidden = !out; $('#badge-place').className = 'rbadge dot';
}
function refreshAll(keepExact = false) {
  renderBoards(); renderPlacement(); renderExposure(); renderLadder(); renderWarnings(); renderStatusSel(); renderBadges(); updateUndo(); updateDirty(); renderProjectName(); renderPrinter(); scheduleCheck();
  if (state.view === 'settings') renderSettings();
  if (!keepExact) plane.invalidate(); plane.draw();
}

// ---------------------------------------------------------------------------------------------------------------
// plane view hooks
const app = {
  plane: () => state.plane, boards: () => state.boards, selected, mode: () => state.mode, grid: () => state.grid, snap: () => state.snap,
  polarity: () => state.polarity, outsidePlane: () => state.boards.some(outside), t, geo, exactImage,
  select(id) { state.selectedId = id; renderBoards(); renderPlacement(); renderStatusSel(); renderBadges(); plane.draw(); $('.board.sel')?.scrollIntoView({ block: 'nearest' }); },
  changed(commitNow) { renderPlacement(); renderStatusSel(); renderBadges(); scheduleCheck(); plane.invalidate(); updateDirty(); if (commitNow) commit(); },
  commit() { commit(); },
  onDouble() { setSection('place'); },
  busy(v) { exactBusy = v; renderBusy(); },
  onCursor(c) {
    if (!c) { $('#st-cursor').textContent = '—'; return; }
    $('#st-cursor').textContent = cursorText(c, state.plane, fmt);
  },
  onZoom(rel, s) { $('#st-zoom').textContent = `${Math.round(rel * 100)}% · ${fmt(s, 1)} px/mm`; },
};
const plane = createPlane($('#plane'), app);

function setMode(m) {
  state.mode = m; $$('.cadtitlebar .seg button').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.mode === m))); plane.invalidate(); plane.draw();
}
function nudge(b, dx, dy) { b.x += dx; b.y += dy; app.changed(false); commitSoon(); }
function rotate(b, d) { b.angle = ((b.angle + d) % 360 + 360) % 360; app.changed(false); commitSoon(); }

// ---------------------------------------------------------------------------------------------------------------
// duplicate dialog
function dupPlan() {
  const base = selected(); if (!base) return null;
  const cols = Math.max(1, +$('#dup-cols').value || 1), rows = Math.max(1, +$('#dup-rows').value || 1), px = +$('#dup-px').value || 0, py = +$('#dup-py').value || 0;
  const e = extent(base), w = e.maxx - e.minx, h = e.maxy - e.miny, items = [];
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) if (r || c) items.push({ x: base.x + c * (w + px), y: base.y - r * (h + py) });
  const p = state.plane, fits = items.every((it) => it.x - w / 2 >= -1e-6 && it.x + w / 2 <= p.w + 1e-6 && it.y - h / 2 >= -1e-6 && it.y + h / 2 <= p.h + 1e-6);
  return { base, items, fits, total: cols * rows };
}
function openDup() {
  if (!selected()) { toast(t('select_board_hint')); return; }
  $('#dlg-dup').showModal(); updateDupInfo();
}
function updateDupInfo() {
  const pl = dupPlan(); if (!pl) return;
  $('#dup-info').innerHTML = pl.total === 1 ? esc(t('dup_none')) : `${esc(t('dup_info', { n: pl.total }))} ${pl.fits ? '✓' : `<span class="lv warn">⚠ ${esc(t('dup_outside'))}</span>`}`;
  $('#dup-ok').disabled = pl.total === 1;
}
function applyDup() {
  const pl = dupPlan(); if (!pl) return; let n = 1;
  for (const it of pl.items) {                                              // independent copies from here on; they share the files by hash
    const o = cloneBoard(pl.base); o.id = 'b' + state.nextId++; o.name = `${pl.base.name} (${++n})`; o.x = it.x; o.y = it.y; o.notes = [];
    state.boards.push(o);
  }
  commit(); refreshAll(); toast(pl.items.length === 1 ? t('toast_dup_one') : t('toast_dup', { n: pl.items.length }));
}

// ---------------------------------------------------------------------------------------------------------------
// MenuBar colour: a tint chosen in Settings, otherwise the default (teal)
const MB = [{ id: 'graphite', bg: '#2b303b' }, { id: 'navy', bg: '#1b2a4a' }, { id: 'indigo', bg: '#3a3f9b' }, { id: 'teal', bg: '#167580' }, { id: 'bordeaux', bg: '#6b2a3d' }, { id: 'slate', bg: '#53627c' }];
const mbChoice = () => store.get('gs-mb');
const mbCurrent = () => MB.find((m) => m.id === (mbChoice() || 'teal'));
function applyMenubar() { document.documentElement.style.setProperty('--mb-bg', mbCurrent().bg); if (state.view === 'settings') renderMbPicker(); }
function renderMbPicker() {
  const cur = mbChoice();
  $('#mb-swatches').innerHTML = [{ id: '', bg: mbCurrent().bg }, ...MB].map((m) => `<button class="swatch" role="radio" aria-checked="${(cur || '') === m.id}" data-mb="${m.id}"><span class="chipcolor" style="background:${m.bg}"></span>${t(m.id ? 'mb_' + m.id : 'mb_default')}</button>`).join('');
}
$('#mb-swatches').addEventListener('click', (e) => { const b = e.target.closest('[data-mb]'); if (!b) return; if (b.dataset.mb) store.set('gs-mb', b.dataset.mb); else { try { localStorage.removeItem('gs-mb'); } catch { /* private mode */ } } applyMenubar(); renderMbPicker(); });

// ---------------------------------------------------------------------------------------------------------------
// views, language, tabs
// the sliding pill of the MenuBar tabs needs to know where the active tab is
function placeIndicator() {
  const tabs = $('.tabs'), a = tabs.querySelector('[aria-selected="true"]'); if (!a) return;
  tabs.style.setProperty('--ind-x', a.offsetLeft + 'px'); tabs.style.setProperty('--ind-w', a.offsetWidth + 'px');
}
const VIEWS = ['plane', 'ladder', 'settings', 'help'];
function setView(v) {
  state.view = v; $('#app').dataset.view = v;
  for (const name of VIEWS) { $(`#view-${name}`).hidden = name !== v; const tab = $(`#tab-${name}`); tab.setAttribute('aria-selected', String(name === v)); tab.tabIndex = name === v ? 0 : -1; }
  if (v === 'plane') plane.draw(); if (v === 'settings') { renderMbPicker(); renderSettings(); refreshLibrary(); } if (v === 'ladder') sizeLadPreview();
  placeIndicator(); if (v === 'plane') placeRail();
}
function applyLang(l) {
  setLang(l); document.documentElement.lang = l; store.set('gs-lang', l); applyI18n(); renderLang(); renderKeys(); renderSideStatus(); refreshAll(true); app.onCursor(null); placeIndicator();
}
function renderKeys() {
  const rows = [['← ↑ → ↓', 'k_move'], ['Shift + ← ↑ → ↓', 'k_move_big'], ['Alt + ← ↑ → ↓', 'k_move_fine'], ['R · Shift+R', 'k_rot'], ['M', 'k_mirror'], ['Del', 'k_delete'], ['Ctrl+Z · Ctrl+Shift+Z', 'k_undo'],
    ['F', 'k_fit'], ['+ · −', 'k_zoom'], ['1 · 2 · 3', 'k_modes'], ['G', 'k_grid'], ['Space + drag', 'k_pan'], ['Alt + ↑ ↓', 'k_layer_order'], ['?', 'k_help']];
  $('#keys-table').innerHTML = rows.map(([k, d]) => `<tr><td><kbd>${esc(k)}</kbd></td><td>${t(d)}</td></tr>`).join('');
}

// ---------------------------------------------------------------------------------------------------------------
// resizable sidebar: drag the handle, arrow keys (Shift for bigger steps), double click to reset; the width is remembered
const SIDE = { min: 320, def: 390, max: () => Math.max(360, Math.min(760, innerWidth - 520)) };
function setSideWidth(w, save = true) {
  w = Math.round(Math.max(SIDE.min, Math.min(SIDE.max(), w)));
  document.documentElement.style.setProperty('--side-w', w + 'px');
  const sp = $('#splitter'); sp.setAttribute('aria-valuenow', String(w)); sp.setAttribute('aria-valuemin', String(SIDE.min)); sp.setAttribute('aria-valuemax', String(SIDE.max()));
  if (save) store.set('gs-side', String(w)); return w;
}
const splitter = $('#splitter');
splitter.addEventListener('pointerdown', (e) => { splitter.setPointerCapture(e.pointerId); splitter.classList.add('dragging'); document.body.classList.add('resizing'); e.preventDefault(); });
splitter.addEventListener('pointermove', (e) => { if (splitter.hasPointerCapture(e.pointerId)) setSideWidth(e.clientX, false); });
const endResize = (e) => { if (!splitter.classList.contains('dragging')) return; splitter.classList.remove('dragging'); document.body.classList.remove('resizing'); setSideWidth(e.clientX); };
splitter.addEventListener('pointerup', endResize); splitter.addEventListener('pointercancel', endResize);
splitter.addEventListener('dblclick', () => setSideWidth(SIDE.def));
splitter.addEventListener('keydown', (e) => {
  const cur = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--side-w')) || SIDE.def, step = e.shiftKey ? 64 : 16;
  const to = { ArrowLeft: cur - step, ArrowRight: cur + step, Home: SIDE.min, End: SIDE.max() }[e.key]; if (to === undefined) return; e.preventDefault(); setSideWidth(to);
});
window.addEventListener('resize', () => setSideWidth(parseInt(getComputedStyle(document.documentElement).getPropertyValue('--side-w')) || SIDE.def, false));

// events
$('#boards-list').addEventListener('click', (e) => {
  const card = e.target.closest('.board'); if (!card) return; const id = card.dataset.id, btn = e.target.closest('[data-act]'), act = btn?.dataset.act;
  if (act === 'tip') { if (tipPin === btn) hideTip(); else { showTip(btn, true); tipPin = btn; } return; }
  if (act === 'resetcolor') { const l = layerOf(btn); if (l) { delete l.color; commit(); refreshAll(true); } return; }
  if (!act && !e.target.closest('input, label')) { state.selectedId = id; refreshAll(true); return; }
  if (act === 'toggle') { if (state.open.has(id)) state.open.delete(id); else state.open.add(id); state.selectedId = id; refreshAll(true); }
  else if (act === 'remove') removeBoard(id); else if (act === 'dup') { state.selectedId = id; refreshAll(true); openDup(); }
});
$('#boards-list').addEventListener('input', (e) => {                       // live preview while the picker is open
  const i = e.target.closest('.colorin'); if (!i) return; const l = layerOf(i); if (!l) return;
  l.color = i.value; i.nextElementSibling.style.background = i.value; plane.draw();
});
$('#boards-list').addEventListener('change', (e) => {
  const c = e.target.closest('.colorin'); if (c) { commit(); renderBoards(); return; }
  const i = e.target.closest('input[role="switch"]'); if (i) toggleLayer(i.dataset.board, i.dataset.layer, i.checked);
});
$('#boards-list').addEventListener('mouseover', (e) => { const b = e.target.closest('.lw'); if (b && !tipPin) showTip(b, false); });
$('#boards-list').addEventListener('mouseout', (e) => { if (e.target.closest('.lw') && !tipPin) hideTip(); });
$('#boards-list').addEventListener('focusin', (e) => { const b = e.target.closest('.lw'); if (b && !tipPin) showTip(b, false); });
$('#boards-list').addEventListener('focusout', (e) => { if (e.target.closest('.lw') && !tipPin) hideTip(); });
document.addEventListener('click', (e) => { if (tipPin && !e.target.closest('.lw') && !e.target.closest('#tip')) hideTip(); });
window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !tipEl.hidden) hideTip(); });
// sidebar sections (icon rail)
function placeRail() {   // the notch of the SideBar follows the selected icon
  const rail = $('#rail'), a = rail.querySelector('[aria-selected="true"]'); if (!a || !a.offsetHeight) return;
  rail.style.setProperty('--rail-y', a.offsetTop - 3 + 'px'); rail.style.setProperty('--rail-h', a.offsetHeight + 6 + 'px');
}
function setSection(id) {
  for (const s of ['boards', 'place', 'expo']) { $('#sec-' + s).hidden = s !== id; const r = $('#rail-' + s); r.setAttribute('aria-selected', String(s === id)); r.tabIndex = s === id ? 0 : -1; }
  store.set('gs-sec', id); placeRail();
}
$$('#rail button').forEach((b) => (b.onclick = () => setSection(b.dataset.sec)));
$('#rail').addEventListener('keydown', (e) => {
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return; e.preventDefault();
  const ids = ['boards', 'place', 'expo'], cur = ids.indexOf($$('#rail button').find((b) => b.getAttribute('aria-selected') === 'true')?.dataset.sec);
  const next = ids[(cur + (e.key === 'ArrowDown' ? 1 : ids.length - 1)) % ids.length]; setSection(next); $('#rail-' + next).focus();
});
$('#btn-expand-all').onclick = () => { state.boards.forEach((b) => state.open.add(b.id)); renderBoards(); };
$('#btn-collapse-all').onclick = () => { state.open.clear(); renderBoards(); };
$('#btn-add').onclick = $('#btn-empty-add').onclick = () => $('#file-add').click();
$('#file-add').onchange = (e) => { addFiles([...e.target.files]); e.target.value = ''; };
$('#btn-open').onclick = () => $('#file-open').click();
$('#file-open').onchange = (e) => { const f = e.target.files[0]; e.target.value = ''; if (!f) return; if (isProjectFile(f.name)) openProjectFile(f); else toast(t('toast_unsupported')); };     // the dialog can be switched to "all files": the extension is checked here too
$('#btn-save').onclick = saveProject;
$('#btn-download').onclick = downloadProject;
window.addEventListener('beforeunload', (e) => { if (isDirty()) { e.preventDefault(); e.returnValue = ''; } });
for (const id of ['dup-cols', 'dup-rows', 'dup-px', 'dup-py']) $('#' + id).addEventListener('input', updateDupInfo);
$('#dlg-dup').addEventListener('close', () => { if ($('#dlg-dup').returnValue === 'ok') applyDup(); $('#dlg-dup').returnValue = ''; });
$('#btn-new').onclick = () => { const before = snapshot(), name = state.name; state.boards = []; state.selectedId = null; state.name = ''; state.printerNote = null; commit(); refreshAll(); toast(t('toast_new'), t('undo_action'), () => { state.name = name; restore(before); commit(); renderProjectName(); }); };
// language: a flag in the MenuBar; clicking it lists the other flags with the language names
const langBtn = $('#lang-btn'), langMenu = $('#lang-menu');
function renderLang() {
  const cur = LANGS.find((l) => l.id === getLang()) || LANGS[0], label = t('lang_label') + ': ' + cur.name;
  langBtn.innerHTML = `<span class="flag">${cur.flag}</span>`; langBtn.title = label; langBtn.setAttribute('aria-label', label);
  langMenu.setAttribute('aria-label', t('lang_label'));
  langMenu.innerHTML = LANGS.map((l) => `<button type="button" role="option" lang="${l.id}" tabindex="-1" data-lang="${l.id}" aria-selected="${l.id === cur.id}"><span class="flag">${l.flag}</span><span>${l.name}</span></button>`).join('');
}
function openLangMenu() {
  const r = langBtn.getBoundingClientRect();
  langMenu.style.top = r.bottom + 6 + 'px'; langMenu.style.right = Math.max(8, window.innerWidth - r.right) + 'px';
  langMenu.hidden = false; langBtn.setAttribute('aria-expanded', 'true');
  (langMenu.querySelector('[aria-selected="true"]') || langMenu.firstElementChild).focus();
}
function closeLangMenu(refocus) { if (langMenu.hidden) return; langMenu.hidden = true; langBtn.setAttribute('aria-expanded', 'false'); if (refocus) langBtn.focus(); }
langBtn.onclick = () => (langMenu.hidden ? openLangMenu() : closeLangMenu(true));
langBtn.addEventListener('keydown', (e) => { if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); e.stopPropagation(); openLangMenu(); } });
langMenu.addEventListener('keydown', (e) => {                                  // the board shortcuts must not see these keys
  const items = [...langMenu.children], i = items.indexOf(document.activeElement), go = (n) => items[(n + items.length) % items.length].focus();
  if (e.key === 'ArrowDown') go(i + 1); else if (e.key === 'ArrowUp') go(i - 1); else if (e.key === 'Home') go(0); else if (e.key === 'End') go(items.length - 1);
  else if (e.key === 'Escape' || e.key === 'Tab') closeLangMenu(true); else return;
  e.preventDefault(); e.stopPropagation();
});
langMenu.addEventListener('click', (e) => { const b = e.target.closest('[data-lang]'); if (!b) return; closeLangMenu(true); if (b.dataset.lang !== getLang()) applyLang(b.dataset.lang); });
document.addEventListener('pointerdown', (e) => { if (!langMenu.hidden && !langMenu.contains(e.target) && !langBtn.contains(e.target)) closeLangMenu(false); });
window.addEventListener('resize', () => closeLangMenu(false));
$$('.tabs button').forEach((b) => (b.onclick = () => setView(b.dataset.view)));
$('.tabs').addEventListener('keydown', (e) => {                         // arrow keys move between the tabs (ARIA tabs pattern)
  const names = VIEWS, i = names.indexOf(state.view), len = names.length; let n = null;
  if (e.key === 'ArrowRight') n = names[(i + 1) % len]; else if (e.key === 'ArrowLeft') n = names[(i + len - 1) % len]; else if (e.key === 'Home') n = names[0]; else if (e.key === 'End') n = names[len - 1];
  if (n) { e.preventDefault(); setView(n); $(`#tab-${n}`).focus(); }
});
$$('.cadtitlebar .seg button').forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));
$('#btn-zoom-in').onclick = () => plane.zoomBy(1.3); $('#btn-zoom-out').onclick = () => plane.zoomBy(1 / 1.3); $('#btn-fit').onclick = () => plane.fit();
// Grid and Snap in the StatusBar: two buttons that stay pressed (aria-pressed says it to everyone), with the zoom ones
function renderToggles() { $('#btn-grid').setAttribute('aria-pressed', String(state.grid)); $('#btn-snap').setAttribute('aria-pressed', String(state.snap)); }
$('#btn-grid').onclick = () => { state.grid = !state.grid; renderToggles(); plane.draw(); };
$('#btn-snap').onclick = () => { state.snap = !state.snap; renderToggles(); };
$('#btn-undo').onclick = undo; $('#btn-redo').onclick = redo;
// placement fields
const num = (el) => { const v = parseFloat(el.value); return Number.isFinite(v) ? v : null; };
$('#in-x').oninput = (e) => { const b = selected(), v = num(e.target); if (b && v !== null) { b.x = v; app.changed(false); commitSoon(); } };
$('#in-y').oninput = (e) => { const b = selected(), v = num(e.target); if (b && v !== null) { b.y = v; app.changed(false); commitSoon(); } };
$('#in-angle').oninput = (e) => { const b = selected(), v = num(e.target); if (b && v !== null) { b.angle = v; app.changed(false); commitSoon(); } };
$('#btn-rot-ccw').onclick = () => { const b = selected(); if (b) rotate(b, TURN.ccw); }; $('#btn-rot-cw').onclick = () => { const b = selected(); if (b) rotate(b, TURN.cw); };
// the mirror: two pills with a switch between them, as the resist (the radios are the keyboard's and the screen readers' way in)
for (const radio of $$('input[name="mirror"]')) radio.onchange = (e) => { const b = selected(); if (b) { b.mirror = e.target.value === 'on'; app.changed(true); } };
$('#mirror-toggle').onclick = () => { const b = selected(); if (b) { b.mirror = !b.mirror; app.changed(true); } };
$$('#anchor-pick button').forEach((b) => (b.onclick = () => { state.anchor = b.dataset.corner; $$('#anchor-pick button').forEach((q) => q.setAttribute('aria-checked', String(q === b))); }));
$('#in-ax').oninput = (e) => fitValue(e.target); $('#in-ay').oninput = (e) => fitValue(e.target);
// the buttons of the value cards of this section: one click moves the number by its `data-jump` (1 mm, or 1°), negative numbers included (a board may leave the plane);
// it is dispatched as an input, so the board follows as if the number had been typed
function stepPlacement(input, dir) {
  input.value = String(Math.round(((num(input) ?? 0) + dir * (+input.dataset.jump || 1)) * 100) / 100);
  input.dispatchEvent(new Event('input', { bubbles: true }));
}
$('#place-body').addEventListener('click', (e) => { const b = e.target.closest('.vstep'); if (b) stepPlacement($('#' + b.dataset.for), +b.dataset.step); });
$('#btn-anchor').onclick = () => { const b = selected(); if (b) { anchorTo(b, state.plane, state.anchor, num($('#in-ax')) || 0, num($('#in-ay')) || 0); app.changed(true); } };
// resist and settings
// the resist by hand: two pills with a switch between them (the pill on the chosen side is coloured, the other muted); the radios are the keyboard and the screen readers' way in
function setManualPolarity(value) {
  if (recipe() || state.polarity === value) return;                            // by hand only: a recipe's polarity is the recipe's
  state.polarity = value; renderExposure(); plane.invalidate(); plane.draw(); updateDirty();
}
for (const radio of document.querySelectorAll('input[name="polarity"]')) radio.onchange = (e) => setManualPolarity(e.target.value);
$('#pol-toggle').onclick = () => setManualPolarity(state.polarity === 'positive' ? 'negative' : 'positive');
// the buttons of a value card: one step of the input (its `step`, never under its `min` and, if it has one, over its `max`) at each click, no repetition when held; they are
// dispatched as an input, so the state, the memory of the last values and the rest of the panel follow as if the number had been typed. The minus is off when the value
// cannot go lower, the plus when it cannot go higher.
function stepValue(input, dir) {
  const step = +input.step || 1, min = input.min === '' ? 0 : +input.min, max = input.max === '' ? Infinity : +input.max, cur = num(input) ?? 0;
  input.value = String(Math.min(max, Math.max(min, Math.round((cur + dir * step) * 100) / 100)));
  input.dispatchEvent(new Event('input', { bubbles: true }));
}
function syncSteppers() {
  for (const b of $$('#values .vstep[data-step="-1"], #view-ladder .vstep[data-step="-1"]')) { const input = $('#' + b.dataset.for), v = num(input); b.disabled = v !== null && v <= (input.min === '' ? 0 : +input.min); }
  for (const b of $$('#view-ladder .vstep[data-step="1"]')) { const input = $('#' + b.dataset.for), v = num(input); b.disabled = v !== null && input.max !== '' && v >= +input.max; }
}
$('#values').addEventListener('click', (e) => { const b = e.target.closest('.vstep'); if (b && !b.disabled) stepValue($('#' + b.dataset.for), +b.dataset.step); });
$('#view-ladder').addEventListener('click', (e) => { const b = e.target.closest('.vstep'); if (b && !b.disabled) stepValue($('#' + b.dataset.for), +b.dataset.step); });
for (const [id, key] of [['in-total', 'total_s'], ['in-pulses', 'pulses'], ['in-rest', 'rest_s']]) $('#' + id).oninput = (e) => {
  fitValue(e.target); const x = { total_s: null, pulses: null, rest_s: null, ...(state.working || {}) }; x[key] = num(e.target);
  state.working = x.total_s === null && x.pulses === null && x.rest_s === null ? null : x;
  if (!recipe()) store.set('gs-manual', JSON.stringify(state.working));          // by hand, the browser remembers the last values (this is not a library)
  renderExposure();
};
// ---------------------------------------------------------------------------------------------------------------
// the Calibration ladder (its page). The values and the choices are the page's own (the resist and the mirror too: no recipe is chosen here) and the browser remembers
// the last ones; the printer is the one in use, changed here with a list like the PrinterPill's. What the values say, what is wrong with them, where the strips go and the
// preview (an SVG with its zoom) are in ladder.js; the file itself comes with the generation (7d), until then its button is off.
// the two tabs over the values (Parametri, Gradino). The panel keeps the two sections in the same place and only one can be reached (the other is `inert`).
const LD_TABS = ['params', 'strip'];
function setLadTab(id, focus) {
  for (const name of LD_TABS) { const on = name === id, tab = $('#ld-tab-' + name), sec = $('#ld-sec-' + name); tab.setAttribute('aria-selected', String(on)); tab.tabIndex = on ? 0 : -1; sec.classList.toggle('off', !on); sec.inert = !on; }
  $('#lad-tabs').dataset.active = id; store.set('gs-ldtab', id); if (focus) $('#ld-tab-' + id).focus();      // (the notch under the tabs slides by CSS, from the attribute)
}
for (const tab of $$('#lad-tabs [role="tab"]')) tab.onclick = () => setLadTab(tab.dataset.ldtab);
$('#lad-tabs').addEventListener('keydown', (e) => {
  const cur = LD_TABS.indexOf($$('#lad-tabs [role="tab"]').find((b) => b.getAttribute('aria-selected') === 'true')?.dataset.ldtab);
  const next = { ArrowRight: (cur + 1) % LD_TABS.length, ArrowLeft: (cur + LD_TABS.length - 1) % LD_TABS.length, Home: 0, End: LD_TABS.length - 1 }[e.key];
  if (next === undefined) return; e.preventDefault(); setLadTab(LD_TABS[next], true);
});
setLadTab(LD_TABS.includes(store.get('gs-ldtab')) ? store.get('gs-ldtab') : 'params');
const LD_FIELDS = [['ld-step', 'step'], ['ld-bands', 'bands'], ['ld-pulses', 'pulses'], ['ld-rest', 'rest'], ['ld-width', 'width'], ['ld-height', 'height']];
const ldSave = () => store.set('gs-ladder', JSON.stringify(state.ladder));
const ldPrinter = (p) => `<span class="pk-thumb">${printerPicture(p, esc)}</span><span class="pk-text"><span class="pk-name">${esc(p.name)}</span><small class="pk-size">${esc(planeSize(p, fmt))} mm</small></span>`;       // the picture, and the name over the size of the plane
makePicker('ld-printer', {
  items: () => state.printers.map((p) => ({ id: p.id, main: ldPrinter(p), title: printerTip(p), selected: p.id === state.printerId })),
  pick: (id) => selectPrinter(id),
});
const ldFit = () => fitBox(state.plane);
function ldDraw() {                                                           // only the part of the plane that is shown (the zoom and the panning), without drawing the ladder again
  const box = state.ldBox || ldFit(), fit = ldFit(), svg = $('#ld-view svg'), z = zoomOf(box, fit);
  if (svg) svg.setAttribute('viewBox', `${+box.x.toFixed(3)} ${+box.y.toFixed(3)} ${+box.w.toFixed(3)} ${+box.h.toFixed(3)}`);
  $('#btn-ld-zoom-out').disabled = $('#btn-ld-fit').disabled = z <= 1.0001; $('#btn-ld-zoom-in').disabled = z >= MAX_ZOOM - 1e-6;
}
function renderLadder() {
  const L = state.ladder, p = currentPrinter(), plane_ = state.plane, multi = state.printers.length > 1;
  const btn = $('#ld-printer-btn'); btn.innerHTML = (p ? ldPrinter(p) : '') + CHEVRON; btn.disabled = !multi; btn.title = p ? printerTip(p) : '';
  $('#ld-printer-picker').classList.toggle('single', !multi);
  for (const radio of $$('input[name="ld-polarity"]')) radio.checked = radio.value === L.polarity;
  for (const radio of $$('input[name="ld-mirror"]')) radio.checked = (radio.value === 'on') === L.mirror;
  for (const [id, key] of LD_FIELDS) setVal($('#' + id), L[key] ?? '');
  syncSteppers();
  for (const box of $$('#ld-tests input')) box.checked = L.tests.includes(box.dataset.test);
  $('#btn-ld-all').disabled = L.tests.length === TESTS.length; $('#btn-ld-none').disabled = !L.tests.length;
  for (const b of $$('#ld-seg button')) b.setAttribute('aria-checked', String(b.dataset.ldview === L.view));
  const ok = isValid(L); if (ok) state.ldGood = { ...L };
  const shown = state.ldGood || L, layout = ladderLayout(shown, plane_), issues = ok ? ladderIssues(L, plane_, p?.limits) : [];
  $('#ld-notes').innerHTML = issues.map(ldNote).filter(Boolean).map(([bad, text]) => `<p class="small flash-note${bad ? ' bad' : ''}">${esc(text)}</p>`).join('');
  if (ok) { const f = L.step / L.pulses; $('#ld-summary').innerHTML = t('ld_summary', { bands: esc(String(L.bands)), from: esc(sec(L.step)), to: esc(sec(L.bands * L.step)), flash: esc(sec(+f.toFixed(2))), rest: esc(sec(L.rest)) }); }
  else $('#ld-summary').textContent = t('ld_summary_none');
  const key = `${plane_.w}x${plane_.h}`; if (state.ldKey !== key) { state.ldKey = key; state.ldBox = null; }       // another plane: the whole of it again
  const fit = ldFit(), view = $('#ld-view'); view.style.aspectRatio = `${fit.w} / ${fit.h}`; sizeLadPreview();
  view.innerHTML = ladderSvg(layout, { plane: plane_, view: L.view, polarity: L.polarity, mirror: L.mirror, box: state.ldBox || fit, sec });
  view.title = t(L.view === 'uv' ? 'ld_cap_light' : 'ld_cap_material'); $('#ld-dims').textContent = t('ld_dims', { w: sec(+layout.width.toFixed(1)), h: sec(layout.height) });       // (what the view shows is the tip of the picture)
  renderLadderGen(); ldDraw();
}
// The file of the ladder: the button is on when nothing blocks (`ladderBlock`); the printer's own problem is written under it (the notes and the summary above already say the others), and
// under that a line says what the last file did, while the values are the same.
function renderLadderGen() {
  const g = state.ldGen, L = state.ladder, p = currentPrinter(), block = ladderBlock(L, state.plane, p?.limits, printerIssues(state.printers, state.printerId));
  const text = !block ? '' : block.kind === 'printer' ? issueText(block.issue) : block.kind === 'ladder' ? (ldNote(block.note) || [0, ''])[1] : '';
  $('#btn-ld-generate').disabled = !!block || g.busy; $('#btn-ld-generate').title = text;
  const why = $('#ld-gen-reason'); why.textContent = block?.kind === 'printer' ? text : ''; why.classList.toggle('bad', block?.kind === 'printer');
  const done = $('#ld-gen-done'), show = !!g.last && isValid(L) && g.last.key === ladderKey(L, state.printerId);
  done.hidden = !show;
  if (show) done.textContent = t('ld_res_line', { name: g.last.filename, n: g.last.summary.layers, flash: sec(+g.last.summary.flash_s.toFixed(2)), time: durationText(g.last.summary.estimated_s) });
}
async function generateLadderFile() {
  if ($('#btn-ld-generate').disabled) return;
  const L = state.ladder, key = ladderKey(L, state.printerId), request = ladderRequest(L, state.printerId);        // what the file is made of is what is on the page when it is clicked
  state.ldGen.busy = true; renderLadderGen(); setLoading(true, 'ex_generating');
  try {
    const out = await api.generateLadder(request);
    const summary = parseSummary(out.summary), filename = out.filename || 'ladder';
    download(out.blob, filename);
    state.ldGen.last = summary ? { key, filename, summary } : null;
    toast(t('ex_toast_generated', { name: filename }));
  } catch (e) { generationFailed(e); }
  finally { state.ldGen.busy = false; setLoading(false); renderLadderGen(); }
}
$('#btn-ld-generate').onclick = generateLadderFile;
// what is wrong, as a sentence: [is it an error, the text]; the flash over the longest tried and the tests that have no room only warn
function ldNote(x) {
  if (x.kind === 'too_big') return [true, t('ld_too_big', { w: sec(+x.w.toFixed(1)), h: sec(x.h), pw: fmt(x.pw, 2), ph: fmt(x.ph, 2), sw: sec(x.sw), maxn: String(x.maxn), maxh: sec(+x.maxh.toFixed(1)) })];
  if (x.kind === 'flash_below') return [true, t('ex_flash_below', { flash: sec(x.flash), min: sec(x.min) })];
  if (x.kind === 'flash_beyond') return [false, t('ex_flash_beyond', { flash: sec(x.flash), max: sec(x.max) })];
  if (x.kind === 'no_tests') return [false, t('ld_no_tests')];
  if (x.kind === 'dropped') return [false, quantity(t, 'ld_dropped', x.ids.length)];
  return null;
}
// The card of the preview is as high as the panel beside it when the panel has no warnings. The picture keeps the proportions of the plane, so it takes what is left of that height (the card's
// header and the line under it are what they are) and its width follows; the card is as wide as the picture (and no wider than the window leaves). A narrow window makes the card lower, never the
// picture bent; a warning makes the panel higher and changes nothing in the card.
function sizeLadPreview() {
  const side = $('.lad-side'), card = $('.lad-preview'), view = $('#ld-view'), page = $('#view-ladder'), fit = ldFit();
  if (!side.offsetHeight || !view.offsetHeight) return;                         // (the page is not showing: it is done when it shows)
  const extra = $$('#ld-notes p, #ld-gen-reason, #ld-gen-done').reduce((a, p) => (p.offsetHeight ? a + p.offsetHeight + parseFloat(getComputedStyle(p).marginTop) : a), 0);       // what the warnings and the lines under the button add to the panel is not counted: the picture keeps its size when one comes or goes
  const chrome = card.offsetHeight - view.offsetHeight, fw = Math.min((side.offsetHeight - extra - chrome) * (fit.w / fit.h), page.clientWidth * 0.96 - 330 - 14 - 34);
  $('.lad-main').style.setProperty('--ld-fw', Math.max(200, fw).toFixed(1) + 'px');
}
new ResizeObserver(sizeLadPreview).observe($('.lad-side'));                      // the panel changes its height (a warning, a language) or shows for the first time
window.addEventListener('resize', sizeLadPreview);
const ldChanged = () => { ldSave(); renderLadder(); };
$('#btn-ld-all').onclick = () => { state.ladder.tests = [...TESTS]; ldChanged(); }; $('#btn-ld-none').onclick = () => { state.ladder.tests = []; ldChanged(); };
for (const box of $$('#ld-tests input')) box.onchange = () => { state.ladder.tests = TESTS.filter((id) => $(`#ld-tests [data-test="${id}"]`).checked); ldChanged(); };
for (const [id, key] of LD_FIELDS) $('#' + id).oninput = (e) => { fitValue(e.target); state.ladder[key] = num(e.target); ldChanged(); };
for (const radio of $$('input[name="ld-polarity"]')) radio.onchange = (e) => { state.ladder.polarity = e.target.value; ldChanged(); };
$('#ld-pol-toggle').onclick = () => { state.ladder.polarity = state.ladder.polarity === 'positive' ? 'negative' : 'positive'; ldChanged(); };
for (const radio of $$('input[name="ld-mirror"]')) radio.onchange = (e) => { state.ladder.mirror = e.target.value === 'on'; ldChanged(); };
$('#ld-mirror-toggle').onclick = () => { state.ladder.mirror = !state.ladder.mirror; ldChanged(); };
for (const b of $$('#ld-seg button')) b.onclick = () => { state.ladder.view = b.dataset.ldview; ldChanged(); };
// the zoom of the preview: the buttons (about the middle of what is shown), the wheel (about the pointer), dragging to move it, a double click to see it all, and from the keyboard
// + - 0 and the arrows with the preview in focus
function ldZoom(factor, at) {
  const box = state.ldBox || ldFit(), c = at || [box.x + box.w / 2, box.y + box.h / 2];
  const next = zoomBox(box, factor, c[0], c[1], ldFit()); state.ldBox = zoomOf(next, ldFit()) <= 1.0001 ? null : next; ldDraw();
}
$('#btn-ld-zoom-in').onclick = () => ldZoom(1.5); $('#btn-ld-zoom-out').onclick = () => ldZoom(1 / 1.5); $('#btn-ld-fit').onclick = () => { state.ldBox = null; ldDraw(); };
$('#ld-view').addEventListener('wheel', (e) => { e.preventDefault(); const box = state.ldBox || ldFit(); ldZoom(Math.exp(-e.deltaY * 0.0022), boxPoint(box, e.currentTarget.getBoundingClientRect(), e.clientX, e.clientY)); }, { passive: false });
$('#ld-view').addEventListener('dblclick', () => { state.ldBox = null; ldDraw(); });
let ldPan = null;
$('#ld-view').addEventListener('pointerdown', (e) => { if (e.button !== 0 || !state.ldBox) return; ldPan = { x: e.clientX, y: e.clientY }; e.currentTarget.setPointerCapture(e.pointerId); e.currentTarget.classList.add('panning'); });
$('#ld-view').addEventListener('pointermove', (e) => {
  if (!ldPan) return; const r = e.currentTarget.getBoundingClientRect(), box = state.ldBox;
  state.ldBox = panBox(box, -((e.clientX - ldPan.x) / r.width) * box.w, -((e.clientY - ldPan.y) / r.height) * box.h, ldFit()); ldPan = { x: e.clientX, y: e.clientY }; ldDraw();
});
const ldEndPan = (e) => { ldPan = null; e.currentTarget.classList.remove('panning'); };
$('#ld-view').addEventListener('pointerup', ldEndPan); $('#ld-view').addEventListener('pointercancel', ldEndPan);
$('#ld-view').addEventListener('keydown', (e) => {
  const box = state.ldBox || ldFit(), arrows = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
  if (e.key === '+' || e.key === '=') ldZoom(1.5); else if (e.key === '-') ldZoom(1 / 1.5); else if (e.key === '0') { state.ldBox = null; ldDraw(); }
  else if (arrows && state.ldBox) state.ldBox = panBox(box, arrows[0] * box.w * 0.1, arrows[1] * box.h * 0.1, ldFit());
  else return;
  e.preventDefault(); ldDraw();
});
$('#btn-dos-manual').onclick = () => $('#in-total').focus();                      // by hand: the cursor goes to the total time, nothing is filled in
$('#btn-dos-ladder').onclick = () => setView('ladder');
$('#btn-dos-saveas').onclick = () => openDosageDialog();
$('#btn-dos-update').onclick = updateDosageValues;
$('#btn-recipe-new2').onclick = () => openRecipeDialog('new');                    // recipes are made and changed in Settings only (the Exposure panel only chooses one)
$('#tbl-recipes').addEventListener('click', (e) => {
  const th = e.target.closest('[data-sort]');
  if (th) { const id = th.closest('details').dataset.recipe, next = nextSort(dosageSort.get(id), th.dataset.sort); if (next) dosageSort.set(id, next); else dosageSort.delete(id);
    renderSettings(); $(`#tbl-recipes [data-recipe="${CSS.escape(id)}"] [data-sort="${th.dataset.sort}"]`)?.focus(); return; }                // the keyboard stays on the column it sorted
  
  const b = e.target.closest('[data-act]');
  if (!b) { const sum = e.target.closest('summary'); if (sum) { e.preventDefault(); toggleRecipe(sum.closest('details')); } return; }          // the row is opened and closed here, with its animation
  e.preventDefault();                                                                                              // a button inside a summary must not fold the recipe
  const id = b.closest('details').dataset.recipe, act = b.dataset.act, row = b.closest('tr'), r = state.library.recipes.find((x) => x.id === id);
  if (act === 'dos-new') openSettingsDosage(id, null);
  else if (act === 'dos-edit') openSettingsDosage(id, row?.dataset.dosage);
  else if (act === 'dos-del') { const d = r?.dosages.find((x) => x.id === row?.dataset.dosage); if (d) deleteDosageOf(id, d); }
  else if (act === 'del') deleteRecipe(id); else openRecipeDialog(act === 'edit' ? 'edit' : 'dup', id);
});
$('#tbl-recipes').addEventListener('toggle', (e) => {                                                                       // the browser opened or closed a recipe by itself (find in page, for one): follow it
  const d = e.target.closest('details'); if (!d || d._anim || d.open === d.hasAttribute('data-open')) return;
  d.toggleAttribute('data-open', d.open); openRecipe = openAfterToggle(openRecipe, d.dataset.recipe, d.open);
  if (d.open) for (const other of $('#tbl-recipes').querySelectorAll('details.recipe[data-open]')) if (other !== d) setRecipeOpen(other, false);
}, true);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshLibrary(); });           // another browser may have changed the library
$('#st-warn').onclick = (e) => { const pop = $('#warn-pop'); pop.hidden = !pop.hidden; e.currentTarget.setAttribute('aria-expanded', String(!pop.hidden)); };
document.addEventListener('click', (e) => { if (!e.target.closest('#warn-pop') && !e.target.closest('#st-warn')) { $('#warn-pop').hidden = true; $('#st-warn').setAttribute('aria-expanded', 'false'); } });
$('#set-outline').oninput = (e) => { const v = num(e.target); if (v && v > 0) { state.minOutline = v; plane.invalidate(); plane.draw(); scheduleCheck(); updateDirty(); } };
// drag and drop of files
let dragDepth = 0; const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
window.addEventListener('dragenter', (e) => { if (hasFiles(e)) { dragDepth++; $('#drop').hidden = false; } });
window.addEventListener('dragover', (e) => { if (hasFiles(e)) e.preventDefault(); });
window.addEventListener('dragleave', (e) => { if (hasFiles(e) && --dragDepth <= 0) { dragDepth = 0; $('#drop').hidden = true; } });
window.addEventListener('drop', (e) => { if (!hasFiles(e)) return; e.preventDefault(); dragDepth = 0; $('#drop').hidden = true; addFiles([...e.dataTransfer.files]); });
// keyboard
window.addEventListener('keydown', (e) => {
  if (document.querySelector('dialog[open]')) return;
  const tag = e.target.tagName, typing = ['INPUT', 'SELECT', 'TEXTAREA'].includes(tag);
  const mod = e.ctrlKey || e.metaKey, k = e.key;
  if (k === '?' && !typing && !mod) { setView('help'); $('#tab-help').focus(); return; }                // from any tab
  if (state.view !== 'plane') return;
  if (mod && k.toLowerCase() === 'z') { if (typing) return; e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
  if (mod && k.toLowerCase() === 'y') { if (typing) return; e.preventDefault(); redo(); return; }
  if (typing || mod) return;
  const b = selected(), step = e.shiftKey ? 1 : e.altKey ? 0.01 : 0.1;
  if (k === 'f' || k === 'F' || k === '0') { plane.fit(); return; }
  if (k === '+' || k === '=') { plane.zoomBy(1.25); return; } if (k === '-' || k === '_') { plane.zoomBy(0.8); return; }
  if (k === 'g' || k === 'G') { state.grid = !state.grid; renderToggles(); plane.draw(); return; }
  if (k === '1') return setMode('material'); if (k === '2') return setMode('light'); if (k === '3') return setMode('exact');
  if (!b) return;
  const arrows = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
  if (arrows[k]) { e.preventDefault(); nudge(b, ...arrows[k]); return; }
  if (k === 'r') rotate(b, TURN.ccw); else if (k === 'R') rotate(b, TURN.cw); else if (k === 'm' || k === 'M') { b.mirror = !b.mirror; app.changed(true); }
  else if (k === 'Delete' || k === 'Backspace') { e.preventDefault(); removeBoard(b.id); }
});
window.addEventListener('resize', () => { placeIndicator(); placeRail(); });

// ---------------------------------------------------------------------------------------------------------------
// start
const savedLang = store.get('gs-lang') || 'it';
setLang(savedLang); document.documentElement.lang = savedLang; applyI18n(); renderLang(); renderKeys(); applyMenubar(); document.fonts?.ready.then(placeIndicator);
renderToggles(); setSection(store.get('gs-sec') || 'boards'); setSideWidth(parseInt(store.get('gs-side')) || SIDE.def, false);
(async function start() {
  try {
    state.info = await api.getInfo();
    state.printers = state.info.printers; state.defaultPrinter = state.info.default_printer; setPrinter(state.defaultPrinter);
    renderSideStatus();
  } catch (e) { toast(errorText(e)); }
  await loadLibrary();                                                         // before a project is recovered: the project's recipe is looked up in it
  commit(); refreshAll(); plane.fit(); state.saved = fingerprint(); updateDirty();
  await wc.claim().catch(() => {});                                            // this tab's id: Save needs it whatever happens next
  const sample = new URLSearchParams(location.search).get('sample');           // only when the server was started with a folder of samples
  if (!sample) await recoverWork();                                            // a sample is opened instead of the last work
  if (sample && state.info?.dev_samples?.includes(sample)) {
    const r = await fetch('/dev/samples/' + encodeURIComponent(sample));
    if (r.ok) await addFiles([new File([await r.blob()], sample)]);
  }
})();
