import { Hint } from "./Hint";
import { NumberInput } from "./controls";

/**
 * A property that is either one number or a number per zone.
 *
 * Conductivity is the reason this exists. A real model almost never has one
 * conductivity, and until now the only way to vary it was to calibrate an
 * array somewhere else and point at the file — which works, and is no help at
 * all when what you want to say is "the sand is 12 and the clay is 0.0001".
 *
 * Zones are shared across properties on purpose, so this control lists the
 * project's zones rather than owning any. The sand is the sand for porosity
 * too, and two outlines of it would be two things to keep in step.
 */

export interface PropertyField {
  kind: "constant" | "zones" | "array";
  value?: number;
  default?: number;
  values?: Record<string, number>;
  path?: string;
}

export function PropertyValue({
  label,
  hint,
  field,
  zones,
  /** What an unset field falls back to, when something else supplies it. */
  inherited,
  onChange,
  onAddZone,
}: {
  label: string;
  hint?: string;
  field: PropertyField | null | undefined;
  zones: { id: string; label?: string }[];
  inherited?: number;
  onChange: (field: PropertyField) => void;
  /** Opens the zone editor, for when there are none yet. */
  onAddZone?: () => void;
}) {
  const kind = field?.kind ?? "constant";

  if (kind === "array") {
    // A calibrated array is a file, not something to retype here. Saying where
    // it comes from is more useful than a control that could only break it.
    return (
      <div>
        <span className="mb-0.5 flex items-center gap-1 text-[10px] text-zinc-500">
          {label}
          {hint && <Hint>{hint}</Hint>}
        </span>
        <p className="rounded border border-zinc-800 px-2 py-1 font-mono text-[10px] text-zinc-400">
          {field?.path}
        </p>
        <button
          type="button"
          onClick={() => onChange({ kind: "constant", value: 0 })}
          className="mt-1 text-[10px] text-sky-400 hover:text-sky-300"
        >
          use a value instead
        </button>
      </div>
    );
  }

  const zoned = kind === "zones";
  // An unset field shows what it will actually be — vertical conductivity
  // following the horizontal value, transport porosity following the flow one.
  // Showing 0 there says the model has no conductivity, which is a lie.
  const fallback = zoned ? (field?.default ?? 0) : (field?.value ?? inherited ?? 0);

  return (
    <div>
      <div className="mb-0.5 flex items-center gap-1">
        <span className="text-[10px] text-zinc-500">{label}</span>
        {hint && <Hint>{hint}</Hint>}
        <button
          type="button"
          onClick={() => {
            if (zoned) {
              onChange({ kind: "constant", value: fallback });
              return;
            }
            if (zones.length === 0) {
              onAddZone?.();
              return;
            }
            onChange({ kind: "zones", default: fallback, values: {} });
          }}
          className="ml-auto text-[10px] text-sky-400 hover:text-sky-300"
          title={
            zones.length === 0 && !zoned
              ? "Draw a zone first — the button opens the zone list"
              : undefined
          }
        >
          {zoned ? "one value" : "by zone"}
        </button>
      </div>

      <NumberInput
        value={fallback}
        label={zoned ? `${label} outside every zone` : label}
        onCommit={(value) =>
          onChange(zoned ? { ...field!, default: value } : { kind: "constant", value })
        }
      />

      {zoned && (
        <div className="mt-1.5 space-y-1 border-l border-zinc-800 pl-2">
          <p className="text-[10px] text-zinc-600">
            The value above applies where no zone reaches. Later zones win where two overlap.
          </p>
          {zones.map((zone) => {
            const set = field?.values?.[zone.id] !== undefined;
            return (
              <div key={zone.id} className="flex items-center gap-2">
                <span className="w-24 shrink-0 truncate text-[10px] text-zinc-400">
                  {zone.label || zone.id}
                </span>
                {set ? (
                  <>
                    <NumberInput
                      value={field!.values![zone.id]}
                      label={`${label} in ${zone.label || zone.id}`}
                      onCommit={(value) =>
                        onChange({
                          ...field!,
                          values: { ...field!.values, [zone.id]: value },
                        })
                      }
                    />
                    <button
                      type="button"
                      onClick={() => {
                        const next = { ...field!.values };
                        delete next[zone.id];
                        onChange({ ...field!, values: next });
                      }}
                      className="text-[10px] text-zinc-600 hover:text-red-400"
                    >
                      unset
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={() =>
                      onChange({
                        ...field!,
                        values: { ...field!.values, [zone.id]: fallback },
                      })
                    }
                    className="text-[10px] text-zinc-600 hover:text-sky-400"
                    // Not defaulted silently: a zone with no value here takes
                    // the fallback, and saying so is the whole point of the
                    // row existing while empty.
                    title="Give this zone its own value"
                  >
                    + set a value
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
