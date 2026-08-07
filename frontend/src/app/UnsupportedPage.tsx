import type { GpuSupport } from "@/lib/webgpu";

const BROWSERS = [
  "Chrome or Edge 113+ on Windows, macOS, Linux or ChromeOS",
  "Safari 26+ on macOS",
  "Firefox 141+ on Windows (Linux and macOS still rolling out)",
];

/**
 * Shown when WebGPU is unavailable. The viewport renders 3D grids with no
 * WebGL fallback, so there is no degraded mode to offer — say why, and give
 * the user something to copy into a bug report.
 */
export function UnsupportedPage({
  support,
}: {
  support: Extract<GpuSupport, { supported: false }>;
}) {
  const diagnostics = [
    `reason: ${support.reason}`,
    `detail: ${support.detail}`,
    `userAgent: ${navigator.userAgent}`,
  ].join("\n");

  return (
    <main className="mx-auto flex min-h-full max-w-2xl flex-col justify-center gap-6 p-8">
      <div>
        <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
          MUP Studio needs WebGPU
        </h1>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          The 3D viewport draws model grids directly on the GPU. That requires WebGPU, and this
          browser cannot provide it.
        </p>
      </div>

      <section>
        <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">What happened</h2>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">{support.detail}</p>
      </section>

      <section>
        <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
          Known-good browsers
        </h2>
        <ul className="mt-1 list-inside list-disc text-sm text-zinc-600 dark:text-zinc-400">
          {BROWSERS.map((browser) => (
            <li key={browser}>{browser}</li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">Diagnostics</h2>
        <pre className="mt-1 overflow-x-auto rounded bg-zinc-100 p-3 text-xs text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200">
          {diagnostics}
        </pre>
      </section>
    </main>
  );
}
