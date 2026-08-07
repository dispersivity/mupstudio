/** An empty tab that says what belongs there and offers the one action. */
export function Empty({
  message,
  action,
  onAction,
}: {
  message: string;
  action: string;
  onAction: () => void;
}) {
  return (
    <div className="max-w-lg rounded border border-dashed border-zinc-800 p-6">
      <p className="text-[11px] leading-relaxed text-zinc-500">{message}</p>
      <button
        type="button"
        onClick={onAction}
        className="mt-3 rounded bg-sky-600 px-3 py-1 text-xs font-medium text-white hover:bg-sky-500"
      >
        {action}
      </button>
    </div>
  );
}
