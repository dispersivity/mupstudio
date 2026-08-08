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
  showEdges?: boolean;
  /** Value marking an inactive cell; those fragments are discarded. */
  nodata?: number;
  verticalExaggeration?: number;
  colormap?: ColormapName;
}

export interface PickedCell {
  /** Index within the layer: cell2d on a vertex grid. */
  cell: number;
  layer: number;
}

export interface CameraView {
  /** World direction that points right on screen. */
  right: [number, number, number];
  /** World direction that points up on screen. */
  up: [number, number, number];
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
  /** Draw cell outlines, so grid structure is visible. */
  setShowEdges(enabled: boolean): void;
  /**
   * Draw cells with no value as a dim shell instead of not at all.
   *
   * Wanted when a field applies to only some cells — where a boundary acts,
   * which zone holds which minerals — because the cells that carry a value mean
   * nothing without the grid around them. Not wanted for a grid with inactive
   * regions, where a hole is the truth.
   */
  setGhostAbsent(enabled: boolean): void;
  /**
   * Show one layer, one row, one column, or the whole model.
   *
   * Checking model input means answering "which cells", and an oblique view of
   * a solid block cannot: the near faces hide the ones behind them. A single
   * layer seen from above has nothing hidden in it.
   *
   * ``columns`` is the grid's columns per row, needed by the row and column
   * modes and meaningless on a vertex grid, which has neither.
   */
  setSlice(mode: "all" | "layer" | "row" | "column", index: number, columns?: number): void;
  /** Point the camera from a named direction, or return it to free orbit. */
  setCanonicalView(view: "plan" | "front" | "side" | "free"): void;
  setVerticalExaggeration(factor: number): void;
  /**
   * Scale the model along each world axis.
   *
   * Vertical exaggeration is the z component. The horizontal components exist
   * for models with a single row or column, where a width chosen for tidy
   * geometry (1 m is common) can be larger than the modelled length and makes
   * a 1D column render as a slab.
   */
  setAxisScale(x: number, y: number, z: number): void;
  /**
   * Watch the camera, for overlays drawn in HTML over the canvas.
   *
   * Fires on orbit, pan and zoom with the world directions that currently
   * point right and up on screen. Returns an unsubscribe function.
   */
  onCamera(listener: (view: CameraView) => void): () => void;
  /**
   * Which cell is under a point on the canvas, or null for the background.
   *
   * Coordinates are in canvas pixels. Answered by rendering cell identities to
   * an offscreen target and reading one pixel, so it is exact at any camera
   * angle and costs nothing when nobody is clicking.
   */
  pick(x: number, y: number): Promise<PickedCell | null>;
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
