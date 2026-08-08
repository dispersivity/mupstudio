import { chromium } from "playwright";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const shots = process.argv[2] || "e2e";
const browser = await chromium.launch({
  channel: "chromium",
  headless: true,
  args: ["--enable-unsafe-webgpu", "--no-sandbox"],
});
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
page.on("pageerror", (e) => console.error("[pageerror]", e.message));
page.on("console", (m) => {
  if (m.type() === "error") console.error("[console]", m.text());
});

await page.goto("http://localhost:5173/", { waitUntil: "domcontentloaded" });

// 1. Create a project.
await page.getByRole("button", { name: "Project" }).click();
await page.waitForSelector("text=New project");
const parent = mkdtempSync(join(tmpdir(), "mup-e2e-"));
await page.getByLabel("Name").fill("starter column");
await page.getByLabel("Cells along the column").fill("40");
await page.getByLabel(/Create in/).fill(parent);
await page.getByRole("button", { name: "Create project" }).click();
await page.waitForSelector("text=starter column: mf6rtm", { timeout: 30000 });
await page.screenshot({ path: `${shots}-project.png` });
console.log(
  "1. created:",
  await page.locator("text=/starter column: mf6rtm/").first().textContent(),
);

// 2. Validate and write, then read a written file.
await page.getByRole("button", { name: "Simulate" }).click();
await page.waitForSelector("text=Write input");
await page.getByRole("button", { name: "Validate" }).click();
await page.waitForSelector("text=/ok — /", { timeout: 30000 });
console.log("2. validation:", await page.locator("text=/ok — /").first().textContent());

await page.getByRole("button", { name: "Write input" }).click();
await page.waitForSelector("text=/Written files/", { timeout: 30000 });
await page.waitForTimeout(800);
await page.screenshot({ path: `${shots}-write.png` });
const preview = await page.locator("pre").first().textContent();
console.log("3. preview starts:", (preview || "").slice(0, 60).replace(/\n/g, " "));

// 3. Run it and wait to land on Results.
await page.getByRole("button", { name: "Write and run" }).click();
await page.waitForSelector('[aria-label="Timestep"]', { timeout: 120000 });
await page.waitForTimeout(2500);
await page.screenshot({ path: `${shots}-results.png` });
console.log("4. header:", (await page.innerText("header")).replace(/\n/g, " | "));
await page.getByLabel("Cell edges").click();
await page.getByLabel("y exaggeration").fill("-1.4");
await page.getByLabel("Timestep").fill("7");
await page.waitForTimeout(1500);
await page.screenshot({ path: `${shots}-field.png` });
const range = await page.locator("text=/Auto from data/").first().isVisible();
console.log(
  "5. range inputs:",
  await page.getByLabel("Minimum").inputValue(),
  "to",
  await page.getByLabel("Maximum").inputValue(),
  "| auto:",
  range,
);

await browser.close();
