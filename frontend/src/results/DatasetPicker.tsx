export interface RunSummary {
  id: string;
  label: string | null;
  engine: string;
  state: string;
  startedAt: string;
  hasResults: boolean;
}

export interface DatasetListing {
  demo: { id: string; kind: string };
  runs: RunSummary[];
}

const STATE_COLOUR: Record<string, string> = {
  succeeded: "text-emerald-400",
  running: "text-sky-400",
  queued: "text-zinc-400",
  failed: "text-red-400",
  cancelled: "text-amber-400",
  unknown: "text-amber-400",
};

/**
 * Choose what the viewport shows: the synthetic demo, or a run on disk.
 *
 * Runs without collected results are listed but not selectable, so a failed or
 * still-running model is visible rather than absent.
 */
export function DatasetPicker({
  listing,
  active,
  onSelect,
}: {
  listing: DatasetListing | null;
  active: string;
  onSelect: (datasetId: string) => void;
}) {
  const runs = listing?.runs ?? [];

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => onSelect("demo")}
        aria-pressed={active === "demo"}
        className={`w-full rounded border px-2 py-1.5 text-left ${
          active === "demo"
            ? "border-sky-500 bg-sky-500/10 text-zinc-100"
            : "border-zinc-700 text-zinc-300 hover:border-zinc-600"
        }`}
      >
        <div className="flex items-center justify-between">
          <span>Synthetic demo</span>
          <span className="text-[10px] text-amber-300">demo</span>
        </div>
      </button>

      {runs.length === 0 && (
        <p className="text-[10px] leading-relaxed text-zinc-600">
          No runs yet. Add one you ran elsewhere with{" "}
          <code className="text-zinc-500">mupstudio import-run &lt;directory&gt;</code>.
        </p>
      )}

      {runs.map((run) => (
        <button
          key={run.id}
          type="button"
          disabled={!run.hasResults}
          onClick={() => onSelect(run.id)}
          aria-pressed={active === run.id}
          title={run.hasResults ? undefined : "This run has no collected results"}
          className={`w-full rounded border px-2 py-1.5 text-left disabled:opacity-40 ${
            active === run.id
              ? "border-sky-500 bg-sky-500/10 text-zinc-100"
              : "border-zinc-700 text-zinc-300 enabled:hover:border-zinc-600"
          }`}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="truncate">{run.label || run.id}</span>
            <span className={`shrink-0 text-[10px] ${STATE_COLOUR[run.state] ?? "text-zinc-500"}`}>
              {run.state}
            </span>
          </div>
          <div className="text-[10px] text-zinc-600">{run.engine}</div>
        </button>
      ))}
    </div>
  );
}
