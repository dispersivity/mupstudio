import { describe, expect, it } from "vitest";
import { FRAME_BUDGET_MS, measureFrameTimes, summarise, type RunContext } from "./harness";

const VALID: RunContext = {
  ncpl: 50_000,
  nlay: 10,
  triangles: 9_984_000,
  framesDrawn: 200,
  canvasWidth: 1600,
  canvasHeight: 900,
  adapter: "apple metal-3",
};

/** Samples whose p95 lands on a chosen value. */
function samplesWithP95(fast: number, slow: number, count = 100): number[] {
  return Array.from({ length: count }, (_, index) => (index < count * 0.95 ? fast : slow));
}

describe("summarise", () => {
  it("passes a fast run on a real adapter", () => {
    const result = summarise(samplesWithP95(4, 5), VALID);

    expect(result.valid).toBe(true);
    expect(result.passed).toBe(true);
    expect(result.p95Ms).toBeLessThanOrEqual(FRAME_BUDGET_MS);
  });

  it("fails a run that misses the budget", () => {
    const result = summarise(samplesWithP95(12, 20), VALID);

    expect(result.valid).toBe(true);
    expect(result.passed).toBe(false);
  });

  it("reports percentiles in order", () => {
    const result = summarise([1, 2, 3, 4, 5, 20], VALID);

    expect(result.p50Ms).toBeLessThanOrEqual(result.p95Ms);
    expect(result.p95Ms).toBeLessThanOrEqual(result.p99Ms);
    expect(result.maxMs).toBe(20);
  });

  it("refuses to pass when the renderer drew almost nothing", () => {
    // The failure that produced a bogus 0.1ms "pass": frames measured but not
    // drawn, so the loop was timing itself.
    const result = summarise(samplesWithP95(0.1, 0.2), { ...VALID, framesDrawn: 3 });

    expect(result.valid).toBe(false);
    expect(result.passed).toBe(false);
  });

  it("refuses to pass when the canvas had no size", () => {
    const result = summarise(samplesWithP95(0.1, 0.2), { ...VALID, canvasWidth: 0 });

    expect(result.valid).toBe(false);
    expect(result.passed).toBe(false);
  });

  it("refuses to pass when no geometry was loaded", () => {
    const result = summarise(samplesWithP95(0.1, 0.2), { ...VALID, triangles: 0 });

    expect(result.valid).toBe(false);
    expect(result.passed).toBe(false);
  });

  it("carries the adapter through so a software fallback is visible", () => {
    const result = summarise(samplesWithP95(4, 5), { ...VALID, adapter: "google swiftshader" });

    expect(result.adapter).toBe("google swiftshader");
  });

  it("derives the cell count from the grid", () => {
    expect(summarise([4], VALID).cells).toBe(500_000);
  });
});

describe("measureFrameTimes", () => {
  it("discards warmup frames and returns the rest", async () => {
    let rendered = 0;
    const samples = await measureFrameTimes(
      {
        step: () => {},
        renderAndWait: async () => {
          rendered++;
        },
      },
      { frames: 10, warmup: 4 },
    );

    expect(samples).toHaveLength(10);
    expect(rendered).toBe(14);
  });

  it("advances the animation once per frame", async () => {
    const steps: number[] = [];
    await measureFrameTimes(
      {
        step: (frame) => steps.push(frame),
        renderAndWait: async () => {},
      },
      { frames: 3, warmup: 0 },
    );

    expect(steps).toEqual([0, 1, 2]);
  });

  it("times the wait, not just the call", async () => {
    const samples = await measureFrameTimes(
      {
        step: () => {},
        renderAndWait: () => new Promise((resolve) => setTimeout(resolve, 12)),
      },
      { frames: 2, warmup: 0 },
    );

    for (const sample of samples) {
      expect(sample).toBeGreaterThan(8);
    }
  });
});
