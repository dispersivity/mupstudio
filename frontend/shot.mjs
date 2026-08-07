import { chromium } from "playwright";
const SHOTS = "/private/tmp/claude-501/-Users-portega-dev-code-mupstudio/a7828c49-0c3c-4f8a-8ca5-26f204ffb181/scratchpad/shots";
const PROJECT = "/private/tmp/claude-501/-Users-portega-dev-code-mupstudio/a7828c49-0c3c-4f8a-8ca5-26f204ffb181/scratchpad/uiproj/Calcite-column.mup";
const PORT = process.env.PORT ?? "8768";

const browser = await chromium.launch({ args: ["--enable-unsafe-webgpu", "--use-angle=metal"] });
const page = await browser.newPage({ viewport: { width: 1700, height: 1000 } });
const problems = [];
page.on("console", (m) => m.type() === "error" && problems.push(m.text().slice(0, 200)));
page.on("pageerror", (e) => problems.push(`pageerror: ${e.message.slice(0, 200)}`));

await page.goto(`http://127.0.0.1:${PORT}/`);
await page.waitForTimeout(1200);
await page.locator("text=Project").first().click();
await page.waitForTimeout(500);
await page.locator('input[placeholder*="mup" i], input[type="text"]').first().fill(PROJECT);
await page.keyboard.press("Enter");
await page.waitForTimeout(1500);

for (const step of ["Grid", "Flow", "Transport", "Chemistry"]) {
  await page.locator(`text=${step}`).first().click();
  await page.waitForTimeout(3000);
  await page.screenshot({ path: `${SHOTS}/v2-${step.toLowerCase()}.png` });
  const text = await page.locator("main").innerText();
  console.log(step, "|", /not run, this is the input/.test(text) ? "PREVIEW OK" : "no preview", "|",
    (text.match(/failed[^\n]*|Viewport[^\n]*/) ?? [""])[0].slice(0,120));
}
console.log("problems:", problems.length ? problems.slice(0, 5) : "none");
await browser.close();
