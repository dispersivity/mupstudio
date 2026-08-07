import { useMemo } from "react";
import { colormapCss, type ColormapName } from "@/viewport/scalars/colormap";

const TICKS = 5;

function formatValue(value: number): string {
  if (value === 0) return "0";
  const magnitude = Math.abs(value);
  if (magnitude < 1e-3 || magnitude >= 1e5) return value.toExponential(1);
  return value.toPrecision(3);
}

/**
 * Colour scale legend. Drawn in HTML over the canvas rather than in the render
 * pass: it changes rarely and never needs to be in the frame loop.
 */
export function Colorbar({
  colormap,
  vmin,
  vmax,
  unit,
  label,
}: {
  colormap: ColormapName;
  vmin: number;
  vmax: number;
  unit?: string;
  label?: string;
}) {
  const gradient = useMemo(() => {
    const stops = Array.from({ length: 16 }, (_, index) => {
      const t = index / 15;
      return `${colormapCss(colormap, t)} ${(t * 100).toFixed(1)}%`;
    });
    return `linear-gradient(to top, ${stops.join(", ")})`;
  }, [colormap]);

  const ticks = Array.from({ length: TICKS }, (_, index) => {
    const t = index / (TICKS - 1);
    return { t, value: vmin + (vmax - vmin) * t };
  });

  return (
    <div className="pointer-events-none absolute right-4 top-4 flex items-stretch gap-2 rounded bg-black/40 p-2 backdrop-blur-sm">
      <div className="h-40 w-4 rounded-sm" style={{ background: gradient }} />
      <div className="relative h-40 w-16 text-[10px] text-zinc-200">
        {ticks.map(({ t, value }) => (
          <div
            key={t}
            className="absolute left-0 -translate-y-1/2 tabular-nums"
            style={{ bottom: `${t * 100}%` }}
          >
            {formatValue(value)}
          </div>
        ))}
      </div>
      {(label || unit) && (
        <div className="self-end text-[10px] text-zinc-400">
          {label}
          {unit ? ` (${unit})` : ""}
        </div>
      )}
    </div>
  );
}
