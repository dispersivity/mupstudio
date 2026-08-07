import {
  EditorShell,
  Labelled,
  NumberInput,
  Section,
  NoProject,
  TextInput,
} from "./editor/controls";
import { useProjectDocument, type ProjectDocument } from "./editor/useProjectDocument";

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

  if (!path) return <NoProject onGo={onGoToProject} />;
  if (!editor.document) {
    return <div className="p-6 text-xs text-zinc-500">Loading…</div>;
  }

  const grid = editor.document.grid;
  const stranded = strandedBoundaries(editor.document);

  return (
    <EditorShell
      title="Grid"
      blurb="A structured grid: cells along x and y, layers down. Column benchmarks use one row and one layer, with unit width so cell volume equals cell length."
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
      {stranded.length > 0 && (
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

      <Section
        title="Layers"
        hint="Each layer gives the elevation of its bottom. Sublayers split it into that many equal thicknesses."
      >
        <div className="mb-3 grid max-w-md grid-cols-2 gap-3">
          <Labelled label="Model top">
            <NumberInput
              value={grid.top}
              label="Model top"
              onCommit={(value) => editor.edit((draft) => void (draft.grid.top = value))}
            />
          </Labelled>
        </div>

        <table className="w-full max-w-2xl text-xs">
          <thead>
            <tr className="text-left text-[10px] text-zinc-500">
              <th className="pb-1 font-normal">Name</th>
              <th className="pb-1 font-normal">Bottom</th>
              <th className="pb-1 font-normal">Sublayers</th>
              <th className="pb-1 font-normal">Thickness</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {grid.layers.map((layer: ProjectDocument, index: number) => {
              const above = index === 0 ? grid.top : grid.layers[index - 1].bottom;
              return (
                <tr key={index} className="border-t border-zinc-800">
                  <td className="py-1 pr-3">
                    <TextInput
                      value={layer.name ?? ""}
                      placeholder={`layer ${index + 1}`}
                      label={`Layer ${index + 1} name`}
                      onCommit={(value) =>
                        editor.edit((draft) => void (draft.grid.layers[index].name = value || null))
                      }
                    />
                  </td>
                  <td className="py-1 pr-3">
                    <NumberInput
                      value={layer.bottom}
                      label={`Layer ${index + 1} bottom`}
                      onCommit={(value) =>
                        editor.edit((draft) => void (draft.grid.layers[index].bottom = value))
                      }
                    />
                  </td>
                  <td className="py-1 pr-3">
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
                  </td>
                  <td className="py-1 pr-3 tabular-nums text-zinc-500">
                    {(above - layer.bottom).toPrecision(4)}
                  </td>
                  <td className="py-1 text-right">
                    <button
                      type="button"
                      disabled={grid.layers.length === 1}
                      onClick={() =>
                        editor.edit((draft) => void draft.grid.layers.splice(index, 1))
                      }
                      title={
                        grid.layers.length === 1 ? "A model needs at least one layer" : "Remove"
                      }
                      className="text-[10px] text-zinc-500 hover:text-red-400 disabled:opacity-30"
                    >
                      remove
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        <button
          type="button"
          onClick={() =>
            editor.edit((draft) => {
              const last = draft.grid.layers[draft.grid.layers.length - 1];
              const above = draft.grid.layers.length === 1 ? draft.grid.top : last.bottom;
              const thickness = Math.abs(above - last.bottom) || 1;
              draft.grid.layers.push({
                name: null,
                bottom: last.bottom - thickness,
                sublayers: 1,
              });
            })
          }
          className="mt-2 rounded border border-zinc-700 px-2 py-1 text-[10px] text-zinc-300 hover:border-zinc-600"
        >
          Add layer
        </button>
      </Section>

      <Section title="Placement" hint="Where the grid sits in the world. Irrelevant to a column.">
        <div className="grid max-w-lg grid-cols-3 gap-3">
          <Labelled label="Origin x">
            <NumberInput
              value={grid.origin_x}
              label="Origin x"
              onCommit={(value) => editor.edit((draft) => void (draft.grid.origin_x = value))}
            />
          </Labelled>
          <Labelled label="Origin y">
            <NumberInput
              value={grid.origin_y}
              label="Origin y"
              onCommit={(value) => editor.edit((draft) => void (draft.grid.origin_y = value))}
            />
          </Labelled>
          <Labelled label="Rotation (degrees)">
            <NumberInput
              value={grid.rotation}
              label="Rotation"
              onCommit={(value) => editor.edit((draft) => void (draft.grid.rotation = value))}
            />
          </Labelled>
        </div>
      </Section>

      <GridSummary grid={grid} />
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
