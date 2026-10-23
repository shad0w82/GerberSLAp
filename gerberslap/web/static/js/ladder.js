// The Calibration ladder as the page shows it, without the DOM (so that it is tried with Node): the values of the page and how they are remembered, what they say
// (the totals of the steps, the flash, the layers), what is wrong with them for a printer, where the strips go on the plane, the test drawing in every strip and the
// preview (an SVG), with its zoom. The drawing is in millimetres on the plane seen from above, the back at the top, as the CadWindow shows it.
//
// The ladder is a set of strips side by side, the first on the left; the strip k is lit for k times the time of the first one: the layer i of the file opens
// the strips from i on, every layer with the same time (the printer takes one time for all of them: see the file-format notes, `ctb_*_formato.md`). Each step is
// made of `pulses` flashes of `step / pulses` seconds with the rest between them. A strip has the size the person chooses (`width` × `height`, 1 mm of dark
// between two strips) and, under its time, the tests the person switched on: blocks of copper that are laid out in rows (see `stripDrawing`).
// THE FILE OF THE LADDER (step 7d) MUST HAVE THE SAME LAYOUT AS THIS: the strips, the blocks, the way they are laid out and the text are the contract, and a test
// will compare the two.
import { POLARITIES } from './exposure.js';

export const STRIP = { w: 13, h: 76, gap: 1 };                         // mm: the size a strip starts with, and the dark between two strips
export const LIMITS = { step: [1, 600], bands: [2, 20], pulses: [1, 20], rest: [0, 60], width: [6, 40], height: [15, 150] };
export const VIEWS = ['material', 'uv'];
// the tests a strip can hold, in the order they are laid out (and listed on the page)
export const TESTS = ['lines_v', 'lines_h', 'gaps', 'soic8', 'fine', 'passives', 'rings'];
// those of the first ladder tried on a printer, at the size it had, with all the tests
export const DEFAULTS = { step: 10, bands: 8, pulses: 2, rest: 4, width: STRIP.w, height: STRIP.h, tests: [...TESTS], polarity: 'positive', mirror: false, view: 'material' };
const NUMBERS = [['step', false], ['bands', true], ['pulses', true], ['rest', false], ['width', false], ['height', false]];     // the fields, and whether each is a whole number
const within = (x, key, whole) => typeof x === 'number' && Number.isFinite(x) && x >= LIMITS[key][0] && x <= LIMITS[key][1] && (!whole || Number.isInteger(x));

// What the browser remembers of the page (the last values used); anything damaged or half-typed falls back to the default of that value.
export function parseLadder(text) {
  let v = null; try { v = JSON.parse(text); } catch { /* nothing remembered */ }
  if (!v || typeof v !== 'object' || Array.isArray(v)) return { ...DEFAULTS, tests: [...TESTS] };
  const out = { polarity: POLARITIES.includes(v.polarity) ? v.polarity : DEFAULTS.polarity, mirror: v.mirror === true, view: VIEWS.includes(v.view) ? v.view : DEFAULTS.view,
    tests: Array.isArray(v.tests) ? TESTS.filter((id) => v.tests.includes(id)) : [...TESTS] };                                  // a list that is there is kept (even empty); one that is not, is all of them
  for (const [key, whole] of NUMBERS) out[key] = within(v[key], key, whole) ? v[key] : DEFAULTS[key];
  return out;
}
// the numbers, as the fields have them (`null` for one not filled in): good enough to say what the file would be?
export const isValid = (v) => !!v && NUMBERS.every(([k, whole]) => within(v[k], k, whole));

// what the values make: the time of every step (k times the first), the flash, and how many layers the file has
export function ladderSpec(v) {
  return { bands: v.bands, flash: v.step / v.pulses, layers: v.bands * v.pulses, totals: Array.from({ length: v.bands }, (_, i) => (i + 1) * v.step), first: v.step, last: v.bands * v.step };
}
// Where the strips are on the plane: centred both ways. `fits` says whether all of it is inside the plane (a ladder is a piece of copper: it has to fit the board).
export function ladderLayout(v, plane) {
  const pitch = v.width + STRIP.gap, width = (v.bands - 1) * pitch + v.width, x0 = (plane.w - width) / 2, y0 = (plane.h - v.height) / 2;
  const strips = Array.from({ length: v.bands }, (_, i) => ({ i, x: x0 + i * pitch, y: y0, w: v.width, h: v.height, total_s: (i + 1) * v.step }));
  return { x0, y0, width, height: v.height, pitch, strips, fits: x0 >= -1e-9 && y0 >= -1e-9, drawing: stripDrawing(v.width, v.height, v.tests) };
}
// what is wrong, for a printer (`limits` are the printer's: `min_flash_s`, `max_proven_flash_s`; `plane` is what `planeOf` gives). The first three stop the file, the
// others only say: the ladder does not fit the plane, a flash is under the minimum; tests that have no room in the strip; no test chosen; a flash over the longest tried.
export function ladderIssues(v, plane, limits) {
  if (!isValid(v)) return [];
  const out = [], flash = v.step / v.pulses, l = ladderLayout(v, plane);
  if (limits?.min_flash_s != null && flash < limits.min_flash_s) out.push({ kind: 'flash_below', flash, min: limits.min_flash_s });
  else if (limits?.max_proven_flash_s != null && flash > limits.max_proven_flash_s) out.push({ kind: 'flash_beyond', flash, max: limits.max_proven_flash_s });
  if (!l.fits) out.push({ kind: 'too_big', w: l.width, h: l.height, pw: plane.w, ph: plane.h, sw: v.width, maxn: Math.floor((plane.w + STRIP.gap) / (v.width + STRIP.gap)), maxh: plane.h });
  if (!v.tests.length) out.push({ kind: 'no_tests' });
  else if (l.drawing.dropped.length) out.push({ kind: 'dropped', ids: l.drawing.dropped });
  return out;
}
// the file can be generated: the values are good, the flash is not under the minimum and the ladder fits the plane
export const canGenerate = (v, plane, limits) => isValid(v) && !ladderIssues(v, plane, limits).some((x) => x.kind === 'flash_below' || x.kind === 'too_big');

// ---------------------------------------------------------------------------------------------------------------
// The tests. Each one is made of one or more pieces of copper (what is to be left on the board), each drawn from its own corner (0, 0) in millimetres, x to the right and y
// down. A shape is { r: [x, y, w, h] } a rectangle, { ring: [cx, cy, outer, inner] } a pad with a hole (the two diameters) or { dot: [cx, cy, r] } a round pad.
// A piece is as big as its shapes (`h` can be given, to make it taller). The fine details are far apart so that they
// can be told (0.10 mm is about two pixels of the plane the ladder was tried on). `gx` is the space between the pieces of a test when they stand side by side.
const R = (x, y, w, h) => ({ r: [x, y, w, h] });
const range = (n) => Array.from({ length: n }, (_, k) => k);
const FINE = (() => { const out = [], row = (n, pitch, w, y) => { const x0 = (5.78 - ((n - 1) * pitch + w)) / 2; for (let k = 0; k < n; k++) out.push(R(x0 + k * pitch, y, w, 1.3)); }; row(8, 0.65, 0.35, 0); row(12, 0.5, 0.28, 2.5); row(14, 0.4, 0.2, 5); return out; })();
const DEFS = {
  lines_v: { gx: 0.35, pieces: () => [0.10, 0.15, 0.20, 0.30, 0.40].map((w) => ({ s: range(5).map((k) => R(k * 2 * w, 0, w, 8.5)) })) },                         // lines and spaces, vertical: five of each width
  lines_h: { gx: 0.25, pieces: () => [0.10, 0.15, 0.20, 0.30, 0.40].map((w) => ({ s: range(5).map((k) => R(0, k * 2 * w, 2.2, w)) })) },                         // ... and horizontal
  gaps: { gx: 0.8, pieces: () => [0.10, 0.15, 0.20, 0.30].map((g) => ({ s: [R(0, 0, 1.1, 3.6), R(1.1 + g, 0, 1.1, 3.6)] })) },                                  // two pads with a narrow gap
  soic8: { gx: 0.8, pieces: () => [{ s: range(4).flatMap((k) => [R(0, k * 1.27, 1.5, 0.6), R(5.4, k * 1.27, 1.5, 0.6)]) }] },                                    // a SOIC-8 (1.27 mm pitch)
  fine: { gx: 0.8, pieces: () => [{ s: FINE }] },                                                                                                               // pads at 0.65, 0.5 and 0.4 mm, centred on each other
  passives: { gx: 0.8, pieces: () => [{ s: [R(0, 0, 1.2, 1.4), R(2.2, 0, 1.2, 1.4)] }, { s: [R(0, 0, 0.9, 0.95), R(1.7, 0, 0.9, 0.95)] }, { s: [R(0, 0, 0.6, 0.6), R(1.1, 0, 0.6, 0.6)] }] },   // 0805, 0603, 0402
  rings: { gx: 0.8, pieces: () => [{ s: [{ ring: [1, 1, 2.0, 0.8] }], h: 2 }, { s: [{ ring: [0.8, 1, 1.6, 0.6] }], h: 2 }, { s: [{ ring: [0.6, 1, 1.2, 0.5] }], h: 2 }, { s: [{ dot: [0.4, 1, 0.4] }], h: 2 }] },   // pads with a hole, and a round one
};
function bounds(s) {
  if (s.r) return [s.r[0], s.r[1], s.r[0] + s.r[2], s.r[1] + s.r[3]];
  if (s.ring) return [s.ring[0] - s.ring[2] / 2, s.ring[1] - s.ring[2] / 2, s.ring[0] + s.ring[2] / 2, s.ring[1] + s.ring[2] / 2];
  return [s.dot[0] - s.dot[2], s.dot[1] - s.dot[2], s.dot[0] + s.dot[2], s.dot[1] + s.dot[2]];
}
function moved(s, dx, dy) {
  if (s.r) return { r: [s.r[0] + dx, s.r[1] + dy, s.r[2], s.r[3]] };
  if (s.ring) return { ring: [s.ring[0] + dx, s.ring[1] + dy, s.ring[2], s.ring[3]] };
  return { dot: [s.dot[0] + dx, s.dot[1] + dy, s.dot[2]] };
}
// each test with its pieces and their sizes (the box of their shapes, from (0, 0))
export const BLOCK = Object.fromEntries(TESTS.map((id) => [id, {
  id, gx: DEFS[id].gx,
  pieces: DEFS[id].pieces().map((p) => { const b = p.s.map(bounds); return { shapes: p.s, w: Math.max(...b.map((x) => x[2])), h: p.h ?? Math.max(...b.map((x) => x[3])) }; }),
}]));

// How the tests of a strip are laid out. The time takes the top (`HEAD` mm from the back); under it the tests go in the order of TESTS. A test is put at the end of the last
// row if all of it fits there (`GAP_X` mm after the one before); if not, on a new row, and its pieces wrap onto more rows when they do not fit the width (`MARGIN` mm
// are kept free at each side). A piece wider than the strip has no room; rows that do not fit the height (with at least `GAP_Y[0]` between them) are left out from the
// last one on; the tests that lost a piece are reported. Every row is centred, with its pieces at the top, and the rows are spread over the height with the gap between
// them growing to `GAP_Y[1]`. Returns { shapes, dropped, rows }.
export const HEAD = 9, FOOT = 0.8, MARGIN = 0.3, GAP_X = 0.8, GAP_Y = [1.2, 3.5];
export function stripDrawing(width, height, tests) {
  const inner = width - 2 * MARGIN, avail = height - HEAD - FOOT, rows = [], dropped = new Set(), eps = 1e-9;
  for (const id of TESTS.filter((x) => tests.includes(x))) {
    const b = BLOCK[id], pieces = b.pieces.filter((p) => { if (p.w > inner + eps) dropped.add(id); return p.w <= inner + eps; });
    if (!pieces.length) continue;
    const total = pieces.reduce((a, p) => a + p.w, 0) + (pieces.length - 1) * b.gx;
    let row = rows.at(-1); if (!(row && row.w + GAP_X + total <= inner + eps)) row = null;               // all of it at the end of the last row, or on a new one
    for (const p of pieces) {
      if (row && row.w + (row.last === id ? b.gx : GAP_X) + p.w > inner + eps) row = null;              // (this piece does not fit the row any more)
      if (!row) { row = { items: [], w: 0, h: 0, last: null }; rows.push(row); }
      const gap = row.items.length ? (row.last === id ? b.gx : GAP_X) : 0;
      row.items.push({ id, p, dx: row.w + gap }); row.w += gap + p.w; row.h = Math.max(row.h, p.h); row.last = id;
    }
  }
  const taken = (n) => rows.slice(0, n).reduce((a, r) => a + r.h, 0) + Math.max(0, n - 1) * GAP_Y[0];
  while (rows.length && taken(rows.length) > avail + eps) for (const it of rows.pop().items) dropped.add(it.id);
  const sum = rows.reduce((a, r) => a + r.h, 0), gap = rows.length > 1 ? Math.min(GAP_Y[1], Math.max(GAP_Y[0], (avail - sum) / (rows.length - 1))) : 0;
  const shapes = [], placed = []; let y = HEAD;
  for (const row of rows) {
    const x0 = (width - row.w) / 2;
    for (const it of row.items) for (const sh of it.p.shapes) shapes.push(moved(sh, x0 + it.dx, y));
    placed.push({ y, h: row.h, ids: [...new Set(row.items.map((it) => it.id))] }); y += row.h + gap;
  }
  return { shapes, dropped: TESTS.filter((id) => dropped.has(id)), rows: placed };
}
// the time written at the top of a strip: its size shrinks with the number of characters (and with a narrow strip) so that it stays inside it
export const labelSize = (text, width = STRIP.w) => Math.min(4.4, (width - 0.5) / (text.length * 0.6));
export const LABEL_Y = 6.2;                                                                                                                                    // mm from the back: the baseline of the time

const n3 = (x) => +x.toFixed(3);
function shapesSvg(list) {
  return list.map((s) => {
    if (s.r) { const [x, y, w, h] = s.r; return `<rect fill="currentColor" x="${n3(x)}" y="${n3(y)}" width="${n3(w)}" height="${n3(h)}"/>`; }
    if (s.ring) { const [cx, cy, o, i] = s.ring; return `<circle fill="none" stroke="currentColor" cx="${n3(cx)}" cy="${n3(cy)}" r="${n3((o + i) / 4)}" stroke-width="${n3((o - i) / 2)}"/>`; }
    const [cx, cy, r] = s.dot; return `<circle fill="currentColor" cx="${n3(cx)}" cy="${n3(cy)}" r="${r}"/>`;
  }).join('');
}

// The plane seen from above with the ladder in it. `view` is 'material' (the copper that is to be left) or 'uv' (what the LCD projects: white where the light passes,
// which is the lit strip with the copper dark for a positive resist and only the copper for a negative one); a mirrored ladder is turned over left to right (the text
// too). `box` is the part shown: { x, y, w, h } in mm. `sec` writes a number of seconds. The drawing of the strips is made once and used by all of them (`<use>`): its
// colour is the `color` of the `<use>` (the stylesheet sets it by view and resist), which the shapes take as `currentColor`.
export function ladderSvg(layout, { plane, view, polarity, mirror, box, sec }) {
  const flip = mirror ? ` transform="translate(${n3(plane.w)} 0) scale(-1 1)"` : '';
  const strips = layout.strips.map((s) => {
    const text = `${sec(s.total_s)} s`;
    return `<g transform="translate(${n3(s.x)} ${n3(s.y)})"><rect class="ld-field" x="0" y="0" width="${n3(s.w)}" height="${n3(s.h)}"/><use href="#ld-draw"/>`
      + `<text class="ld-text" x="${n3(s.w / 2)}" y="${LABEL_Y}" text-anchor="middle" font-size="${n3(labelSize(text, s.w))}" font-weight="700">${text}</text></g>`;
  }).join('');
  const pol = polarity === 'negative' ? 'neg' : 'pos';
  return `<svg viewBox="${n3(box.x)} ${n3(box.y)} ${n3(box.w)} ${n3(box.h)}" class="ld-plane ld-${view} ${pol}${layout.fits ? '' : ' out'}" aria-hidden="true" focusable="false">`
    + `<defs><pattern id="ld-grid" width="10" height="10" patternUnits="userSpaceOnUse"><path class="ld-gl" d="M10 0H0V10"/></pattern><g id="ld-draw">${shapesSvg(layout.drawing.shapes)}</g></defs>`
    + `<rect class="ld-bg" x="0" y="0" width="${n3(plane.w)}" height="${n3(plane.h)}" rx="2"/><rect class="ld-grid" x="0" y="0" width="${n3(plane.w)}" height="${n3(plane.h)}" fill="url(#ld-grid)"/>`
    + `<g${flip}>${strips}</g><rect class="ld-edge" x="0" y="0" width="${n3(plane.w)}" height="${n3(plane.h)}" rx="2"/></svg>`;
}

// ---------------------------------------------------------------------------------------------------------------
// The zoom of the preview. The part shown is a box { x, y, w, h } of the plane (mm) with always the proportions of the whole (the pad is 1 mm around the plane), so
// the picture fills its frame at any zoom; it cannot leave the whole and cannot be smaller than a twentieth of it.
export const MAX_ZOOM = 20;
export const fitBox = (plane) => ({ x: -1, y: -1, w: plane.w + 2, h: plane.h + 2 });
const clampBox = (b, fit) => ({ x: Math.min(Math.max(b.x, fit.x), fit.x + fit.w - b.w), y: Math.min(Math.max(b.y, fit.y), fit.y + fit.h - b.h), w: b.w, h: b.h });
export const zoomOf = (b, fit) => fit.w / b.w;
// zoom by `factor` keeping the point (cx, cy) of the plane where it is
export function zoomBox(b, factor, cx, cy, fit) {
  const w = Math.min(fit.w, Math.max(fit.w / MAX_ZOOM, b.w / factor)), k = w / b.w, h = b.h * k;
  return clampBox({ x: cx - (cx - b.x) * k, y: cy - (cy - b.y) * k, w, h }, fit);
}
export const panBox = (b, dx, dy, fit) => clampBox({ ...b, x: b.x + dx, y: b.y + dy }, fit);
// the point of the plane under a point of the frame (px): `rect` is the frame's { left, top, width, height }
export const boxPoint = (b, rect, px, py) => [b.x + ((px - rect.left) / rect.width) * b.w, b.y + ((py - rect.top) / rect.height) * b.h];

// ---------------------------------------------------------------------------------------------------------------
// The file of the ladder. What the server is told (the values, with the tests in the order they are laid out, and the printer), what makes the same file (the key: a note of the last file
// stays only while it is the same), and why "Generate" is off.
export const ladderRequest = (v, printerId) => ({ printer_id: printerId || null, supersample: 16,
  ladder: { step: v.step, bands: v.bands, pulses: v.pulses, rest: v.rest, width: v.width, height: v.height, tests: TESTS.filter((id) => v.tests.includes(id)), polarity: v.polarity, mirror: v.mirror } });
export const ladderKey = (v, printerId) => JSON.stringify(ladderRequest(v, printerId));
// Why the file cannot be made now, or null: the printer's own problem first (its issues, which come with `/api/info`), then values that are not good, then a flash under the minimum or a ladder that
// does not fit the plane (the same rule as `canGenerate`). The page already says the last two in its notes and its summary: only the printer's is said again under the button.
export function ladderBlock(v, plane, limits, printerIssues) {
  const printer = printerIssues.find((i) => i.blocking);
  if (printer) return { kind: 'printer', issue: printer };
  if (!isValid(v)) return { kind: 'values' };
  const found = ladderIssues(v, plane, limits).find((x) => x.kind === 'flash_below' || x.kind === 'too_big');
  return found ? { kind: 'ladder', note: found } : null;
}
