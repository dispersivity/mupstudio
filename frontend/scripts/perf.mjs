/**
 * Drives the perf page in a real browser and prints the frame-time summary.
 *
 * Usage: node scripts/perf.mjs [--ncpl 50000] [--nlay 10] [--frames 600] [--headed]
 *
 * Assumes the app is being served (vite dev or `mupstudio serve`) at --url.
 * vsync is disabled so what gets measured is how long a frame takes to
 * produce, not how long until the display accepts it.
 */

import { chromium } from "playwright";

const args = process.argv.slice(2);
function arg(name, fallback) {
  const index = args.indexOf(`--${name}`);
  return index >= 0 ? args[index + 1] : fallback;
}

const url = arg("url", "http://127.0.0.1:5173");
const ncpl = arg("ncpl", "50000");
const nlay = arg("nlay", "10");
const ntimes = arg("ntimes", "40");
const frames = arg("frames", "600");
const headed = args.includes("--headed");

// Playwright's bundled headless shell has no GPU and silently falls back to
// SwiftShader, which makes perf numbers meaningless. Real timings need the
// full browser; --channel chrome uses the installed one.
const channel = arg("channel", headed ? "chrome" : undefined);

const browser = await chromium.launch({
  headless: !headed,
  channel,
  args: [
    "--enable-unsafe-webgpu",
    "--disable-gpu-vsync",
    "--disable-frame-rate-limit",
    "--no-sandbox",
  ],
});

const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
page.on("console", (message) => {
  if (message.type() === "error") console.error("[browser]", message.text());
});
page.on("pageerror", (error) => console.error("[browser]", error.message));

const target = `${url}/?perf=1&ncpl=${ncpl}&nlay=${nlay}&ntimes=${ntimes}&frames=${frames}`;
console.log(`loading ${target}`);
await page.goto(target, { waitUntil: "domcontentloaded" });

try {
  await page.waitForFunction(() => window.__mupPerf !== undefined, null, { timeout: 300_000 });
} catch {
  const status = await page.getByTestId("perf-status").textContent().catch(() => null);
  console.error(`perf run did not finish. last status: ${status ?? "unknown"}`);
  await browser.close();
  process.exit(1);
}

const result = await page.evaluate(() => window.__mupPerf);
await browser.close();

const line = (label, value) => console.log(`  ${label.padEnd(12)} ${value}`);
console.log("");
line("adapter", result.adapter);
line("canvas", `${result.canvasWidth}x${result.canvasHeight}`);
line("cells", result.cells.toLocaleString());
line("triangles", result.triangles.toLocaleString());
line("frames", `${result.framesDrawn} drawn / ${result.framesMeasured} measured`);
line("p50", `${result.p50Ms} ms`);
line("p95", `${result.p95Ms} ms`);
line("p99", `${result.p99Ms} ms`);
line("max", `${result.maxMs} ms`);
line("mean fps", result.impliedFps);
console.log("");
if (!result.valid) {
  console.log(
    "INVALID  the renderer was idle or the canvas had no size; these timings measure nothing",
  );
} else {
  console.log(
    result.passed
      ? `PASS  p95 ${result.p95Ms} ms is within the ${result.budgetMs} ms budget`
      : `FAIL  p95 ${result.p95Ms} ms exceeds the ${result.budgetMs} ms budget`,
  );
}

process.exit(result.passed ? 0 : 1);
