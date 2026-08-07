/**
 * WebGPU capability detection.
 *
 * The viewport has no WebGL fallback by design, so the app checks once at
 * startup and routes to an explanatory page when the browser can't run it.
 */

export type GpuSupport =
  | { supported: true; adapterInfo: GPUAdapterInfo | null }
  | { supported: false; reason: "no-api" | "no-adapter" | "error"; detail: string };

export async function detectWebGPU(): Promise<GpuSupport> {
  if (typeof navigator === "undefined" || !navigator.gpu) {
    return {
      supported: false,
      reason: "no-api",
      detail: "navigator.gpu is undefined — this browser does not expose the WebGPU API.",
    };
  }

  try {
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) {
      return {
        supported: false,
        reason: "no-adapter",
        detail:
          "The WebGPU API exists but no adapter was returned. The GPU may be blocklisted or " +
          "hardware acceleration may be disabled.",
      };
    }
    return { supported: true, adapterInfo: adapter.info ?? null };
  } catch (error) {
    return {
      supported: false,
      reason: "error",
      detail: error instanceof Error ? error.message : String(error),
    };
  }
}
