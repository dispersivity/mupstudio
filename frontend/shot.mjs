import { chromium } from "playwright";
const SCRATCH = "/private/tmp/claude-501/-Users-portega-dev-code-mupstudio/a7828c49-0c3c-4f8a-8ca5-26f204ffb181/scratchpad";
const project = SCRATCH + "/gisproj/Maipo.mup";
const browser = await chromium.launch({ args: ["--enable-unsafe-webgpu"] });
const page = await browser.newPage({ viewport: { width: 1700, height: 1000 } });
const log = [];
page.on("console", (m) => log.push(m.type() + ": " + m.text().slice(0, 160)));
page.on("pageerror", (e) => log.push("PAGEERROR " + e.message.slice(0, 200)));
await page.addInitScript(([p]) => {
  localStorage.setItem("mupstudio.step", "grid");
  localStorage.setItem("mupstudio.project", p);
}, [project]);
await page.goto("http://127.0.0.1:8850/");
await page.waitForTimeout(6000);
console.log("BODY:", (await page.locator("body").innerText()).slice(0, 400).replace(/\n+/g, " | "));
for (const tab of ["Layers", "Domain"]) {
  const b = page.locator("button", { hasText: new RegExp(`^${tab}$`) }).first();
  if (await b.count()) await b.click(); else console.log("no tab", tab);
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${SCRATCH}/shots/grid-${tab.toLowerCase()}.png` });
}
console.log("LOG:\n" + log.slice(0, 6).join("\n"));
await browser.close();
