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
import { ModelPreview } from "@/preview/ModelPreview";
import { gridLimits, type Limits } from "./editor/grid";
import {
  BOUNDARY_PACKAGES,
  flowPackages,
  PACKAGE_FOR_KIND,
  ZONES_TAB,
  type PackageTab,
} from "./editor/packages";
import { PackageTabs } from "./editor/PackageTabs";
import { useProjectDocument, type ProjectDocument } from "./editor/useProjectDocument";
import { CellSelector } from "./editor/CellSelector";
import { PropertyValue } from "./editor/PropertyValue";
import { ZoneList } from "./editor/ZoneList";
import { toggleCell, type CellSelection, type CellTriple } from "./editor/selection";

/**
 * Which property each package holds.
 *
 * Grouped by the file MODFLOW writes rather than by what the value means: a
 * modeller chasing an error reads the package name, and specific storage is in
 * STO whether or not it feels like a property of the aquifer.
 */
const PACKAGE_PROPERTIES: Record<string, { key: string; label: string; hint: string }[]> = {
  NPF: [
    { key: "k", label: "Horizontal conductivity", hint: "K along the rows and columns" },
    {
      key: "porosity",
      label: "Porosity",
      hint: "Used for flow storage and, by default, transport",
    },
  ],
  LPF: [
    { key: "k", label: "Horizontal conductivity", hint: "K along the rows and columns" },
    {
      key: "porosity",
      label: "Porosity",
      hint: "Used for flow storage and, by default, transport",
    },
    {
      key: "specific_storage",
      label: "Specific storage",
      hint: "Only matters in transient periods",
    },
    { key: "specific_yield", label: "Specific yield", hint: "Only used where cells can dewater" },
  ],
  STO: [
    {
      key: "specific_storage",
      label: "Specific storage",
      hint: "Only matters in transient periods",
    },
    { key: "specific_yield", label: "Specific yield", hint: "Only used where cells can dewater" },
  ],
  IC: [{ key: "starting_head", label: "Starting head", hint: "The head the solver starts from" }],
  BAS: [{ key: "starting_head", label: "Starting head", hint: "The head the solver starts from" }],
};

/** The field the viewport draws when a package tab is opened. */
const PACKAGE_FIELD: Record<string, string> = {
  NPF: "k",
  LPF: "k",
  STO: "ss",
  IC: "strt",
  BAS: "strt",
};

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
  const [tab, setTab] = useState<string | null>(null);
  // Which selection clicks in the viewport are currently going into. One at a
  // time: a click has to mean one thing, and two open pickers would make it
  // ambiguous which entry just gained a cell.
  const [picking, setPicking] = useState<PickTarget | null>(null);
  // What the viewport draws. Opening a package points it at that package's
  // cells, so checking boundaries one by one is what the screen is for; the
  // picker above the canvas still allows anything else.
  const [drawn, setDrawn] = useState<string>("k");

  if (!path) return <NoProject onGo={onGoToProject} />;
  if (!editor.document) return <div className="p-6 text-xs text-zinc-500">Loading…</div>;

  const flow = editor.document.flow;
  const grid = editor.document.grid;
  const nper = (editor.document.time.periods as unknown[]).length;
  const limits = gridLimits(grid);
  const engine = editor.document.meta.engine as string;
  const properties = flowPackages(engine);
  const active = tab ?? properties[0].id;
  const allTabs = [...properties, ZONES_TAB];
  const packages = flow.packages as ProjectDocument[];
  const zones = (editor.document.zones ?? []) as ProjectDocument[];
  const sources = ((editor.document.data?.sources ?? []) as ProjectDocument[]).map((item) => ({
    id: item.id as string,
    name: item.name as string,
    geometry: item.geometry as string | undefined,
  }));

  // Whatever the open picker points at, read back out of the document so the
  // highlight follows an edit made anywhere — including an undo.
  const pickedCells = picking ? (readSelection(editor.document, picking)?.indices ?? []) : [];

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
      preview={
        <ModelPreview
          path={path}
          revision={editor.revision}
          field={drawn}
          onFieldChange={setDrawn}
          picking={
            picking
              ? {
                  cells: pickedCells as CellTriple[],
                  onToggle: (cell) =>
                    editor.edit((draft) => {
                      const selection = readSelection(draft, picking);
                      if (selection?.kind === "list") {
                        selection.indices = toggleCell(selection.indices as CellTriple[], cell);
                      }
                    }),
                }
              : null
          }
          className="h-full"
        />
      }
    >
      <PackageTabs
        groups={[
          { label: "Aquifer", tabs: [...properties, ZONES_TAB] },
          { label: "Boundaries", tabs: BOUNDARY_PACKAGES },
        ]}
        active={active}
        counts={boundaryCounts(packages)}
        onSelect={(id) => {
          setTab(id);
          const field = PACKAGE_FIELD[id];
          if (field) setDrawn(field);
        }}
      />

      {PACKAGE_PROPERTIES[active] && (
        <Section
          field={PACKAGE_FIELD[active]}
          onShow={setDrawn}
          title={describePackage(active, allTabs)}
          hint="Each property is one value everywhere, or a value per zone. Zones are shared with transport, so the sand is the sand for porosity too."
        >
          <div className="grid max-w-2xl grid-cols-2 gap-x-8 gap-y-3">
            {PACKAGE_PROPERTIES[active].map((property) => (
              <PropertyValue
                key={property.key}
                label={property.label}
                hint={property.hint}
                field={flow.properties[property.key]}
                zones={zones as { id: string; label?: string }[]}
                onAddZone={() => setTab("ZONES")}
                onChange={(next) =>
                  editor.edit((draft) => void (draft.flow.properties[property.key] = next))
                }
              />
            ))}
            {(active === "NPF" || active === "LPF") && (
              <div>
                <PropertyValue
                  label="Vertical conductivity"
                  hint="Unset follows the horizontal value, which is what MODFLOW assumes."
                  field={flow.properties.k33}
                  inherited={flow.properties.k?.value ?? flow.properties.k?.default}
                  zones={zones as { id: string; label?: string }[]}
                  onAddZone={() => setTab("ZONES")}
                  onChange={(next) =>
                    editor.edit((draft) => void (draft.flow.properties.k33 = next))
                  }
                />
                <label className="mt-1 flex items-center gap-1 text-[10px] text-zinc-500">
                  <input
                    type="checkbox"
                    checked={flow.properties.k33 === null}
                    onChange={(event) =>
                      editor.edit((draft) => {
                        draft.flow.properties.k33 = event.target.checked
                          ? null
                          : { kind: "constant", value: draft.flow.properties.k.value ?? 1 };
                      })
                    }
                  />
                  follow K
                </label>
              </div>
            )}
            {(active === "NPF" || active === "LPF") && (
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
            )}
          </div>
        </Section>
      )}

      {active === "ZONES" && (
        <Section
          field="zones"
          onShow={setDrawn}
          title="Zones"
          hint="Named parts of the grid. Draw one here, then give any property its own value inside it. Later zones win where two overlap."
        >
          <ZoneList
            zones={zones as never}
            limits={limits}
            sources={sources}
            path={path}
            pickingZone={picking?.kind === "zone" ? picking.zone : null}
            onPick={(index) => setPicking(index === null ? null : { kind: "zone", zone: index })}
            onChange={(change) =>
              editor.edit((draft) => {
                draft.zones = draft.zones ?? [];
                change(draft.zones);
              })
            }
          />
        </Section>
      )}

      {isBoundary(active) && (
        <Section
          title={describePackage(active, BOUNDARY_PACKAGES)}
          hint="A package holds as many entries as you like. One entry over fifty cells writes fifty records sharing a value; fifty entries of one cell each writes fifty different values. That is what a MODFLOW package file holds."
        >
          {packages.filter((item) => PACKAGE_FOR_KIND[item.kind] === active).length === 0 && (
            <p className="mb-2 text-[11px] leading-relaxed text-zinc-600">
              No {active} in this model.
            </p>
          )}

          <ul className="space-y-2">
            {packages.map((item, index) =>
              PACKAGE_FOR_KIND[item.kind] !== active ? null : (
                <li key={index} className="rounded border border-zinc-800">
                  <div className="flex items-center gap-3 px-3 py-2">
                    <button
                      type="button"
                      onClick={() => {
                        const opening = expanded !== item.id;
                        setExpanded(opening ? item.id : null);
                        if (!opening) setPicking(null);
                        if (opening) setDrawn(`boundary:${item.id}`);
                      }}
                      className="flex-1 text-left"
                    >
                      <span className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[10px] text-sky-300">
                        {PACKAGE_NAME[item.kind] ?? item.kind.toUpperCase()}
                      </span>
                      <span className="ml-2 text-xs text-zinc-200">{item.id}</span>
                      <span className="ml-2 text-[10px] text-zinc-600">{summarise(item)}</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setPicking(null);
                        editor.edit((draft) => void draft.flow.packages.splice(index, 1));
                      }}
                      className="text-[10px] text-zinc-500 hover:text-red-400"
                    >
                      remove
                    </button>
                  </div>

                  {expanded === item.id && (
                    <PackageEditor
                      item={item}
                      packageIndex={index}
                      nper={nper}
                      limits={limits}
                      sources={sources}
                      path={path}
                      picking={picking}
                      onPick={setPicking}
                      onEdit={(change) =>
                        editor.edit((draft) => change(draft.flow.packages[index], draft))
                      }
                    />
                  )}
                </li>
              ),
            )}
          </ul>

          <button
            type="button"
            onClick={() =>
              editor.edit((draft) => {
                const created = newBoundary(kindFor(active), draft, limits);
                draft.flow.packages.push(created);
                setExpanded(created.id);
                setDrawn(`boundary:${created.id}`);
              })
            }
            className="mt-3 rounded border border-zinc-700 px-2 py-1 font-mono text-[10px] text-zinc-300 hover:border-zinc-600 hover:text-zinc-100"
          >
            + {active}
          </button>
        </Section>
      )}

      {isSolver(active) && (
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
      )}
    </EditorShell>
  );
}

/**
 * Where an open picker is putting the cells it collects.
 *
 * A path into the document rather than the selection object itself, so a click
 * reads the current draft and writes back into it. Holding the object would
 * mean writing into a copy the editor has already replaced.
 */
type PickTarget =
  { kind: "entry"; package: number; entry: number } | { kind: "zone"; zone: number };

function readSelection(document: ProjectDocument, target: PickTarget): ProjectDocument | null {
  if (target.kind === "zone") return document.zones?.[target.zone]?.cells ?? null;
  return document.flow?.packages?.[target.package]?.entries?.[target.entry]?.cells ?? null;
}

/** Whether this tab is one of the boundary packages. */
function isBoundary(id: string): boolean {
  return BOUNDARY_PACKAGES.some((item) => item.id === id);
}

/** Whether this tab is the flow solver, which each engine names differently. */
function isSolver(id: string): boolean {
  return id === "IMS" || id === "PCG";
}

/** The boundary kind a package tab creates. */
function kindFor(packageId: string): string {
  const found = Object.entries(PACKAGE_FOR_KIND).find(([, id]) => id === packageId);
  return found ? found[0] : "well";
}

/** How many instances of each boundary package the model has. */
function boundaryCounts(packages: ProjectDocument[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const item of packages) {
    const id = PACKAGE_FOR_KIND[item.kind];
    if (id) counts[id] = (counts[id] ?? 0) + 1;
  }
  return counts;
}

/** "NPF — Node property flow", the way the package list in a manual reads. */
function describePackage(id: string, tabs: PackageTab[]): string {
  const found = tabs.find((item) => item.id === id);
  return found ? `${found.id} — ${found.label}` : id;
}

/** "2 wells · -250 to -10" — enough to spot a sign error without opening it. */
function summarise(item: ProjectDocument): string {
  const entries = (item.entries ?? []) as ProjectDocument[];
  if (entries.length === 0) return "empty";

  const field = PACKAGE_FIELDS[item.kind]?.[0]?.field;
  const values = entries
    .map((entry) => entry[field ?? ""])
    .flatMap((series) =>
      series?.kind === "constant" ? [series.value as number] : ((series?.values ?? []) as number[]),
    );

  const count = `${entries.length} entr${entries.length === 1 ? "y" : "ies"}`;
  if (values.length === 0) return count;

  const low = Math.min(...values);
  const high = Math.max(...values);
  const range =
    low === high ? String(Number(low.toPrecision(4))) : `${short(low)} to ${short(high)}`;
  return `${count} · ${field} ${range}`;
}

function short(value: number): string {
  return String(Number(value.toPrecision(3)));
}

/** A fresh entry for a package kind, at whatever cells make sense to start at. */
function newEntry(kind: string, limits: Limits, existing: number): ProjectDocument {
  const cells = { kind: "cells", layers: [1], rows: [1], columns: [1] };
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

  const base = { label: "", ...defaults[kind] };
  // A drain only removes water, so it never carries an inflow concentration.
  const entry = SOLUTE_CARRYING.has(kind) ? { ...base, concentration: null } : base;

  // A second entry starts empty rather than on the first one's cells: two
  // entries claiming a cell is refused, and starting in that state would make
  // every new entry open as an error.
  return existing > 0 ? { ...entry, cells: { kind: "list", indices: [] } } : entry;
}

function newBoundary(kind: string, document: ProjectDocument, limits: Limits): ProjectDocument {
  const existing = new Set((document.flow.packages as ProjectDocument[]).map((item) => item.id));
  let id = kind;
  let suffix = 2;
  while (existing.has(id)) id = `${kind}${suffix++}`;

  return { kind, id, entries: [newEntry(kind, limits, 0)] };
}

/**
 * One package, and the entries inside it.
 *
 * The entry list is the part that matters. A well field is one WEL package
 * with an entry per well, not eight packages — that is how MODFLOW writes it
 * and how anyone reading a listing file expects to find it.
 */
function PackageEditor({
  item,
  packageIndex,
  nper,
  limits,
  sources,
  path,
  picking,
  onPick,
  onEdit,
}: {
  item: ProjectDocument;
  packageIndex: number;
  nper: number;
  limits: Limits;
  sources: { id: string; name: string; geometry?: string }[];
  path: string | null;
  picking: PickTarget | null;
  onPick: (target: PickTarget | null) => void;
  onEdit: (change: (item: ProjectDocument, document: ProjectDocument) => void) => void;
}) {
  const entries = (item.entries ?? []) as ProjectDocument[];

  return (
    <div className="space-y-3 border-t border-zinc-800 px-3 py-3">
      <Labelled label="Package name" hint="What the file and any error about it will be called.">
        <TextInput
          value={item.id}
          label={`${item.id} name`}
          onCommit={(value) => onEdit((draft) => void (draft.id = value))}
        />
      </Labelled>

      {entries.map((entry, index) => (
        <div key={index} className="rounded border border-zinc-800/80 bg-zinc-950/40 p-2">
          <div className="mb-2 flex items-center gap-2">
            <span className="text-[10px] text-zinc-600">{index + 1}</span>
            <TextInput
              value={(entry.label as string) ?? ""}
              label={`entry ${index + 1} name`}
              placeholder={`${PACKAGE_NAME[item.kind] ?? item.kind} ${index + 1}`}
              onCommit={(value) =>
                onEdit((draft) => void ((draft.entries as ProjectDocument[])[index].label = value))
              }
            />
            {entries.length > 1 && (
              <button
                type="button"
                onClick={() => {
                  onPick(null);
                  onEdit((draft) => void (draft.entries as ProjectDocument[]).splice(index, 1));
                }}
                className="ml-auto text-[10px] text-zinc-500 hover:text-red-400"
              >
                remove
              </button>
            )}
          </div>

          {entry.cells !== null && entry.cells !== undefined ? (
            <CellSelector
              selection={entry.cells as CellSelection}
              limits={limits}
              sources={sources}
              path={path}
              picking={
                picking?.kind === "entry" &&
                picking.package === packageIndex &&
                picking.entry === index
              }
              onPick={(on) =>
                onPick(on ? { kind: "entry", package: packageIndex, entry: index } : null)
              }
              onChange={(selection) =>
                onEdit(
                  (draft) => void ((draft.entries as ProjectDocument[])[index].cells = selection),
                )
              }
            />
          ) : (
            <div className="rounded border border-zinc-800 bg-zinc-900/40 p-2">
              <p className="text-[10px] text-zinc-500">
                Falls on the whole top of the model.
                <button
                  type="button"
                  onClick={() =>
                    onEdit(
                      (draft) =>
                        void ((draft.entries as ProjectDocument[])[index].cells = {
                          kind: "cells",
                          layers: [1],
                          rows: [1],
                          columns: [1],
                        }),
                    )
                  }
                  className="ml-2 text-sky-400 hover:text-sky-300"
                >
                  choose cells instead
                </button>
              </p>
            </div>
          )}

          <div className="mt-2 space-y-2">
            {(PACKAGE_FIELDS[item.kind] ?? []).map((field) => (
              <SeriesEditor
                key={field.field}
                label={field.label}
                hint={field.hint}
                series={entry[field.field]}
                nper={nper}
                onEdit={(change) =>
                  onEdit((draft) =>
                    change((draft.entries as ProjectDocument[])[index][field.field]),
                  )
                }
                onReplace={(series) =>
                  onEdit(
                    (draft) =>
                      void ((draft.entries as ProjectDocument[])[index][field.field] = series),
                  )
                }
              />
            ))}

            {SOLUTE_CARRYING.has(item.kind) && (
              <SeriesEditor
                label="Inflow concentration"
                hint="What the water entering here carries. Zero unless set."
                series={entry.concentration}
                nper={nper}
                optional
                onEdit={(change) =>
                  onEdit((draft) =>
                    change((draft.entries as ProjectDocument[])[index].concentration),
                  )
                }
                onReplace={(series) =>
                  onEdit(
                    (draft) =>
                      void ((draft.entries as ProjectDocument[])[index].concentration = series),
                  )
                }
              />
            )}
          </div>
        </div>
      ))}

      <button
        type="button"
        onClick={() =>
          onEdit((draft) => {
            const list = draft.entries as ProjectDocument[];
            list.push(newEntry(item.kind as string, limits, list.length));
            onPick({ kind: "entry", package: packageIndex, entry: list.length - 1 });
          })
        }
        className="rounded border border-zinc-700 px-2 py-1 text-[10px] text-zinc-300 hover:border-zinc-600 hover:text-zinc-100"
      >
        + another {PACKAGE_NAME[item.kind] ?? item.kind}
      </button>
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
