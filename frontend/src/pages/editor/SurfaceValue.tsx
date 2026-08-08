import { Hint } from "./Hint";
import { NumberInput, Select } from "./controls";

/**
 * Where a layer's top or bottom comes from.
 *
 * A column has flat layers and one number says it all. A model of a real place
 * almost never does, and until this control existed the only way to say so was
 * to hand-write the TOML — so every field model started life as a flat slab
 * with the topography thrown away.
 *
 * The offset option is the one that gets used most. "The ground, then twenty
 * metres down, then to the base of the alluvium" keeps the layers parallel to
 * the topography, which is what a layer usually is.
 */

export interface Surface {
  kind: "constant" | "raster" | "points" | "offset";
  value?: number;
  source?: string;
  band?: number;
  fill?: number | null;
  offset?: number;
  column?: string;
  power?: number;
  neighbours?: number;
  thickness?: number;
}

const KINDS = [
  {
    kind: "constant",
    label: "Value",
    hint: "One elevation everywhere. What a column or a box uses.",
  },
  {
    kind: "raster",
    label: "Raster",
    hint: "Sampled from an imported raster at each cell centre — a DEM for the model top, an interpolated surface for a contact.",
  },
  {
    kind: "points",
    label: "Points",
    hint: "Interpolated from a table of measurements: borehole tops, picked contacts. Inverse distance, so it never overshoots the data.",
  },
  {
    kind: "offset",
    label: "Below above",
    hint: "A fixed thickness below the surface above it. This is what keeps a layer parallel to the topography instead of flat.",
  },
] as const;

export function SurfaceValue({
  label,
  surface,
  sources,
  /** Offsets need something above them, so the model top cannot use one. */
  allowOffset = true,
  onChange,
}: {
  label: string;
  surface: Surface | number | null | undefined;
  sources: { id: string; name: string; kind?: string; fields?: string[] }[];
  allowOffset?: boolean;
  onChange: (surface: Surface) => void;
}) {
  // Older projects wrote a bare number, and the schema still accepts one.
  const value: Surface =
    typeof surface === "number"
      ? { kind: "constant", value: surface }
      : (surface ?? { kind: "constant", value: 0 });

  const rasters = sources.filter((item) => item.kind === "raster");
  const tables = sources.filter((item) => item.kind === "points");

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1">
        <span className="text-[10px] text-zinc-500">{label}</span>
        {KINDS.filter((item) => allowOffset || item.kind !== "offset").map((item) => {
          const missing =
            (item.kind === "raster" && rasters.length === 0) ||
            (item.kind === "points" && tables.length === 0);
          return (
            <button
              key={item.kind}
              type="button"
              disabled={missing}
              title={missing ? "Import one on the Data step first" : item.hint}
              onClick={() => onChange(startOf(item.kind, value, rasters[0]?.id, tables[0]?.id))}
              className={`rounded px-1.5 py-0.5 text-[10px] ${
                value.kind === item.kind
                  ? "bg-zinc-800 text-sky-300"
                  : missing
                    ? "text-zinc-700"
                    : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {item.label}
            </button>
          );
        })}
        <Hint>{KINDS.find((item) => item.kind === value.kind)?.hint ?? ""}</Hint>
      </div>

      {value.kind === "constant" && (
        <NumberInput
          value={value.value ?? 0}
          label={label}
          onCommit={(next) => onChange({ kind: "constant", value: next })}
        />
      )}

      {value.kind === "offset" && (
        <div className="flex items-center gap-2">
          <NumberInput
            value={value.thickness ?? 1}
            label={`${label} thickness`}
            onCommit={(next) => onChange({ kind: "offset", thickness: Math.max(1e-6, next) })}
          />
          <span className="text-[10px] text-zinc-600">below the surface above</span>
        </div>
      )}

      {value.kind === "raster" && (
        <div className="flex items-center gap-2">
          <Select
            value={value.source ?? ""}
            label={`${label} raster`}
            options={rasters.map((item) => ({ value: item.id, label: item.name }))}
            onChange={(next) => onChange({ ...value, source: next })}
          />
          <span className="text-[10px] text-zinc-600">shift</span>
          <NumberInput
            value={value.offset ?? 0}
            label={`${label} shift`}
            onCommit={(next) => onChange({ ...value, offset: next })}
          />
        </div>
      )}

      {value.kind === "points" && (
        <div className="flex items-center gap-2">
          <Select
            value={value.source ?? ""}
            label={`${label} points`}
            options={tables.map((item) => ({ value: item.id, label: item.name }))}
            onChange={(next) => onChange({ ...value, source: next, column: "" })}
          />
          <Select
            value={value.column ?? ""}
            label={`${label} column`}
            options={(tables.find((item) => item.id === value.source)?.fields ?? []).map(
              (field) => ({ value: field, label: field }),
            )}
            onChange={(next) => onChange({ ...value, column: next })}
          />
        </div>
      )}
    </div>
  );
}

/** A fresh surface of a kind, keeping what carries across. */
function startOf(
  kind: Surface["kind"],
  previous: Surface,
  firstRaster?: string,
  firstTable?: string,
): Surface {
  if (kind === "constant") return { kind, value: previous.value ?? 0 };
  if (kind === "offset") return { kind, thickness: previous.thickness ?? 10 };
  if (kind === "raster") return { kind, source: previous.source ?? firstRaster ?? "", offset: 0 };
  return { kind, source: firstTable ?? "", column: "", power: 2, neighbours: 8 };
}

/**
 * A surface said in one line, for a summary or a list row.
 *
 * A sampled surface has no single elevation to show, so it names where it
 * comes from instead — which is more useful than a number that would have to
 * be an average of a hundred thousand cells.
 */
export function describeSurface(surface: Surface | number | null | undefined): string {
  if (typeof surface === "number") return String(surface);
  if (!surface) return "\u2014";
  if (surface.kind === "constant") return String(surface.value ?? 0);
  if (surface.kind === "offset") return `${surface.thickness ?? 0} below`;
  if (surface.kind === "raster") return `from ${surface.source ?? "a raster"}`;
  return `from ${surface.source ?? "points"}${surface.column ? "." + surface.column : ""}`;
}
