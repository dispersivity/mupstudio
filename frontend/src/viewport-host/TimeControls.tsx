import { useEffect } from "react";

/**
 * Play, scrub and step through time.
 *
 * The slider writes straight to the viewport (a bind-group swap) and keeps the
 * index in React state only so the label and the thumb position render. No
 * array ever passes through here.
 */
export function TimeControls({
  timestep,
  times,
  playing,
  timeStride,
  onSeek,
  onTogglePlay,
}: {
  timestep: number;
  times: number[];
  playing: boolean;
  timeStride: number;
  onSeek: (index: number) => void;
  onTogglePlay: () => void;
}) {
  const last = Math.max(times.length - 1, 0);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement) return;
      if (event.code === "Space") {
        event.preventDefault();
        onTogglePlay();
      } else if (event.code === "ArrowLeft") {
        onSeek(Math.max(0, timestep - 1));
      } else if (event.code === "ArrowRight") {
        onSeek(Math.min(last, timestep + 1));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [timestep, last, onSeek, onTogglePlay]);

  return (
    <div className="absolute inset-x-4 bottom-4 flex items-center gap-3 rounded bg-black/40 px-3 py-2 backdrop-blur-sm">
      <button
        type="button"
        onClick={onTogglePlay}
        aria-label={playing ? "Pause" : "Play"}
        className="rounded px-2 py-1 text-sm text-zinc-100 hover:bg-white/10"
      >
        {playing ? "❚❚" : "▶"}
      </button>

      <input
        type="range"
        min={0}
        max={last}
        step={1}
        value={timestep}
        onChange={(event) => onSeek(Number(event.target.value))}
        aria-label="Timestep"
        className="flex-1 accent-sky-400"
      />

      <span className="w-32 text-right text-xs tabular-nums text-zinc-300">
        t = {times[timestep]?.toFixed(1) ?? "—"} ({timestep + 1}/{times.length})
      </span>

      {timeStride > 1 && (
        <span
          className="rounded bg-amber-500/20 px-2 py-0.5 text-[10px] text-amber-200"
          title="The full run did not fit in GPU memory, so every Nth step was loaded."
        >
          1 of {timeStride} steps
        </span>
      )}
    </div>
  );
}
