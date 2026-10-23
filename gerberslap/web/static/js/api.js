// The calls to the backend. Every failure becomes an ApiError with the backend's code and parameters (the page owns the wording).
export class ApiError extends Error {
  constructor(status, code, params = {}) { super(code); this.status = status; this.code = code; this.params = params; }
}

async function call(url, options) {
  let response;
  try { response = await fetch(url, options); } catch (e) { if (e.name === 'AbortError') throw e; throw new ApiError(0, 'network'); }
  let body = null;
  try { body = await response.json(); } catch { /* not JSON */ }
  if (!response.ok) throw new ApiError(response.status, body?.error?.code || 'unknown', body?.error?.params || {});
  return body;
}
const json = (data, extra = {}) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data), ...extra });

// The server only caches the Gerber files; when it no longer has one (restart, eviction) the page may know how to give them again.
let recover = null;
export const onFilesMissing = (fn) => { recover = fn; };
async function withRecovery(fn) {
  try { return await fn(); } catch (e) {
    if (e instanceof ApiError && e.code === 'file_missing' && recover && await recover()) return fn();           // once: no loops
    throw e;
  }
}

export const getInfo = () => call('/api/info');
// the recipe library: every call answers with the recipe as it is afterwards (the server decides ids and dates)
export const listRecipes = () => call('/api/recipes');
export const createRecipe = (body) => call('/api/recipes', json(body));
export const editRecipe = (id, body) => call(`/api/recipes/${id}`, json(body, { method: 'PATCH' }));
export const deleteRecipe = (id) => call(`/api/recipes/${id}`, { method: 'DELETE' });
export const duplicateRecipe = (id, body) => call(`/api/recipes/${id}/duplicate`, json(body));
export const addDosage = (id, body) => call(`/api/recipes/${id}/dosages`, json(body));
export const editDosage = (id, dosageId, body) => call(`/api/recipes/${id}/dosages/${dosageId}`, json(body, { method: 'PATCH' }));
export const deleteDosage = (id, dosageId) => call(`/api/recipes/${id}/dosages/${dosageId}`, { method: 'DELETE' });
export function openZip(file, boardId, mirror = false, printerId = null) {
  const form = new FormData();
  form.append('file', file, file.name); form.append('board_id', boardId); form.append('mirror', String(mirror));
  if (printerId) form.append('printer_id', printerId);
  return call('/api/boards', { method: 'POST', body: form });
}
export const getGeometry = (request) => withRecovery(() => call('/api/geometry', json(request)));
export const renderMask = (project, polarity, signal) => withRecovery(() => call('/api/render', json({ project, polarity, supersample: 16 }, { signal })));
// the checks of the project: `request` is what `checkRequest` (exposure.js) makes: the project, the values and the recipe chosen
export const checkProject = (request) => call('/api/check', json(request));
export function openProject(file) {
  const form = new FormData(); form.append('file', file, file.name);
  return call('/api/project/open', { method: 'POST', body: form });
}
// a file the server makes as a download: the bytes, the name the server suggests and, for a print file, what it says of it (the summary comes in a header, as text)
async function download(url, body) {
  let response;
  try { response = await fetch(url, json(body)); } catch { throw new ApiError(0, 'network'); }
  if (!response.ok) {
    let err = null; try { err = await response.json(); } catch { /* not JSON */ }
    throw new ApiError(response.status, err?.error?.code || 'unknown', err?.error?.params || {});
  }
  const filename = /filename="([^"]+)"/.exec(response.headers.get('content-disposition') || '')?.[1] || null;
  return { blob: await response.blob(), filename, summary: response.headers.get('x-build-summary') || '' };
}
export const saveProject = (body) => withRecovery(async () => { const r = await download('/api/project/save', body); return { ...r, filename: r.filename || 'project.gslp' }; });
// the print file of the board: `generation_blocked` carries the issues that stop it (`params.issues`)
export const generateFile = (request) => withRecovery(() => download('/api/generate', request));
// the file of the calibration ladder (it needs none of the files of the project)
export const generateLadder = (request) => download('/api/generate/ladder', request);
