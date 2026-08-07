import { useState } from "react";
import { COLORMAP_NAMES, colormapCss, type ColormapName } from "@/viewport/scalars/colormap";
import type { DatasetCatalog } from "@/net/viewportClient";
import { DatasetPicker, type DatasetListing } from "@/results/DatasetPicker";

export interface ViewSettings {
  colormap: ColormapName;
  vmin: number;
  vmax: number;
  autoRange: boolean;
  logScale: boolean;
  /** Scale on z. Kept as its own name because it is the one people reach for. */
  verticalExaggeration: number;
  /**
   * Scale on x and y. Below 1 they squash, above 1 they stretch. A column
   * discretised 1 m across for tidy geometry renders as a slab until the wide
   * axis is squashed; a long thin reach reads better stretched the other way.
   */
  xExaggeration: number;
  yExaggeration: number;
  /** Outline cells, which is how you check a grid looks like you intended. */
  showEdges: boolean;
}

/**
 * Controls for how the field is drawn.
 *
 * Everything here maps to a method the viewport already exposes; each change
 * is one imperative call and one redraw, with no React involvement in the
 * frame itself.
 */
export function ViewportInspector({
  settings,
  dataRange,
  catalog,
  component,
  listing,
  onChange,
  onSelectComponent,
  onSelectDataset,
}: {
  settings: ViewSettings;
  dataRange: [number, number];
  catalog: DatasetCatalog;
  component: string;
  listing: DatasetListing | null;
  onChange: (next: Partial<ViewSettings>) => void;
  onSelectComponent: (name: string) => void;
  onSelectDataset?: (datasetId: string) => void;
}) {
  const unit = catalog.components.find((entry) => entry.name === component)?.unit ?? "";

  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-4 text-xs text-zinc-300">
      {onSelectDataset && (
        <Section title="Dataset">
          <DatasetPicker listing={listing} active={catalog.dataset} onSelect={onSelectDataset} />
        </Section>
      )}

      <Section title="Field">
        <Field label={`Component (${unit || "no unit"})`}>
          {catalog.components.length > 1 ? (
            <select
              value={component}
              onChange={(event) => onSelectComponent(event.target.value)}
              aria-label="Component"
              className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-zinc-100"
            >
              {catalog.components.map((entry) => (
                <option key={entry.name} value={entry.name}>
                  {entry.name}
                </option>
              ))}
            </select>
          ) : (
            <div className="text-zinc-100">{component}</div>
          )}
        </Field>
        <Field label="Grid">
          <span className="tabular-nums text-zinc-100">
            {catalog.ncells.toLocaleString()} cells, {catalog.nlay}{" "}
            {catalog.nlay === 1 ? "layer" : "layers"}
          </span>
        </Field>
        {catalog.warnings && catalog.warnings.length > 0 && (
          <Field label="Warnings">
            <ul className="space-y-1 text-[10px] text-amber-300">
              {catalog.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </Field>
        )}
      </Section>

      <Section title="Colour">
        <Field label="Colormap">
          <div className="grid grid-cols-2 gap-1">
            {COLORMAP_NAMES.map((name) => (
              <button
                key={name}
                type="button"
                onClick={() => onChange({ colormap: name })}
                aria-pressed={settings.colormap === name}
                className={`flex items-center gap-2 rounded border px-2 py-1 text-left ${
                  settings.colormap === name
                    ? "border-sky-500 bg-sky-500/10 text-zinc-100"
                    : "border-zinc-700 hover:border-zinc-600"
                }`}
              >
                <span
                  className="h-3 w-6 shrink-0 rounded-sm"
                  style={{ background: rampPreview(name) }}
                />
                {name}
              </button>
            ))}
          </div>
        </Field>

        <Field label="Range">
          <label className="mb-2 flex items-center gap-2">
            <input
              type="checkbox"
              checked={settings.autoRange}
              onChange={(event) => {
                const auto = event.target.checked;
                onChange(
                  auto
                    ? { autoRange: true, vmin: dataRange[0], vmax: dataRange[1] }
                    : { autoRange: false },
                );
              }}
            />
            <span>Auto from data</span>
          </label>
          <div className="flex items-center gap-2">
            <NumberInput
              value={settings.vmin}
              disabled={settings.autoRange}
              onCommit={(value) => onChange({ vmin: value })}
              label="Minimum"
            />
            <span className="text-zinc-600">to</span>
            <NumberInput
              value={settings.vmax}
              disabled={settings.autoRange}
              onCommit={(value) => onChange({ vmax: value })}
              label="Maximum"
            />
          </div>
        </Field>

        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={settings.logScale}
            onChange={(event) => onChange({ logScale: event.target.checked })}
          />
          <span>Logarithmic scale</span>
        </label>
      </Section>

      <Section title="Geometry">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={settings.showEdges}
            onChange={(event) => onChange({ showEdges: event.target.checked })}
          />
          <span>Cell edges</span>
        </label>

        {catalog.thinAxis && (
          <p className="rounded bg-zinc-800/60 px-2 py-1.5 text-[10px] leading-relaxed text-zinc-400">
            This grid is one cell across <span className="text-zinc-200">{catalog.thinAxis}</span>.
            Squashing that axis makes the profile readable. Scaling changes only the picture, never
            the model.
          </p>
        )}

        <AxisSlider
          axis="x"
          value={settings.xExaggeration}
          onChange={(value) => onChange({ xExaggeration: value })}
        />
        <AxisSlider
          axis="y"
          value={settings.yExaggeration}
          onChange={(value) => onChange({ yExaggeration: value })}
        />
        <AxisSlider
          axis="z"
          value={settings.verticalExaggeration}
          onChange={(value) => onChange({ verticalExaggeration: value })}
        />

        {(settings.xExaggeration !== 1 ||
          settings.yExaggeration !== 1 ||
          settings.verticalExaggeration !== 1) && (
          <button
            type="button"
            onClick={() =>
              onChange({ xExaggeration: 1, yExaggeration: 1, verticalExaggeration: 1 })
            }
            className="rounded border border-zinc-700 px-2 py-1 text-[10px] text-zinc-400 hover:border-zinc-600 hover:text-zinc-200"
          >
            Reset to true scale
          </button>
        )}
      </Section>

      <p className="mt-auto text-[10px] leading-relaxed text-zinc-600">
        Drag to orbit, shift-drag to pan, scroll to zoom. Space plays, arrow keys step through time.
      </p>
    </div>
  );
}

/**
 * One axis scale, on a log slider.
 *
 * Logarithmic because the useful range spans two orders of magnitude in each
 * direction, and a linear slider would bury everything below 1 in a few pixels.
 */
function AxisSlider({
  axis,
  value,
  onChange,
}: {
  axis: "x" | "y" | "z";
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <Field label={`${axis} exaggeration ${formatScale(value)}`}>
      <input
        type="range"
        min={Math.log10(MIN_SCALE)}
        max={Math.log10(MAX_SCALE)}
        step={0.02}
        value={Math.log10(value)}
        onChange={(event) => onChange(snapScale(10 ** Number(event.target.value)))}
        className="w-full accent-sky-400"
        aria-label={`${axis} exaggeration`}
      />
    </Field>
  );
}

const MIN_SCALE = 0.01;
const MAX_SCALE = 100;

/** Land exactly on 1 near the middle, so true scale is reachable by dragging. */
function snapScale(scale: number): number {
  return Math.abs(scale - 1) < 0.03 ? 1 : scale;
}

function formatScale(scale: number): string {
  if (scale === 1) return "1x (true)";
  if (scale < 1) return `1/${(1 / scale).toFixed(scale < 0.1 ? 0 : 1)}`;
  return `${scale.toFixed(scale < 10 ? 1 : 0)}x`;
}

function rampPreview(name: ColormapName): string {
  const stops = [0, 0.25, 0.5, 0.75, 1]
    .map((t) => `${colormapCss(name, t)} ${t * 100}%`)
    .join(", ");
  return `linear-gradient(to right, ${stops})`;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">{title}</h3>
      {children}
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-zinc-500">{label}</div>
      {children}
    </div>
  );
}

/** Commits on blur or Enter rather than per keystroke, so typing "1e-" is fine. */
function NumberInput({
  value,
  disabled,
  label,
  onCommit,
}: {
  value: number;
  disabled?: boolean;
  label: string;
  onCommit: (value: number) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);

  const commit = () => {
    if (draft === null) return;
    const parsed = Number(draft);
    if (Number.isFinite(parsed)) onCommit(parsed);
    setDraft(null);
  };

  return (
    <input
      type="text"
      inputMode="decimal"
      aria-label={label}
      disabled={disabled}
      value={draft ?? formatNumber(value)}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit();
        if (event.key === "Escape") setDraft(null);
      }}
      className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 tabular-nums text-zinc-100 disabled:opacity-40"
    />
  );
}

function formatNumber(value: number): string {
  if (value === 0) return "0";
  const magnitude = Math.abs(value);
  if (magnitude < 1e-3 || magnitude >= 1e5) return value.toExponential(2);
  return String(Number(value.toPrecision(4)));
}
