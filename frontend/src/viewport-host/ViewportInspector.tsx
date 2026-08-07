import { useState } from "react";
import { COLORMAP_NAMES, colormapCss, type ColormapName } from "@/viewport/scalars/colormap";

export interface ViewSettings {
  colormap: ColormapName;
  vmin: number;
  vmax: number;
  autoRange: boolean;
  logScale: boolean;
  verticalExaggeration: number;
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
  cells,
  layers,
  component,
  unit,
  onChange,
}: {
  settings: ViewSettings;
  dataRange: [number, number];
  cells: number;
  layers: number;
  component: string;
  unit: string;
  onChange: (next: Partial<ViewSettings>) => void;
}) {
  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-4 text-xs text-zinc-300">
      <Section title="Field">
        <Field label="Component">
          <div className="text-zinc-100">
            {component} <span className="text-zinc-500">({unit})</span>
          </div>
        </Field>
        <Field label="Cells">
          <span className="tabular-nums text-zinc-100">
            {cells.toLocaleString()} in {layers} layers
          </span>
        </Field>
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
        <Field label={`Vertical exaggeration ${settings.verticalExaggeration.toFixed(1)}x`}>
          <input
            type="range"
            min={0.5}
            max={20}
            step={0.5}
            value={settings.verticalExaggeration}
            onChange={(event) => onChange({ verticalExaggeration: Number(event.target.value) })}
            className="w-full accent-sky-400"
            aria-label="Vertical exaggeration"
          />
        </Field>
      </Section>

      <p className="mt-auto text-[10px] leading-relaxed text-zinc-600">
        Drag to orbit, shift-drag to pan, scroll to zoom. Space plays, arrow keys step through time.
      </p>
    </div>
  );
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
