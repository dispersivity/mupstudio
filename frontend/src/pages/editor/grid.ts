import type { ProjectDocument } from "./useProjectDocument";

/** How many cells there are along each axis, and in total. */
export interface Limits {
  layers: number;
  rows: number;
  columns: number;
}

/**
 * The grid's shape, worked out from what the document holds.
 *
 * The counts are not stored: an axis is either a cell count with a total
 * length or a list of explicit widths, and a layer may be split into
 * sublayers. Both spellings resolve here, so every screen that needs a cell
 * index limit gets the same answer.
 */
export function gridLimits(grid: ProjectDocument): Limits {
  return {
    layers: (grid.layers as ProjectDocument[]).reduce((total, layer) => total + layer.sublayers, 0),
    rows: grid.rows.widths?.length ?? grid.rows.ncells,
    columns: grid.columns.widths?.length ?? grid.columns.ncells,
  };
}

export function cellCount(grid: ProjectDocument): number {
  const limits = gridLimits(grid);
  return limits.layers * limits.rows * limits.columns;
}
