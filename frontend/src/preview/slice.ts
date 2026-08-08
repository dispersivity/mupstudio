import type { DatasetCatalog } from "@/net/viewportClient";

/**
 * Choosing what part of the model to look at.
 *
 * Plan, row and column rather than 3D by default, because the question in a
 * builder is "which cells", and an oblique view of a solid block cannot answer
 * it: the near faces hide the ones behind. One layer from above, or one row
 * from the side, hides nothing. 3D is for shape and extent, which you check
 * once and then stop looking at.
 */

export type ViewMode = "plan" | "row" | "column" | "free";

export interface Slice {
  mode: ViewMode;
  layer: number;
  row: number;
  column: number;
}

/**
 * What a model of this shape should open on.
 *
 * A column benchmark is one row and one layer: plan view of it is a single line
 * of cells seen edge-on, which says nothing. The row section is the model. A
 * layered field model is the other way round.
 */
export function defaultSlice(catalog: DatasetCatalog | null): Slice {
  const rows = catalog?.nrow ?? 0;
  const layers = catalog?.nlay ?? 1;
  const mode: ViewMode = rows === 1 && layers > 0 ? "row" : "plan";
  return { mode, layer: 0, row: 0, column: 0 };
}

/** How many slices there are in the current mode, and what to call one. */
export function sliceExtent(
  slice: Slice,
  catalog: DatasetCatalog | null,
): { count: number; label: string; index: number } | null {
  if (slice.mode === "free") return null;
  if (slice.mode === "plan") {
    return { count: catalog?.nlay ?? 1, label: "Layer", index: slice.layer };
  }
  if (slice.mode === "row") {
    return { count: catalog?.nrow ?? 0, label: "Row", index: slice.row };
  }
  return { count: catalog?.ncol ?? 0, label: "Column", index: slice.column };
}

export function withIndex(slice: Slice, index: number): Slice {
  if (slice.mode === "plan") return { ...slice, layer: index };
  if (slice.mode === "row") return { ...slice, row: index };
  if (slice.mode === "column") return { ...slice, column: index };
  return slice;
}

/**
 * How much to stretch the vertical axis for a given view.
 *
 * An aquifer is thousands of metres across and tens thick, so a section drawn
 * at true scale is a hairline: correct, and useless. Exaggerating the vertical
 * is what every hydrogeological section does, and the factor is chosen here so
 * the section fills its frame rather than being a number to remember.
 *
 * Plan view is left alone. Stretching an axis you are looking straight down is
 * both invisible and, if you then orbit, disorienting.
 */
export function verticalExaggeration(slice: Slice, catalog: DatasetCatalog | null): number {
  if (slice.mode === "plan" || !catalog) return 1;

  const { min, max } = catalog.bounds;
  const across = slice.mode === "column" ? max[1] - min[1] : max[0] - min[0];
  const thickness = max[2] - min[2];
  if (!(across > 0) || !(thickness > 0)) return 1;

  // A section reads best a few times wider than it is tall; much more and the
  // layers are hard to tell apart, much less and it stops looking like a
  // section.
  const target = 4;
  // Capped, because a grid built to cover a catchment before its layers have
  // real elevations is kilometres across and metres thick, and the factor that
  // would fill the frame is in the thousands. A section stretched that far
  // stops describing anything; the slider is still there for anyone who wants
  // it.
  return Math.min(MAX_AUTO_EXAGGERATION, Math.max(1, across / thickness / target));
}

/** As far as the automatic factor will go on its own. */
export const MAX_AUTO_EXAGGERATION = 100;

/** A factor as a person would write it: "12x", "1.5x". */
export function formatExaggeration(factor: number): string {
  return `${factor >= 10 ? Math.round(factor) : Number(factor.toPrecision(2))}x`;
}
