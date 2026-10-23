// The plane view: the LCD seen from above on a Canvas 2D. Boards are drawn from the real shapes the backend sends (polygons relative to
// the board's centre, holes already cut out), placed with the board's position, rotation and mirror. Interaction: cursor-anchored
// zoom, drag with snapping, rulers in mm, and a pixel-exact view that is the backend's own mask.
import { drawOrder, extent, hit, margins, rad } from './model.js';

const RULER = { l: 38, t: 24 };
const NICE = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100];

// Render one board into `ctx` with the base transform T = [a, b, c, d, e, f] (plane mm -> device px). `geo.paths(b, layer)` gives the
// layer's Path2D list, or null while the shapes are still being fetched (the board is drawn again when they arrive).
export function renderBoard(ctx, b, T, col, geo) {
  ctx.save();
  ctx.setTransform(...T);
  ctx.translate(b.x, b.y); ctx.rotate(rad(b.angle)); if (b.mirror) ctx.scale(-1, 1);
  for (const l of drawOrder(b)) {                                          // the stack from the bottom layer up (turned over if mirrored), the outline last
    const paths = geo.paths(b, l);
    if (!paths) continue;
    ctx.fillStyle = (!col.mono && l.color) || col[l.role];                // a layer's own colour counts only in the material view
    for (const path of paths) ctx.fill(path, 'evenodd');
  }
  ctx.restore();
}

export function createPlane(canvas, app) {
  const ctx = canvas.getContext('2d');
  canvas.parentElement?.style.setProperty('--ruler-l', `${RULER.l}px`); canvas.parentElement?.style.setProperty('--ruler-t', `${RULER.t}px`);       // the stylesheet knows the room of the Rulers (what is laid over the CadWindow is centred in the rest)
  const tmp = document.createElement('canvas'), tctx = tmp.getContext('2d');
  const view = { s: 5, ox: 0, oy: 0 };
  let W = 0, H = 0, dpr = 1, raf = 0, drag = null, space = false, cursor = null, guides = [], fitScale = 5, autoFit = true;
  const exact = { img: null, dirty: true, timer: 0, seq: 0 };

  const toScreen = (x, y) => [view.ox + x * view.s, view.oy - y * view.s];
  const toWorld = (px, py) => [(px - view.ox) / view.s, (view.oy - py) / view.s];
  const colors = () => {
    const cs = getComputedStyle(document.documentElement), g = (n) => cs.getPropertyValue(n).trim();
    return { canvasBg: g('--canvas-bg'), plane: g('--plane'), grid: g('--plane-grid'), major: g('--plane-grid-major'), border: g('--plane-border'),
             rulerBg: g('--ruler-bg'), rulerText: g('--ruler-text'), label: g('--label'), copper: g('--copper'), outline: g('--outline'),
             mask: g('--mask'), silk: g('--silk'), board: g('--board'), sel: g('--sel'), guide: g('--guide'), pixel: g('--pixel-grid'), danger: g('--danger') };
  };
  const mono = (c) => ({ copper: c, outline: c, mask: c, silk: c, mono: true });
  const polColors = () => (app.polarity() === 'negative' ? { base: '#000', ink: '#fff' } : { base: '#fff', ink: '#000' });

  function fit() {
    const p = app.plane(), vw = W - RULER.l, vh = H - RULER.t;
    view.s = Math.max(0.5, Math.min((vw * 0.9) / p.w, (vh * 0.86) / p.h)); fitScale = view.s;
    view.ox = RULER.l + (vw - p.w * view.s) / 2; view.oy = RULER.t + (vh + p.h * view.s) / 2;
    autoFit = true; app.onZoom(1, view.s); schedule();
  }
  function zoomAt(factor, px, py) {
    const [wx, wy] = toWorld(px, py), s = Math.min(600, Math.max(fitScale * 0.3, view.s * factor));
    view.s = s; view.ox = px - wx * s; view.oy = py + wy * s; autoFit = false; app.onZoom(view.s / fitScale, view.s); schedule();
  }
  function schedule() { if (!raf) raf = requestAnimationFrame(draw); }
  function invalidate() { exact.dirty = true; if (app.mode() === 'exact') computeExactSoon(); schedule(); }

  // ---- the pixel-exact view: the mask the backend computes from the vectors at the printer's resolution ------------------
  function computeExactSoon() {
    clearTimeout(exact.timer); app.busy(true); const seq = ++exact.seq;
    exact.timer = setTimeout(async () => {
      exact.timer = 0;
      let img = null;
      try { img = await app.exactImage(); } catch { img = null; }
      if (seq !== exact.seq) return;                                       // a newer request has taken over
      exact.img = img; exact.dirty = false; app.busy(false); schedule();
    }, 250);
  }

  // ---- drawing ---------------------------------------------------------------------------------------------
  function paintBoards(target, c, col, tintOutside) {
    const p = app.plane(), T = [dpr * view.s, 0, 0, -dpr * view.s, dpr * view.ox, dpr * view.oy];
    for (const b of app.boards()) {
      tctx.setTransform(1, 0, 0, 1, 0, 0); tctx.clearRect(0, 0, tmp.width, tmp.height);
      renderBoard(tctx, b, T, col, app.geo);
      if (tintOutside) {                                    // the part of a board outside the plane is not exposed
        const [x0, y0] = toScreen(0, p.h);
        tctx.globalCompositeOperation = 'source-atop'; tctx.fillStyle = 'rgba(220,38,38,.55)'; tctx.beginPath();
        tctx.rect(0, 0, tmp.width, tmp.height); tctx.rect(x0 * dpr, y0 * dpr, p.w * view.s * dpr, p.h * view.s * dpr); tctx.fill('evenodd');
        tctx.globalCompositeOperation = 'source-over';
      }
      target.drawImage(tmp, 0, 0, tmp.width, tmp.height, 0, 0, W, H);
    }
  }
  function niceStep(minPx) { for (const n of NICE) if (n * view.s >= minPx) return n; return 100; }
  function lines(c, x0, y0, pw, ph) {
    if (!app.grid()) return;
    const minor = niceStep(10) <= 1 ? 1 : niceStep(10), major = 10;
    const draw = (step, style, lw) => {
      ctx.strokeStyle = style; ctx.lineWidth = lw; ctx.beginPath(); const p = app.plane();
      for (let u = 0; u <= p.w + 1e-6; u += step) { const [x] = toScreen(u, 0); ctx.moveTo(Math.round(x) + .5, y0); ctx.lineTo(Math.round(x) + .5, y0 + ph); }
      for (let v = 0; v <= p.h + 1e-6; v += step) { const [, y] = toScreen(0, v); ctx.moveTo(x0, Math.round(y) + .5); ctx.lineTo(x0 + pw, Math.round(y) + .5); }
      ctx.stroke();
    };
    if (minor * view.s >= 7 && minor < major) draw(minor, c.grid, 1);
    draw(major, c.major, 1);
  }
  function pixelGrid(c, x0, y0, pw, ph) {
    const p = app.plane(), pxs = p.pitch * view.s; if (pxs < 8) return;
    ctx.strokeStyle = c.pixel; ctx.lineWidth = 1; ctx.beginPath();
    const [wl] = toWorld(RULER.l, 0), [wr] = toWorld(W, 0), [, wt] = toWorld(0, RULER.t), [, wb] = toWorld(0, H);
    for (let i = Math.max(0, Math.floor(wl / p.pitch)); i <= Math.min(p.px[0], Math.ceil(wr / p.pitch)); i++) { const [x] = toScreen(i * p.pitch, 0); ctx.moveTo(Math.round(x) + .5, y0); ctx.lineTo(Math.round(x) + .5, y0 + ph); }
    for (let j = Math.max(0, Math.floor(wb / p.pitch)); j <= Math.min(p.px[1], Math.ceil(wt / p.pitch)); j++) { const [, y] = toScreen(0, j * p.pitch); ctx.moveTo(x0, Math.round(y) + .5); ctx.lineTo(x0 + pw, Math.round(y) + .5); }
    ctx.stroke();
  }
  function selection(c) {
    const b = app.selected(); if (!b) return;
    ctx.save(); ctx.setTransform(dpr * view.s, 0, 0, -dpr * view.s, dpr * view.ox, dpr * view.oy);
    ctx.translate(b.x, b.y); ctx.rotate(rad(b.angle)); if (b.mirror) ctx.scale(-1, 1);
    ctx.strokeStyle = c.sel; ctx.lineWidth = 1.6 / view.s; ctx.setLineDash([5 / view.s, 3 / view.s]); ctx.strokeRect(-b.w / 2, -b.h / 2, b.w, b.h);
    ctx.setLineDash([]); ctx.fillStyle = c.sel; const r = 3 / view.s;     // a small mark on the board's local +x edge shows the mirror/rotation
    ctx.beginPath(); ctx.moveTo(b.w / 2, 0); ctx.lineTo(b.w / 2 + r * 1.6, r); ctx.lineTo(b.w / 2 + r * 1.6, -r); ctx.closePath(); ctx.fill();
    ctx.restore();
  }
  function rulers(c) {
    ctx.fillStyle = c.rulerBg; ctx.fillRect(0, 0, W, RULER.t); ctx.fillRect(0, 0, RULER.l, H);
    ctx.fillStyle = c.rulerText; ctx.strokeStyle = c.rulerText; ctx.font = '10px system-ui, sans-serif'; ctx.lineWidth = 1;
    const step = niceStep(70), minor = step / 5, [u0] = toWorld(RULER.l, 0), [u1] = toWorld(W, 0), [, v0] = toWorld(0, H), [, v1] = toWorld(0, RULER.t);
    ctx.textBaseline = 'middle'; ctx.beginPath();
    ctx.textAlign = 'left';
    for (let u = Math.floor(u0 / step) * step; u <= u1; u += step) { const [x] = toScreen(u, 0); if (x < RULER.l) continue; ctx.moveTo(Math.round(x) + .5, 10); ctx.lineTo(Math.round(x) + .5, RULER.t); ctx.fillText(String(+u.toFixed(2)), x + 3, 8); }
    if (minor * view.s >= 6) for (let u = Math.floor(u0 / minor) * minor; u <= u1; u += minor) { const [x] = toScreen(u, 0); if (x >= RULER.l) { ctx.moveTo(Math.round(x) + .5, 18); ctx.lineTo(Math.round(x) + .5, RULER.t); } }
    ctx.textAlign = 'right';
    for (let v = Math.floor(v0 / step) * step; v <= v1; v += step) { const [, y] = toScreen(0, v); if (y < RULER.t) continue; ctx.moveTo(RULER.l - 8, Math.round(y) + .5); ctx.lineTo(RULER.l, Math.round(y) + .5); ctx.fillText(String(+v.toFixed(2)), RULER.l - 10, y - 6); }
    if (minor * view.s >= 6) for (let v = Math.floor(v0 / minor) * minor; v <= v1; v += minor) { const [, y] = toScreen(0, v); if (y >= RULER.t) { ctx.moveTo(RULER.l - 4, Math.round(y) + .5); ctx.lineTo(RULER.l, Math.round(y) + .5); } }
    ctx.stroke();
    if (cursor) { ctx.strokeStyle = c.sel; ctx.beginPath(); const [x, y] = toScreen(cursor[0], cursor[1]); if (x >= RULER.l) { ctx.moveTo(Math.round(x) + .5, 0); ctx.lineTo(Math.round(x) + .5, RULER.t); } if (y >= RULER.t) { ctx.moveTo(0, Math.round(y) + .5); ctx.lineTo(RULER.l, Math.round(y) + .5); } ctx.stroke(); }
  }
  function draw() {
    raf = 0; if (!W) return;
    const c = colors(), p = app.plane(), mode = app.mode();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.fillStyle = c.canvasBg; ctx.fillRect(0, 0, W, H);
    ctx.save(); ctx.beginPath(); ctx.rect(RULER.l, RULER.t, W - RULER.l, H - RULER.t); ctx.clip();
    const [x0, y0] = toScreen(0, p.h), pw = p.w * view.s, ph = p.h * view.s, pc = polColors();
    if (mode === 'material') {
      ctx.fillStyle = c.plane; ctx.fillRect(x0, y0, pw, ph); lines(c, x0, y0, pw, ph); paintBoards(ctx, c, c, true);
    } else if (mode === 'light') {
      ctx.fillStyle = pc.base; ctx.fillRect(x0, y0, pw, ph);
      ctx.save(); ctx.beginPath(); ctx.rect(x0, y0, pw, ph); ctx.clip(); paintBoards(ctx, c, mono(pc.ink), false); ctx.restore();
    } else {
      if (exact.dirty && !exact.timer) computeExactSoon();
      if (exact.img && !exact.dirty) { ctx.imageSmoothingEnabled = false; ctx.drawImage(exact.img, x0, y0, pw, ph); }
      else { ctx.fillStyle = c.plane; ctx.fillRect(x0, y0, pw, ph); }
    }
    pixelGrid(c, x0, y0, pw, ph);
    ctx.strokeStyle = app.outsidePlane() ? c.danger : c.border; ctx.lineWidth = app.outsidePlane() ? 2 : 1.5; ctx.strokeRect(x0, y0, pw, ph);
    selection(c);
    ctx.strokeStyle = c.guide; ctx.lineWidth = 1; ctx.setLineDash([4, 4]); ctx.beginPath();
    for (const g of guides) { if (g.axis === 'x') { const [x] = toScreen(g.v, 0); ctx.moveTo(x, RULER.t); ctx.lineTo(x, H); } else { const [, y] = toScreen(0, g.v); ctx.moveTo(RULER.l, y); ctx.lineTo(W, y); } }
    ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = c.label; ctx.font = '600 11px system-ui, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(app.t('edge_back'), x0 + pw / 2, y0 - 12); ctx.fillText(app.t('edge_front'), x0 + pw / 2, y0 + ph + 12);
    ctx.save(); ctx.translate(x0 - 12, y0 + ph / 2); ctx.rotate(-Math.PI / 2); ctx.fillText(app.t('edge_left'), 0, 0); ctx.restore();
    ctx.save(); ctx.translate(x0 + pw + 12, y0 + ph / 2); ctx.rotate(Math.PI / 2); ctx.fillText(app.t('edge_right'), 0, 0); ctx.restore();
    ctx.restore();
    rulers(c);
    app.onZoom(view.s / fitScale, view.s);
  }

  // ---- interaction -----------------------------------------------------------------------------------------
  const pos = (e) => { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  function snapMove(b, nx, ny) {
    guides = []; if (!app.snap()) return [nx, ny];
    const p = app.plane(), tol = 8 / view.s, e = extent({ ...b, x: nx, y: ny });
    const xs = [0, p.w / 2, p.w], ys = [0, p.h / 2, p.h];
    for (const o of app.boards()) if (o.id !== b.id) { const q = extent(o); xs.push(q.minx, q.maxx, (q.minx + q.maxx) / 2); ys.push(q.miny, q.maxy, (q.miny + q.maxy) / 2); }
    const best = (mine, targets) => { let r = null; for (const m of mine) for (const t of targets) { const d = t - m; if (Math.abs(d) <= tol && (!r || Math.abs(d) < Math.abs(r.d))) r = { d, t }; } return r; };
    const bx = best([e.minx, (e.minx + e.maxx) / 2, e.maxx], xs), by = best([e.miny, (e.miny + e.maxy) / 2, e.maxy], ys);
    if (bx) { nx += bx.d; guides.push({ axis: 'x', v: bx.t }); }
    if (by) { ny += by.d; guides.push({ axis: 'y', v: by.t }); }
    return [nx, ny];
  }
  canvas.addEventListener('pointerdown', (e) => {
    canvas.focus(); const [mx, my] = pos(e), [wx, wy] = toWorld(mx, my);
    if (e.button === 1 || e.button === 2 || space) drag = { type: 'pan', mx, my, ox: view.ox, oy: view.oy };
    else if (e.button === 0) {
      const list = app.boards(); let found = null;
      for (let i = list.length - 1; i >= 0; i--) if (hit(list[i], wx, wy)) { found = list[i]; break; }
      if (found) { app.select(found.id); drag = { type: 'move', id: found.id, wx, wy, bx: found.x, by: found.y, moved: false }; }
      else { app.select(null); drag = { type: 'pan', mx, my, ox: view.ox, oy: view.oy }; }
    }
    if (drag) { canvas.setPointerCapture(e.pointerId); canvas.style.cursor = drag.type === 'pan' ? 'grabbing' : 'move'; }
  });
  canvas.addEventListener('pointermove', (e) => {
    const [mx, my] = pos(e), [wx, wy] = toWorld(mx, my), p = app.plane();
    cursor = mx >= RULER.l && my >= RULER.t ? [wx, wy] : null; app.onCursor(cursor && wx >= 0 && wy >= 0 && wx <= p.w && wy <= p.h ? cursor : null);
    if (drag?.type === 'pan') { view.ox = drag.ox + (mx - drag.mx); view.oy = drag.oy + (my - drag.my); autoFit = false; }
    else if (drag?.type === 'move') {
      const b = app.boards().find((q) => q.id === drag.id); if (!b) return;
      const [nx, ny] = snapMove(b, drag.bx + (wx - drag.wx), drag.by + (wy - drag.wy));
      if (nx !== b.x || ny !== b.y) { b.x = nx; b.y = ny; drag.moved = true; app.changed(false); }
    } else if (!space) canvas.style.cursor = app.boards().some((b) => hit(b, wx, wy)) ? 'move' : 'default';
    schedule();
  });
  const end = () => { if (drag?.type === 'move' && drag.moved) app.commit(); drag = null; guides = []; canvas.style.cursor = space ? 'grab' : 'default'; schedule(); };
  canvas.addEventListener('pointerup', end); canvas.addEventListener('pointercancel', end);
  canvas.addEventListener('pointerleave', () => { cursor = null; app.onCursor(null); schedule(); });
  canvas.addEventListener('contextmenu', (e) => e.preventDefault());
  canvas.addEventListener('dblclick', (e) => { const [mx, my] = pos(e), [wx, wy] = toWorld(mx, my); if (app.boards().some((b) => hit(b, wx, wy))) app.onDouble(); });
  canvas.addEventListener('wheel', (e) => { e.preventDefault(); const [mx, my] = pos(e); zoomAt(Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0016)), mx, my); }, { passive: false });
  window.addEventListener('keydown', (e) => { if (e.code === 'Space' && document.activeElement === canvas) { space = true; canvas.style.cursor = 'grab'; e.preventDefault(); } });
  window.addEventListener('keyup', (e) => { if (e.code === 'Space') { space = false; canvas.style.cursor = 'default'; } });

  new ResizeObserver(() => {
    const r = canvas.getBoundingClientRect(); if (!r.width) return; const first = !W;
    dpr = window.devicePixelRatio || 1; W = r.width; H = r.height;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr); tmp.width = canvas.width; tmp.height = canvas.height;
    if (first || autoFit) fit(); else schedule();
  }).observe(canvas);

  return { draw: schedule, fit, invalidate, zoomBy: (f) => zoomAt(f, (RULER.l + W) / 2, (RULER.t + H) / 2),
           get exactReady() { return !exact.dirty; }, margins };
}
