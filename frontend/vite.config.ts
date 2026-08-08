// vitest/config re-exports vite's defineConfig with the `test` block typed.
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import type { Plugin } from "vite";

// The dev server proxies to uvicorn so the browser only ever talks to one origin.
const BACKEND = "http://127.0.0.1:8000";

/**
 * Ship MapLibre's worker alongside the bundle.
 *
 * MapLibre builds the worker's URL at run time — `new URL("./maplibre-gl-worker.mjs", <its own
 * module URL>)` — which no bundler can see, so Vite emits the main module and leaves the worker
 * behind. The failure is quiet and misleading: raster tiles keep working because they do not need
 * the worker, while every GeoJSON source silently produces nothing, so a basemap appears with no
 * data on it and no error to explain why.
 *
 * The files are copied next to the bundle, which is where that run-time URL resolves to.
 */
function maplibreWorker(): Plugin {
  const require = createRequire(import.meta.url);
  const dist = path.dirname(require.resolve("maplibre-gl/dist/maplibre-gl.mjs"));

  return {
    name: "maplibre-worker",
    apply: "build",
    generateBundle() {
      // The worker, and the shared module it imports.
      for (const name of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
        this.emitFile({
          type: "asset",
          fileName: `assets/${name}`,
          source: readFileSync(path.join(dist, name), "utf8"),
        });
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), maplibreWorker()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: {
    port: 5173,
    proxy: {
      // ws:true because the viewport socket lives at /api/v1/ws/viewport;
      // without it the upgrade request is proxied as plain HTTP and hangs.
      "/api": { target: BACKEND, changeOrigin: true, ws: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
