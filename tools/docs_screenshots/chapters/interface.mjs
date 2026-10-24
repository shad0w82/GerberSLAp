// Chapter 3, "Interface tour": the shots of docs/<lang>/usage/img/interface-*.png
import { addDemoBoard, annotate, setNumber, sleep } from "../lib.mjs";

export const name = "interface";

// The 18 zones of the interface, numbered as in the table of the chapter. Positions: see `annotate` in lib.mjs.
const ZONES = [
  { n: 1, sel: ".menubar", fx: 0.2, fy: 1, dx: 0, dy: -1 },
  { n: 2, sel: ".tabs", fx: 0.5, fy: 1, dx: 0, dy: 2 },
  { n: 3, sel: "#project-name", fx: 0, fy: 0.5, dx: -22, dy: 0 },
  { n: 4, sel: ".menu", fx: 0, fy: 0.5, dx: -14, dy: 0 },
  { n: 5, sel: "#lang-btn", fx: 0, fy: 0.5, dx: -14, dy: 0 },
  { n: 6, sel: "#rail", fx: 0.5, fy: 1, dx: 0, dy: -20 },
  { n: 7, sel: ".panels", fx: 0.5, fy: 0.72, dx: 0, dy: 0 },
  { n: 8, sel: ".board", fx: 0.5, fy: 1, dx: 0, dy: 0 },
  { n: 9, sel: ".side-statusbar", fx: 1, fy: 0.5, dx: -18, dy: 0 },
  { n: 10, sel: "#canvas-wrap", fx: 0.97, fy: 0.9, dx: 0, dy: 0 },
  { n: 11, sel: ".cadtitlebar", fx: 0.5, fy: 0.5, dx: -300, dy: 0 },
  { n: 12, sel: ".seg", fx: 0, fy: 0.5, dx: -18, dy: 0 },
  { n: 13, sel: "#st-save", fx: 0.5, fy: 1, dx: 0, dy: 14 },
  { n: 14, sel: "#st-warn", fx: 0.5, fy: 1, dx: 0, dy: 14 },
  { n: 15, sel: "#printer-pill", fx: 1, fy: 0.5, dx: 18, dy: 0 },
  { n: 16, abs: [500, 222] },
  { n: 17, abs: [452, 104] },
  { n: 18, sel: ".statusbar", fx: 0.55, fy: 0.5, dx: 0, dy: 0 },
];

export async function run({ page, shot, clipShot }) {
  await addDemoBoard(page);
  const box = (sel) => page.$eval(sel, (e) => { const b = e.getBoundingClientRect(); return { x: b.x, y: b.y, width: b.width, height: b.height }; });

  // the warning of the StatusPill, open (the exposure values are still missing)
  await page.click("#st-warn");
  await page.waitForSelector("#warn-pop:not([hidden])");
  await sleep(500);
  await clipShot("interface-3-warning", async () => {
    const bar = await box(".cadtitlebar"), pop = await box("#warn-pop"), x = (await box(".seg")).x - 20;
    return { x, y: bar.y, width: bar.x + bar.width - x, height: pop.y + pop.height + 20 - bar.y };
  });
  await page.keyboard.press("Escape");
  await sleep(300);

  // the example values, so that the pill turns green, and the cursor over the plane for the status bar
  await page.click("#rail-expo");
  await page.waitForSelector("#values");
  await setNumber(page, "#in-total", 10);
  await setNumber(page, "#in-pulses", 1);
  await setNumber(page, "#in-rest", 0);
  await sleep(500);
  await page.click("#rail-boards");
  await sleep(500);
  const plane = await box("#plane");
  await page.mouse.move(plane.x + plane.width * 0.55, plane.y + plane.height * 0.5);
  await sleep(500);

  const clear = await annotate(page, ZONES);
  await shot("interface-1-overview");
  await clear();

  await clipShot("interface-2-menubar", async () => { const b = await box(".menubar"); return { x: b.x, y: b.y, width: b.width, height: b.height }; });
  await clipShot("interface-4-statusbar", async () => { const b = await box(".statusbar"); return { x: 0, y: b.y, width: 1440, height: b.height }; });

  // the exact view, zoomed on the board
  await page.click('.seg [data-mode="exact"]');
  await page.mouse.move(plane.x + plane.width * 0.5, plane.y + plane.height * 0.5);
  await page.mouse.wheel({ deltaY: -2200 });
  await sleep(3000);
  await shot("interface-5-exact", "#canvas-wrap");
  await page.keyboard.press("1");
  await page.keyboard.press("f");

  await page.click("#tab-settings");
  await sleep(900);
  await shot("interface-6-settings");
  await page.click("#tab-help");
  await sleep(900);
  await shot("interface-7-help");
  await page.click("#tab-plane");
}
