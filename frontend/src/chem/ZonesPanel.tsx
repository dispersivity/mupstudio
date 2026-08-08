import type { Limits } from "@/pages/editor/grid";
import type { DatabaseIndex } from "./database";
import { AddFromDatabase, Chooser, RowButton } from "./pickers";
import { estimateSize, uniqueId } from "./edits";
import { Empty } from "./Empty";
import { CellSelector } from "@/pages/editor/CellSelector";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Chemistry = Record<string, any>;
type Edit = (change: (draft: Chemistry) => void) => void;

/** The assemblage kinds a composition can name, and where each comes from. */
const SLOTS = [
  { field: "solution", list: "solutions", label: "Solution", required: true },
  {
    field: "equilibrium_phases",
    list: "equilibrium_phases",
    label: "Minerals",
    required: false,
  },
  { field: "exchange", list: "exchange", label: "Exchange", required: false },
  { field: "surface", list: "surface", label: "Surface", required: false },
  { field: "kinetics", list: "kinetics", label: "Kinetics", required: false },
  { field: "gas_phase", list: "gas_phases", label: "Gas", required: false },
] as const;

/**
 * Compositions and where they apply.
 *
 * A composition is a named bundle: this water, in contact with these minerals,
 * on this exchanger. ORTi3D packed that tuple into a single integer per cell,
 * which is dense and breaks past nine assemblages. Naming it means a cell is
 * assigned "leachate" rather than 2101, and the name survives inserting an
 * assemblage in the middle of a list.
 */
export function ZonesPanel({
  chemistry,
  limits,
  edit,
  sources = [],
  path = null,
  pickingZone = null,
  onPick = () => {},
}: {
  chemistry: Chemistry;
  limits: Limits;
  edit: Edit;
  /** Imported shapes a zone can be drawn from. */
  sources?: { id: string; name: string; geometry?: string }[];
  path?: string | null;
  /** Index of the zone whose cells clicks are going into, or null. */
  pickingZone?: number | null;
  onPick?: (index: number | null) => void;
}) {
  const compositions = chemistry.compositions ?? [];

  const addComposition = () =>
    edit((draft) => {
      const id = uniqueId(
        "material",
        draft.compositions.map((item: any) => item.id),
      );
      draft.compositions.push({
        id,
        label: "",
        colour: null,
        solution: draft.solutions[0]?.id ?? null,
        equilibrium_phases: null,
        exchange: null,
        surface: null,
        kinetics: null,
        gas_phase: null,
      });
      draft.background ??= id;
    });

  if (compositions.length === 0) {
    return (
      <Empty
        message="No compositions. A composition bundles a water with the solids it touches, and that bundle is what a cell is assigned."
        action="Add a composition"
        onAction={addComposition}
      />
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <div className="mb-2 flex flex-wrap items-center gap-3">
          <RowButton onClick={addComposition} title="Add a composition">
            + composition
          </RowButton>
          <label className="flex items-center gap-2 text-[11px] text-zinc-400">
            Background
            <span className="w-44">
              <Chooser
                label="Background composition"
                value={chemistry.background}
                options={compositions}
                onChange={(value) =>
                  edit((draft) => {
                    draft.background = value;
                  })
                }
              />
            </span>
          </label>
          <span className="text-[10px] text-zinc-600">
            Every cell no zone covers gets the background, so no cell is left without water.
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="text-[11px]">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-zinc-600">
                <th className="pb-1 pr-3 font-medium">Name</th>
                {SLOTS.map((slot) => (
                  <th key={slot.field} className="pb-1 pr-3 font-medium">
                    {slot.label}
                  </th>
                ))}
                <th />
              </tr>
            </thead>
            <tbody>
              {compositions.map((composition: any, row: number) => (
                <tr key={row} className="border-t border-zinc-900">
                  <td className="py-1 pr-3">
                    <input
                      value={composition.id}
                      aria-label={`Name of composition ${row + 1}`}
                      onChange={(event) =>
                        edit((draft) => renameComposition(draft, row, event.target.value))
                      }
                      className="w-32 rounded border border-transparent bg-transparent px-1 py-0.5 font-mono text-[11px] text-zinc-100 hover:border-zinc-700 focus:border-sky-600 focus:outline-none"
                    />
                  </td>
                  {SLOTS.map((slot) => (
                    <td key={slot.field} className="w-36 py-1 pr-3">
                      <Chooser
                        label={`${slot.label} for ${composition.id}`}
                        value={composition[slot.field]}
                        options={chemistry[slot.list] ?? []}
                        allowNone={!slot.required}
                        onChange={(value) =>
                          edit((draft) => {
                            draft.compositions[row][slot.field] = value;
                          })
                        }
                      />
                    </td>
                  ))}
                  <td>
                    {chemistry.background === composition.id ? (
                      <span
                        className="text-[10px] text-zinc-600"
                        title="The background cannot be deleted"
                      >
                        background
                      </span>
                    ) : (
                      <RowButton
                        danger
                        title={`Delete ${composition.id}`}
                        onClick={() =>
                          edit((draft) => {
                            const [removed] = draft.compositions.splice(row, 1);
                            draft.zones = (draft.zones ?? []).filter(
                              (zone: any) => zone.composition !== removed.id,
                            );
                          })
                        }
                      >
                        delete
                      </RowButton>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <ZoneList
        chemistry={chemistry}
        limits={limits}
        edit={edit}
        sources={sources}
        path={path}
        pickingZone={pickingZone}
        onPick={onPick}
      />
    </div>
  );
}

/**
 * Renaming a composition carries everything that points at it.
 *
 * Zones name their composition, and one of them is the background. A rename
 * that left those behind would break the project the moment it was saved, which
 * would make the name feel like an identifier rather than a label.
 */
function renameComposition(draft: Chemistry, row: number, next: string): void {
  const previous = draft.compositions[row].id;
  draft.compositions[row].id = next;
  if (previous === next) return;

  for (const zone of draft.zones ?? []) {
    if (zone.composition === previous) zone.composition = next;
  }
  if (draft.background === previous) draft.background = next;
}

/**
 * Where each composition applies.
 *
 * Cells are named by index because there is no map to paint on yet. Later zones
 * win where they overlap, so a broad material can be corrected by a narrow
 * patch without editing the first one.
 */
function ZoneList({
  chemistry,
  limits,
  edit,
  sources,
  path,
  pickingZone,
  onPick,
}: {
  chemistry: Chemistry;
  limits: Limits;
  edit: Edit;
  sources: { id: string; name: string; geometry?: string }[];
  path: string | null;
  pickingZone: number | null;
  onPick: (index: number | null) => void;
}) {
  const zones = chemistry.zones ?? [];
  const compositions = chemistry.compositions ?? [];

  return (
    <div>
      <h4 className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Zones</h4>
      <p className="mt-1 max-w-xl text-[11px] leading-relaxed text-zinc-600">
        Cells that get something other than the background. Indices count from one, and a later zone
        wins where two overlap.
      </p>

      <div className="mt-2 space-y-2">
        {zones.map((zone: any, row: number) => (
          <div
            key={row}
            className="flex flex-wrap items-end gap-3 rounded border border-zinc-800 p-2"
          >
            <label className="block w-32">
              <span className="mb-1 block text-[10px] text-zinc-500">Zone</span>
              <input
                value={zone.id}
                aria-label={`Name of zone ${row + 1}`}
                onChange={(event) =>
                  edit((draft) => {
                    draft.zones[row].id = event.target.value;
                  })
                }
                className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 font-mono text-[11px] text-zinc-100 focus:border-sky-600 focus:outline-none"
              />
            </label>

            <label className="block w-40">
              <span className="mb-1 block text-[10px] text-zinc-500">Composition</span>
              <Chooser
                label={`Composition for zone ${zone.id}`}
                value={zone.composition}
                options={compositions}
                onChange={(value) =>
                  edit((draft) => {
                    draft.zones[row].composition = value;
                  })
                }
              />
            </label>

            <div className="w-full">
              {/* The same control the flow boundaries and property zones use.
                  Where a water composition applies is the same question as
                  where a conductivity applies, and it had two answers. */}
              <CellSelector
                selection={zone.cells}
                limits={limits}
                sources={sources}
                path={path}
                picking={pickingZone === row}
                onPick={(on) => onPick(on ? row : null)}
                onChange={(selection) =>
                  edit((draft) => {
                    draft.zones[row].cells = selection;
                  })
                }
              />
            </div>

            <div className="ml-auto">
              <RowButton
                danger
                title={`Delete zone ${zone.id}`}
                onClick={() =>
                  edit((draft) => {
                    draft.zones.splice(row, 1);
                  })
                }
              >
                delete
              </RowButton>
            </div>
          </div>
        ))}

        <RowButton
          title="Add a zone"
          onClick={() =>
            edit((draft) => {
              draft.zones.push({
                id: uniqueId(
                  "zone",
                  draft.zones.map((item: any) => item.id),
                ),
                composition: draft.compositions[0]?.id,
                cells: { kind: "cells", layers: [1], rows: [1], columns: [1] },
              });
            })
          }
        >
          + zone
        </RowButton>
      </div>
    </div>
  );
}

// --- Boundary chemistry -----------------------------------------------------

/** Packages that bring water in, and so can bring solute. A drain only removes. */
const SOLUTE_CARRYING = new Set(["well", "chd", "recharge", "riv", "ghb"]);

const PACKAGE_NAME: Record<string, string> = {
  well: "WEL",
  chd: "CHD",
  recharge: "RCH",
  drn: "DRN",
  riv: "RIV",
  ghb: "GHB",
};

/**
 * What water each boundary brings in.
 *
 * Rows come from the Flow step rather than being added here: a boundary that
 * carries solute always needs a chemistry, and one that does not cannot have
 * one. Leaving a row unset means the boundary injects the background water.
 */
export function BoundaryPanel({
  chemistry,
  packages,
  edit,
}: {
  chemistry: Chemistry;
  packages: { id: string; kind: string }[];
  edit: Edit;
}) {
  const carrying = packages.filter((pack) => SOLUTE_CARRYING.has(pack.kind));
  const solutions = chemistry.solutions ?? [];

  if (carrying.length === 0) {
    return (
      <p className="max-w-xl text-[11px] leading-relaxed text-zinc-500">
        No boundary brings water into this model, so there is no inflow chemistry to set. Add a
        well, constant head, recharge, river or general head boundary on the Flow step.
      </p>
    );
  }

  return (
    <div>
      <p className="mb-2 max-w-xl text-[11px] leading-relaxed text-zinc-600">
        Water entering through these boundaries carries the solution chosen here. A boundary left
        unset injects the background composition&rsquo;s water.
      </p>

      <table className="text-[11px]">
        <thead>
          <tr className="text-left text-[10px] uppercase tracking-wider text-zinc-600">
            <th className="pb-1 pr-4 font-medium">Boundary</th>
            <th className="pb-1 pr-4 font-medium">Package</th>
            <th className="pb-1 font-medium">Injects</th>
          </tr>
        </thead>
        <tbody>
          {carrying.map((pack) => (
            <tr key={pack.id} className="border-t border-zinc-900">
              <td className="py-1 pr-4 font-mono text-zinc-200">{pack.id}</td>
              <td className="py-1 pr-4 text-zinc-500">{PACKAGE_NAME[pack.kind] ?? pack.kind}</td>
              <td className="w-52 py-1">
                <Chooser
                  label={`Solution injected by ${pack.id}`}
                  value={chemistry.boundary_solutions?.[pack.id] ?? null}
                  options={solutions}
                  allowNone
                  noneLabel="the background water"
                  onChange={(value) =>
                    edit((draft) => {
                      draft.boundary_solutions ??= {};
                      if (value === null) delete draft.boundary_solutions[pack.id];
                      else draft.boundary_solutions[pack.id] = value;
                    })
                  }
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- Selected output --------------------------------------------------------

const OUTPUT_KINDS = [
  {
    field: "totals",
    label: "Element totals",
    hint: "Dissolved concentration of each element, which is what a breakthrough curve plots.",
    from: (index: DatabaseIndex | null) => [
      ...new Set((index?.elements ?? []).map((group) => group.element)),
    ],
  },
  {
    field: "equilibrium_phases",
    label: "Mineral amounts",
    hint: "Moles present, and how much dissolved or precipitated this step.",
    from: (index: DatabaseIndex | null) => (index?.phases ?? []).map((phase) => phase.name),
  },
  {
    field: "saturation_indices",
    label: "Saturation indices",
    hint: "Whether the water is over or under saturated with a mineral.",
    from: (index: DatabaseIndex | null) => (index?.phases ?? []).map((phase) => phase.name),
  },
  {
    field: "kinetic_reactants",
    label: "Kinetic reactants",
    hint: "Amounts remaining of anything reacting at a rate.",
    from: (index: DatabaseIndex | null) => (index?.rates ?? []).map((rate) => rate.name),
  },
  {
    field: "gases",
    label: "Gases",
    hint: "Partial pressures in the gas phase.",
    from: (index: DatabaseIndex | null) => (index?.gases ?? []).map((gas) => gas.name),
  },
] as const;

/**
 * What PHREEQC is asked to report.
 *
 * This decides what can be looked at afterwards. Anything not selected is not
 * written, and getting it means running the model again — which for a reactive
 * model can be hours, so the cost of forgetting something is real.
 */
export function OutputPanel({
  chemistry,
  index,
  cells,
  times,
  edit,
}: {
  chemistry: Chemistry;
  index: DatabaseIndex | null;
  cells: number;
  times: number;
  edit: Edit;
}) {
  const output = chemistry.selected_output ?? {};
  const count =
    OUTPUT_KINDS.reduce((total, kind) => total + (output[kind.field]?.length ?? 0), 0) +
    (output.ph ? 1 : 0) +
    (output.pe ? 1 : 0);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-4">
        {(["ph", "pe"] as const).map((field) => (
          <label key={field} className="flex items-center gap-2 text-[11px] text-zinc-300">
            <input
              type="checkbox"
              checked={output[field] ?? false}
              onChange={(event) =>
                edit((draft) => {
                  draft.selected_output[field] = event.target.checked;
                })
              }
              className="accent-sky-600"
            />
            {field === "ph" ? "pH" : "pe"}
          </label>
        ))}
        <span className="text-[10px] text-zinc-600">
          {count} column{count === 1 ? "" : "s"} × {cells.toLocaleString()} cells ×{" "}
          {times.toLocaleString()} steps ≈ {estimateSize(count, cells, times)}
        </span>
      </div>

      {count === 0 && (
        <p className="text-[11px] text-amber-300">
          Nothing is selected, so the run would produce no chemistry to look at.
        </p>
      )}

      {OUTPUT_KINDS.map((kind) => (
        <div key={kind.field}>
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            {kind.label}
          </h4>
          <p className="mt-0.5 text-[10px] text-zinc-600">{kind.hint}</p>

          <div className="mt-1.5 flex flex-wrap items-start gap-2">
            <AddFromDatabase
              label={`Report ${kind.label.toLowerCase()}`}
              placeholder="Add…"
              options={kind.from(index)}
              chosen={output[kind.field] ?? []}
              onAdd={(name) =>
                edit((draft) => {
                  draft.selected_output[kind.field] = [
                    ...(draft.selected_output[kind.field] ?? []),
                    name,
                  ];
                })
              }
            />
            <ul className="flex flex-wrap gap-1">
              {(output[kind.field] ?? []).map((name: string) => (
                <li key={name}>
                  <button
                    type="button"
                    title={`Stop reporting ${name}`}
                    onClick={() =>
                      edit((draft) => {
                        draft.selected_output[kind.field] = draft.selected_output[
                          kind.field
                        ].filter((item: string) => item !== name);
                      })
                    }
                    className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[11px] text-zinc-300 hover:bg-red-950 hover:text-red-300"
                  >
                    {name} <span className="text-zinc-600">×</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      ))}
    </div>
  );
}
