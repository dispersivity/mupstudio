import { describe, expect, it } from "vitest";
import {
  cellFromPick,
  describeSelection,
  emptySelection,
  formatIndexList,
  localCells,
  parseIndexList,
  toggleCell,
  type CellTriple,
} from "./selection";

describe("cellFromPick", () => {
  it("turns a layer and a cell number into a one-based cell", () => {
    // The viewport numbers cells within a layer, row-major, from zero. The
    // screen counts from one, the way MODFLOW input reads.
    expect(cellFromPick({ layer: 0, cell: 0 }, 10)).toEqual([1, 1, 1]);
    expect(cellFromPick({ layer: 0, cell: 9 }, 10)).toEqual([1, 1, 10]);
    expect(cellFromPick({ layer: 0, cell: 10 }, 10)).toEqual([1, 2, 1]);
    expect(cellFromPick({ layer: 2, cell: 34 }, 10)).toEqual([3, 4, 5]);
  });
});

describe("toggleCell", () => {
  it("adds a cell that is not there", () => {
    expect(toggleCell([], [1, 1, 1])).toEqual([[1, 1, 1]]);
  });

  it("removes a cell that is", () => {
    // Clicking is how a selection is corrected as well as built; a click that
    // only ever adds makes the mistake unfixable without leaving the viewport.
    const cells: CellTriple[] = [
      [1, 1, 1],
      [1, 1, 2],
    ];

    expect(toggleCell(cells, [1, 1, 1])).toEqual([[1, 1, 2]]);
  });

  it("leaves the rest of the selection alone", () => {
    const cells: CellTriple[] = [
      [1, 1, 1],
      [2, 2, 2],
    ];

    expect(toggleCell(cells, [3, 3, 3])).toHaveLength(3);
  });
});

describe("localCells", () => {
  it("expands a range into every combination", () => {
    const cells = localCells({ kind: "cells", layers: [1, 2], rows: [3], columns: [4, 5] });

    expect(cells).toHaveLength(4);
    expect(cells).toContainEqual([2, 3, 5]);
  });

  it("returns a picked list as it is", () => {
    expect(localCells({ kind: "list", indices: [[1, 1, 1]] })).toEqual([[1, 1, 1]]);
  });

  it("cannot answer for a shape, which only the grid can resolve", () => {
    expect(
      localCells({ kind: "shape", source: "river", layers: [1], rule: "intersects", buffer: 0 }),
    ).toBeNull();
  });
});

describe("describeSelection", () => {
  it("counts what it can count", () => {
    expect(describeSelection({ kind: "cells", layers: [1], rows: [1], columns: [1, 2] })).toBe(
      "2 cells",
    );
  });

  it("names the source of a shape rather than guessing a count", () => {
    expect(
      describeSelection({
        kind: "shape",
        source: "river",
        layers: [1],
        rule: "intersects",
        buffer: 0,
      }),
    ).toBe("from river");
  });
});

describe("emptySelection", () => {
  it("keeps the layers when the mode changes", () => {
    // Which layers a boundary is in is a decision independent of how its
    // footprint was chosen, so switching mode should not discard it.
    const previous = { kind: "cells" as const, layers: [2, 3], rows: [1], columns: [1] };

    expect(emptySelection("shape", previous, "river")).toMatchObject({ layers: [2, 3] });
  });

  it("takes the layers out of a picked list", () => {
    const previous = {
      kind: "list" as const,
      indices: [
        [3, 1, 1],
        [1, 1, 1],
      ] as CellTriple[],
    };

    expect(emptySelection("cells", previous, "river")).toMatchObject({ layers: [1, 3] });
  });

  it("starts a shape on the first source, so it is never left empty", () => {
    expect(emptySelection("shape", null, "boundary")).toMatchObject({ source: "boundary" });
  });
});

describe("parseIndexList", () => {
  it("reads a plain list", () => {
    expect(parseIndexList("1, 3, 5", 10)).toEqual([1, 3, 5]);
  });

  it("expands a range, which is how a whole edge gets typed", () => {
    expect(parseIndexList("2-5", 10)).toEqual([2, 3, 4, 5]);
  });

  it("mixes the two", () => {
    expect(parseIndexList("1, 4-6, 9", 10)).toEqual([1, 4, 5, 6, 9]);
  });

  it("drops what the grid does not have rather than saving a bad index", () => {
    expect(parseIndexList("1, 99", 10)).toEqual([1]);
  });

  it("takes a reversed range the way it was meant", () => {
    expect(parseIndexList("5-2", 10)).toEqual([2, 3, 4, 5]);
  });

  it("ignores stray text instead of producing NaN", () => {
    expect(parseIndexList("1, , abc, 2", 10)).toEqual([1, 2]);
  });
});

describe("formatIndexList", () => {
  it("collapses a run so a long edge stays readable", () => {
    expect(formatIndexList([1, 2, 3, 4, 5])).toBe("1-5");
  });

  it("leaves a pair as a pair, which is shorter than a range", () => {
    expect(formatIndexList([7, 8])).toBe("7, 8");
  });

  it("mixes runs and singletons", () => {
    expect(formatIndexList([1, 4, 5, 6, 9])).toBe("1, 4-6, 9");
  });

  it("round-trips through the parser", () => {
    const indices = [1, 2, 3, 7, 11, 12];

    expect(parseIndexList(formatIndexList(indices), 20)).toEqual(indices);
  });
});
