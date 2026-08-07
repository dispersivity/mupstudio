import {
  EditorShell,
  Labelled,
  NoProject,
  NumberInput,
  Section,
  TextInput,
} from "./editor/controls";
import { useProjectDocument, type ProjectDocument } from "./editor/useProjectDocument";

/**
 * Stress periods.
 *
 * Adding or removing one invalidates any boundary whose value is given per
 * period, so those are listed with a fix rather than left to fail on save.
 */
export function TimeStep({
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
  if (!editor.document) return <div className="p-6 text-xs text-zinc-500">Loading…</div>;

  const time = editor.document.time;
  const periods = time.periods as ProjectDocument[];
  const unit = editor.document.meta.time_unit;
  const mismatched = mismatchedSeries(editor.document);

  return (
    <EditorShell
      title="Time"
      blurb={`How the simulation is divided in time. Each stress period holds the boundary conditions steady and is solved in the number of steps given. Lengths are in ${unit}.`}
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
      {mismatched.length > 0 && (
        <div className="mb-6 rounded border border-amber-900 bg-amber-950/30 p-3">
          <p className="text-xs text-amber-200">
            {mismatched.length === 1 ? "A boundary gives" : "Boundaries give"} a value per stress
            period, and the counts no longer match:
          </p>
          <ul className="mt-1 text-[11px] text-amber-300">
            {mismatched.map((item) => (
              <li key={`${item.id}-${item.field}`}>
                {item.id}.{item.field} — {item.given} value{item.given === 1 ? "" : "s"} for{" "}
                {periods.length} period{periods.length === 1 ? "" : "s"}
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => editor.edit((draft) => resizeSeries(draft))}
            className="mt-2 rounded border border-amber-700 px-2 py-1 text-[10px] text-amber-200 hover:border-amber-500"
          >
            Resize them, repeating the last value where needed
          </button>
        </div>
      )}

      <Section title="Stress periods">
        <table className="w-full max-w-3xl text-xs">
          <thead>
            <tr className="text-left text-[10px] text-zinc-500">
              <th className="pb-1 font-normal">#</th>
              <th className="pb-1 font-normal">Length</th>
              <th className="pb-1 font-normal">Steps</th>
              <th className="pb-1 font-normal" title="Each step this factor longer than the last">
                Multiplier
              </th>
              <th className="pb-1 font-normal">Steady</th>
              <th className="pb-1 font-normal">Ends at</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {periods.map((period, index) => (
              <tr key={index} className="border-t border-zinc-800">
                <td className="py-1 pr-3 tabular-nums text-zinc-500">{index + 1}</td>
                <td className="py-1 pr-3">
                  <NumberInput
                    value={period.perlen}
                    min={0}
                    label={`Period ${index + 1} length`}
                    onCommit={(value) =>
                      editor.edit((draft) => void (draft.time.periods[index].perlen = value))
                    }
                  />
                </td>
                <td className="py-1 pr-3">
                  <NumberInput
                    value={period.nstp}
                    min={1}
                    step={1}
                    label={`Period ${index + 1} steps`}
                    onCommit={(value) =>
                      editor.edit(
                        (draft) =>
                          void (draft.time.periods[index].nstp = Math.max(1, Math.round(value))),
                      )
                    }
                  />
                </td>
                <td className="py-1 pr-3">
                  <NumberInput
                    value={period.tsmult}
                    min={0}
                    label={`Period ${index + 1} multiplier`}
                    onCommit={(value) =>
                      editor.edit((draft) => void (draft.time.periods[index].tsmult = value))
                    }
                  />
                </td>
                <td className="py-1 pr-3">
                  <input
                    type="checkbox"
                    checked={period.steady}
                    aria-label={`Period ${index + 1} steady state`}
                    onChange={(event) =>
                      editor.edit(
                        (draft) => void (draft.time.periods[index].steady = event.target.checked),
                      )
                    }
                  />
                </td>
                <td className="py-1 pr-3 tabular-nums text-zinc-500">
                  {periods
                    .slice(0, index + 1)
                    .reduce((total, item) => total + item.perlen, 0)
                    .toPrecision(5)}
                </td>
                <td className="py-1 text-right">
                  <button
                    type="button"
                    disabled={periods.length === 1}
                    onClick={() => editor.edit((draft) => void draft.time.periods.splice(index, 1))}
                    title={
                      periods.length === 1
                        ? "A simulation needs at least one stress period"
                        : "Remove"
                    }
                    className="text-[10px] text-zinc-500 hover:text-red-400 disabled:opacity-30"
                  >
                    remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <button
          type="button"
          onClick={() =>
            editor.edit((draft) => {
              const last = draft.time.periods[draft.time.periods.length - 1];
              draft.time.periods.push({ ...last });
            })
          }
          className="mt-2 rounded border border-zinc-700 px-2 py-1 text-[10px] text-zinc-300 hover:border-zinc-600"
        >
          Add period (copies the last)
        </button>
      </Section>

      <Section
        title="Start date"
        hint="Optional, and only used to label output. The simulation itself runs in elapsed time."
      >
        <div className="max-w-xs">
          <Labelled label="ISO date">
            <TextInput
              value={time.start_datetime ?? ""}
              placeholder="2026-01-01"
              label="Start date"
              onCommit={(value) =>
                editor.edit((draft) => void (draft.time.start_datetime = value || null))
              }
            />
          </Labelled>
        </div>
      </Section>

      <div className="rounded border border-zinc-800 bg-zinc-900/50 p-3 text-xs">
        <span className="tabular-nums text-zinc-200">
          {periods.length} period{periods.length === 1 ? "" : "s"},{" "}
          {periods.reduce((total, item) => total + item.perlen, 0).toPrecision(5)} {unit}
        </span>
        <span className="ml-2 text-zinc-500">
          {periods.reduce((total, item) => total + item.nstp, 0)} time steps in total
        </span>
      </div>
    </EditorShell>
  );
}

interface Mismatch {
  id: string;
  field: string;
  given: number;
}

/** Per-period series whose length no longer matches the period count. */
function mismatchedSeries(document: ProjectDocument): Mismatch[] {
  const nper = (document.time.periods as unknown[]).length;
  const found: Mismatch[] = [];

  for (const item of document.flow.packages ?? []) {
    for (const field of ["rate", "head", "concentration"]) {
      const series = item[field];
      if (series?.kind === "per_period" && series.values.length !== nper) {
        found.push({ id: item.id, field, given: series.values.length });
      }
    }
  }
  return found;
}

/** Grow or trim each per-period series to the current period count. */
function resizeSeries(document: ProjectDocument): void {
  const nper = (document.time.periods as unknown[]).length;

  for (const item of document.flow.packages ?? []) {
    for (const field of ["rate", "head", "concentration"]) {
      const series = item[field];
      if (series?.kind !== "per_period") continue;

      const values = series.values as number[];
      while (values.length < nper) values.push(values[values.length - 1] ?? 0);
      series.values = values.slice(0, nper);
    }
  }
}
