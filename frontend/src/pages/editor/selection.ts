/**
 * Which cells something applies to, in the browser.
 *
 * Mirrors the schema's three ways of naming cells. The distinction that matters
 * for the screen is that the first two are lists of numbers the user owns, and
 * the third is a question the server answers — so a shape selection cannot be
 * counted or drawn without asking, and the other two can.
 */

export type CellTriple = [number, number, number];

export interface CellRange {
  kind: "cells";
  layers: number[];
  rows: number[];
  columns: number[];
}

export interface CellList {
  kind: "list";
  indices: CellTriple[];
}

export interface ShapeSelection {
  kind: "shape";
  source: string;
  layers: number[];
  rule: "intersects" | "centroid";
  buffer: number;
}

export type CellSelection = CellRange | CellList | ShapeSelection;

export const SELECTION_MODES = [
  {
    kind: "cells" as const,
    label: "Range",
    hint: "Layers, rows and columns by number. Every combination of them is taken, so 2 layers and 3 rows is 6 cells.",
  },
  {
    kind: "list" as const,
    label: "Picked",
    hint: "Cells clicked in the viewport. Use this for anything that is not a block: a diagonal, a scatter of wells, an edge with a notch in it.",
  },
  {
    kind: "shape" as const,
    label: "From data",
    hint: "Cells under an imported shape. This is the only one that stays right after the grid is rebuilt, because the shape is kept and the cells are worked out again.",
  },
];

/** A one-based cell, from what the viewport's picker returns. */
export function cellFromPick(picked: { layer: number; cell: number }, columns: number): CellTriple {
  return [picked.layer + 1, Math.floor(picked.cell / columns) + 1, (picked.cell % columns) + 1];
}

export function sameCell(a: CellTriple, b: CellTriple): boolean {
  return a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
}

/**
 * Add a cell, or remove it if it is already there.
 *
 * Clicking is how a selection is both built and corrected, and a click that
 * only ever adds makes the mistake unfixable without leaving the viewport.
 */
export function toggleCell(indices: CellTriple[], cell: CellTriple): CellTriple[] {
  const without = indices.filter((item) => !sameCell(item, cell));
  return without.length === indices.length ? [...indices, cell] : without;
}

/** The cells a selection names, where that can be known without the server. */
export function localCells(selection: CellSelection | null): CellTriple[] | null {
  if (!selection) return null;
  if (selection.kind === "list") return selection.indices;
  if (selection.kind === "cells") {
    const out: CellTriple[] = [];
    for (const layer of selection.layers) {
      for (const row of selection.rows) {
        for (const column of selection.columns) out.push([layer, row, column]);
      }
    }
    return out;
  }
  // A shape has to be resolved against the grid, which only the server can do.
  return null;
}

export function describeSelection(selection: CellSelection | null): string {
  const cells = localCells(selection);
  if (cells) return `${cells.length} cell${cells.length === 1 ? "" : "s"}`;
  if (selection?.kind === "shape") return `from ${selection.source}`;
  return "everywhere";
}

/** An empty selection of a given kind, keeping what carries across. */
export function emptySelection(
  kind: CellSelection["kind"],
  previous: CellSelection | null,
  firstSource: string,
): CellSelection {
  // Layers survive a mode change because "which layers is this in" is a
  // decision independent of how the footprint was chosen, and retyping it
  // every time the mode is switched is pure friction.
  const layers = previous
    ? previous.kind === "list"
      ? [...new Set(previous.indices.map((cell) => cell[0]))].sort((a, b) => a - b)
      : previous.layers
    : [1];

  if (kind === "cells") return { kind: "cells", layers, rows: [1], columns: [1] };
  if (kind === "list") return { kind: "list", indices: [] };
  return { kind: "shape", source: firstSource, layers, rule: "intersects", buffer: 0 };
}

/** Parse "1, 3, 5-8" into [1, 3, 5, 6, 7, 8]. */
export function parseIndexList(text: string, limit: number): number[] {
  const found = new Set<number>();

  for (const part of text.split(",")) {
    const trimmed = part.trim();
    if (!trimmed) continue;

    // A range is how anyone writes "the whole west edge" without typing
    // ninety numbers, and it is what every other modelling tool accepts.
    const range = /^(\d+)\s*-\s*(\d+)$/.exec(trimmed);
    if (range) {
      const [from, to] = [Number(range[1]), Number(range[2])];
      for (let index = Math.min(from, to); index <= Math.max(from, to); index++) {
        if (index >= 1 && index <= limit) found.add(index);
      }
      continue;
    }

    const value = Math.round(Number(trimmed));
    if (Number.isFinite(value) && value >= 1 && value <= limit) found.add(value);
  }

  return [...found].sort((a, b) => a - b);
}

/** The inverse, collapsing runs back into ranges so the field stays readable. */
export function formatIndexList(indices: number[]): string {
  if (indices.length === 0) return "";
  const sorted = [...indices].sort((a, b) => a - b);
  const parts: string[] = [];

  let start = sorted[0];
  let previous = sorted[0];

  const flush = () => {
    if (start === previous) parts.push(String(start));
    else if (previous === start + 1) parts.push(`${start}, ${previous}`);
    else parts.push(`${start}-${previous}`);
  };

  for (const value of sorted.slice(1)) {
    if (value === previous + 1) {
      previous = value;
      continue;
    }
    flush();
    start = previous = value;
  }
  flush();

  return parts.join(", ");
}
