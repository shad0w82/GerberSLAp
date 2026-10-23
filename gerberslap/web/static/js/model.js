// Boards in the browser and the maths of placing them on the plane (mm; u left to right, v front to back, the back at the top of the
// screen; rotation counterclockwise seen from above; mirror before rotation, both about the board's extent centre). The API sends
// boards as the backend's own model; here they get a few shortcuts (x, y, angle, mirror, w, h) because the UI reads them all the time.

export const rad = (d) => (d * Math.PI) / 180;
export const TAU = Math.PI * 2;

// A board as the UI holds it. `api` is the board the backend returned; `cx, cy` is the centre of the board in the coordinates of its own
// files (the shapes are sent relative to it), and `x, y` is where that centre sits on the plane.
export function fromApi(api, notes = [], cad = '') {
  return {
    id: api.id, name: api.name, source: api.source, w: api.size.width_mm, h: api.size.height_mm, cx: api.source_center[0], cy: api.source_center[1],
    x: api.placement.x, y: api.placement.y, angle: api.placement.angle, mirror: api.placement.mirror, cad, notes,
    layers: api.layers.map((l) => ({ id: l.id, role: l.role, name: l.name, files: l.files, side: l.side, on: l.on, status: l.status, ...(l.color ? { color: l.color } : {}) })),
  };
}

// The board in the form the backend validates and uses (its Project model).
// the layer a board's area comes from: the outline layer without an error with the smallest id, switched on or not, wherever it stands
// in the list (the backend picks the same one)
export const areaOutline = (b) => b.layers.filter((l) => l.role === 'outline' && l.status.level !== 'error').reduce((m, l) => (!m || l.id < m.id ? l : m), null);

// What a board is called in the page: its name with the extension of the file it came from (a copy keeps its own name: "x (2).zip"), so that
// there is one name for it and not a name and a file name side by side. The model's `name` stays as it is.
export function boardTitle(b) {
  const ext = /\.[A-Za-z0-9]{1,6}$/.exec(b.source || '')?.[0] ?? '';
  return ext && !b.name.toLowerCase().endsWith(ext.toLowerCase()) ? b.name + ext : b.name;
}

// ---- the printer: it fixes the plane (size in mm and pixel grid) the page draws and the server computes on -----------------------------
// The page's plane for a printer as `/api/info` describes it.
export const planeOf = (p) => ({ w: p.plane.width_mm, h: p.plane.height_mm, px: [p.grid.width, p.grid.height], pitch: p.grid.pitch, name: p.name });
// Which printer a project is for: the one it asks for if this app has it; otherwise the printer in use (or the default one), and `unknown` names
// what the project asked for and the app does not have, so that it can be said instead of replaced in silence. A project with none asks for none.
export function pickPrinter(requested, printers, current, fallback) {
  const has = (id) => printers.some((p) => p.id === id);
  if (requested && has(requested)) return { id: requested, unknown: null };
  return { id: has(current) ? current : fallback, unknown: requested ? requested : null };
}
// The size of a printer's plane and its pixels, and with the name in front the line of the printer pill. `fmt(number, decimals)` writes a number the way
// the page's language does.
export const planeSize = (p, fmt) => `${fmt(p.plane.width_mm, 2)} × ${fmt(p.plane.height_mm, 2)}`;                      // in mm: the unit is where the number is shown (the column name, the line)
export const pixelSize = (p) => `${p.grid.width} × ${p.grid.height}`;                                                    // in px
export const printerSize = (p, fmt) => `${planeSize(p, fmt)} mm · ${pixelSize(p)} px`;
// The size of a pixel of the printer's plane, in micrometres, as the page writes it: whole when it is whole to the tenth of a micrometre, else with one decimal.
export function pitchValue(pitchMm, fmt) {
  const um = pitchMm * 1000;
  return `${Math.abs(um - Math.round(um)) < 0.05 ? Math.round(um) : fmt(um, 1)}`;
}
export const pitchLabel = (pitchMm, fmt) => `${pitchValue(pitchMm, fmt)} µm`;
export const printerLine = (p, fmt) => `${p.name} · ${printerSize(p, fmt)}`;
// What the installation of a printer lacks or gets wrong (its template, its settings), as `/api/info` carries it with each printer. A printer the page
// does not know, or one that came without a list, has nothing to show.
export const printerIssues = (printers, id) => printers.find((p) => p.id === id)?.issues ?? [];

// The warnings pill is only an icon: a green tick when there is nothing to say, else a warning sign and how many (red if one of them is an error).
// `warnings` is a list of { lv: 'warn' | 'bad' }; `t` the page's translator. `label` is the text for the tooltip and the screen reader.
export function warningStatus(warnings, t) {
  const n = warnings.length, bad = warnings.some((w) => w.lv === 'bad');
  return { text: n ? `⚠ ${n}` : '✓', cls: `chip ${bad ? 'bad' : n ? 'warn' : 'ok'}`, label: n ? `${t('warnings')}: ${n}` : t('no_warnings') };
}

// A project file is recognised by its extension: ".gslp" (older ".gerberslap" files are not opened until they are renamed).
export const isProjectFile = (fileName) => /\.gslp$/i.test(fileName);
// The name of a project from the name of its file: without the extension and without control characters.
export const projectStem = (fileName) => fileName.replace(/\.gslp$/i, '').replace(/[\x00-\x1f\x7f]+/g, ' ').trim();
// The name a person types for the project: no control characters (the server refuses them), no ".gslp" at the end, no blanks at the edges, 200 characters at most.
export const cleanProjectName = (text) => projectStem(String(text ?? '')).slice(0, 200).trim();

// The number the next board of the page gets: boards are named b1, b2, ...; a project that is opened brings its own ids (some from
// elsewhere, like b-9f3a2c1d), and a new board must never take one of them.
export const nextBoardNumber = (boards) => 1 + Math.max(0, ...boards.map((b) => +(/^b(\d+)$/.exec(b.id)?.[1] ?? 0)));

// ---- the order of a board's layers --------------------------------------------------------------------------------------------
// The layers of the stack (copper, mask, silkscreen) lie one over the other; the first of the list is the top one and is drawn last. The
// outline (always drawn over the stack) and the holes are kept apart from it and cannot be moved.
export const STACK_ROLES = ['copper', 'mask', 'silk'];
export const isStacked = (l) => STACK_ROLES.includes(l.role);
// The list with the layer `id` at position `to` among the layers of the stack (0 = the top one), or null if nothing would change. The
// other layers stay where they are in the list; only the stack's own places are shuffled.
export function moveLayer(layers, id, to) {
  const slots = layers.flatMap((l, i) => (isStacked(l) ? [i] : [])), stack = slots.map((i) => layers[i]);
  const from = stack.findIndex((l) => l.id === id);
  if (from < 0) return null;
  const target = Math.max(0, Math.min(stack.length - 1, to));
  if (target === from) return null;
  const [moved] = stack.splice(from, 1); stack.splice(target, 0, moved);
  const out = layers.slice(); slots.forEach((slot, k) => { out[slot] = stack[k]; });
  return out;
}
// The layers of a board in the order they are drawn, the first drawn being the lowest: the stack from its bottom up, then the outline over
// all. The list runs from the top side of the board down, and the plane is seen from above; a mirrored board is turned over, so what
// is nearest to the viewer is the bottom side (silkscreen bottom, mask bottom, copper bottom, ...) and the stack is drawn the other way round.
export function drawOrder(b) {
  const stack = b.layers.filter((l) => l.on && isStacked(l));
  return [...(b.mirror ? stack : stack.reverse()), ...b.layers.filter((l) => l.on && l.role === 'outline')];
}
// one place up (delta -1) or down (+1)
export function stepLayer(layers, id, delta) {
  const at = layers.filter(isStacked).findIndex((l) => l.id === id);
  return at < 0 ? null : moveLayer(layers, id, at + delta);
}
export function toApiBoard(b) {
  return {
    id: b.id, name: b.name, source: b.source ?? null, size: { width_mm: b.w, height_mm: b.h }, source_center: [b.cx, b.cy],
    placement: { x: b.x, y: b.y, angle: b.angle, mirror: !!b.mirror },
    layers: b.layers.map((l) => ({ id: l.id, role: l.role, name: l.name, files: l.files, side: l.side, on: l.on, status: l.status, color: l.color || null })),
  };
}
// `recipe` is what the project remembers of its recipe: { id, name, dosageId } (a reference, never the values), or none.
export function toApiProject(boards, polarity, minOutline, printerId = null, recipe = null) {
  return { format: 'gerberslap', schema_version: 2, printer_id: printerId, recipe_id: recipe?.id ?? null, recipe_name: recipe?.name ?? null, dosage_id: recipe?.dosageId ?? null,
           polarity, min_outline_mm: minOutline, boards: boards.map(toApiBoard) };
}

// copies for undo/redo and duplication: plain data, no shared references
export const cloneBoard = (b) => JSON.parse(JSON.stringify(b));

// ---- placement ---------------------------------------------------------------------------------------------
export function localToWorld(b, lx, ly) {
  const m = b.mirror ? -1 : 1, a = rad(b.angle), x = lx * m;
  return [b.x + x * Math.cos(a) - ly * Math.sin(a), b.y + x * Math.sin(a) + ly * Math.cos(a)];
}
export function worldToLocal(b, wx, wy) {
  const a = rad(b.angle), dx = wx - b.x, dy = wy - b.y;
  let x = dx * Math.cos(a) + dy * Math.sin(a);
  const y = -dx * Math.sin(a) + dy * Math.cos(a);
  if (b.mirror) x = -x;
  return [x, y];
}
export function extent(b) {
  const xs = [], ys = [];
  for (const [sx, sy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
    const [x, y] = localToWorld(b, (sx * b.w) / 2, (sy * b.h) / 2);
    xs.push(x); ys.push(y);
  }
  return { minx: Math.min(...xs), maxx: Math.max(...xs), miny: Math.min(...ys), maxy: Math.max(...ys) };
}
export function hit(b, wx, wy) { const [x, y] = worldToLocal(b, wx, wy); return Math.abs(x) <= b.w / 2 && Math.abs(y) <= b.h / 2; }
export function margins(b, plane) { const e = extent(b); return { left: e.minx, right: plane.w - e.maxx, front: e.miny, back: plane.h - e.maxy }; }
export function overlaps(a, b) {
  const ea = extent(a), eb = extent(b);
  return Math.min(ea.maxx, eb.maxx) - Math.max(ea.minx, eb.minx) > 0.01 && Math.min(ea.maxy, eb.maxy) - Math.max(ea.miny, eb.miny) > 0.01;
}
// Anchor the *placed* extent to a corner of the plane (TL = left/back ... BR = right/front) with an inward offset.
export function anchorTo(b, plane, corner, ox, oy) {
  const e = extent(b), cx = (e.minx + e.maxx) / 2, cy = (e.miny + e.maxy) / 2, hw = (e.maxx - e.minx) / 2, hh = (e.maxy - e.miny) / 2;
  const t = { TL: [ox + hw, plane.h - oy - hh], TR: [plane.w - ox - hw, plane.h - oy - hh], BL: [ox + hw, oy + hh],
              BR: [plane.w - ox - hw, oy + hh], C: [plane.w / 2 + ox, plane.h / 2 + oy] }[corner];
  b.x += t[0] - cx; b.y += t[1] - cy;
}

// How the app was started, as `/api/info` says it (`flags`: names only): what the SideStatusBar writes, and what the flags mean, for its tooltip.
// `t` writes a text and `has` says whether the page has it: a flag of a newer server that this page does not know is written as it is.
export const flagsText = (flags) => (flags?.length ? flags.join(' ') : '');
export const flagsTitle = (flags, t, has) => (flags?.length
  ? t('flags_title', { list: flags.map((f) => { const key = 'flag_' + f.replace(/^-+/, '').replace(/-/g, '_'); return has(key) ? t(key) : f; }).join(' · ') }) : '');

// The cursor in the StatusBar: millimetres, then pixels, both written the same way, (x; y). The millimetres count from the bottom-left corner of the plane (the Rulers' zero);
// the pixels are the plane's own grid as it is seen from above, from the top-left corner: (column; row). `c` is [x, y] in mm, `plane` is what `planeOf` gives.
export function cursorText(c, plane, fmt) {
  const col = Math.min(plane.px[0] - 1, Math.max(0, Math.floor(c[0] / plane.pitch))), row = Math.min(plane.px[1] - 1, Math.max(0, Math.floor((plane.h - c[1]) / plane.pitch)));
  return `mm(${fmt(c[0], 2)}; ${fmt(c[1], 2)}) · px(${col}; ${row})`;
}

// The selected board in the StatusBar: name, size, rotation and, when it is mirrored, the word for it (a symbol was too small to read and said little).
export const selectionText = (b, fmt, t) => `${boardTitle(b)} · ${fmt(b.w, 1)} × ${fmt(b.h, 1)} mm · ${fmt(((b.angle % 360) + 360) % 360, 0)}°${b.mirror ? ' · ' + t('st_mirrored') : ''}`;

// How much a board's angle changes for each way of turning it. The angle is counterclockwise as it is seen on the plane (the backend's own rule, `Placement.angle`):
// turning counterclockwise ADDS to it, turning clockwise TAKES from it. The buttons' tooltips say it, the keys R (counterclockwise) and Shift+R (clockwise) do it.
export const TURN = { ccw: 90, cw: -90 };
