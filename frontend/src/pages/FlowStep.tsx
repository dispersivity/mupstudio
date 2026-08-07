import { useState } from "react";
import {
  EditorShell,
  Labelled,
  NoProject,
  NumberInput,
  Section,
  Select,
  TextInput,
} from "./editor/controls";
import { gridLimits, type Limits } from "./editor/grid";
import { useProjectDocument, type ProjectDocument } from "./editor/useProjectDocument";

const PROPERTIES: { key: string; label: string; hint: string }[] = [
  { key: "k", label: "Horizontal conductivity", hint: "K along the rows and columns" },
  { key: "porosity", label: "Porosity", hint: "Used for flow storage and, by default, transport" },
  { key: "specific_storage", label: "Specific storage", hint: "Only matters in transient periods" },
  { key: "specific_yield", label: "Specific yield", hint: "Only used where cells can dewater" },
  { key: "starting_head", label: "Starting head", hint: "The initial condition for flow" },
];

/**
 * Boundary packages, named the way MODFLOW names them.
 *
 * The acronym is the primary label because that is what a modeller reads in a
 * name file and a listing file; the description is the secondary hint.
 */
const PACKAGES = [
  { kind: "well", name: "WEL", description: "Injection or extraction at cells" },
  { kind: "chd", name: "CHD", description: "Head held constant" },
  { kind: "recharge", name: "RCH", description: "Areal inflow at the top" },
  { kind: "drn", name: "DRN", description: "Drains water above an elevation" },
  { kind: "riv", name: "RIV", description: "Exchange through a streambed" },
  { kind: "ghb", name: "GHB", description: "Head boundary through a conductance" },
] as const;

const PACKAGE_NAME: Record<string, string> = Object.fromEntries(
  PACKAGES.map((item) => [item.kind, item.name]),
);

/** The values each package holds, in the order MODFLOW reads them. */
const PACKAGE_FIELDS: Record<string, { field: string; label: string; hint: string }[]> = {
  well: [{ field: "rate", label: "Rate", hint: "Positive injects, negative extracts." }],
  chd: [{ field: "head", label: "Head", hint: "The head this boundary holds." }],
  recharge: [{ field: "rate", label: "Rate", hint: "Per unit area." }],
  drn: [
    { field: "elevation", label: "Drain elevation", hint: "Water leaves above this." },
    { field: "conductance", label: "Conductance", hint: "Of the drain material." },
  ],
  riv: [
    { field: "stage", label: "River stage", hint: "Water surface elevation." },
    { field: "conductance", label: "Conductance", hint: "Of the streambed." },
    { field: "bottom", label: "Streambed bottom", hint: "Below the stage." },
  ],
  ghb: [
    { field: "head", label: "Boundary head", hint: "The head some distance away." },
    { field: "conductance", label: "Conductance", hint: "Of the path to it." },
  ],
};

/** Packages that can bring water in, and so can bring solute. DRN only removes. */
const SOLUTE_CARRYING = new Set(["well", "chd", "recharge", "riv", "ghb"]);

/**
 * Aquifer properties and boundary conditions.
 *
 * Cells are named by index because there is no map to draw on yet. Indices
 * count from one, matching how MODFLOW input reads, so a listing file can be
 * checked against this screen directly.
 */
export function FlowStep({
  path,
  onGoToProject,
  onSaved,
}: {
  path: string | null;
  onGoToProject: () => void;
  onSaved: () => void;
}) {
  const editor = useProjectDocument(path);
  const [expanded, setExpanded] = useState<string | null>(null);

  if (!path) return <NoProject onGo={onGoToProject} />;
  if (!editor.document) return <div className="p-6 text-xs text-zinc-500">Loading…</div>;

  const flow = editor.document.flow;
  const grid = editor.document.grid;
  const nper = (editor.document.time.periods as unknown[]).length;
  const limits = gridLimits(grid);

  return (
    <EditorShell
      title="Flow"
      blurb="What the aquifer is made of, and where water enters and leaves. A model with no boundaries has no flow, so nothing moves."
      dirty={editor.dirty}
      saving={editor.saving}
      problems={editor.problems}
      error={editor.error}
      savedSummary={editor.savedSummary}
      onSave={async () => {
        if (await editor.save()) onSaved();
      }}
      onRevert={() => void editor.reload()}
    >
      <Section
        title="Properties"
        hint="One value everywhere for now. Values per zone arrive with the map-based builder."
      >
        <div className="grid max-w-2xl grid-cols-2 gap-x-8 gap-y-3">
          {PROPERTIES.map((property) => (
            <Labelled key={property.key} label={property.label} hint={property.hint}>
              <NumberInput
                value={flow.properties[property.key]?.value ?? 0}
                label={property.label}
                onCommit={(value) =>
                  editor.edit((draft) => {
                    draft.flow.properties[property.key] = { kind: "constant", value };
                  })
                }
              />
            </Labelled>
          ))}
          <Labelled
            label="Vertical conductivity"
            hint="Blank follows the horizontal value, which is what MODFLOW assumes."
          >
            <div className="flex items-center gap-2">
              <NumberInput
                value={flow.properties.k33?.value ?? flow.properties.k?.value ?? 0}
                disabled={flow.properties.k33 === null}
                label="Vertical conductivity"
                onCommit={(value) =>
                  editor.edit((draft) => {
                    draft.flow.properties.k33 = { kind: "constant", value };
                  })
                }
              />
              <label className="flex items-center gap-1 text-[10px] text-zinc-500">
                <input
                  type="checkbox"
                  checked={flow.properties.k33 === null}
                  onChange={(event) =>
                    editor.edit((draft) => {
                      draft.flow.properties.k33 = event.target.checked
                        ? null
                        : { kind: "constant", value: draft.flow.properties.k.value };
                    })
                  }
                />
                follow K
              </label>
            </div>
          </Labelled>
          <Labelled
            label="Cell type"
            hint="Confined is the usual choice for a column; convertible lets cells dewater."
          >
            <Select
              value={String(flow.properties.icelltype)}
              label="Cell type"
              options={[
                { value: "0", label: "Confined" },
                { value: "1", label: "Convertible" },
              ]}
              onChange={(value) =>
                editor.edit((draft) => void (draft.flow.properties.icelltype = Number(value)))
              }
            />
          </Labelled>
        </div>
      </Section>

      <Section
        title={`Boundaries (${(flow.packages as unknown[]).length})`}
        hint={`Cells are named by index, counting from one. This grid has ${limits.layers} layer${
          limits.layers === 1 ? "" : "s"
        }, ${limits.rows} row${limits.rows === 1 ? "" : "s"} and ${limits.columns} column${
          limits.columns === 1 ? "" : "s"
        }.`}
      >
        {(flow.packages as ProjectDocument[]).length === 0 && (
          <p className="mb-2 text-[11px] text-amber-300">
            No boundaries: this model will run but nothing will flow.
          </p>
        )}

        <ul className="max-w-3xl space-y-2">
          {(flow.packages as ProjectDocument[]).map((item, index) => (
            <li key={index} className="rounded border border-zinc-800">
              <div className="flex items-center gap-3 px-3 py-2">
                <button
                  type="button"
                  onClick={() => setExpanded(expanded === item.id ? null : item.id)}
                  className="flex-1 text-left"
                >
                  <span className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[10px] text-sky-300">
                    {PACKAGE_NAME[item.kind] ?? item.kind.toUpperCase()}
                  </span>
                  <span className="ml-2 text-xs text-zinc-200">{item.id}</span>
                  <span className="ml-2 text-[10px] text-zinc-600">{summarise(item, nper)}</span>
                </button>
                <button
                  type="button"
                  onClick={() => editor.edit((draft) => void draft.flow.packages.splice(index, 1))}
                  className="text-[10px] text-zinc-500 hover:text-red-400"
                >
                  remove
                </button>
              </div>

              {expanded === item.id && (
                <BoundaryEditor
                  item={item}
                  nper={nper}
                  limits={limits}
                  onEdit={(change) =>
                    editor.edit((draft) => change(draft.flow.packages[index], draft))
                  }
                />
              )}
            </li>
          ))}
        </ul>

        <div className="mt-3 flex flex-wrap gap-2">
          {PACKAGES.map((item) => (
            <button
              key={item.kind}
              type="button"
              title={item.description}
              onClick={() =>
                editor.edit((draft) => {
                  const created = newBoundary(item.kind, draft, limits);
                  draft.flow.packages.push(created);
                  setExpanded(created.id);
                })
              }
              className="rounded border border-zinc-700 px-2 py-1 font-mono text-[10px] text-zinc-300 hover:border-zinc-600 hover:text-zinc-100"
            >
              + {item.name}
            </button>
          ))}
        </div>
      </Section>

      <Section title="Solver" hint="Loosen these only if the flow solution will not converge.">
        <div className="grid max-w-xl grid-cols-2 gap-x-8 gap-y-3">
          <Labelled label="Complexity">
            <Select
              value={flow.solver.complexity}
              label="Solver complexity"
              options={[
                { value: "simple", label: "Simple" },
                { value: "moderate", label: "Moderate" },
                { value: "complex", label: "Complex" },
              ]}
              onChange={(value) =>
                editor.edit((draft) => void (draft.flow.solver.complexity = value))
              }
            />
          </Labelled>
          <Labelled label="Outer closure">
            <NumberInput
              value={flow.solver.outer_dvclose}
              label="Outer closure"
              onCommit={(value) =>
                editor.edit((draft) => void (draft.flow.solver.outer_dvclose = value))
              }
            />
          </Labelled>
        </div>
      </Section>
    </EditorShell>
  );
}

function summarise(item: ProjectDocument, nper: number): string {
  const first = PACKAGE_FIELDS[item.kind]?.[0];
  if (!first) return "";
  const series = item[first.field];
  const value =
    series?.kind === "constant"
      ? String(Number(series.value.toPrecision(4)))
      : `${series?.values?.length ?? 0}/${nper} periods`;
  return `${first.field} ${value}`;
}

function newBoundary(kind: string, document: ProjectDocument, limits: Limits): ProjectDocument {
  const existing = new Set((document.flow.packages as ProjectDocument[]).map((item) => item.id));
  let id = kind;
  let suffix = 2;
  while (existing.has(id)) id = `${kind}${suffix++}`;

  const cells = { kind: "cells", layers: [1], rows: [1], columns: [1] };

  // Head-type boundaries usually sit at the far end of a column, so that is
  // where a new one starts rather than on top of the inflow.
  const atFarEnd = { ...cells, columns: [limits.columns] };

  const defaults: Record<string, ProjectDocument> = {
    well: { cells, rate: { kind: "constant", value: 0 } },
    chd: { cells: atFarEnd, head: { kind: "constant", value: 0 } },
    recharge: { cells: null, rate: { kind: "constant", value: 1e-4 } },
    drn: {
      cells: atFarEnd,
      elevation: { kind: "constant", value: 0 },
      conductance: { kind: "constant", value: 1 },
    },
    riv: {
      cells: atFarEnd,
      stage: { kind: "constant", value: 0 },
      conductance: { kind: "constant", value: 1 },
      bottom: { kind: "constant", value: -1 },
    },
    ghb: {
      cells: atFarEnd,
      head: { kind: "constant", value: 0 },
      conductance: { kind: "constant", value: 1 },
    },
  };

  const base = { kind, id, ...defaults[kind] };
  // A drain only removes water, so it never carries an inflow concentration.
  return SOLUTE_CARRYING.has(kind) ? { ...base, concentration: null } : base;
}

function BoundaryEditor({
  item,
  nper,
  limits,
  onEdit,
}: {
  item: ProjectDocument;
  nper: number;
  limits: Limits;
  onEdit: (change: (item: ProjectDocument, document: ProjectDocument) => void) => void;
}) {
  const fields = PACKAGE_FIELDS[item.kind] ?? [];

  return (
    <div className="space-y-4 border-t border-zinc-800 px-3 py-3">
      <div className="grid max-w-md grid-cols-2 gap-3">
        <Labelled label="Name">
          <TextInput
            value={item.id}
            label={`${item.id} name`}
            onCommit={(value) => onEdit((draft) => void (draft.id = value))}
          />
        </Labelled>
      </div>

      {fields.map((field) => (
        <SeriesEditor
          key={field.field}
          label={field.label}
          hint={field.hint}
          series={item[field.field]}
          nper={nper}
          onEdit={(change) => onEdit((draft) => change(draft[field.field]))}
          onReplace={(series) => onEdit((draft) => void (draft[field.field] = series))}
        />
      ))}

      {SOLUTE_CARRYING.has(item.kind) && (
        <SeriesEditor
          label="Inflow concentration"
          hint="What the water entering here carries. Zero unless set."
          series={item.concentration}
          nper={nper}
          optional
          onEdit={(change) => onEdit((draft) => change(draft.concentration))}
          onReplace={(series) => onEdit((draft) => void (draft.concentration = series))}
        />
      )}

      {item.cells !== null && item.cells !== undefined && (
        <div className="grid max-w-lg grid-cols-3 gap-3">
          {(["layers", "rows", "columns"] as const).map((axis) => (
            <Labelled key={axis} label={`${axis} (1 to ${limits[axis]})`}>
              <TextInput
                value={(item.cells[axis] as number[]).join(", ")}
                label={`${item.id} ${axis}`}
                onCommit={(text) =>
                  onEdit((draft) => {
                    const parsed = text
                      .split(",")
                      .map((part) => Math.round(Number(part.trim())))
                      .filter((value) => Number.isFinite(value) && value >= 1);
                    if (parsed.length > 0) draft.cells[axis] = [...new Set(parsed)];
                  })
                }
              />
            </Labelled>
          ))}
        </div>
      )}
    </div>
  );
}

function SeriesEditor({
  label,
  hint,
  series,
  nper,
  optional,
  onEdit,
  onReplace,
}: {
  label: string;
  hint: string;
  series: ProjectDocument | null;
  nper: number;
  optional?: boolean;
  onEdit: (change: (series: ProjectDocument) => void) => void;
  onReplace: (series: ProjectDocument | null) => void;
}) {
  if (series === null || series === undefined) {
    return (
      <div>
        <span className="mb-1 block text-[10px] text-zinc-500">{label}</span>
        <button
          type="button"
          onClick={() => onReplace({ kind: "constant", value: 0 })}
          className="rounded border border-zinc-700 px-2 py-1 text-[10px] text-zinc-300 hover:border-zinc-600"
        >
          Set a value
        </button>
        <span className="ml-2 text-[10px] text-zinc-600">{hint}</span>
      </div>
    );
  }

  const perPeriod = series.kind === "per_period";

  return (
    <div>
      <div className="mb-1 flex items-center gap-2">
        <span className="text-[10px] text-zinc-500">{label}</span>
        <button
          type="button"
          onClick={() =>
            onReplace(
              perPeriod
                ? { kind: "constant", value: (series.values as number[])[0] ?? 0 }
                : {
                    kind: "per_period",
                    values: Array.from({ length: nper }, () => series.value),
                  },
            )
          }
          className="text-[10px] text-sky-400 hover:text-sky-300"
        >
          {perPeriod ? "use one value" : "vary by period"}
        </button>
        {optional && (
          <button
            type="button"
            onClick={() => onReplace(null)}
            className="text-[10px] text-zinc-500 hover:text-red-400"
          >
            clear
          </button>
        )}
      </div>

      {perPeriod ? (
        <div className="flex flex-wrap gap-2">
          {(series.values as number[]).map((value, index) => (
            <div key={index} className="flex items-center gap-1">
              <span className="text-[10px] text-zinc-600">{index + 1}</span>
              <NumberInput
                value={value}
                label={`${label} period ${index + 1}`}
                onCommit={(next) => onEdit((draft) => void (draft.values[index] = next))}
              />
            </div>
          ))}
        </div>
      ) : (
        <NumberInput
          value={series.value}
          label={label}
          onCommit={(value) => onEdit((draft) => void (draft.value = value))}
        />
      )}
      <span className="mt-1 block text-[10px] text-zinc-600">{hint}</span>
    </div>
  );
}
