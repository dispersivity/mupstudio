/**
 * Binary frame decoder. Mirrors src/mupstudio/server/ws/frames.py — the two are
 * pinned together by shared fixtures in tests/fixtures/frames.
 *
 * Layout (little-endian throughout):
 *   0   4  magic "MUPB"
 *   4   2  version u16
 *   6   2  flags u16, bit 0 = zstd
 *   8   4  header length u32
 *   12  .. header, UTF-8 JSON
 *   ..  .. payload, C-order array bytes
 *
 * The encoder pads the header with spaces so the payload starts on an 8-byte
 * boundary, which is what lets the payload be viewed rather than copied:
 * typed-array views cannot start at an unaligned offset, and these payloads
 * reach hundreds of megabytes and go straight to the GPU.
 */

export const MAGIC = 0x4250554d; // "MUPB" read as a little-endian u32
export const VERSION = 1;
export const FLAG_ZSTD = 1 << 0;
const HEADER_OFFSET = 12;

export type FrameKind =
  | "mesh_vertices"
  | "mesh_cell_offsets"
  | "mesh_cell_indices"
  | "mesh_cell_centers"
  | "cell_elevations"
  | "scalar"
  | "scalar_block";

export type FrameDtype = "float32" | "int32" | "uint32" | "uint8";

export interface FrameHeader {
  kind: FrameKind;
  dtype: FrameDtype;
  shape: number[];
  reqId?: number;
  component?: string;
  timeIdx?: number;
  time?: number;
  timeStride?: number;
  vmin?: number;
  vmax?: number;
  nodata?: number;
  gridHash?: string;
  [key: string]: unknown;
}

// Parameterised on ArrayBuffer (not ArrayBufferLike) because these views go
// straight to WebGPU, which rejects SharedArrayBuffer-backed views.
export type FrameArray =
  | Float32Array<ArrayBuffer>
  | Int32Array<ArrayBuffer>
  | Uint32Array<ArrayBuffer>
  | Uint8Array<ArrayBuffer>;

export interface Frame {
  header: FrameHeader;
  array: FrameArray;
}

const VIEWS = {
  float32: Float32Array,
  int32: Int32Array,
  uint32: Uint32Array,
  uint8: Uint8Array,
} as const;

export class FrameError extends Error {}

export function decodeFrame(buffer: ArrayBuffer): Frame {
  if (buffer.byteLength < HEADER_OFFSET) {
    throw new FrameError(`frame is ${buffer.byteLength} bytes, too short to hold a header`);
  }

  const view = new DataView(buffer);
  const magic = view.getUint32(0, true);
  if (magic !== MAGIC) {
    throw new FrameError(`expected magic MUPB, got 0x${magic.toString(16)}`);
  }

  const version = view.getUint16(4, true);
  if (version !== VERSION) {
    throw new FrameError(
      `frame version ${version} is not supported (this build speaks ${VERSION})`,
    );
  }

  const flags = view.getUint16(6, true);
  if (flags & FLAG_ZSTD) {
    throw new FrameError("payload is zstd compressed; decompression is not wired up yet");
  }

  const headerLen = view.getUint32(8, true);
  const headerEnd = HEADER_OFFSET + headerLen;
  if (buffer.byteLength < headerEnd) {
    throw new FrameError(`header claims ${headerLen} bytes but the frame ends early`);
  }

  const header = JSON.parse(
    new TextDecoder().decode(new Uint8Array(buffer, HEADER_OFFSET, headerLen)),
  ) as FrameHeader;

  const View = VIEWS[header.dtype];
  if (!View) {
    throw new FrameError(`unknown dtype ${header.dtype}`);
  }

  if (headerEnd % View.BYTES_PER_ELEMENT !== 0) {
    throw new FrameError(
      `payload starts at byte ${headerEnd}, which is not aligned for ${header.dtype}; ` +
        "the encoder should have padded the header",
    );
  }

  const expected = header.shape.reduce((total, dim) => total * dim, 1);
  const payloadBytes = buffer.byteLength - headerEnd;
  if (payloadBytes !== expected * View.BYTES_PER_ELEMENT) {
    throw new FrameError(
      `payload is ${payloadBytes} bytes but shape ${header.shape.join("x")} of ` +
        `${header.dtype} needs ${expected * View.BYTES_PER_ELEMENT}`,
    );
  }

  return { header, array: new View(buffer, headerEnd, expected) };
}
