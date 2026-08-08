import { describe, expect, it } from "vitest";
import type { DatasetCatalog } from "@/net/viewportClient";
import {
  defaultSlice,
  formatExaggeration,
  sliceExtent,
  verticalExaggeration,
  withIndex,
  type Slice,
} from "./slice";

function catalog(over: Partial<DatasetCatalog> = {}): DatasetCatalog {
  return {
    dataset: "preview",
    gridHash: "x",
    ncpl: 300,
    nlay: 3,
    ncells: 900,
    nverts: 400,
    bounds: { min: [0, 0, -20], max: [2000, 1500, 50] },
    times: [0],
    components: [],
    nrow: 15,
    ncol: 20,
    ...over,
  };
}

const PLAN: Slice = { mode: "plan", layer: 0, row: 0, column: 0 };

describe("defaultSlice", () => {
  it("opens a layered model in plan", () => {
    expect(defaultSlice(catalog()).mode).toBe("plan");
  });

  it("opens a single-row model on a section", () => {
    // A column benchmark seen in plan is one line of cells edge-on, which
    // shows nothing. The section is the model.
    expect(defaultSlice(catalog({ nrow: 1, nlay: 1 })).mode).toBe("row");
  });

  it("starts at the first slice", () => {
    expect(defaultSlice(catalog())).toMatchObject({ layer: 0, row: 0, column: 0 });
  });

  it("falls back to plan when the grid shape is unknown", () => {
    expect(defaultSlice(null).mode).toBe("plan");
  });
});

describe("sliceExtent", () => {
  it("counts layers in plan", () => {
    expect(sliceExtent(PLAN, catalog())).toEqual({ count: 3, label: "Layer", index: 0 });
  });

  it("counts rows and columns in the section views", () => {
    expect(sliceExtent({ ...PLAN, mode: "row", row: 4 }, catalog())).toEqual({
      count: 15,
      label: "Row",
      index: 4,
    });
    expect(sliceExtent({ ...PLAN, mode: "column", column: 2 }, catalog())).toEqual({
      count: 20,
      label: "Column",
      index: 2,
    });
  });

  it("has nothing to step through in 3D", () => {
    expect(sliceExtent({ ...PLAN, mode: "free" }, catalog())).toBeNull();
  });
});

describe("withIndex", () => {
  it("moves only the index the current mode uses", () => {
    const slice: Slice = { mode: "row", layer: 1, row: 2, column: 3 };
    expect(withIndex(slice, 9)).toEqual({ mode: "row", layer: 1, row: 9, column: 3 });
  });

  it("keeps each mode's position, so switching back returns to it", () => {
    let slice: Slice = { mode: "plan", layer: 0, row: 0, column: 0 };
    slice = withIndex(slice, 2);
    slice = withIndex({ ...slice, mode: "column" }, 7);

    expect(slice).toMatchObject({ layer: 2, column: 7 });
  });

  it("leaves 3D alone", () => {
    const slice: Slice = { mode: "free", layer: 1, row: 1, column: 1 };
    expect(withIndex(slice, 5)).toEqual(slice);
  });
});

describe("verticalExaggeration", () => {
  it("leaves plan view at true scale", () => {
    // Stretching an axis you are looking straight down does nothing visible
    // and makes orbiting away from it disorienting.
    expect(verticalExaggeration(PLAN, catalog())).toBe(1);
  });

  it("stretches a wide, thin section until it can be read", () => {
    // 2000 m across and 70 m thick draws as a hairline at true scale.
    const factor = verticalExaggeration({ ...PLAN, mode: "row" }, catalog());

    expect(factor).toBeGreaterThan(5);
    expect(factor).toBeLessThan(10);
  });

  it("measures a column section across the other axis", () => {
    const factor = verticalExaggeration({ ...PLAN, mode: "column" }, catalog());

    // 1500 m across rather than 2000, so less stretch is needed.
    expect(factor).toBeLessThan(verticalExaggeration({ ...PLAN, mode: "row" }, catalog()));
  });

  it("never squashes a model that is already tall enough", () => {
    const deep = catalog({ bounds: { min: [0, 0, -500], max: [100, 100, 0] } });

    expect(verticalExaggeration({ ...PLAN, mode: "row" }, deep)).toBe(1);
  });

  it("does not divide by a zero thickness", () => {
    const flat = catalog({ bounds: { min: [0, 0, 0], max: [100, 100, 0] } });

    expect(verticalExaggeration({ ...PLAN, mode: "row" }, flat)).toBe(1);
  });

  it("has nothing to measure without a catalog", () => {
    expect(verticalExaggeration({ ...PLAN, mode: "row" }, null)).toBe(1);
  });

  it("stops short of a factor that would stop meaning anything", () => {
    // A grid built to cover a catchment before its layers have real elevations
    // is kilometres across and a metre thick. Filling the frame would need
    // thousands, and a section stretched that far describes nothing.
    const flat = catalog({ bounds: { min: [0, 0, -1], max: [24000, 20000, 0] } });

    expect(verticalExaggeration({ ...PLAN, mode: "row" }, flat)).toBe(100);
  });
});

describe("formatExaggeration", () => {
  it("rounds a large factor to a whole number", () => {
    expect(formatExaggeration(28.4)).toBe("28x");
  });

  it("keeps the detail in a small one", () => {
    expect(formatExaggeration(1.5)).toBe("1.5x");
  });
});
