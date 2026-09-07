// Regenerates every screenshot and the demo GIF in docs/ from a running site.
// It drives the real Chrome already on the machine rather than downloading one,
// and it captures the recording in the same run as the stills, so the two can
// never drift into showing different versions.
//
//   SITE=https://... OUT=$PWD/docs FRAMES=/tmp/a FRAMES2=/tmp/c node docs/capture.mjs
//   python3 docs/make_gif.py /tmp/a docs/demo.gif --thin 42:3
//   python3 docs/make_gif.py /tmp/c docs/company.gif
//
// Run it from the repository root. puppeteer-core resolves from the working
// directory, so running it from anywhere else fails to find the module.
//
// Needs puppeteer-core, which is not a dependency of the app:
//   npm install --no-save puppeteer-core

import puppeteer from "puppeteer-core";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const { SITE, OUT, FRAMES, FRAMES2 } = process.env;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--hide-scrollbars"],
});

// A page only reaches its real height once the client has rendered into it, and
// networkidle fires before that. Scrolling to the bottom and re-measuring is
// what stops a full-page capture stopping a third of the way down.
async function settle(page) {
  await page.evaluate(async () => {
    for (let y = 0; y < document.body.scrollHeight; y += 800) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 60));
    }
    window.scrollTo(0, 0);
  });
  await wait(900);
}

async function shot(path, url, { full = false, scale = 2, seed } = {}) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: scale });
  if (seed) {
    await page.goto(`${SITE}/`, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.evaluate(seed);
  }
  await page.goto(url, { waitUntil: "networkidle2", timeout: 90000 });
  await settle(page);
  await page.screenshot({ path: `${OUT}/${path}`, fullPage: full });
  const h = await page.evaluate(() => document.body.scrollHeight);
  console.log(`${path}  page ${h}px`);
  await page.close();
}

await shot("home.png", `${SITE}/`, { full: true });
await shot("watchlist.png", `${SITE}/watchlist`, {
  full: true,
  seed: () => localStorage.setItem("readbase.watchlist",
    JSON.stringify(["VRTX", "MRNA", "SRPT", "ALNY"])),
});
// scale 1 for the company page: at 2x a 14,000px page exceeds Chrome's limit

// browse, with something typed, since an empty search box shows nothing
{
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 });
  await page.goto(`${SITE}/browse`, { waitUntil: "networkidle2", timeout: 60000 });
  const box = await page.$('input[aria-label="Search the corpus"]');
  await box.type("ivacaftor", { delay: 12 });
  await wait(2500);
  await page.screenshot({ path: `${OUT}/browse.png` });
  console.log("browse.png");
  await page.close();
}

// ask: the landing state, the answer, and a citation opened into its passage,
// capturing a frame throughout so the recording is this same run
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 });
let n = 0;
const frame = async () => page.screenshot({ path: `${FRAMES}/f${String(n++).padStart(3, "0")}.png` });

await page.goto(`${SITE}/ask`, { waitUntil: "networkidle2", timeout: 60000 });
await frame(); await frame();

const q = "What does Vertex say about its intellectual property risks?";
const box = await page.$('input[aria-label="Ask a question"]');
for (const ch of q) { await box.type(ch, { delay: 0 }); await frame(); }
await frame();

await page.evaluate(() => [...document.querySelectorAll("button")].find((b) => b.type === "submit").click());
for (let i = 0; i < 14; i++) { await wait(900); await frame(); }

const chip = await page.$(".cite-chip, [data-cite-chip]");
if (chip) {
  await chip.click();
  for (let i = 0; i < 6; i++) { await wait(500); await frame(); }
  await page.screenshot({ path: `${OUT}/passage.png` });
  console.log("passage.png");
}
console.log(`${n} frames (ask)`);
await page.close();

// The company page is 5,238 pixels, which is a poor screenshot and a decent
// recording: find a company the way a reader would, then read down it.
{
  const p2 = await browser.newPage();
  await p2.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  let m = 0;
  const f2 = () => p2.screenshot({ path: `${FRAMES2}/f${String(m++).padStart(3, "0")}.png` });

  await p2.goto(`${SITE}/browse`, { waitUntil: "networkidle2", timeout: 60000 });
  await f2(); await f2();
  const search = await p2.$('input[aria-label="Search the corpus"]');
  for (const ch of "vertex") { await search.type(ch, { delay: 0 }); await f2(); }
  await wait(2200);
  await f2(); await f2(); await f2();

  await Promise.all([
    p2.waitForNavigation({ waitUntil: "networkidle2", timeout: 60000 }),
    p2.evaluate(() => document.querySelector('a[href^="/companies/"]').click()),
  ]);
  await settle(p2);
  await p2.evaluate(() => window.scrollTo(0, 0));
  await wait(700);
  for (let i = 0; i < 5; i++) await f2();

  // re-read the height every step rather than once: the tables render as they
  // are approached, so a height measured at the top is an underestimate and the
  // recording stops halfway down a page it thought it had finished
  for (let y = 0, guard = 0; guard < 60; y += 260, guard++) {
    const bottom = await p2.evaluate(() => document.body.scrollHeight - window.innerHeight);
    if (y > bottom) break;
    await p2.evaluate((y) => window.scrollTo(0, y), y);
    await wait(70);
    await f2();
  }
  for (let i = 0; i < 6; i++) await f2();
  console.log(`${m} frames (company)`);
  await p2.close();
}

await browser.close();
