import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { decodeFrame, FrameError, MAGIC, VERSION } from "./frames";

const FIXTURES = join(__dirname, "../../../tests/fixtures/frames");

interface ManifestEntry {
  file: string;
  kind: string;
  dtype: string;
  shape: number[];
  values: number[];
  component?: string;
  timeIdx?: number;
  gridHash?: string;
}

const manifest = JSON.parse(
  readFileSync(join(FIXTURES, "manifest.json"), "utf-8"),
) as ManifestEntry[];

function loadFixture(name: string): ArrayBuffer {
  const buffer = readFileSync(join(FIXTURES, name));
  return buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
}

/**
 * Build a frame by hand so the malformed-input tests don't depend on fixtures.
 * Pads the header like the Python encoder does unless `pad` is turned off.
 */
function makeFrame(
  headerObject: object,
  payload: ArrayBufferView,
  { magic = MAGIC, version = VERSION, flags = 0, pad = true } = {},
): ArrayBuffer {
  let json = JSON.stringify(headerObject);
  if (pad) {
    while ((12 + new TextEncoder().encode(json).byteLength) % 8 !== 0) {
      json += " ";
    }
  }
  const header = new TextEncoder().encode(json);
  const buffer = new ArrayBuffer(12 + header.byteLength + payload.byteLength);
  const view = new DataView(buffer);
  view.setUint32(0, magic, true);
  view.setUint16(4, version, true);
  view.setUint16(6, flags, true);
  view.setUint32(8, header.byteLength, true);
  new Uint8Array(buffer).set(header, 12);
  new Uint8Array(buffer).set(
    new Uint8Array(payload.buffer, payload.byteOffset, payload.byteLength),
    12 + header.byteLength,
  );
  return buffer;
}

describe("decodeFrame against the shared Python fixtures", () => {
  it("has fixtures to check", () => {
    expect(manifest.length).toBeGreaterThan(0);
  });

  it.each(manifest)("decodes $file as the manifest describes", (entry) => {
    const { header, array } = decodeFrame(loadFixture(entry.file));

    expect(header.kind).toBe(entry.kind);
    expect(header.dtype).toBe(entry.dtype);
    expect(header.shape).toEqual(entry.shape);
    expect(Array.from(array)).toHaveLength(entry.values.length);
    Array.from(array).forEach((value, index) => {
      expect(value).toBeCloseTo(entry.values[index], 5);
    });
  });

  it("carries optional header fields through", () => {
    const { header } = decodeFrame(loadFixture("scalar_f32.bin"));

    expect(header.component).toBe("Ca");
    expect(header.timeIdx).toBe(3);
    expect(header.vmin).toBeCloseTo(-100000000, 0);
  });
});

describe("decodeFrame error handling", () => {
  const payload = new Float32Array([1, 2]);
  const goodHeader = { kind: "scalar", dtype: "float32", shape: [2] };

  it("rejects a buffer too short to hold a header", () => {
    expect(() => decodeFrame(new ArrayBuffer(4))).toThrow(FrameError);
  });

  it("rejects a bad magic", () => {
    const frame = makeFrame(goodHeader, payload, { magic: 0xdeadbeef });

    expect(() => decodeFrame(frame)).toThrow(/magic/);
  });

  it("rejects a version it does not speak", () => {
    const frame = makeFrame(goodHeader, payload, { version: 99 });

    expect(() => decodeFrame(frame)).toThrow(/version 99/);
  });

  it("rejects a compressed payload until decompression is wired up", () => {
    const frame = makeFrame(goodHeader, payload, { flags: 1 });

    expect(() => decodeFrame(frame)).toThrow(/zstd/);
  });

  it("rejects an unknown dtype", () => {
    const frame = makeFrame({ kind: "scalar", dtype: "float64", shape: [2] }, payload);

    expect(() => decodeFrame(frame)).toThrow(/dtype float64/);
  });

  it("rejects a payload whose length disagrees with the shape", () => {
    const frame = makeFrame({ kind: "scalar", dtype: "float32", shape: [7] }, payload);

    expect(() => decodeFrame(frame)).toThrow(/payload is 8 bytes/);
  });

  it("rejects an unaligned payload rather than crashing on the view", () => {
    const frame = makeFrame(goodHeader, payload, { pad: false });

    expect(() => decodeFrame(frame)).toThrow(/not aligned/);
  });

  it("views the payload without copying it", () => {
    const frame = decodeFrame(loadFixture("scalar_f32.bin"));

    // A view, not a copy: the payload can be hundreds of megabytes.
    expect(frame.array.buffer.byteLength).toBeGreaterThan(frame.array.byteLength);
  });
});
