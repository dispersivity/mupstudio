import { afterEach, describe, expect, it, vi } from "vitest";
import { detectWebGPU } from "./webgpu";

function setGpu(gpu: unknown) {
  Object.defineProperty(navigator, "gpu", { value: gpu, configurable: true });
}

afterEach(() => {
  setGpu(undefined);
});

describe("detectWebGPU", () => {
  it("reports no-api when the browser has no WebGPU", async () => {
    setGpu(undefined);

    const result = await detectWebGPU();

    expect(result).toMatchObject({ supported: false, reason: "no-api" });
  });

  it("reports no-adapter when requestAdapter resolves null", async () => {
    setGpu({ requestAdapter: vi.fn().mockResolvedValue(null) });

    const result = await detectWebGPU();

    expect(result).toMatchObject({ supported: false, reason: "no-adapter" });
  });

  it("reports the failure message when requestAdapter throws", async () => {
    setGpu({ requestAdapter: vi.fn().mockRejectedValue(new Error("device lost")) });

    const result = await detectWebGPU();

    expect(result).toMatchObject({ supported: false, reason: "error", detail: "device lost" });
  });

  it("reports support and passes adapter info through", async () => {
    const info = { vendor: "apple", architecture: "metal-3" };
    setGpu({ requestAdapter: vi.fn().mockResolvedValue({ info }) });

    const result = await detectWebGPU();

    expect(result).toEqual({ supported: true, adapterInfo: info });
  });
});
