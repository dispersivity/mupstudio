/**
 * WebSocket client for viewport data.
 *
 * Requests are correlated by reqId: each reply is a run of binary frames
 * carrying that id, ended by a `done` message. Frames arrive as ArrayBuffers
 * and are handed to the caller as typed-array views, never copied into React
 * state.
 */

import { decodeFrame, type Frame } from "./frames";
import type { GridGeometry, ScalarSet } from "@/viewport/types";

export interface DatasetCatalog {
  dataset: string;
  /** "synthetic" for the demo grid, "run" for a collected model run. */
  kind?: string;
  status?: string;
  engine?: string;
  warnings?: string[];
  gridHash: string;
  ncpl: number;
  nlay: number;
  ncells: number;
  nverts: number;
  bounds: { min: [number, number, number]; max: [number, number, number] };
  /** "x" or "y" when the grid is one cell across that axis; null otherwise. */
  thinAxis?: "x" | "y" | null;
  times: number[];
  components: { name: string; unit: string; vmin: number; vmax: number }[];
  /**
   * What each component is, when the dataset says. A project preview groups its
   * fields into properties, boundaries and chemistry so the picker can too; a
   * run has no such distinction and omits this.
   */
  fields?: { name: string; label: string; kind: string; unit: string; setCells: number }[];
  /**
   * Rows and columns, for a structured grid.
   *
   * Absent on a vertex grid, which has cells in a layer and no notion of either.
   * Slicing by row or column needs them.
   */
  nrow?: number;
  ncol?: number;
}

interface Pending {
  frames: Frame[];
  resolve: (frames: Frame[]) => void;
  reject: (error: Error) => void;
}

/** Dataset ids with this prefix name a project on disk, not a finished run. */
export const PREVIEW = "preview:";

export async function fetchCatalog(
  datasetId: string,
  params: URLSearchParams,
): Promise<DatasetCatalog> {
  // A project preview is addressed by a filesystem path, which cannot sit in a
  // URL path segment, so it has its own endpoint and passes the path as a
  // query parameter.
  const url = datasetId.startsWith(PREVIEW)
    ? `/api/v1/datasets/preview?path=${encodeURIComponent(datasetId.slice(PREVIEW.length))}`
    : `/api/v1/datasets/${encodeURIComponent(datasetId)}?${params}`;

  const response = await fetch(url);
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(`could not load dataset ${datasetId}: ${response.status} ${detail}`);
  }
  return (await response.json()) as DatasetCatalog;
}

export async function fetchDatasetListing(): Promise<
  import("@/results/DatasetPicker").DatasetListing
> {
  const response = await fetch("/api/v1/datasets");
  if (!response.ok) {
    throw new Error(`dataset listing failed: ${response.status}`);
  }
  return await response.json();
}

export class ViewportClient {
  private socket: WebSocket | null = null;
  private pending = new Map<number, Pending>();
  private nextReqId = 1;

  constructor(private readonly params: URLSearchParams) {}

  connect(): Promise<void> {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${location.host}/api/v1/ws/viewport?${this.params}`);
    socket.binaryType = "arraybuffer";
    this.socket = socket;

    socket.addEventListener("message", (event) => this.onMessage(event));
    socket.addEventListener("close", () => this.failAll(new Error("socket closed")));

    return new Promise((resolve, reject) => {
      socket.addEventListener("open", () => resolve(), { once: true });
      socket.addEventListener("error", () => reject(new Error("socket failed to open")), {
        once: true,
      });
    });
  }

  private onMessage(event: MessageEvent) {
    if (event.data instanceof ArrayBuffer) {
      const frame = decodeFrame(event.data);
      const reqId = frame.header.reqId;
      if (typeof reqId === "number") {
        this.pending.get(reqId)?.frames.push(frame);
      }
      return;
    }

    const message = JSON.parse(event.data as string) as {
      op: string;
      reqId?: number;
      message?: string;
    };

    if (message.op === "done" && typeof message.reqId === "number") {
      const pending = this.pending.get(message.reqId);
      if (pending) {
        this.pending.delete(message.reqId);
        pending.resolve(pending.frames);
      }
    } else if (message.op === "error") {
      const error = new Error(message.message ?? "server error");
      if (typeof message.reqId === "number") {
        const pending = this.pending.get(message.reqId);
        this.pending.delete(message.reqId);
        pending?.reject(error);
      } else {
        this.failAll(error);
      }
    }
  }

  private failAll(error: Error) {
    for (const pending of this.pending.values()) {
      pending.reject(error);
    }
    this.pending.clear();
  }

  private request(message: Record<string, unknown>): Promise<Frame[]> {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error("socket is not open"));
    }
    const reqId = this.nextReqId++;
    const promise = new Promise<Frame[]>((resolve, reject) => {
      this.pending.set(reqId, { frames: [], resolve, reject });
    });
    this.socket.send(JSON.stringify({ ...message, reqId }));
    return promise;
  }

  async getGeometry(catalog: DatasetCatalog): Promise<GridGeometry> {
    const frames = await this.request({ op: "get_mesh" });
    const byKind = new Map(frames.map((frame) => [frame.header.kind, frame]));

    const elevations = byKind.get("cell_elevations")!.array as Float32Array<ArrayBuffer>;
    const perLayer = catalog.nlay * catalog.ncpl;

    return {
      vertices: byKind.get("mesh_vertices")!.array as Float32Array<ArrayBuffer>,
      cellOffsets: byKind.get("mesh_cell_offsets")!.array as Int32Array,
      cellIndices: byKind.get("mesh_cell_indices")!.array as Int32Array,
      // The server stacks top and bottom into one (2, nlay, ncpl) frame.
      top: elevations.subarray(0, perLayer),
      botm: elevations.subarray(perLayer, perLayer * 2),
      nlay: catalog.nlay,
      ncpl: catalog.ncpl,
      bounds: catalog.bounds,
    };
  }

  async getScalars(component: string, catalog: DatasetCatalog): Promise<ScalarSet> {
    const [frame] = await this.request({ op: "get_scalar_block", component });
    const block = frame.array as Float32Array<ArrayBuffer>;
    const perStep = catalog.nlay * catalog.ncpl;
    const ntimes = block.length / perStep;

    // Views into the one received buffer; each becomes a GPU buffer with no
    // intermediate copy.
    const timesteps: Float32Array<ArrayBuffer>[] = [];
    for (let step = 0; step < ntimes; step++) {
      timesteps.push(block.subarray(step * perStep, (step + 1) * perStep));
    }

    return {
      component,
      timesteps,
      times: (frame.header.times as number[]) ?? catalog.times,
      vmin: frame.header.vmin ?? 0,
      vmax: frame.header.vmax ?? 1,
      timeStride: frame.header.timeStride ?? 1,
    };
  }

  close() {
    this.socket?.close();
    this.socket = null;
  }
}
