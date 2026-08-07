/**
 * Frame-time harness for the 500k-cell gate.
 *
 * Measures the interval between presented frames while driving the camera
 * along a fixed path, so runs are comparable. The number that matters is p95
 * frame time, not mean fps: an average hides the stalls that are actually
 * visible as stutter.
 *
 * Run it by loading the app with ?perf=1. Results land on window.__mupPerf and
 * are printed to the console.
 */

export interface PerfResult {
  cells: number;
  ncpl: number;
  nlay: number;
  triangles: number;
  framesMeasured: number;
  /** Frames the viewport actually drew. Far below framesMeasured means the
   * renderer was idle and the timings describe an empty loop. */
  framesDrawn: number;
  /** Drawing buffer size. Zero here also produces meaninglessly fast frames. */
  canvasWidth: number;
  canvasHeight: number;
  adapter: string;
  p50Ms: number;
  p95Ms: number;
  p99Ms: number;
  meanMs: number;
  maxMs: number;
  impliedFps: number;
  /** p95 at or under this many ms is the gate. */
  budgetMs: number;
  /** False when the run did not actually render; the timings mean nothing then. */
  valid: boolean;
  passed: boolean;
}

declare global {
  interface Window {
    __mupPerf?: PerfResult;
  }
}

export const FRAME_BUDGET_MS = 1000 / 120;

function percentile(sorted: number[], fraction: number): number {
  if (sorted.length === 0) return Number.NaN;
  const rank = Math.min(sorted.length - 1, Math.floor(fraction * sorted.length));
  return sorted[rank];
}

export interface HarnessTarget {
  /** Called before each frame to advance the animation. */
  step(frame: number): void;
  /** Renders one frame and resolves once the GPU has finished drawing it. */
  renderAndWait(): Promise<void>;
}

/**
 * Time complete frames: encode, draw, and wait for the GPU to finish.
 *
 * Timing around submission alone measures how fast commands are written, which
 * on a large scene is a small fraction of the work and gives absurdly fast
 * numbers. Each sample here spans a whole frame's GPU work.
 */
export async function measureFrameTimes(
  target: HarnessTarget,
  { frames = 600, warmup = 60 }: { frames?: number; warmup?: number } = {},
): Promise<number[]> {
  const samples: number[] = [];

  for (let index = 0; index < frames + warmup; index++) {
    target.step(index);

    const started = performance.now();
    await target.renderAndWait();
    const elapsed = performance.now() - started;

    // Warmup frames carry shader compilation and first-use allocation: real
    // costs, but not the steady-state ones this is measuring.
    if (index >= warmup) {
      samples.push(elapsed);
    }
  }

  return samples;
}

export interface RunContext {
  ncpl: number;
  nlay: number;
  triangles: number;
  framesDrawn: number;
  canvasWidth: number;
  canvasHeight: number;
  adapter: string;
}

export function summarise(samples: number[], context: RunContext): PerfResult {
  const sorted = [...samples].sort((a, b) => a - b);
  const mean = samples.reduce((total, value) => total + value, 0) / samples.length;
  const p95 = percentile(sorted, 0.95);

  // A fast p95 only means something if the renderer was actually working.
  // An unsized canvas or an idle render loop both produce sub-millisecond
  // frames that would otherwise read as a spectacular pass.
  const rendered =
    context.framesDrawn >= samples.length * 0.9 &&
    context.canvasWidth > 0 &&
    context.canvasHeight > 0 &&
    context.triangles > 0;

  return {
    cells: context.ncpl * context.nlay,
    ncpl: context.ncpl,
    nlay: context.nlay,
    triangles: context.triangles,
    framesMeasured: samples.length,
    framesDrawn: context.framesDrawn,
    canvasWidth: context.canvasWidth,
    canvasHeight: context.canvasHeight,
    adapter: context.adapter,
    p50Ms: round(percentile(sorted, 0.5)),
    p95Ms: round(p95),
    p99Ms: round(percentile(sorted, 0.99)),
    meanMs: round(mean),
    maxMs: round(sorted[sorted.length - 1]),
    impliedFps: round(1000 / mean),
    budgetMs: round(FRAME_BUDGET_MS),
    valid: rendered,
    passed: rendered && p95 <= FRAME_BUDGET_MS,
  };
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}
