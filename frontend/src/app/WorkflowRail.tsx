import { IMPLEMENTED, STEPS, type StepId, type StepStatus } from "./workflow";

const DOT: Record<StepStatus, string> = {
  locked: "bg-zinc-700",
  empty: "bg-zinc-600",
  partial: "bg-amber-400",
  complete: "bg-emerald-400",
  stale: "bg-amber-500",
  error: "bg-red-500",
};

/**
 * The pipeline, top to bottom, with where you are and what is done.
 *
 * Steps stay clickable even when they have no data: the point is that the
 * whole workflow is visible from anywhere, not that it be walked in order.
 */
export function WorkflowRail({
  active,
  statuses,
  expanded,
  onSelect,
  onToggleExpanded,
}: {
  active: StepId;
  statuses: Partial<Record<StepId, StepStatus>>;
  expanded: boolean;
  onSelect: (step: StepId) => void;
  onToggleExpanded: () => void;
}) {
  return (
    <nav
      aria-label="Workflow"
      className={`flex shrink-0 flex-col border-r border-zinc-800 bg-zinc-900 transition-[width] ${
        expanded ? "w-52" : "w-14"
      }`}
    >
      <button
        type="button"
        onClick={onToggleExpanded}
        aria-label={expanded ? "Collapse workflow rail" : "Expand workflow rail"}
        className="flex h-12 items-center gap-3 border-b border-zinc-800 px-4 text-zinc-400 hover:text-zinc-100"
      >
        <span className="text-base leading-none">{expanded ? "«" : "»"}</span>
        {expanded && <span className="text-xs font-medium">MUP Studio</span>}
      </button>

      <ol className="flex-1 py-2">
        {STEPS.map((step, index) => {
          const status = statuses[step.id] ?? "empty";
          const isActive = step.id === active;
          const built = IMPLEMENTED.has(step.id);

          return (
            <li key={step.id}>
              <button
                type="button"
                onClick={() => onSelect(step.id)}
                title={expanded ? undefined : `${step.label} — ${step.purpose}`}
                aria-current={isActive ? "page" : undefined}
                className={`flex w-full items-center gap-3 px-4 py-2 text-left text-xs transition-colors ${
                  isActive
                    ? "bg-zinc-800 text-zinc-100"
                    : "text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200"
                }`}
              >
                <span className="w-3 shrink-0 text-right text-[10px] tabular-nums text-zinc-600">
                  {index + 1}
                </span>
                <span className={`h-2 w-2 shrink-0 rounded-full ${DOT[status]}`} />
                {expanded && (
                  <span className="flex-1 truncate">
                    {step.label}
                    {!built && <span className="ml-1 text-[10px] text-zinc-600">soon</span>}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
