import type { DatasetCatalog } from "@/net/viewportClient";
import { sliceExtent, withIndex, type Slice, type ViewMode } from "./slice";

/**
 * Choosing what part of the model to look at.
 *
 * Plan, row and column rather than 3D by default, because the question in a
 * builder is "which cells", and an oblique view of a solid block cannot answer
 * it: the near faces hide the ones behind. One layer from above, or one row
 * from the side, hides nothing. 3D is for shape and extent, which you check
 * once and then stop looking at.
 */

const MODES: { id: ViewMode; label: string; title: string }[] = [
  { id: "plan", label: "Plan", title: "One layer, from above" },
  { id: "row", label: "Row", title: "One row of cells, from the front" },
  { id: "column", label: "Column", title: "One column of cells, from the side" },
  { id: "free", label: "3D", title: "The whole model, free to orbit" },
];

export function ViewControls({
  slice,
  catalog,
  onChange,
}: {
  slice: Slice;
  catalog: DatasetCatalog | null;
  onChange: (slice: Slice) => void;
}) {
  const extent = sliceExtent(slice, catalog);
  const structured = (catalog?.ncol ?? 0) > 0;

  return (
    <div className="flex items-center gap-2">
      <div className="flex overflow-hidden rounded border border-zinc-700">
        {MODES.map((mode) => {
          // Rows and columns only mean something on a structured grid.
          const usable = structured || mode.id === "plan" || mode.id === "free";
          return (
            <button
              key={mode.id}
              type="button"
              title={usable ? mode.title : "This grid has no rows or columns"}
              disabled={!usable}
              onClick={() => onChange({ ...slice, mode: mode.id })}
              className={`px-2 py-1 text-[10px] ${
                slice.mode === mode.id
                  ? "bg-zinc-700 text-zinc-100"
                  : "text-zinc-500 hover:text-zinc-300 disabled:opacity-30 disabled:hover:text-zinc-500"
              }`}
            >
              {mode.label}
            </button>
          );
        })}
      </div>

      {extent && extent.count > 1 && (
        <Stepper
          label={extent.label}
          index={extent.index}
          count={extent.count}
          onChange={(index) => onChange(withIndex(slice, index))}
        />
      )}
    </div>
  );
}

/**
 * Walking through slices one at a time.
 *
 * Arrows rather than a dropdown: stepping through layers to find the one with
 * the mistake in it is the whole task, and a dropdown makes it a two-click
 * operation per layer.
 */
function Stepper({
  label,
  index,
  count,
  onChange,
}: {
  label: string;
  index: number;
  count: number;
  onChange: (index: number) => void;
}) {
  const clamped = Math.min(index, count - 1);

  return (
    <div className="flex items-center gap-0.5 rounded border border-zinc-700 px-1">
      <button
        type="button"
        aria-label={`Previous ${label.toLowerCase()}`}
        disabled={clamped <= 0}
        onClick={() => onChange(clamped - 1)}
        className="px-1 text-[11px] text-zinc-400 hover:text-zinc-100 disabled:opacity-30"
      >
        &#8249;
      </button>
      <span className="min-w-20 text-center text-[10px] tabular-nums text-zinc-300">
        {label} {clamped + 1}
        <span className="text-zinc-600"> / {count}</span>
      </span>
      <button
        type="button"
        aria-label={`Next ${label.toLowerCase()}`}
        disabled={clamped >= count - 1}
        onClick={() => onChange(clamped + 1)}
        className="px-1 text-[11px] text-zinc-400 hover:text-zinc-100 disabled:opacity-30"
      >
        &#8250;
      </button>
    </div>
  );
}
