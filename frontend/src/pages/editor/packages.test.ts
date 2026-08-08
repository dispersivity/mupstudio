import { describe, expect, it } from "vitest";
import { BOUNDARY_PACKAGES, flowPackages, PACKAGE_FOR_KIND, transportPackages } from "./packages";

/**
 * The two engines are different stacks, not two spellings of one. Showing MF6
 * package names on a PHT3D project would be a lie about what gets written, and
 * the acronyms are exactly what someone reads in a listing file when chasing an
 * error.
 */
describe("flowPackages", () => {
  it("gives MODFLOW 6 its own packages", () => {
    expect(flowPackages("mf6rtm").map((item) => item.id)).toEqual(["NPF", "IC", "STO", "IMS"]);
  });

  it("gives PHT3D the MODFLOW-2005 stack", () => {
    // LPF is 2005's NPF and STO together; there is no IMS, only PCG.
    expect(flowPackages("pht3d").map((item) => item.id)).toEqual(["LPF", "BAS", "PCG"]);
  });

  it("falls back rather than showing an empty screen for an unknown engine", () => {
    expect(flowPackages("something-else")).toEqual(flowPackages("mf6rtm"));
  });
});

describe("transportPackages", () => {
  it("gives MODFLOW 6 its GWT packages", () => {
    expect(transportPackages("mf6rtm").map((item) => item.id)).toEqual([
      "MST",
      "ADV",
      "DSP",
      "SSM",
    ]);
  });

  it("gives PHT3D the MT3DMS packages", () => {
    expect(transportPackages("pht3d").map((item) => item.id)).toEqual([
      "BTN",
      "ADV",
      "DSP",
      "SSM",
      "GCG",
    ]);
  });

  it("shares the packages the two stacks genuinely have in common", () => {
    const shared = ["ADV", "DSP", "SSM"];
    for (const id of shared) {
      expect(transportPackages("mf6rtm").some((item) => item.id === id)).toBe(true);
      expect(transportPackages("pht3d").some((item) => item.id === id)).toBe(true);
    }
  });
});

describe("boundary packages", () => {
  it("covers every boundary kind the schema can hold", () => {
    const named = new Set(Object.values(PACKAGE_FOR_KIND));
    for (const item of BOUNDARY_PACKAGES) {
      expect(named.has(item.id)).toBe(true);
    }
    expect(named.size).toBe(BOUNDARY_PACKAGES.length);
  });

  it("maps each kind to the package it is written into", () => {
    expect(PACKAGE_FOR_KIND.well).toBe("WEL");
    expect(PACKAGE_FOR_KIND.recharge).toBe("RCH");
    expect(PACKAGE_FOR_KIND.chd).toBe("CHD");
  });
});

describe("every tab", () => {
  it("says what it is and what it decides, since the acronym alone does not", () => {
    const all = [
      ...flowPackages("mf6rtm"),
      ...flowPackages("pht3d"),
      ...transportPackages("mf6rtm"),
      ...transportPackages("pht3d"),
      ...BOUNDARY_PACKAGES,
    ];

    for (const tab of all) {
      expect(tab.label.length).toBeGreaterThan(2);
      expect(tab.purpose.endsWith(".")).toBe(true);
    }
  });

  it("uses the acronym as the id, which is what the file is called", () => {
    for (const tab of [...flowPackages("mf6rtm"), ...BOUNDARY_PACKAGES]) {
      expect(tab.id).toBe(tab.id.toUpperCase());
    }
  });
});
