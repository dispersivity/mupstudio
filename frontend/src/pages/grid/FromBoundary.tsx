import { useEffect, useState } from "react";
import {
  fetchData,
  gridFromBoundary,
  type DataSource,
  type GeneratedGrid,
} from "@/data/dataClient";
import { Labelled, NumberInput, Section } from "../editor/controls";
import { Outcome } from "@/sim/Prerequisites";

/**
 * Turning an imported boundary into a grid.
 *
 * The alternative is what everyone does by hand: read the shapefile's extent
 * out of a GIS, divide by the cell size, type four numbers into a form, and
 * find out later that the origin was wrong. Here the polygon supplies the
 * extent and the origin, and you choose only the thing that is a modelling
 * decision — how big a cell should be.
 *
 * The count is shown before anything is written. Cell size is the one number
 * people try three times, and a preview that costs nothing is what makes trying
 * it reasonable.
 */
export function FromBoundary({ path, onApplied }: { path: string; onApplied: () => void }) {
  const [areas, setAreas] = useState<DataSource[]>([]);
  const [source, setSource] = useState<string | null>(null);
  const [cellSize, setCellSize] = useState<number | null>(null);
  const [margin, setMargin] = useState(0);
  const [result, setResult] = useState<GeneratedGrid | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchData(path)
      .then((state) => {
        const polygons = state.sources.filter(
          (item) => item.kind === "vector" && item.geometry === "polygon",
        );
        setAreas(polygons);
        setSource((current) => current ?? polygons[0]?.id ?? null);
      })
      .catch(() => setAreas([]));
  }, [path]);

  const run = async (apply: boolean) => {
    if (!source) return;
    setBusy(true);
    setError(null);
    try {
      const generated = await gridFromBoundary(path, {
        source,
        cellSize: cellSize ?? undefined,
        margin,
        apply,
      });
      setResult(generated);
      // The server picks a cell size when none is given; showing it back means
      // the next preview starts from what was actually used.
      setCellSize(generated.cellSize);
      if (apply) onApplied();
    } catch (problem) {
      setError((problem as Error).message);
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  if (areas.length === 0) {
    return (
      <Section
        title="From a boundary"
        hint="Import an area on the Data step and the grid can be built to cover it."
      >
        <p className="max-w-md text-[11px] leading-relaxed text-zinc-600">
          No areas imported. A catchment outline is the usual one; it supplies the extent and the
          origin, so the only thing left to choose is how big a cell should be.
        </p>
      </Section>
    );
  }

  return (
    <Section
      title="From a boundary"
      hint="Covers the area with square cells. Cells whose centre falls outside it are left out of the model."
    >
      <div className="flex max-w-2xl flex-wrap items-end gap-3">
        <label className="block w-44">
          <span className="mb-1 block text-[10px] text-zinc-500">Area</span>
          <select
            value={source ?? ""}
            aria-label="Boundary to cover"
            onChange={(event) => {
              setSource(event.target.value);
              setResult(null);
            }}
            className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-100 focus:border-sky-600 focus:outline-none"
          >
            {areas.map((area) => (
              <option key={area.id} value={area.id}>
                {area.label}
              </option>
            ))}
          </select>
        </label>

        <Labelled label="Cell size" hint="In the model's own units.">
          <NumberInput
            value={cellSize ?? 0}
            label="Cell size"
            onCommit={(value) => {
              setCellSize(value);
              setResult(null);
            }}
          />
        </Labelled>

        <Labelled label="Margin" hint="Extends the grid past the boundary.">
          <NumberInput
            value={margin}
            label="Margin"
            onCommit={(value) => {
              setMargin(value);
              setResult(null);
            }}
          />
        </Labelled>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          disabled={busy || !source}
          onClick={() => void run(false)}
          className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-300 hover:border-zinc-600 disabled:opacity-40"
        >
          {cellSize ? "Count cells" : "Suggest a size"}
        </button>
        <button
          type="button"
          disabled={busy || !source}
          onClick={() => void run(true)}
          className="rounded bg-sky-600 px-3 py-1 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-40"
        >
          Build the grid
        </button>
        {busy && <span className="text-[10px] text-zinc-500">working…</span>}
      </div>

      <Outcome>
        {result ? `${result.summary}${result.applied ? "" : " — not saved yet"}` : null}
      </Outcome>

      {result?.warnings.map((warning) => (
        <p key={warning} className="mt-1 text-[10px] text-amber-300">
          {warning}
        </p>
      ))}

      {error && <p className="mt-1.5 max-w-md text-[10px] leading-relaxed text-red-300">{error}</p>}

      {result?.applied && (
        <p className="mt-1.5 text-[10px] leading-relaxed text-zinc-600">
          Cells outside the boundary are still in the grid. Making them inactive needs IDOMAIN,
          which is not written yet.
        </p>
      )}
    </Section>
  );
}
