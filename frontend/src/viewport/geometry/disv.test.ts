import { describe, expect, it } from "vitest";
import { CAP_BOTTOM, CAP_TOP, FLOATS_PER_VERTEX, packDisv, type Footprint } from "./disv";

/** Two adjacent unit squares sharing an edge. */
function twoSquares(): Footprint {
  return {
    vertices: new Float32Array([0, 0, 1, 0, 1, 1, 0, 1, 2, 0, 2, 1]),
    cellOffsets: new Int32Array([0, 4, 8]),
    cellIndices: new Int32Array([0, 1, 2, 3, 1, 4, 5, 2]),
  };
}

/** One square and one triangle: cells with different corner counts. */
function mixedShapes(): Footprint {
  return {
    vertices: new Float32Array([0, 0, 1, 0, 1, 1, 0, 1, 2, 0]),
    cellOffsets: new Int32Array([0, 4, 7]),
    cellIndices: new Int32Array([0, 1, 2, 3, 1, 4, 2]),
  };
}

function vertexAt(buffer: Float32Array, index: number) {
  const base = index * FLOATS_PER_VERTEX;
  return {
    x: buffer[base],
    y: buffer[base + 1],
    cell: buffer[base + 2],
    face: buffer[base + 3],
  };
}

describe("packDisv", () => {
  it("reports the cells-per-layer stride", () => {
    expect(packDisv(twoSquares()).ncpl).toBe(2);
  });

  it("emits both caps for every cell", () => {
    const mesh = packDisv(twoSquares());

    // 2 cells x 4 corners x 2 faces
    expect(mesh.capVertices.length / FLOATS_PER_VERTEX).toBe(16);
    // Each square fans into 2 triangles, twice over
    expect(mesh.capIndices.length).toBe(2 * 2 * 2 * 3);
  });

  it("emits one quad per cell edge", () => {
    const mesh = packDisv(twoSquares());

    // 8 edges total x 4 vertices
    expect(mesh.wallVertices.length / FLOATS_PER_VERTEX).toBe(32);
    expect(mesh.wallIndices.length).toBe(8 * 6);
  });

  it("handles cells with different corner counts", () => {
    const mesh = packDisv(mixedShapes());

    // Square fans to 2 triangles, triangle to 1; both caps
    expect(mesh.capIndices.length).toBe((2 + 1) * 2 * 3);
    // 4 + 3 edges
    expect(mesh.wallIndices.length).toBe(7 * 6);
  });

  it("tags every vertex with the cell it belongs to", () => {
    const mesh = packDisv(twoSquares());
    const cells = new Set<number>();
    for (let i = 0; i < mesh.capVertices.length / FLOATS_PER_VERTEX; i++) {
      cells.add(vertexAt(mesh.capVertices, i).cell);
    }

    expect([...cells].sort()).toEqual([0, 1]);
  });

  it("marks top and bottom faces distinctly", () => {
    const mesh = packDisv(twoSquares());
    const faces = new Set<number>();
    for (let i = 0; i < mesh.capVertices.length / FLOATS_PER_VERTEX; i++) {
      faces.add(vertexAt(mesh.capVertices, i).face);
    }

    expect([...faces].sort()).toEqual([CAP_TOP, CAP_BOTTOM]);
  });

  it("keeps footprint xy on the vertices it packs", () => {
    const mesh = packDisv(twoSquares());
    const first = vertexAt(mesh.capVertices, 0);

    expect([first.x, first.y]).toEqual([0, 0]);
  });

  it("gives each wall quad two top and two bottom corners", () => {
    const mesh = packDisv(twoSquares());

    for (let quad = 0; quad < 8; quad++) {
      const faces = [0, 1, 2, 3].map(
        (corner) => vertexAt(mesh.wallVertices, quad * 4 + corner).face,
      );
      expect(faces).toEqual([CAP_TOP, CAP_TOP, CAP_BOTTOM, CAP_BOTTOM]);
    }
  });

  it("winds the two caps oppositely so neither is culled", () => {
    const mesh = packDisv(twoSquares());
    const signedArea = (indices: Uint32Array, from: number) => {
      const points = [0, 1, 2].map((offset) => vertexAt(mesh.capVertices, indices[from + offset]));
      return (
        (points[1].x - points[0].x) * (points[2].y - points[0].y) -
        (points[2].x - points[0].x) * (points[1].y - points[0].y)
      );
    };

    // First triangle of the top cap against the first of the bottom cap.
    expect(Math.sign(signedArea(mesh.capIndices, 0))).toBe(
      -Math.sign(signedArea(mesh.capIndices, 6)),
    );
  });

  it("never indexes past the vertices it wrote", () => {
    const mesh = packDisv(mixedShapes());
    const capVertexCount = mesh.capVertices.length / FLOATS_PER_VERTEX;
    const wallVertexCount = mesh.wallVertices.length / FLOATS_PER_VERTEX;

    expect(Math.max(...mesh.capIndices)).toBeLessThan(capVertexCount);
    expect(Math.max(...mesh.wallIndices)).toBeLessThan(wallVertexCount);
  });

  it("counts the triangles it produced", () => {
    const mesh = packDisv(twoSquares());

    expect(mesh.triangleCount).toBe(mesh.capIndices.length / 3 + mesh.wallIndices.length / 3);
  });

  it("rejects a degenerate cell rather than emitting broken geometry", () => {
    const broken: Footprint = {
      vertices: new Float32Array([0, 0, 1, 0]),
      cellOffsets: new Int32Array([0, 2]),
      cellIndices: new Int32Array([0, 1]),
    };

    expect(() => packDisv(broken)).toThrow(/at least 3/);
  });

  it("scales linearly with cell count", () => {
    const cells = 5000;
    const vertices = new Float32Array(cells * 8);
    const cellOffsets = new Int32Array(cells + 1);
    const cellIndices = new Int32Array(cells * 4);
    for (let cell = 0; cell < cells; cell++) {
      const x = cell * 2;
      vertices.set([x, 0, x + 1, 0, x + 1, 1, x, 1], cell * 8);
      cellOffsets[cell + 1] = (cell + 1) * 4;
      cellIndices.set([cell * 4, cell * 4 + 1, cell * 4 + 2, cell * 4 + 3], cell * 4);
    }

    const mesh = packDisv({ vertices, cellOffsets, cellIndices });

    expect(mesh.ncpl).toBe(cells);
    expect(mesh.triangleCount).toBe(cells * (2 * 2 + 4 * 2));
  });
});

describe("packDisv edge indices", () => {
  it("emits three line pairs per cell edge", () => {
    const mesh = packDisv(twoSquares());

    // 8 cell edges x 3 lines x 2 endpoints
    expect(mesh.wallEdgeIndices.length).toBe(8 * 6);
  });

  it("indexes only wall vertices it wrote", () => {
    const mesh = packDisv(mixedShapes());
    const wallVertexCount = mesh.wallVertices.length / FLOATS_PER_VERTEX;

    expect(Math.max(...mesh.wallEdgeIndices)).toBeLessThan(wallVertexCount);
  });

  it("outlines each quad along its top, bottom and one vertical", () => {
    const mesh = packDisv(twoSquares());
    const lines: [number, number][] = [];
    for (let i = 0; i < 6; i += 2) {
      lines.push([mesh.wallEdgeIndices[i], mesh.wallEdgeIndices[i + 1]]);
    }

    // Quad corners are [topFrom, topTo, botTo, botFrom].
    expect(lines).toEqual([
      [0, 1], // top
      [3, 2], // bottom
      [0, 3], // vertical
    ]);
  });

  it("never draws a line between a point and itself", () => {
    const mesh = packDisv(mixedShapes());

    for (let i = 0; i < mesh.wallEdgeIndices.length; i += 2) {
      expect(mesh.wallEdgeIndices[i]).not.toBe(mesh.wallEdgeIndices[i + 1]);
    }
  });
});
