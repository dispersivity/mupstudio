/**
 * Packs a DISV footprint into the vertex and index buffers the prism shader draws.
 *
 * Two meshes come out, both describing ONE layer:
 *   - caps: each cell footprint fan-triangulated, emitted twice (top and bottom face)
 *   - walls: one quad per cell edge, spanning that cell's top and bottom
 *
 * The layer dimension is handled by instancing, so these buffers are built once
 * regardless of how many layers the model has. Vertex layout is
 * [x, y, cellInLayer, face] — 16 bytes, and enough for the shader to find both
 * the elevation and the scalar for that vertex.
 *
 * Fan triangulation is valid here because DISV cells are convex: MODFLOW's
 * Voronoi and quadtree grids both produce convex polygons.
 */

export const FLOATS_PER_VERTEX = 4;
export const CAP_TOP = 0;
export const CAP_BOTTOM = 1;

export interface Footprint {
  /** (nverts, 2) xy pairs, flattened. */
  vertices: Float32Array;
  /** (ncpl + 1) CSR offsets into cellIndices. */
  cellOffsets: Int32Array;
  /** Vertex index per cell corner, counter-clockwise. */
  cellIndices: Int32Array;
}

export interface PackedMesh {
  capVertices: Float32Array<ArrayBuffer>;
  capIndices: Uint32Array<ArrayBuffer>;
  wallVertices: Float32Array<ArrayBuffer>;
  wallIndices: Uint32Array<ArrayBuffer>;
  /**
   * Line pairs over the wall vertices outlining each cell.
   *
   * Drawn as lines rather than as a separate mesh so edges reuse the wall
   * vertex buffer and the same extrusion shader, which keeps them correct at
   * any exaggeration for no extra upload.
   */
  wallEdgeIndices: Uint32Array<ArrayBuffer>;
  /** Cells per layer — the stride into the elevation and scalar buffers. */
  ncpl: number;
  triangleCount: number;
}

function cellCornerCount(cellOffsets: Int32Array, cell: number): number {
  return cellOffsets[cell + 1] - cellOffsets[cell];
}

/**
 * Count triangles and vertices up front so the typed arrays are allocated once.
 * Cells may have different corner counts (quadtree grids do), so this cannot be
 * derived from cell count alone.
 */
function measure(footprint: Footprint) {
  const ncpl = footprint.cellOffsets.length - 1;
  let corners = 0;
  let fanTriangles = 0;

  for (let cell = 0; cell < ncpl; cell++) {
    const count = cellCornerCount(footprint.cellOffsets, cell);
    if (count < 3) {
      throw new Error(`cell ${cell} has ${count} corners; need at least 3`);
    }
    corners += count;
    fanTriangles += count - 2;
  }

  return { ncpl, corners, fanTriangles };
}

export function packDisv(footprint: Footprint): PackedMesh {
  const { ncpl, corners, fanTriangles } = measure(footprint);
  const { vertices, cellOffsets, cellIndices } = footprint;

  // Caps: every corner appears once per face. Corners are NOT shared between
  // cells here even though they are shared in the footprint — each copy needs
  // its own cell index so the shader can look up the right elevation.
  const capVertices = new Float32Array(corners * 2 * FLOATS_PER_VERTEX);
  const capIndices = new Uint32Array(fanTriangles * 2 * 3);

  // Walls: one quad per edge, four vertices each, no sharing between edges.
  const wallVertices = new Float32Array(corners * 4 * FLOATS_PER_VERTEX);
  const wallIndices = new Uint32Array(corners * 6);
  // Three edges per quad: its top, its bottom, and one vertical. The other
  // vertical belongs to the neighbouring edge, so outlines close up without
  // drawing anything twice.
  const wallEdgeIndices = new Uint32Array(corners * 6);

  let capVertexCursor = 0;
  let capIndexCursor = 0;
  let wallVertexCursor = 0;
  let wallIndexCursor = 0;
  let wallEdgeCursor = 0;

  const writeVertex = (
    target: Float32Array,
    cursor: number,
    vertexIndex: number,
    cell: number,
    face: number,
  ) => {
    target[cursor] = vertices[vertexIndex * 2];
    target[cursor + 1] = vertices[vertexIndex * 2 + 1];
    target[cursor + 2] = cell;
    target[cursor + 3] = face;
  };

  for (let cell = 0; cell < ncpl; cell++) {
    const start = cellOffsets[cell];
    const count = cellCornerCount(cellOffsets, cell);

    for (const face of [CAP_TOP, CAP_BOTTOM]) {
      const base = capVertexCursor / FLOATS_PER_VERTEX;

      for (let corner = 0; corner < count; corner++) {
        writeVertex(capVertices, capVertexCursor, cellIndices[start + corner], cell, face);
        capVertexCursor += FLOATS_PER_VERTEX;
      }

      // Fan from corner 0. Bottom faces wind the opposite way so both caps
      // front-face outward and back-face culling keeps them both.
      for (let triangle = 0; triangle < count - 2; triangle++) {
        if (face === CAP_TOP) {
          capIndices[capIndexCursor++] = base;
          capIndices[capIndexCursor++] = base + triangle + 1;
          capIndices[capIndexCursor++] = base + triangle + 2;
        } else {
          capIndices[capIndexCursor++] = base;
          capIndices[capIndexCursor++] = base + triangle + 2;
          capIndices[capIndexCursor++] = base + triangle + 1;
        }
      }
    }

    for (let corner = 0; corner < count; corner++) {
      const from = cellIndices[start + corner];
      const to = cellIndices[start + ((corner + 1) % count)];
      const base = wallVertexCursor / FLOATS_PER_VERTEX;

      writeVertex(wallVertices, wallVertexCursor, from, cell, CAP_TOP);
      wallVertexCursor += FLOATS_PER_VERTEX;
      writeVertex(wallVertices, wallVertexCursor, to, cell, CAP_TOP);
      wallVertexCursor += FLOATS_PER_VERTEX;
      writeVertex(wallVertices, wallVertexCursor, to, cell, CAP_BOTTOM);
      wallVertexCursor += FLOATS_PER_VERTEX;
      writeVertex(wallVertices, wallVertexCursor, from, cell, CAP_BOTTOM);
      wallVertexCursor += FLOATS_PER_VERTEX;

      wallIndices[wallIndexCursor++] = base;
      wallIndices[wallIndexCursor++] = base + 1;
      wallIndices[wallIndexCursor++] = base + 2;
      wallIndices[wallIndexCursor++] = base;
      wallIndices[wallIndexCursor++] = base + 2;
      wallIndices[wallIndexCursor++] = base + 3;

      // Quad corners are [topFrom, topTo, botTo, botFrom].
      wallEdgeIndices[wallEdgeCursor++] = base; // top edge
      wallEdgeIndices[wallEdgeCursor++] = base + 1;
      wallEdgeIndices[wallEdgeCursor++] = base + 3; // bottom edge
      wallEdgeIndices[wallEdgeCursor++] = base + 2;
      wallEdgeIndices[wallEdgeCursor++] = base; // vertical at the start corner
      wallEdgeIndices[wallEdgeCursor++] = base + 3;
    }
  }

  return {
    capVertices,
    capIndices,
    wallVertices,
    wallIndices,
    wallEdgeIndices,
    ncpl,
    triangleCount: fanTriangles * 2 + corners * 2,
  };
}
