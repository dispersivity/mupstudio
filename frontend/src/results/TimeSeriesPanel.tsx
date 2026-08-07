import { useMemo, useRef, useState } from "react";

export interface SeriesPoint {
  layer: number;
  cell: number;
  row: number | null;
  column: number | null;
  x: number;
  y: number;
  label: string;
  values: number[];
}

export interface SeriesResponse {
  component: string;
  unit: string;
  times: number[];
  structured: boolean;
  series: SeriesPoint[];
}

// Distinct enough to tell apart at a glance, and readable on a dark panel.
const COLOURS = ["#38bdf8", "#4ade80", "#f87171", "#fbbf24", "#c084fc", "#22d3ee"];

/**
 * Values through time at selected cells.
 *
 * A map answers "where is it now"; this answers "what happened here", which is
 * the question a breakthrough curve or an observation comparison asks.
 *
 * Drawn as an SVG rather than a chart library: a few hundred points per line
 * and no interaction beyond a crosshair does not justify the dependency.
 */
export function TimeSeriesPanel({
  data,
  loading,
  error,
  timeUnit,
  onRemove,
  onClear,
}: {
  data: SeriesResponse | null;
  loading: boolean;
  error: string | null;
  timeUnit: string;
  onRemove: (index: number) => void;
  onClear: () => void;
}) {
  if (error) {
    return (
      <PanelFrame>
        <p className="text-[11px] text-red-300">{error}</p>
      </PanelFrame>
    );
  }

  if (!data || data.series.length === 0) {
    return (
      <PanelFrame>
        <p className="text-[11px] leading-relaxed text-zinc-500">
          {loading
            ? "Loading…"
            : "No cells selected. Click a cell in the viewport, or add one by index or coordinate."}
        </p>
      </PanelFrame>
    );
  }

  return (
    <PanelFrame>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[10px] text-zinc-400">
          {data.component} <span className="text-zinc-600">({data.unit})</span>
        </span>
        <button
          type="button"
          onClick={onClear}
          className="text-[10px] text-zinc-500 hover:text-zinc-300"
        >
          clear
        </button>
      </div>

      <Chart data={data} timeUnit={timeUnit} />

      <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
        {data.series.map((point, index) => (
          <li key={point.label} className="flex items-center gap-1 text-[10px]">
            <span
              className="inline-block h-2 w-2 rounded-sm"
              style={{ background: COLOURS[index % COLOURS.length] }}
            />
            <span className="text-zinc-300">{point.label}</span>
            <button
              type="button"
              onClick={() => onRemove(index)}
              aria-label={`Remove ${point.label}`}
              className="text-zinc-600 hover:text-red-400"
            >
              ×
            </button>
          </li>
        ))}
      </ul>
    </PanelFrame>
  );
}

function PanelFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="pointer-events-auto absolute bottom-20 right-4 w-96 rounded bg-black/70 p-3 backdrop-blur-sm">
      {children}
    </div>
  );
}

const WIDTH = 352;
const HEIGHT = 150;
const PADDING = { left: 44, right: 6, top: 8, bottom: 20 };

function Chart({ data, timeUnit }: { data: SeriesResponse; timeUnit: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const svg = useRef<SVGSVGElement>(null);

  const { times, series } = data;

  const bounds = useMemo(() => {
    const all = series.flatMap((point) => point.values);
    const low = Math.min(...all);
    const high = Math.max(...all);
    // A flat line would otherwise collapse to zero height and vanish.
    const pad = high === low ? Math.abs(high) * 0.1 || 1 : (high - low) * 0.05;
    return { low: low - pad, high: high + pad };
  }, [series]);

  const plotWidth = WIDTH - PADDING.left - PADDING.right;
  const plotHeight = HEIGHT - PADDING.top - PADDING.bottom;

  const toX = (index: number) =>
    PADDING.left + (times.length <= 1 ? plotWidth / 2 : (index / (times.length - 1)) * plotWidth);
  const toY = (value: number) =>
    PADDING.top + plotHeight - ((value - bounds.low) / (bounds.high - bounds.low)) * plotHeight;

  return (
    <div>
      <svg
        ref={svg}
        width={WIDTH}
        height={HEIGHT}
        role="img"
        aria-label={`${data.component} through time`}
        onMouseMove={(event) => {
          const box = svg.current?.getBoundingClientRect();
          if (!box) return;
          const fraction = (event.clientX - box.left - PADDING.left) / plotWidth;
          const index = Math.round(fraction * (times.length - 1));
          setHover(index >= 0 && index < times.length ? index : null);
        }}
        onMouseLeave={() => setHover(null)}
      >
        <line
          x1={PADDING.left}
          y1={PADDING.top}
          x2={PADDING.left}
          y2={PADDING.top + plotHeight}
          stroke="#3f3f46"
        />
        <line
          x1={PADDING.left}
          y1={PADDING.top + plotHeight}
          x2={WIDTH - PADDING.right}
          y2={PADDING.top + plotHeight}
          stroke="#3f3f46"
        />

        <text x={2} y={PADDING.top + 8} fontSize={9} fill="#a1a1aa">
          {format(bounds.high)}
        </text>
        <text x={2} y={PADDING.top + plotHeight} fontSize={9} fill="#a1a1aa">
          {format(bounds.low)}
        </text>
        <text x={PADDING.left} y={HEIGHT - 6} fontSize={9} fill="#71717a">
          {format(times[0])}
        </text>
        <text x={WIDTH - PADDING.right} y={HEIGHT - 6} fontSize={9} fill="#71717a" textAnchor="end">
          {format(times[times.length - 1])} {timeUnit}
        </text>

        {series.map((point, index) => (
          <polyline
            key={point.label}
            fill="none"
            stroke={COLOURS[index % COLOURS.length]}
            strokeWidth={1.5}
            points={point.values.map((value, step) => `${toX(step)},${toY(value)}`).join(" ")}
          />
        ))}

        {hover !== null && (
          <>
            <line
              x1={toX(hover)}
              y1={PADDING.top}
              x2={toX(hover)}
              y2={PADDING.top + plotHeight}
              stroke="#52525b"
              strokeDasharray="2 2"
            />
            {series.map((point, index) => (
              <circle
                key={point.label}
                cx={toX(hover)}
                cy={toY(point.values[hover])}
                r={2.5}
                fill={COLOURS[index % COLOURS.length]}
              />
            ))}
          </>
        )}
      </svg>

      {hover !== null && (
        <div className="mt-0.5 text-[10px] tabular-nums text-zinc-400">
          t = {format(times[hover])} {timeUnit}
          {series.map((point, index) => (
            <span
              key={point.label}
              className="ml-2"
              style={{ color: COLOURS[index % COLOURS.length] }}
            >
              {format(point.values[hover])}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/** Cell picker: by index, or by coordinate. Clicking the viewport adds too. */
export function CellPicker({
  structured,
  onAdd,
}: {
  structured: boolean;
  onAdd: (token: string) => void;
}) {
  const [text, setText] = useState("");

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = text.trim();
    if (trimmed) {
      onAdd(trimmed);
      setText("");
    }
  };

  return (
    <form onSubmit={submit} className="space-y-1">
      <input
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder={structured ? "1:1:25 or @0.25:0.5" : "1:25 or @0.25:0.5"}
        aria-label="Add cell"
        className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-100"
      />
      <p className="text-[10px] leading-relaxed text-zinc-600">
        {structured ? "layer:row:column, layer:cell" : "layer:cell"}, or @x:y for the nearest cell.
        Indices count from one.
      </p>
    </form>
  );
}

function format(value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (value === 0) return "0";
  const magnitude = Math.abs(value);
  if (magnitude < 1e-3 || magnitude >= 1e5) return value.toExponential(2);
  return String(Number(value.toPrecision(4)));
}
