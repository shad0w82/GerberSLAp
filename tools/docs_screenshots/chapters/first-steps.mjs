// Chapter 2, "First steps": the shots of docs/<lang>/usage/img/first-steps-*.png
import { addDemoBoard, setNumber, sleep } from "../lib.mjs";

export const name = "first-steps";

export async function run({ page, shot }) {
  await shot("first-steps-1-empty");

  await addDemoBoard(page);
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
}
