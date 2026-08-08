import { useState } from "react";
import {
  EditorShell,
  Labelled,
  NumberInput,
  Section,
  NoProject,
  TextInput,
} from "./editor/controls";
import { ModelPreview } from "@/preview/ModelPreview";
import { FromBoundary } from "./grid/FromBoundary";
import { useProjectDocument, type ProjectDocument } from "./editor/useProjectDocument";
import { SurfaceValue, describeSurface } from "./editor/SurfaceValue";
import { CellSelector } from "./editor/CellSelector";
import { gridLimits } from "./editor/grid";
import { toggleCell, type CellTriple } from "./editor/selection";

type Tab = "domain" | "discretisation" | "layers";

const TABS: { id: Tab; label: string }[] = [
  { id: "domain", label: "Domain" },
  { id: "discretisation", label: "Discretisation" },
  { id: "layers", label: "Layers" },
];

/**
 * Spatial discretisation: cell spacing along each axis, and the layers stacked
 * beneath the model top.
 *
 * Changing the cell count can leave a boundary pointing at a column that no
 * longer exists, which the schema refuses. Rather than let that be a dead end,
 * the affected boundaries are listed with a one-click fix that moves them to
 * the new edge.
 */
export function GridStep({
  path,
  onGoToProject,
  onSaved,
}: {
  path: string | null;
  onGoToProject: () => void;
  onSaved: () => void;
}) {
  const editor = useProjectDocument(path);
  const [tab, setTab] = useState<Tab>("domain");
  // Whether clicks in the viewport are adding to the active-cell selection.
  const [picking, setPicking] = useState(false);

  if (!path) return <NoProject onGo={onGoToProject} />;
  if (!editor.document) {
    return <div className="p-6 text-xs text-zinc-500">Loading…</div>;
  }

  const grid = editor.document.grid;
  const stranded = strandedBoundaries(editor.document);
  // Imported data a surface can be sampled from, or an active-cell selection
  // drawn from. Kept in the shape both controls take.
  const sources = ((editor.document.data?.sources ?? []) as ProjectDocument[]).map((item) => ({
    id: item.id as string,
    name: item.name as string,
    kind: item.kind as string,
    geometry: item.geometry as string | undefined,
    fields: (item.fields ?? []) as string[],
  }));

  return (
    <EditorShell
      title="Grid"
      blurb="Where the model sits, how finely it is cut up, and what is stacked beneath its top. A column benchmark uses one row and one layer, with unit width so cell volume equals cell length."
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
          initialField="strt"
          picking={
            picking && grid.active?.kind === "list"
              ? {
                  cells: (grid.active.indices ?? []) as CellTriple[],
                  onToggle: (cell) =>
                    editor.edit((draft) => {
                      const selection = draft.grid.active;
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
      <nav className="mb-5 flex gap-1 border-b border-zinc-800 pb-2">
        {TABS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            onClick={() => setTab(entry.id)}
            className={`rounded px-2 py-1 text-[11px] ${
              tab === entry.id ? "bg-zinc-800 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
            }`}
          >
            {entry.label}
          </button>
        ))}
      </nav>

      {stranded.length > 0 && tab === "discretisation" && (
        <div className="mb-6 rounded border border-amber-900 bg-amber-950/30 p-3">
          <p className="text-xs text-amber-200">
            {stranded.length === 1 ? "A boundary refers" : "Boundaries refer"} to cells outside this
            grid, so it will not save:
          </p>
          <ul className="mt-1 text-[11px] text-amber-300">
            {stranded.map((item) => (
              <li key={item.id}>
                {item.id} — {item.axis} {item.indices.join(", ")} (grid has {item.limit})
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() =>
              editor.edit((draft) => {
                clampBoundaries(draft);
              })
            }
            className="mt-2 rounded border border-amber-700 px-2 py-1 text-[10px] text-amber-200 hover:border-amber-500"
          >
            Move them to the nearest cell in the new grid
          </button>
        </div>
      )}

      {tab === "discretisation" && (
        <>
          <Section
            title="Columns (x)"
            hint="Either a count of equal cells, or explicit widths for a graded discretisation."
          >
            <AxisEditor
              axis="columns"
              spacing={grid.columns}
              onEdit={(change) => editor.edit((draft) => change(draft.grid.columns))}
            />
          </Section>

          <Section title="Rows (y)">
            <AxisEditor
              axis="rows"
              spacing={grid.rows}
              onEdit={(change) => editor.edit((draft) => change(draft.grid.rows))}
            />
          </Section>

          <GridSummary grid={grid} />
        </>
      )}

      {tab === "layers" && (
        <>
          <Section
            title="Layers"
            hint="Each layer gives the elevation of its bottom. Sublayers split it into that many equal thicknesses."
          >
            <div className="mb-3 max-w-md">
              <SurfaceValue
                label="Model top"
                surface={grid.top}
                sources={sources}
                allowOffset={false}
                onChange={(value) => editor.edit((draft) => void (draft.grid.top = value))}
              />
            </div>

            <ul className="space-y-2">
              {grid.layers.map((layer: ProjectDocument, index: number) => (
                <li key={index} className="rounded border border-zinc-800 p-2">
                  <div className="mb-2 flex items-center gap-2">
                    <span className="w-4 shrink-0 text-[10px] text-zinc-600">{index + 1}</span>
                    <TextInput
                      value={layer.name ?? ""}
                      placeholder={`layer ${index + 1}`}
                      label={`Layer ${index + 1} name`}
                      onCommit={(value) =>
                        editor.edit((draft) => void (draft.grid.layers[index].name = value || null))
                      }
                    />
                    <button
                      type="button"
                      disabled={grid.layers.length === 1}
                      onClick={() =>
                        editor.edit((draft) => void draft.grid.layers.splice(index, 1))
                      }
                      title={
                        grid.layers.length === 1 ? "A model needs at least one layer" : "Remove"
                      }
                      className="ml-auto shrink-0 text-[10px] text-zinc-500 hover:text-red-400 disabled:opacity-30"
                    >
                      remove
                    </button>
                  </div>

                  <SurfaceValue
                    label="Bottom"
                    surface={layer.bottom}
                    sources={sources}
                    onChange={(value) =>
                      editor.edit((draft) => void (draft.grid.layers[index].bottom = value))
                    }
                  />

                  <div className="mt-2 grid grid-cols-2 gap-2">
                    <Labelled
                      label="Sublayers"
                      hint="Splits this unit into that many cells, each following both surfaces rather than sitting flat."
                    >
                      <NumberInput
                        value={layer.sublayers}
                        min={1}
                        step={1}
                        label={`Layer ${index + 1} sublayers`}
                        onCommit={(value) =>
                          editor.edit(
                            (draft) =>
                              void (draft.grid.layers[index].sublayers = Math.max(
                                1,
                                Math.round(value),
                              )),
                          )
                        }
                      />
                    </Labelled>
                    <Labelled
                      label="Min thickness"
                      hint="Keeps the layer at least this thick where the surfaces cross or it pinches out. The cells that had to be pushed down are reported after the grid is built."
                    >
                      <NumberInput
                        value={layer.minimum_thickness ?? 0}
                        min={0}
                        label={`Layer ${index + 1} minimum thickness`}
                        onCommit={(value) =>
                          editor.edit(
                            (draft) =>
                              void (draft.grid.layers[index].minimum_thickness = Math.max(
                                0,
                                value,
                              )),
                          )
                        }
                      />
                    </Labelled>
                  </div>
                </li>
              ))}
            </ul>

            <button
              type="button"
              onClick={() =>
                editor.edit((draft) => {
                  // A new layer repeats the one above it as a thickness, which
                  // works whatever the surfaces above are: an offset needs no
                  // elevations to be known, and elevations may be sampled.
                  const last = draft.grid.layers[draft.grid.layers.length - 1];
                  const thickness =
                    last?.bottom?.kind === "offset" ? (last.bottom.thickness ?? 10) : 10;
                  draft.grid.layers.push({
                    name: null,
                    bottom: { kind: "offset", thickness },
                    sublayers: 1,
                    minimum_thickness: 0,
                  });
                })
              }
              className="mt-2 rounded border border-zinc-700 px-2 py-1 text-[10px] text-zinc-300 hover:border-zinc-600"
            >
              Add layer
            </button>
          </Section>
        </>
      )}

      {tab === "domain" && (
        <>
          <DomainPanel document={editor.document} edit={editor.edit} />

          <Section
            title="Active cells"
            hint="Which cells are part of the model. Everything unless you say otherwise. A grid built to fit a catchment covers the rectangle around it, and without this the cells outside the catchment still take recharge, pass water and appear in the water balance."
          >
            {grid.active ? (
              <div className="max-w-xl space-y-2">
                <CellSelector
                  selection={grid.active}
                  limits={gridLimits(grid)}
                  sources={sources}
                  path={path}
                  picking={picking}
                  onPick={setPicking}
                  onChange={(selection) =>
                    editor.edit((draft) => void (draft.grid.active = selection))
                  }
                />
                <button
                  type="button"
                  onClick={() => {
                    setPicking(false);
                    editor.edit((draft) => void (draft.grid.active = null));
                  }}
                  className="text-[10px] text-zinc-500 hover:text-zinc-300"
                >
                  use every cell
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() =>
                  editor.edit((draft) => {
                    const outline = sources.find(
                      (item) => item.kind === "vector" && item.geometry === "polygon",
                    );
                    draft.grid.active = outline
                      ? {
                          kind: "shape",
                          source: outline.id,
                          layers: Array.from(
                            { length: gridLimits(draft.grid).layers },
                            (_, i) => i + 1,
                          ),
                          rule: "centroid",
                          buffer: 0,
                        }
                      : { kind: "list", indices: [] };
                  })
                }
                className="rounded border border-zinc-700 px-2 py-1 text-[10px] text-zinc-300 hover:border-zinc-600"
              >
                Limit the model to part of the grid
              </button>
            )}
          </Section>
          {/* Reloaded rather than merged: building a grid writes it on the
              server, so what is on screen has to come back from there. The
              shell is told as well, or every other step keeps quoting the grid
              this one just replaced. */}
          <FromBoundary
            path={path}
            onApplied={() => {
              void editor.reload();
              onSaved();
            }}
          />
        </>
      )}
    </EditorShell>
  );
}

function AxisEditor({
  axis,
  spacing,
  onEdit,
}: {
  axis: "columns" | "rows";
  spacing: ProjectDocument;
  onEdit: (change: (spacing: ProjectDocument) => void) => void;
}) {
  const graded = spacing.widths !== null && spacing.widths !== undefined;

  return (
    <div className="max-w-2xl space-y-2">
      <div className="flex gap-3 text-[10px]">
        <button
          type="button"
          onClick={() =>
            onEdit((draft) => {
              if (!graded) return;
              const total = (draft.widths as number[]).reduce((sum, w) => sum + w, 0);
              draft.ncells = (draft.widths as number[]).length;
              draft.total_length = total;
              draft.widths = null;
            })
          }
          className={`rounded border px-2 py-1 ${
            !graded ? "border-sky-500 bg-sky-500/10 text-sky-200" : "border-zinc-700 text-zinc-400"
          }`}
        >
          Equal cells
        </button>
        <button
          type="button"
          onClick={() =>
            onEdit((draft) => {
              if (graded) return;
              const count = draft.ncells as number;
              const width = (draft.total_length as number) / count;
              draft.widths = Array.from({ length: count }, () => width);
              draft.ncells = null;
              draft.total_length = null;
            })
          }
          className={`rounded border px-2 py-1 ${
            graded ? "border-sky-500 bg-sky-500/10 text-sky-200" : "border-zinc-700 text-zinc-400"
          }`}
        >
          Explicit widths
        </button>
      </div>

      {graded ? (
        <Labelled
          label={`${(spacing.widths as number[]).length} widths, total ${(
            spacing.widths as number[]
          )
            .reduce((sum, w) => sum + w, 0)
            .toPrecision(5)}`}
          hint="Comma separated, from the first cell to the last."
        >
          <TextInput
            value={(spacing.widths as number[]).join(", ")}
            label={`${axis} widths`}
            onCommit={(text) =>
              onEdit((draft) => {
                const parsed = text
                  .split(",")
                  .map((part) => Number(part.trim()))
                  .filter((value) => Number.isFinite(value) && value > 0);
                if (parsed.length > 0) draft.widths = parsed;
              })
            }
          />
        </Labelled>
      ) : (
        <div className="grid grid-cols-3 gap-3">
          <Labelled label="Cells">
            <NumberInput
              value={spacing.ncells}
              min={1}
              step={1}
              label={`${axis} cell count`}
              onCommit={(value) =>
                onEdit((draft) => void (draft.ncells = Math.max(1, Math.round(value))))
              }
            />
          </Labelled>
          <Labelled label="Total length">
            <NumberInput
              value={spacing.total_length}
              min={0}
              label={`${axis} total length`}
              onCommit={(value) => onEdit((draft) => void (draft.total_length = value))}
            />
          </Labelled>
          <Labelled label="Cell width">
            <span className="block py-1 text-xs tabular-nums text-zinc-400">
              {(spacing.total_length / spacing.ncells).toPrecision(4)}
            </span>
          </Labelled>
        </div>
      )}
    </div>
  );
}

function GridSummary({ grid }: { grid: ProjectDocument }) {
  const ncol = grid.columns.widths?.length ?? grid.columns.ncells;
  const nrow = grid.rows.widths?.length ?? grid.rows.ncells;
  const nlay = grid.layers.reduce(
    (total: number, layer: ProjectDocument) => total + layer.sublayers,
    0,
  );

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/50 p-3 text-xs">
      <span className="tabular-nums text-zinc-200">
        {nlay} x {nrow} x {ncol}
      </span>
      <span className="ml-2 text-zinc-500">= {(nlay * nrow * ncol).toLocaleString()} cells</span>
    </div>
  );
}

interface Stranded {
  id: string;
  axis: string;
  indices: number[];
  limit: number;
}

/** Boundaries pointing outside the grid as currently edited. */
function strandedBoundaries(document: ProjectDocument): Stranded[] {
  const grid = document.grid;
  const limits: Record<string, number> = {
    columns: grid.columns.widths?.length ?? grid.columns.ncells,
    rows: grid.rows.widths?.length ?? grid.rows.ncells,
    layers: grid.layers.reduce(
      (total: number, layer: ProjectDocument) => total + layer.sublayers,
      0,
    ),
  };

  const found: Stranded[] = [];
  for (const item of document.flow.packages ?? []) {
    if (!item.cells) continue;
    for (const axis of ["layers", "rows", "columns"]) {
      const outside = (item.cells[axis] as number[]).filter(
        (index) => index < 1 || index > limits[axis],
      );
      if (outside.length > 0) {
        found.push({ id: item.id, axis, indices: outside, limit: limits[axis] });
      }
    }
  }
  return found;
}

/** Pull out-of-range cell indices back inside the grid. */
function clampBoundaries(document: ProjectDocument): void {
  const grid = document.grid;
  const limits: Record<string, number> = {
    columns: grid.columns.widths?.length ?? grid.columns.ncells,
    rows: grid.rows.widths?.length ?? grid.rows.ncells,
    layers: grid.layers.reduce(
      (total: number, layer: ProjectDocument) => total + layer.sublayers,
      0,
    ),
  };

  for (const item of document.flow.packages ?? []) {
    if (!item.cells) continue;
    for (const axis of ["layers", "rows", "columns"]) {
      item.cells[axis] = [
        ...new Set(
          (item.cells[axis] as number[]).map((index) => Math.min(Math.max(index, 1), limits[axis])),
        ),
      ];
    }
  }
}

/**
 * Where the model is, in the world or nowhere in particular.
 *
 * Most reactive transport starts as a column or a box with no location at all,
 * so a coordinate system is opt-in rather than something to dismiss. Turning it
 * on is what makes a basemap meaningful: without a CRS there is nothing to put
 * the grid on top of, and a map underneath an unplaced model would be a
 * decoration that implies a location the model does not have.
 */
function DomainPanel({
  document,
  edit,
}: {
  document: ProjectDocument;
  edit: (change: (draft: ProjectDocument) => void) => void;
}) {
  const grid = document.grid;
  const crs = document.meta.crs as string | null;
  const georeferenced = crs !== null;

  const width = extentOf(grid.columns);
  const height = extentOf(grid.rows);

  return (
    <>
      <Section
        title="Coordinates"
        hint="A column or a box needs no location. Turn this on for a model of a real place, and the grid can be drawn on a map."
      >
        <label className="flex items-center gap-2 text-xs text-zinc-300">
          <input
            type="checkbox"
            checked={georeferenced}
            onChange={(event) =>
              edit((draft) => {
                // Cleared rather than kept when switched off, so a project
                // without a location does not carry a stale one.
                draft.meta.crs = event.target.checked ? (crs ?? "EPSG:4326") : null;
              })
            }
            className="accent-sky-600"
          />
          This model is somewhere real
        </label>

        {georeferenced ? (
          <div className="mt-3 max-w-xs">
            <Labelled
              label="Coordinate reference system"
              hint="An EPSG code. Use a projected system in metres; degrees make cell sizes meaningless."
            >
              <TextInput
                value={crs ?? ""}
                label="Coordinate reference system"
                onCommit={(value) => edit((draft) => void (draft.meta.crs = value || null))}
              />
            </Labelled>
          </div>
        ) : (
          <p className="mt-2 max-w-md text-[11px] leading-relaxed text-zinc-600">
            The grid&rsquo;s origin is just an offset, and distances are whatever the length unit
            says. Nothing is lost: a benchmark column does not belong anywhere.
          </p>
        )}
      </Section>

      <Section
        title="Placement"
        hint={
          georeferenced
            ? "Where the grid's corner sits in the chosen coordinate system, and how far it is turned from north."
            : "An offset and a rotation. Both are free to stay at zero for a column."
        }
      >
        <div className="grid max-w-lg grid-cols-3 gap-3">
          <Labelled label={georeferenced ? "Easting of origin" : "Origin x"}>
            <NumberInput
              value={grid.origin_x}
              label="Origin x"
              onCommit={(value) => edit((draft) => void (draft.grid.origin_x = value))}
            />
          </Labelled>
          <Labelled label={georeferenced ? "Northing of origin" : "Origin y"}>
            <NumberInput
              value={grid.origin_y}
              label="Origin y"
              onCommit={(value) => edit((draft) => void (draft.grid.origin_y = value))}
            />
          </Labelled>
          <Labelled label="Rotation (degrees)">
            <NumberInput
              value={grid.rotation}
              label="Rotation"
              onCommit={(value) => edit((draft) => void (draft.grid.rotation = value))}
            />
          </Labelled>
        </div>
      </Section>

      <Section title="Extent" hint="What the discretisation adds up to.">
        <dl className="grid max-w-md grid-cols-2 gap-x-6 gap-y-1 text-xs">
          <dt className="text-zinc-500">Across (x)</dt>
          <dd className="tabular-nums text-zinc-200">{width}</dd>
          <dt className="text-zinc-500">Along (y)</dt>
          <dd className="tabular-nums text-zinc-200">{height}</dd>
          <dt className="text-zinc-500">Top</dt>
          <dd className="tabular-nums text-zinc-200">{describeSurface(grid.top)}</dd>
          <dt className="text-zinc-500">Base</dt>
          <dd className="tabular-nums text-zinc-200">
            {describeSurface(grid.layers[grid.layers.length - 1]?.bottom)}
          </dd>
        </dl>
      </Section>
    </>
  );
}

/** How far an axis reaches, however its spacing was given. */
function extentOf(spacing: ProjectDocument): number {
  const widths = spacing.widths as number[] | null;
  if (widths) return Number(widths.reduce((total, item) => total + item, 0).toPrecision(6));
  return spacing.total_length;
}
