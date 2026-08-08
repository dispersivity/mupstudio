import type { ProjectDetail } from "@/net/projectClient";

/**
 * Whether a model can run yet, as a list of facts.
 *
 * Each row states what is there rather than whether a rule passed — "2
 * boundaries · 51 cells", not "boundaries: ok" — because the fact is also the
 * thing worth checking: a model with one boundary where you expected two
 * satisfies a rule and fails a reading.
 */

export interface Check {
  label: string;
  detail: string;
  state: "ok" | "warn" | "blocked";
}

export function prerequisitesFor(
  detail: ProjectDetail,
  written: { files: string[]; components?: string[] } | null,
): Check[] {
  const grid = detail.grid;
  const boundaries = detail.boundaries ?? [];
  const carrying = boundaries.filter((item) => item.kind !== "drn");

  const checks: Check[] = [
    {
      label: "Grid",
      detail: `${grid.ncells.toLocaleString()} cells · ${describeShape(grid)}`,
      state: grid.ncells > 0 ? "ok" : "blocked",
    },
    {
      label: "Time",
      detail: `${detail.time.nper} stress ${detail.time.nper === 1 ? "period" : "periods"} · ${
        detail.time.total
      } ${detail.timeUnit}`,
      state: detail.time.nper > 0 ? "ok" : "blocked",
    },
    {
      label: "Boundaries",
      detail:
        boundaries.length === 0
          ? "none — nothing drives flow, so nothing will move"
          : boundaries.map((item) => item.id).join(", "),
      // Not blocked: a model with no boundaries runs and gives a flat field,
      // which is a legitimate thing to want to look at once.
      state: carrying.length > 0 ? "ok" : "warn",
    },
  ];

  checks.push(chemistryCheck(detail));

  checks.push({
    label: "Input written",
    detail: written
      ? `${written.files.length} files${
          written.components?.length ? ` · ${written.components.length} components` : ""
        }`
      : "not yet — running writes it first",
    state: written ? "ok" : "warn",
  });

  return checks;
}

function chemistryCheck(detail: ProjectDetail): Check {
  const chemistry = detail.chemistry;
  if (!chemistry?.enabled) {
    return {
      label: "Chemistry",
      detail: "off — this run transports a conservative tracer",
      state: "warn",
    };
  }
  if (chemistry.solutions === 0) {
    return { label: "Chemistry", detail: "on, but no solutions defined", state: "blocked" };
  }
  return {
    label: "Chemistry",
    detail: `${chemistry.solutions} solution${chemistry.solutions === 1 ? "" : "s"} · ${
      chemistry.database
    }`,
    state: "ok",
  };
}

function describeShape(grid: ProjectDetail["grid"]): string {
  if (grid.nrow == null || grid.ncol == null) return grid.kind;
  return `${grid.nlay} × ${grid.nrow} × ${grid.ncol}`;
}
