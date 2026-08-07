import { chromium } from "playwright";
const SHOTS = "/private/tmp/claude-501/-Users-portega-dev-code-mupstudio/a7828c49-0c3c-4f8a-8ca5-26f204ffb181/scratchpad/shots";
const PROJECT = "/private/tmp/claude-501/-Users-portega-dev-code-mupstudio/a7828c49-0c3c-4f8a-8ca5-26f204ffb181/scratchpad/uiproj/Calcite-column.mup";
const PORT = process.env.PORT ?? "8773";
const browser = await chromium.launch({ args: ["--enable-unsafe-webgpu", "--use-angle=metal"] });
const page = await browser.newPage({ viewport: { width: 1700, height: 1000 } });
const problems = [];
page.on("pageerror", (e) => problems.push(e.message.slice(0, 160)));
await page.goto(`http://127.0.0.1:${PORT}/`);
await page.waitForTimeout(1200);
await page.locator("text=Project").first().click();
await page.waitForTimeout(500);
await page.locator('input[placeholder*="mup" i], input[type="text"]').first().fill(PROJECT);
await page.keyboard.press("Enter");
await page.waitForTimeout(1500);

await page.locator("text=Flow").first().click();
await page.waitForTimeout(2500);
await page.locator('button:has-text("inflow")').first().click();
await page.waitForTimeout(1800);
await page.screenshot({ path: `${SHOTS}/v4-inflow.png`, clip: {x: 220, y: 140, width: 1030, height: 860} });

await page.locator("text=Grid").first().click();
await page.waitForTimeout(2200);
await page.screenshot({ path: `${SHOTS}/v4-grid.png` });
console.log("grid tab text:", (await page.locator("main").innerText()).slice(0, 300).replace(/\n+/g, " | "));
console.log("problems:", problems.length ? problems.slice(0, 4) : "none");
await browser.close();
