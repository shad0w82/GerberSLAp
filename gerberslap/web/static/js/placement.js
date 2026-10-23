// What the Placement section draws from the board and the plane: the margins as a small drawing of the plane, with the board inside it and the four distances written
// around it, and the size of the little plane on which the corner of an anchor is chosen. No DOM here: it returns markup and numbers, so it can be tried with node.
// `t` translates and `fmt(number, decimals)` writes a number the way the page's language does.
import { extent, margins } from './model.js';

// The plane seen from above, the back at the top and the front at the bottom as the CadWindow shows it, in millimetres. The extent of the board is the rectangle in it
// and a dashed line goes from each of its sides to the edge of the plane: the four margins. A board that is not wholly inside the plane (a negative margin) is drawn in
// the colour of the errors, and so is the number. The lines and the colours are in the stylesheet (`.mm-*`); the pad around the plane is 2 mm, so its border shows.
export function marginsMap(b, plane, { t, fmt }) {
  const m = margins(b, plane), e = extent(b), pad = 2, mid = (a, c) => (a + c) / 2;
  const top = plane.h - e.maxy, bottom = plane.h - e.miny, cx = mid(e.minx, e.maxx), cy = mid(top, bottom);
  const out = Math.min(m.left, m.right, m.front, m.back) < -1e-6;
  const n = (v) => +v.toFixed(2);
  const cell = (cls, key, v) => `<div class="mg ${cls}${v < -1e-6 ? ' neg' : ''}"><small>${t(key)}</small><b>${fmt(v, 1)}</b></div>`;
  return `<div class="mmap">${cell('t', 'm_back', m.back)}${cell('l', 'm_left', m.left)}`
    + `<div class="mm"><svg viewBox="${-pad} ${-pad} ${n(plane.w + 2 * pad)} ${n(plane.h + 2 * pad)}" aria-hidden="true" focusable="false">`
    + `<defs><pattern id="mm-grid" width="10" height="10" patternUnits="userSpaceOnUse"><path class="mm-gl" d="M10 0H0V10"/></pattern></defs>`
    + `<rect class="mm-plane" x="0" y="0" width="${n(plane.w)}" height="${n(plane.h)}" rx="2"/><rect class="mm-grid" x="0" y="0" width="${n(plane.w)}" height="${n(plane.h)}" fill="url(#mm-grid)"/>`
    + `<path class="mm-dim" d="M0 ${n(cy)}H${n(e.minx)}M${n(plane.w)} ${n(cy)}H${n(e.maxx)}M${n(cx)} 0V${n(top)}M${n(cx)} ${n(plane.h)}V${n(bottom)}"/>`
    + `<rect class="mm-board${out ? ' out' : ''}" x="${n(e.minx)}" y="${n(top)}" width="${n(e.maxx - e.minx)}" height="${n(e.maxy - e.miny)}" rx="1.5"/></svg></div>`
    + `${cell('r', 'm_right', m.right)}${cell('b', 'm_front', m.front)}</div>`;
}

// The little plane of the anchor: the plane's own proportions, as large as it can be in the box (px).
export function anchorSize(plane, box = { w: 150, h: 96 }) {
  const k = Math.min(box.w / plane.w, box.h / plane.h);
  return { w: Math.round(plane.w * k), h: Math.round(plane.h * k) };
}
