import type { ColormapName } from "./scalars/colormap";

export interface GridGeometry {
  /** (nverts, 2) footprint xy, flattened. */
  vertices: Float32Array;
  /** (ncpl + 1) CSR offsets. */
  cellOffsets: Int32Array;
  /** Vertex index per cell corner. */
  cellIndices: Int32Array;
  /** (nlay, ncpl) top elevation per cell, layer-major. */
  top: Float32Array<ArrayBuffer>;
  /** (nlay, ncpl) bottom elevation per cell, layer-major. */
  botm: Float32Array<ArrayBuffer>;
  nlay: number;
  ncpl: number;
  bounds: { min: [number, number, number]; max: [number, number, number] };
}

export interface ScalarSet {
  component: string;
  /** One entry per timestep, each (nlay * ncpl) long. */
  timesteps: Float32Array<ArrayBuffer>[];
  times: number[];
  vmin: number;
  vmax: number;
  /** 1 unless the server decimated time to fit a memory budget. */
  timeStride: number;
}

export interface ViewportOptions {
  /** Value marking an inactive cell; those fragments are discarded. */
  nodata?: number;
  verticalExaggeration?: number;
  colormap?: ColormapName;
}

export interface FrameStats {
  /** Frames drawn since the viewport was created. */
  frames: number;
  lastFrameMs: number;
  triangles: number;
  /** Which GPU backend the adapter reported, for perf runs. */
  adapter: string;
}

export interface Viewport {
  setGrid(geometry: GridGeometry): void;
  setScalars(set: ScalarSet): void;
  setTimestep(index: number): void;
  getTimestep(): number;
  setColormap(name: ColormapName): void;
  setRange(min: number, max: number): void;
  setLogScale(enabled: boolean): void;
  setVerticalExaggeration(factor: number): void;
  frameAll(): void;
  requestRender(): void;
  /**
   * Render one frame and resolve when the GPU has finished it.
   *
   * The normal loop submits work and returns immediately, so wall-clock time
   * around it measures command encoding, not drawing. Benchmarks need the
   * real cost, which means waiting for the queue to drain.
   */
  renderAndWait(): Promise<void>;
  stats(): FrameStats;
  destroy(): void;
}
