import { describe, expect, it } from "vitest";
import { estimateSize, format, parseIndices, uniqueId } from "./edits";

describe("parseIndices", () => {
  it("reads a list", () => {
    expect(parseIndices("1, 3, 7")).toEqual([1, 3, 7]);
  });

  it("expands a range, because cells come in runs", () => {
    expect(parseIndices("5-9")).toEqual([5, 6, 7, 8, 9]);
  });

  it("mixes both", () => {
    expect(parseIndices("1, 4-6, 10")).toEqual([1, 4, 5, 6, 10]);
  });

  it("accepts a range written backwards", () => {
    expect(parseIndices("9-5")).toEqual([5, 6, 7, 8, 9]);
  });

  it("drops duplicates so overlapping ranges are harmless", () => {
    expect(parseIndices("1-3, 2-4")).toEqual([1, 2, 3, 4]);
  });

  it("sorts, so the order typed does not matter", () => {
    expect(parseIndices("9, 2, 5")).toEqual([2, 5, 9]);
  });

  it("ignores whitespace and empty entries", () => {
    expect(parseIndices(" 1 ,, 2 , ")).toEqual([1, 2]);
  });

  it("drops zero and negatives, because indices count from one", () => {
    expect(parseIndices("0, -3, 2")).toEqual([2]);
  });

  it("drops anything that is not a number rather than guessing", () => {
    expect(parseIndices("1, all, 3")).toEqual([1, 3]);
  });

  it("returns nothing for an empty string", () => {
    expect(parseIndices("")).toEqual([]);
  });
});

describe("uniqueId", () => {
  it("keeps the name when it is free", () => {
    expect(uniqueId("water", ["other"])).toBe("water");
  });

  it("suffixes when taken", () => {
    expect(uniqueId("water", ["water"])).toBe("water_2");
  });

  it("keeps counting past the first collision", () => {
    expect(uniqueId("water", ["water", "water_2", "water_3"])).toBe("water_4");
  });
});

describe("format", () => {
  it("keeps a plain number plain", () => {
    expect(format(0.32)).toBe("0.32");
  });

  it("uses scientific notation where a decimal would be unreadable", () => {
    // The concentrations in a real analysis live here.
    expect(format(1.23e-4)).toBe("1.23e-4");
  });

  it("shows zero as zero rather than 0.000e+0", () => {
    expect(format(0)).toBe("0");
  });

  it.each([1.234567e-7, 1.220625e-4, 0.32, 9.91, 3.42e5, 6.022e23])(
    "round trips %s exactly, because the text is what gets committed back",
    (value) => {
      expect(Number(format(value))).toBe(value);
    },
  );

  it("has nothing to show for a non-number", () => {
    expect(format(NaN)).toBe("");
  });
});

describe("estimateSize", () => {
  it("reports small output in kilobytes", () => {
    expect(estimateSize(8, 50, 24)).toBe("77 kB");
  });

  it("warns in gigabytes when the selection is expensive", () => {
    // 23 variables over half a million cells for forty steps: the case the
    // readout exists to make visible before the run rather than after.
    expect(estimateSize(23, 482_000, 40)).toBe("3.5 GB");
  });
});
