// Takes the screenshots of the manual (docs/it/usage/img and docs/en/usage/img) from the real app, once with the page in
// Italian and once in English. It starts the app on a throw-away data folder with the printer template installed
// (the template is not public: this is why only whoever has it can regenerate the images), opens the demo board of the
// documentation with the file input of the page, and follows the steps of the chapter "First steps".
//
//   cd tools/docs_screenshots && npm install      (once)
//   node shoot.mjs [name-of-one-shot]             (all the shots, or only the one whose name contains the text)
//
// Environment: CHROME (path of Chrome), PYTHON (python of the app), GERBERSLAP_TEMPLATE (a .ctb made with ChiTuBox),
// LANGS ("it,en" by default).
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const chrome = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const python = process.env.PYTHON || path.join(root, ".venv", "bin", "python");
const template = process.env.GERBERSLAP_TEMPLATE || path.join(root, "samples", "speedCube.ctb");
const demoZip = path.join(root, "docs", "assets", "GerberSLAp-demo.zip");
const langs = (process.env.LANGS || "it,en").split(",");
const only = process.argv[2] || "";
const PORT = 8810;
const BASE = `http://127.0.0.1:${PORT}/`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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

async function setNumber(page, selector, value) {
  await page.$eval(selector, (el, v) => { el.value = v; el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); }, String(value));
}

async function run() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "gerberslap-shots-"));
  const dataDir = path.join(tmp, "data");
  const server = await startApp(dataDir);
  const browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--hide-scrollbars"] });
  try {
    const cdp = await browser.target().createCDPSession();
    await cdp.send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: path.join(tmp, "downloads") });
    for (const lang of langs) {
      const outDir = path.join(root, "docs", lang, "usage", "img");
      fs.mkdirSync(outDir, { recursive: true });
      if (!only) for (const f of fs.readdirSync(outDir)) if (/^first-steps-.*\.png$/.test(f)) fs.rmSync(path.join(outDir, f));
      const context = await browser.createBrowserContext();               // a clean profile for each language
      const page = await context.newPage();
      await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 });
      await page.evaluateOnNewDocument((l) => { try { localStorage.setItem("gs-lang", l); } catch { /* private mode */ } }, lang);

      // `selector`: the shot is the box of that element; `until`: it stops 24 px under the bottom of that other element;
      // `within`: it stops 18 px to the right of that other element
      const shot = async (name, selector, until, within) => {
        if (only && !name.includes(only)) return;
        const file = path.join(outDir, `${name}.png`);
        const options = { path: file };
        if (selector) {
          const box = await (await page.$(selector)).boundingBox();
          let height = box.height;
          if (until) { const end = await (await page.$(until)).boundingBox(); height = end.y + end.height + 24 - box.y; }
          let width = box.width;
          if (within) { const inner = await (await page.$(within)).boundingBox(); width = inner.x + inner.width + 18 - box.x; }
          options.clip = { x: box.x, y: box.y, width, height };
        }
        await page.screenshot(options);
        optimise(file);
        console.log(`${lang}: ${path.relative(root, file)} (${Math.round(fs.statSync(file).size / 1024)} KB)`);
      };

      await page.goto(BASE, { waitUntil: "networkidle0" });
      await page.waitForSelector("#printer-pill");
      await sleep(600);
      await shot("first-steps-1-empty");

      await (await page.$("#file-add")).uploadFile(demoZip);              // what the "Add board" button and a drop do
      await page.waitForSelector("#boards-list .board", { timeout: 20000 });
      await sleep(1500);
      await page.waitForSelector("#toast", { hidden: true, timeout: 15000 });     // "Aperta 1 scheda." goes away by itself
      await shot("first-steps-2-board");
      await shot("first-steps-3-layers", "#sec-boards", "#boards-list .board", "#boards-list .board");

      await page.click("#rail-place");
      await page.waitForSelector("#place-body:not([hidden])");
      await page.click("#mirror-toggle");                                  // the copper side goes against the screen
      await sleep(700);
      await shot("first-steps-4-placement");

      await page.click("#rail-expo");
      await page.waitForSelector("#values");
      await setNumber(page, "#in-total", 10);                              // example values, not a recipe
      await setNumber(page, "#in-pulses", 1);
      await setNumber(page, "#in-rest", 0);
      await sleep(900);
      await shot("first-steps-5-exposure");

      await page.click('.seg [data-mode="light"]');                        // what the screen will project
      await sleep(900);
      await shot("first-steps-6-uv");
      await page.click('.seg [data-mode="material"]');

      await page.click("#btn-generate");
      await page.waitForSelector("#gen-result:not([hidden])", { timeout: 60000 });
      await sleep(800);
      await shot("first-steps-7-generated", "#sec-expo", "#gen-result");
      await context.close();
    }
  } finally {
    await browser.close();
    server.kill();
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

run().catch((error) => { console.error(error); process.exit(1); });
