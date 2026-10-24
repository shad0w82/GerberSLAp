// Shared by the chapters: starts the app on a throw-away data folder (with the printer template installed), opens a clean
// browser page in Italian or English, takes the shots and puts the numbered markers on the zones of the interface.
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
export const demoZip = path.join(root, "docs", "assets", "GerberSLAp-demo.zip");
const chrome = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const python = process.env.PYTHON || path.join(root, ".venv", "bin", "python");
const template = process.env.GERBERSLAP_TEMPLATE || path.join(root, "samples", "speedCube.ctb");
const outRoot = process.env.SHOTS_OUT || path.join(root, "docs");              // where docs/<lang>/usage/img goes (SHOTS_OUT: another place, to try)
const PORT = 8810;
export const BASE = `http://127.0.0.1:${PORT}/`;

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function optimise(file) {
  // pngquant (if it is installed) shrinks the PNG a lot without a visible change
  spawnSync("pngquant", ["--force", "--quality=75-95", "--output", file, file], { stdio: "ignore" });
}

async function startApp(dataDir) {
  const install = spawnSync(python, ["-m", "gerberslap.web", "--data", dataDir, "--install-template", "ld002h", template], { cwd: root, encoding: "utf8" });
  if (install.status !== 0) throw new Error(`the template was refused: ${install.stderr || install.stdout}`);
  const server = spawn(python, ["-m", "gerberslap.web", "--port", String(PORT), "--data", dataDir], { cwd: root, stdio: "ignore" });
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(`${BASE}api/info`)).ok) return server; } catch { /* not up yet */ }
    await sleep(200);
  }
  server.kill();
  throw new Error("the app did not start");
}

// Runs `fn({ browser, tmp })` with the app and a headless Chrome up, and cleans up afterwards.
export async function withApp(fn) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "gerberslap-shots-"));
  const server = await startApp(path.join(tmp, "data"));
  const browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--hide-scrollbars"] });
  try {
    const cdp = await browser.target().createCDPSession();
    await cdp.send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: path.join(tmp, "downloads") });
    return await fn({ browser, tmp });
  } finally {
    await browser.close();
    server.kill();
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

// A clean profile and a page of 1440 x 900 at double density, with the page in `lang`, already loaded.
export async function openPage(browser, lang) {
  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 });
  await page.evaluateOnNewDocument((l) => { try { localStorage.setItem("gs-lang", l); } catch { /* private mode */ } }, lang);
  await page.goto(BASE, { waitUntil: "networkidle0" });
  await page.waitForSelector("#printer-pill");
  await sleep(600);
  return { page, context };
}

// shot(name, selector, until, within): the whole window; or the box of `selector`, stopping 24 px under the bottom of `until`
// and 18 px to the right of `within`.   clipShot(name, async () => ({ x, y, width, height })): a box worked out by the chapter.
export function makeShooter({ page, lang, chapter, only }) {
  const outDir = path.join(outRoot, lang, "usage", "img");
  fs.mkdirSync(outDir, { recursive: true });
  const save = async (name, options) => {
    const file = path.join(outDir, `${name}.png`);
    await page.screenshot({ ...options, path: file });
    optimise(file);
    console.log(`${lang}: ${path.relative(root, file)} (${Math.round(fs.statSync(file).size / 1024)} KB)`);
  };
  const wanted = (name) => !only || name.includes(only);
  const shot = async (name, selector, until, within) => {
    if (!wanted(name)) return;
    const options = {};
    if (selector) {
      const box = await (await page.$(selector)).boundingBox();
      let { width, height } = box;
      if (until) { const end = await (await page.$(until)).boundingBox(); height = end.y + end.height + 24 - box.y; }
      if (within) { const inner = await (await page.$(within)).boundingBox(); width = inner.x + inner.width + 18 - box.x; }
      options.clip = { x: box.x, y: box.y, width, height };
    }
    await save(name, options);
  };
  const clipShot = async (name, clipOf) => { if (wanted(name)) await save(name, { clip: await clipOf() }); };
  const clearOld = () => { if (!only) for (const f of fs.readdirSync(outDir)) if (f.startsWith(`${chapter}-`) && f.endsWith(".png")) fs.rmSync(path.join(outDir, f)); };
  return { shot, clipShot, clearOld };
}

export async function addDemoBoard(page) {
  await (await page.$("#file-add")).uploadFile(demoZip);              // what the "Add board" button and a drop do
  await page.waitForSelector("#boards-list .board", { timeout: 20000 });
  await sleep(1500);
  await page.waitForSelector("#toast", { hidden: true, timeout: 15000 });   // "Opened 1 board." goes away by itself
}

export async function setNumber(page, selector, value) {
  await page.$eval(selector, (el, v) => { el.value = v; el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); }, String(value));
}

// Puts a numbered marker on each zone: marks = [{ n, sel, fx, fy, dx, dy }] puts the centre of the marker at the point (fx, fy)
// of the box of `sel` (fractions of its width and height, 0 0 = top left corner), moved by (dx, dy) pixels; or [{ n, abs: [x, y] }]
// at a point of the window. Returns a function that takes the markers away again.
export async function annotate(page, marks) {
  await page.evaluate((list) => {
    const layer = document.createElement("div");
    layer.id = "doc-badges";
    layer.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:99999";
    for (const m of list) {
      let cx, cy;
      if (m.abs) [cx, cy] = m.abs;
      else {
        const el = document.querySelector(m.sel);
        if (!el) throw new Error(`no element for ${m.sel}`);
        const b = el.getBoundingClientRect();
        cx = b.x + (m.fx ?? 0) * b.width + (m.dx ?? 14);
        cy = b.y + (m.fy ?? 0) * b.height + (m.dy ?? 14);
      }
      const d = document.createElement("div");
      d.textContent = m.n;
      d.style.cssText = `position:absolute;left:${cx - 11}px;top:${cy - 11}px;width:22px;height:22px;border-radius:50%;background:#ff2d95;color:#fff;`
        + "font:700 13px/22px Inter,system-ui,sans-serif;text-align:center;box-shadow:0 0 0 2px #fff,0 2px 6px rgba(0,0,0,.55)";
      layer.append(d);
    }
    document.body.append(layer);
  }, marks);
  return () => page.evaluate(() => document.getElementById("doc-badges")?.remove());
}
