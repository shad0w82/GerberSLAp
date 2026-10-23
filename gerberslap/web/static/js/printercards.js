// The printers of Settings as cards: on the left the picture of the printer (upright, as the machines are), then the model (a label and, under it, the name),
// a pill at the top right that says whether the printer is ready (the StatusPill's: a green tick, or a red warning sign) and, under the model, the plane, the
// pixels and the pitch. No DOM here: it returns the markup, so it can be tried with node. `t` translates, `fmt(number, decimals)` writes a number the way the
// page's language does and `esc` makes a text safe to put in markup.
import { pixelSize, pitchLabel, planeSize } from './model.js';

// The picture of a printer: its own photo when the server has one (`/api/info` says where, and the page takes only an address of the app's own), else a drawing
// of a resin printer, the same for all: the amber hood against the UV light sitting on the base with the screen, one body with the same width and no gap
// between the two parts. Its colours are in the stylesheet (`.pp-*`), not here. Both are drawn in the same box (about 6 : 10, as the photos are); the drawing's view is cut to the drawing (it touches the edges of the box), as the photo does.
export const PRINTER_PICTURE = `<svg viewBox="2 5 56 92" aria-hidden="true" focusable="false">
  <rect class="pp-rail" x="39" y="14" width="7" height="48"/>
  <rect class="pp-block" x="12" y="28" width="24" height="10" rx="1.5"/>
  <path class="pp-hood" d="M3 62V16a10 10 0 0 1 10-10h34a10 10 0 0 1 10 10v46z"/>
  <path class="pp-base" d="M3 62h54v28a6 6 0 0 1-6 6H9a6 6 0 0 1-6-6z"/>
  <rect class="pp-screen" x="10" y="71" width="24" height="15" rx="2"/>
  <circle class="pp-ring" cx="45" cy="75" r="3"/><circle class="pp-led" cx="45" cy="85" r="3"/>
</svg>`;
const OWN_PICTURE = /^\/api\/printers\/[A-Za-z0-9_.-]+\/picture$/;
export const printerPicture = (printer, esc) => (OWN_PICTURE.test(printer.picture ?? '')
  ? `<img class="pc-photo" src="${esc(printer.picture)}" alt="" decoding="async">` : PRINTER_PICTURE);

// What a card says about a printer, in the order it is written: plane (mm), pixels (px), pitch (µm).
export const printerFacts = (p, fmt) => [
  ['s_pr_plane', `${planeSize(p, fmt)} mm`],
  ['s_pr_pixels', `${pixelSize(p)} px`],
  ['s_pr_pitch', pitchLabel(p.grid.pitch, fmt)],
];

export function printerCards(printers, { t, fmt, esc }) {
  const card = (p) => {
    const status = t(p.ready ? 's_ready' : 's_notready');
    const facts = printerFacts(p, fmt).map(([key, value]) => `<span class="pc-k">${esc(t(key))}</span><span class="pc-v" title="${esc(value)}">${esc(value)}</span>`).join('');
    return `<li class="printer-card${p.ready ? '' : ' notready'}" data-printer="${esc(p.id)}">`
      + `<div class="pc-strip">${printerPicture(p, esc)}</div>`
      + `<div class="pc-main"><div class="pc-head"><span class="pc-k">${esc(t('s_pr_model'))}</span><span class="pc-name" title="${esc(p.name)}">${esc(p.name)}</span>`
      + `<span class="chip ${p.ready ? 'ok' : 'bad'} pc-state" role="img" title="${esc(status)}" aria-label="${esc(status)}">${p.ready ? '✓' : '⚠'}</span></div>`
      + `<div class="pc-meta">${facts}</div></div></li>`;
  };
  return `<ul class="printer-grid">${printers.map(card).join('')}</ul>`;
}
