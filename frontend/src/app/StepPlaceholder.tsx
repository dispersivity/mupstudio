import { STEP_BY_ID, type StepId } from "./workflow";

/**
 * Stands in for a step that has not been built yet.
 *
 * It says which milestone builds it rather than showing a blank panel or a
 * dead form: an empty screen reads as broken, a stated plan reads as a plan.
 */
export function StepPlaceholder({
  step,
  onGoToResults,
}: {
  step: StepId;
  onGoToResults: () => void;
}) {
  const definition = STEP_BY_ID.get(step);
  if (!definition) return null;

  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="max-w-md space-y-4">
        <div>
          <h2 className="text-lg font-medium text-zinc-100">{definition.label}</h2>
          <p className="mt-1 text-sm text-zinc-400">{definition.purpose}</p>
        </div>

        <div className="rounded border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-xs text-zinc-400">
            Not built yet — this arrives in{" "}
            <span className="font-medium text-zinc-200">{definition.milestone}</span>.
          </p>
          {definition.dependsOn.length > 0 && (
            <p className="mt-2 text-xs text-zinc-500">
              Will need: {definition.dependsOn.join(", ")}.
            </p>
          )}
        </div>

        <button
          type="button"
          onClick={onGoToResults}
          className="rounded border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:border-zinc-600 hover:text-zinc-100"
        >
          Go to Results, which works today
        </button>
      </div>
    </div>
  );
}
