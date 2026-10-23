// Recipes and dosages as the page uses them, without the DOM (so that they are tried with Node). A recipe holds its dosages; a dosage is
// total time, flashes and rest found by trying, for ONE printer (`printer_id`); the dosages of a recipe for a printer are alternatives that all
// stay valid. Which one is preselected, how old its values are, what a project does with a recipe the library no longer has, and whether the three
// values typed in the panel are good enough to be saved: all of it is decided here.

export const POLARITIES = ['positive', 'negative'];

// the dosages of a recipe for a printer, the last changed first (of two changed at the same moment, the one later in the list)
export function dosagesFor(recipe, printerId) {
  return (recipe?.dosages ?? []).map((d, i) => [d, i]).filter(([d]) => d.printer_id === printerId)
    .sort((a, b) => Date.parse(b[0].updated) - Date.parse(a[0].updated) || b[1] - a[1]).map(([d]) => d);
}
// the dosage in use: the one the project chose if it is for this printer, else the last changed for this printer, else none
export function preselected(recipe, printerId, dosageId) {
  const list = dosagesFor(recipe, printerId);
  return list.find((d) => d.id === dosageId) ?? list[0] ?? null;
}

// the three values, as the API names them; `null` for a field not filled in
export const valuesOf = (d) => (d ? { total_s: d.total_s, pulses: d.pulses, rest_s: d.rest_s } : null);
export const sameValues = (a, b) => !!a && !!b && a.total_s === b.total_s && a.pulses === b.pulses && a.rest_s === b.rest_s;
// good enough to be saved or used (the server's limits: 0 < total <= 36000 s, 1 to 1000 flashes, 0 to 3600 s of rest)
export const isComplete = (v) => !!v && Number.isFinite(v.total_s) && v.total_s > 0 && v.total_s <= 36000 && Number.isInteger(v.pulses) && v.pulses >= 1
  && v.pulses <= 1000 && Number.isFinite(v.rest_s) && v.rest_s >= 0 && v.rest_s <= 3600;
export const flashOf = (v) => v.total_s / v.pulses;
// what the printer's limits say of a single flash: under the minimum it cannot be generated; over the longest proven one it can, with a warning
export function flashNote(v, limits) {
  if (!isComplete(v) || !limits) return null;
  const flash = flashOf(v);
  if (limits.min_flash_s != null && flash < limits.min_flash_s) return { kind: 'below', flash, min: limits.min_flash_s };
  if (limits.max_proven_flash_s != null && flash > limits.max_proven_flash_s) return { kind: 'beyond', flash, max: limits.max_proven_flash_s };
  return null;
}

// how old the values are: today, a number of days (under two months) or of months
export function ageOf(updated, nowMs) {
  const days = Math.max(0, Math.round((nowMs - Date.parse(updated)) / 864e5));
  return days === 0 ? { unit: 'today', n: 0 } : days < 60 ? { unit: 'days', n: days } : { unit: 'months', n: Math.round(days / 30) };
}

// The last values typed by hand are remembered by the browser (not a library); what was remembered may be half-typed, or damaged by a person.
export function parseRemembered(text) {
  try {
    const v = JSON.parse(text);
    if (!v || typeof v !== 'object' || Array.isArray(v)) return null;
    const num = (x) => (typeof x === 'number' && Number.isFinite(x) ? x : null);
    const out = { total_s: num(v.total_s), pulses: num(v.pulses), rest_s: num(v.rest_s) };
    return out.total_s === null && out.pulses === null && out.rest_s === null ? null : out;
  } catch { return null; }
}

// What a project that names a recipe becomes against the library of this server. The recipe's polarity wins over the one the project saved (a
// polarity that is wrong ruins the board), and it is said; a recipe the library does not have is said too, and the polarity saved with the project
// is kept with no recipe. Without a library (or a project with no recipe) there is nothing to reconcile: only the polarity.
export function reconcileRecipe(project, library) {
  const saved = POLARITIES.includes(project.polarity) ? project.polarity : null;
  const polarity = saved ?? 'positive';
  if (!library.on || !project.recipe_id) return { recipeId: null, dosageId: null, polarity, notice: null };
  const recipe = library.recipes.find((r) => r.id === project.recipe_id);
  if (!recipe) return { recipeId: null, dosageId: null, polarity, notice: { kind: 'recipe_missing', name: project.recipe_name || '' } };
  const differs = saved !== null && saved !== recipe.polarity;
  return { recipeId: recipe.id, dosageId: project.dosage_id ?? null, polarity: recipe.polarity,
           notice: differs ? { kind: 'polarity_changed', name: recipe.name, was: saved, now: recipe.polarity } : null };
}

// the recipes by name (the server sorts the same way), and the list after one recipe was added, replaced or taken out
export const sortRecipes = (recipes) => [...recipes].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }) || (a.id < b.id ? -1 : 1));
export const putRecipe = (recipes, recipe) => sortRecipes([...recipes.filter((r) => r.id !== recipe.id), recipe]);
export const dropRecipe = (recipes, id) => recipes.filter((r) => r.id !== id);

// the short form of what a recipe says of its resist, its development and its notes: the text alone, one line, a dot between them (the empty ones are left out)
export const recipeBrief = (r) => [r.resist, r.development, r.notes].map((x) => (x ?? '').replace(/\s+/g, ' ').trim()).filter(Boolean).join(' · ');

// ---- the table of a recipe's dosages, sortable by clicking a column's name
// Default order: by printer, then the last changed first. A column is clicked: ascending, again: descending, a third time: back to the default.
export const DOSAGE_COLUMNS = ['printer', 'name', 'updated', 'total', 'pulses', 'rest', 'note'];
export function nextSort(current, key) {
  if (!current || current.key !== key) return { key, dir: 'asc' };
  return current.dir === 'asc' ? { key, dir: 'desc' } : null;
}
// `printerName(id)` gives the name shown for a printer: the table is sorted as the person reads it. Empty names and notes go last in both directions.
export function sortDosages(dosages, sort, printerName = (id) => id) {
  const text = (a, b) => a.localeCompare(b, undefined, { sensitivity: 'base', numeric: true });
  const byDefault = (a, b) => text(printerName(a.printer_id), printerName(b.printer_id)) || Date.parse(b.updated) - Date.parse(a.updated);
  const value = { printer: (d) => printerName(d.printer_id), name: (d) => d.name || '', updated: (d) => Date.parse(d.updated), total: (d) => d.total_s,
                  pulses: (d) => d.pulses, rest: (d) => d.rest_s, note: (d) => d.note || '' };
  const list = [...dosages].map((d, i) => [d, i]);
  if (!sort || !value[sort.key]) return list.sort((a, b) => byDefault(a[0], b[0]) || a[1] - b[1]).map(([d]) => d);
  const sign = sort.dir === 'desc' ? -1 : 1, get = value[sort.key];
  return list.sort((a, b) => {
    const x = get(a[0]), y = get(b[0]);
    if (x === '' || y === '') return x === y ? byDefault(a[0], b[0]) || a[1] - b[1] : (x === '' ? 1 : -1);          // empty last, whichever the direction
    const c = typeof x === 'string' ? text(x, y) : x - y;
    return sign * c || byDefault(a[0], b[0]) || a[1] - b[1];
  }).map(([d]) => d);
}

// a column name that ends with its unit in brackets ("Tempo totale (s)"): the name and the unit apart, so that the page can set the unit smaller
export function splitUnit(text) {
  const m = /^(.*\S)\s*(\([^()]*\))\s*$/.exec(text ?? '');
  return m ? { label: m[1], unit: m[2] } : { label: text ?? '', unit: '' };
}

// a quantity with its unit written out ("1 second", "12.5 seconds"): the key `<base>_one` for exactly 1, `<base>_many` for the rest; `shown` is the number as it is written
export const quantity = (t, base, n, shown = n) => t(base + (n === 1 ? '_one' : '_many'), { n: shown });

// the recipes of Settings are an accordion: only one is open. `current` is the id of the open one (or null) and the browser says that `id` was opened or
// closed. The recipe that closes because another one opened reports it AFTER that one opened: it must not close the new one.
export const openAfterToggle = (current, id, open) => (open ? id : (current === id ? null : current));

// the two key frames of a row opening or closing: its height goes from `from` to `to` (px) and the content fades with it
export function heightFrames(from, to) {
  const full = Math.max(from, to) || 1;
  return [{ height: `${from}px`, opacity: from / full }, { height: `${to}px`, opacity: to / full }];
}

// ---- the file of the board: what the server is told, why "Generate" is off, and what it says afterwards
// The server does not read the library: with each request that depends on it the page says which recipe was chosen (none: the values and the polarity are by hand).
export const recipeSnap = (r) => (r ? { id: r.id, name: r.name, polarity: r.polarity } : null);
// The checks need the values only if they are good: `exposure: null` says "there are none yet". (A request with no `exposure` key at all would be checked for its layout only.)
export const checkRequest = (project, values, recipe) => ({ project, exposure: isComplete(values) ? valuesOf(values) : null, recipe: recipeSnap(recipe) });
export const generateRequest = (project, polarity, values, recipe, name) => ({ project, polarity, exposure: valuesOf(values), recipe: recipeSnap(recipe), name: name || null, supersample: 16 });

// Why the file cannot be made now, or null. In this order: no board; a printer that is not ready (its own issues, which come with `/api/info`); a check that failed or has not answered
// yet; then the first thing the checks say blocks it. `issue` is what the page turns into a sentence.
export function generateBlock({ boards, printerIssues, issues, checkFailed, checking }) {
  if (!boards) return { kind: 'no_board' };
  const printer = printerIssues.find((i) => i.blocking);
  if (printer) return { kind: 'issue', issue: printer };
  if (checkFailed) return { kind: 'check_failed' };
  if (checking) return { kind: 'checking' };
  const found = issues.find((i) => i.blocking);
  return found ? { kind: 'issue', issue: found } : null;
}

// a length of time as people say it: 48 s, 12 min 5 s, 2 h 05 min
export function durationText(seconds) {
  const n = Math.max(0, Math.round(seconds));
  if (n < 60) return `${n} s`;
  const m = Math.floor(n / 60), s = n % 60;
  if (m < 60) return s ? `${m} min ${s} s` : `${m} min`;
  const h = Math.floor(m / 60), r = m % 60;
  return r ? `${h} h ${String(r).padStart(2, '0')} min` : `${h} h`;
}

// What the server said of the file it made (its `X-Build-Summary`, as text) and how the values came about, as the frame under the button shows them. `how` says where the values
// are from: by hand (no recipe), typed under a recipe that has no dosage for the printer, or a dosage (and whether what is in the panel differs from it).
export function parseSummary(text) {
  try { const s = JSON.parse(text); return s && typeof s === 'object' && Number.isFinite(s.layers) && Number.isFinite(s.estimated_s) ? s : null; } catch { return null; }
}
export function resultOf(summary, { recipe, dosage, values }) {
  const how = !recipe ? { kind: 'manual' } : !dosage ? { kind: 'typed', recipe: recipe.name } : { kind: 'dosage', recipe: recipe.name, dosage, edited: !sameValues(values, valuesOf(dosage)) };
  return { layers: summary.layers, flash: summary.flash_s, rest: summary.rest_s, total: summary.total_light_s, estimated: summary.estimated_s, area_cm2: summary.lit_area_mm2 / 100, how };
}
