// Takes the screenshots of the manual (docs/it/usage/img and docs/en/usage/img) from the real app, once with the page in
// Italian and once in English. It starts the app on a throw-away data folder with the printer template installed
// (the template is not public: this is why only whoever has it can regenerate the images), opens the demo board of the
// documentation with the file input of the page, and follows the steps of each chapter (chapters/*.mjs).
//
//   cd tools/docs_screenshots && npm install      (once)
//   node shoot.mjs [chapter [name-of-one-shot]]   (all the chapters, one chapter, or only the shot whose name contains the text)
//
// Environment: CHROME (path of Chrome), PYTHON (python of the app), GERBERSLAP_TEMPLATE (a .ctb made with ChiTuBox),
// LANGS ("it,en" by default), SHOTS_OUT (write the images under this folder instead of docs/, to try).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { makeShooter, openPage, withApp } from "./lib.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const langs = (process.env.LANGS || "it,en").split(",");
const wantedChapter = process.argv[2] || "";
const only = process.argv[3] || "";

const files = fs.readdirSync(path.join(here, "chapters")).filter((f) => f.endsWith(".mjs")).sort();
const chapters = [];
for (const f of files) {
  const mod = await import(`./chapters/${f}`);
  if (!wantedChapter || mod.name === wantedChapter) chapters.push(mod);
}
if (!chapters.length) { console.error(`no chapter called "${wantedChapter}" (${files.map((f) => f.replace(".mjs", "")).join(", ")})`); process.exit(1); }

await withApp(async ({ browser }) => {
  for (const chapter of chapters) {
    for (const lang of langs) {
      const { page, context } = await openPage(browser, lang);            // a clean profile for each chapter and language
      const shooter = makeShooter({ page, lang, chapter: chapter.name, only });
      shooter.clearOld();
      await chapter.run({ page, lang, ...shooter });
      await context.close();
    }
  }
}).catch((error) => { console.error(error); process.exit(1); });
