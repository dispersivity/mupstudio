import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against the packaged app.
 *
 * Against `mupstudio serve` and the built bundle rather than the Vite dev
 * server, because packaging is one of the things that breaks: a wheel that
 * ships without its frontend, an index.html served from cache pointing at a
 * bundle that no longer exists, a route that only exists behind the dev proxy.
 * None of those are visible when the tests run against the dev server.
 */

const PORT = Number(process.env.MUPSTUDIO_E2E_PORT ?? 8765);

export default defineConfig({
  testDir: "./e2e",
  // These drive a real browser against a real server; running specs of the
  // same project in parallel would have them fighting over its files.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  timeout: 90_000,
  expect: { timeout: 15_000 },

  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // The bundled headless shell has no GPU and silently falls back to a
        // software rasteriser, which reports success while drawing nothing
        // that resembles the real thing. WebGPU needs the full browser.
        channel: "chromium",
        viewport: { width: 1600, height: 950 },
        launchOptions: {
          args: [
            "--enable-unsafe-webgpu",
            // SwiftShader is what makes WebGPU work on a CI machine with no
            // GPU. Correctness only: nothing here measures frame times.
            "--enable-unsafe-swiftshader",
            "--use-angle=vulkan",
            "--enable-features=Vulkan",
            "--disable-vulkan-surface",
            "--no-sandbox",
          ],
        },
      },
    },
  ],

  webServer: {
    // `--no-browser` because a test opening a window on the developer's
    // machine is a surprise, and on CI there is nothing to open.
    // --strict-port so a busy port fails here rather than moving the server
    // somewhere the tests are not looking, which reads as a startup timeout.
    command: `uv run mupstudio serve --port ${PORT} --no-browser --strict-port`,
    url: `http://127.0.0.1:${PORT}/api/v1/health`,
    cwd: "..",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
