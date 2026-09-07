// Regenerates the screenshots and the demo GIF in docs/ from a running site.
// It drives the real Chrome already on the machine rather than downloading one,
// and it captures a frame every step so the recording is the same run as the
// stills, not a re-enactment of it.
//
//   SITE=https://... OUT=$PWD/docs FRAMES=/tmp/frames node docs/capture.mjs
//   python3 docs/make_gif.py /tmp/frames docs/demo.gif
//
// Needs puppeteer-core, which is not a dependency of the app:
//   npm install --no-save puppeteer-core

import puppeteer from "puppeteer-core";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const SITE = process.env.SITE;
const OUT = process.env.OUT;
const FRAMES = process.env.FRAMES;

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--hide-scrollbars"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 });

// 1. the company page, whole
await page.goto(`${SITE}/companies/VRTX`, { waitUntil: "networkidle2", timeout: 60000 });
await page.screenshot({ path: `${OUT}/company-full.png`, fullPage: true });
console.log("company-full.png");

// 2. ask, answered, with the passage panel open
let n = 0;
const frame = async () => {
  await page.screenshot({ path: `${FRAMES}/f${String(n++).padStart(3, "0")}.png` });
};

await page.goto(`${SITE}/ask`, { waitUntil: "networkidle2", timeout: 60000 });
await frame(); await frame();                       // hold on the landing state

const q = "What does Vertex say about its intellectual property risks?";
const box = await page.$('input[aria-label="Ask a question"], input[placeholder^="Ask about"]');
for (const ch of q) { await box.type(ch, { delay: 0 }); if (n < 40) await frame(); }
await frame();

await page.evaluate(() => [...document.querySelectorAll("button")].find(b => b.type === "submit").click());
for (let i = 0; i < 12; i++) { await new Promise(r => setTimeout(r, 900)); await frame(); }

await page.screenshot({ path: `${OUT}/answer.png` });
console.log("answer.png");

// open a citation, so the passage panel is in the recording
const chip = await page.$('[data-cite-chip], .cite-chip, button[aria-label*="citation" i]');
if (chip) {
  await chip.click();
  for (let i = 0; i < 6; i++) { await new Promise(r => setTimeout(r, 500)); await frame(); }
  await page.screenshot({ path: `${OUT}/passage.png` });
  console.log("passage.png");
} else {
  console.log("no citation chip found; skipped the passage panel");
}
console.log(`${n} frames`);
await browser.close();
