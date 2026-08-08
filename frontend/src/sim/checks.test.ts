import { describe, expect, it } from "vitest";
import type { ProjectDetail } from "@/net/projectClient";
import { prerequisitesFor } from "./checks";

function detail(over: Partial<ProjectDetail> = {}): ProjectDetail {
  return {
    name: "column",
    engine: "mf6rtm",
    description: "",
    summary: "",
    lengthUnit: "meters",
    timeUnit: "days",
    grid: { kind: "structured", nlay: 1, nrow: 1, ncol: 50, ncells: 50 },
    time: { nper: 1, total: 0.24, periods: [{ perlen: 0.24, nstp: 24 }] },
    boundaries: [
      { id: "inflow", kind: "well" },
      { id: "outflow", kind: "chd" },
    ],
    transport: { advection: "tvd", dispersion: true, dualPorosity: false },
    chemistry: { enabled: true, database: "phreeqc.dat", solutions: 2, compositions: 1 },
    ...over,
  };
}

function find(checks: ReturnType<typeof prerequisitesFor>, label: string) {
  const check = checks.find((item) => item.label === label);
  if (!check) throw new Error(`no check called ${label}`);
  return check;
}

describe("prerequisitesFor", () => {
  it("passes a model that is ready", () => {
    const checks = prerequisitesFor(detail(), { files: ["a.dis"], components: ["Ca", "Cl"] });

    expect(checks.filter((check) => check.state === "blocked")).toEqual([]);
  });

  it("states the fact rather than the verdict", () => {
    // "900 cells · 3 × 15 × 20" is checkable; "grid: ok" is not.
    const checks = prerequisitesFor(
      detail({ grid: { kind: "structured", nlay: 3, nrow: 15, ncol: 20, ncells: 900 } }),
      null,
    );

    expect(find(checks, "Grid").detail).toBe("900 cells · 3 × 15 × 20");
  });

  it("blocks a grid with no cells in it", () => {
    const checks = prerequisitesFor(
      detail({ grid: { kind: "structured", nlay: 0, nrow: 0, ncol: 0, ncells: 0 } }),
      null,
    );

    expect(find(checks, "Grid").state).toBe("blocked");
  });

  it("warns rather than blocks when nothing drives flow", () => {
    // A model with no boundaries runs and gives a flat field, which is a
    // legitimate thing to look at once. It is just rarely what was meant.
    const checks = prerequisitesFor(detail({ boundaries: [] }), null);
    const boundaries = find(checks, "Boundaries");

    expect(boundaries.state).toBe("warn");
    expect(boundaries.detail).toContain("nothing will move");
  });

  it("does not count a drain as something that drives flow", () => {
    // A drain only removes water; a model with nothing but drains never fills.
    const checks = prerequisitesFor(detail({ boundaries: [{ id: "ditch", kind: "drn" }] }), null);

    expect(find(checks, "Boundaries").state).toBe("warn");
  });

  it("says when a run will be conservative rather than reactive", () => {
    const checks = prerequisitesFor(
      detail({
        chemistry: { enabled: false, database: "phreeqc.dat", solutions: 0, compositions: 0 },
      }),
      null,
    );
    const chemistry = find(checks, "Chemistry");

    expect(chemistry.state).toBe("warn");
    expect(chemistry.detail).toContain("conservative tracer");
  });

  it("blocks chemistry that is on with nothing in it", () => {
    const checks = prerequisitesFor(
      detail({
        chemistry: { enabled: true, database: "phreeqc.dat", solutions: 0, compositions: 0 },
      }),
      null,
    );

    expect(find(checks, "Chemistry").state).toBe("blocked");
  });

  it("names the database, since which one decides what the names mean", () => {
    const checks = prerequisitesFor(
      detail({
        chemistry: { enabled: true, database: "pht3d_datab.dat", solutions: 3, compositions: 1 },
      }),
      null,
    );

    expect(find(checks, "Chemistry").detail).toBe("3 solutions · pht3d_datab.dat");
  });

  it("says the input is written and how much of it", () => {
    const checks = prerequisitesFor(detail(), {
      files: ["a", "b", "c"],
      components: ["Ca", "Cl", "pH"],
    });

    expect(find(checks, "Input written").detail).toBe("3 files · 3 components");
  });

  it("does not treat an unwritten model as a blocker", () => {
    // Running writes it first, so this is a statement of where you are rather
    // than something to go and do.
    const checks = prerequisitesFor(detail(), null);
    const written = find(checks, "Input written");

    expect(written.state).toBe("warn");
    expect(written.detail).toContain("running writes it first");
  });

  it("copes with a project whose detail predates chemistry reporting", () => {
    const checks = prerequisitesFor(detail({ chemistry: undefined }), null);

    expect(find(checks, "Chemistry").state).toBe("warn");
  });

  it("describes a vertex grid by its kind, having no rows or columns", () => {
    const checks = prerequisitesFor(
      detail({ grid: { kind: "voronoi", nlay: 2, nrow: null, ncol: null, ncells: 6332 } }),
      null,
    );

    expect(find(checks, "Grid").detail).toBe("6,332 cells · voronoi");
  });
});
