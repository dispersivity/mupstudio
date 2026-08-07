/**
 * The build pipeline, as data.
 *
 * The rail, the routing and the gating all read from this one list, so adding
 * a step or changing what it depends on is a single edit here.
 */

export type StepId =
  | "project"
  | "data"
  | "domain"
  | "grid"
  | "time"
  | "flow"
  | "transport"
  | "chemistry"
  | "simulate"
  | "results";

export type StepStatus = "locked" | "empty" | "partial" | "complete" | "stale" | "error";

export interface Step {
  id: StepId;
  label: string;
  /** One line explaining what this step is for, shown in its empty state. */
  purpose: string;
  /** Steps that must have data before this one is useful. */
  dependsOn: StepId[];
  /** Milestone that builds it, for the not-yet-built notice. */
  milestone: string;
}

export const STEPS: Step[] = [
  {
    id: "project",
    label: "Project",
    purpose: "Name the project, choose its engine and units, and open or create one.",
    dependsOn: [],
    milestone: "M3",
  },
  {
    id: "data",
    label: "Data",
    purpose: "Import shapefiles, GeoJSON, DEM rasters and well CSVs.",
    dependsOn: ["project"],
    milestone: "M4",
  },
  {
    id: "domain",
    label: "Domain",
    purpose: "Draw or import the model boundary.",
    dependsOn: ["project"],
    milestone: "M4",
  },
  {
    id: "grid",
    label: "Grid",
    purpose: "Cell spacing along each axis, and the layers stacked beneath the model top.",
    dependsOn: ["project"],
    milestone: "M4",
  },
  {
    id: "time",
    label: "Time",
    purpose: "Stress periods: how long each lasts and how many steps it is solved in.",
    dependsOn: ["project"],
    milestone: "M4",
  },
  {
    id: "flow",
    label: "Flow",
    purpose: "Hydraulic properties, stress periods and boundary conditions.",
    dependsOn: ["grid"],
    milestone: "M4",
  },
  {
    id: "transport",
    label: "Transport",
    purpose: "Porosity, dispersivity, diffusion and dual porosity.",
    dependsOn: ["grid"],
    milestone: "M4",
  },
  {
    id: "chemistry",
    label: "Chemistry",
    purpose: "PHREEQC database, solutions, assemblages, kinetics and where they apply.",
    dependsOn: ["grid"],
    milestone: "M5",
  },
  {
    id: "simulate",
    label: "Simulate",
    purpose: "Validate the model, inspect the written input files and run the engine.",
    dependsOn: ["flow"],
    milestone: "M2",
  },
  {
    id: "results",
    label: "Results",
    purpose: "Visualise heads, concentrations and mineral amounts through time.",
    dependsOn: [],
    milestone: "M1",
  },
];

export const STEP_BY_ID = new Map(STEPS.map((step) => [step.id, step]));

/** Steps that have something behind them today. The rest say so plainly. */
export const IMPLEMENTED: ReadonlySet<StepId> = new Set<StepId>([
  "project",
  "grid",
  "time",
  "flow",
  "transport",
  "simulate",
  "results",
]);
