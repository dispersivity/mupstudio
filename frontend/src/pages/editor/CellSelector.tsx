import { useEffect, useState } from "react";
import { Hint } from "./Hint";
import { TextInput, NumberInput, Select } from "./controls";
import type { Limits } from "./grid";
import {
  SELECTION_MODES,
  emptySelection,
  formatIndexList,
  parseIndexList,
  type CellSelection,
} from "./selection";

/**
 * Where something applies, however the modeller wants to say it.
 *
 * One control for every part of the model that covers only part of the grid: a
 * well field, a fixed-head edge, a conductivity zone, an initial water. They
 * are the same question, and having three dialogs for it was the thing that
 * made zones feel like a different feature from boundaries when they are not.
 *
 * The count under the control is the point of it. A range typed in three boxes
 * is easy to get wrong by an order of magnitude, and "4 cells" versus "400
 * cells" is the difference nobody notices in the numbers themselves.
 */
export function CellSelector({
  selection,
  limits,
  sources,
  picking,
  onPick,
  onChange,
  path,
}: {
  selection: CellSelection | null;
  limits: Limits;
  /** Imported data that a shape selection can be drawn from. */
  sources: { id: string; name: string; geometry?: string }[];
  /** Whether clicks in the viewport are currently adding to this selection. */
  picking: boolean;
  onPick: (on: boolean) => void;
  onChange: (selection: CellSelection) => void;
  path: string | null;
}) {
  const resolved = useResolvedCount(path, selection);

  if (!selection) return null;

  const mode = SELECTION_MODES.find((item) => item.kind === selection.kind) ?? SELECTION_MODES[0];

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-2">
      <div className="mb-2 flex items-center gap-1">
        <span className="mr-1 text-[10px] uppercase tracking-wider text-zinc-600">Cells</span>
        {SELECTION_MODES.map((item) => {
          // Nothing to intersect with is not a mode worth offering; the Data
          // step is where that gets fixed, and the hint says so.
          const unavailable = item.kind === "shape" && sources.length === 0;
          return (
            <button
              key={item.kind}
              type="button"
              disabled={unavailable}
              title={unavailable ? "Import something on the Data step first" : item.hint}
              onClick={() => {
                onPick(item.kind === "list");
                onChange(emptySelection(item.kind, selection, sources[0]?.id ?? ""));
              }}
              className={`rounded px-1.5 py-0.5 text-[10px] ${
                selection.kind === item.kind
                  ? "bg-zinc-800 text-sky-300"
                  : unavailable
                    ? "text-zinc-700"
                    : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {item.label}
            </button>
          );
        })}
        <Hint>{mode.hint}</Hint>
      </div>

      {selection.kind === "cells" && (
        <div className="grid grid-cols-3 gap-2">
          {(["layers", "rows", "columns"] as const).map((axis) => (
            <label key={axis} className="block">
              <span className="mb-0.5 block text-[10px] text-zinc-500">
                {axis} <span className="text-zinc-700">1-{limits[axis]}</span>
              </span>
              <TextInput
                value={formatIndexList(selection[axis])}
                label={`${axis}, 1 to ${limits[axis]}`}
                onCommit={(text) => {
                  const parsed = parseIndexList(text, limits[axis]);
                  // An empty axis would mean a selection of nothing, which is
                  // never what a blank field was meant to say.
                  if (parsed.length > 0) onChange({ ...selection, [axis]: parsed });
                }}
              />
            </label>
          ))}
        </div>
      )}

      {selection.kind === "list" && (
        <div>
          <button
            type="button"
            onClick={() => onPick(!picking)}
            className={`rounded border px-2 py-1 text-[10px] ${
              picking
                ? "border-sky-600 bg-sky-950/40 text-sky-300"
                : "border-zinc-700 text-zinc-300 hover:border-zinc-600"
            }`}
          >
            {picking ? "Picking — click cells, or stop" : "Pick in the viewport"}
          </button>
          {selection.indices.length > 0 && (
            <button
              type="button"
              onClick={() => onChange({ kind: "list", indices: [] })}
              className="ml-2 text-[10px] text-zinc-500 hover:text-red-400"
            >
              clear
            </button>
          )}
          <p className="mt-1 text-[10px] leading-relaxed text-zinc-600">
            {picking
              ? "Clicking a picked cell again removes it. Drag still turns and pans the view."
              : "Cells clicked in the viewport. Switch to the layer or section you want first."}
          </p>
        </div>
      )}

      {selection.kind === "shape" && (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="mb-0.5 block text-[10px] text-zinc-500">Shape</span>
              <Select
                value={selection.source}
                label="Data source"
                options={sources.map((item) => ({
                  value: item.id,
                  label: item.geometry ? `${item.name} (${item.geometry})` : item.name,
                }))}
                onChange={(value) => onChange({ ...selection, source: value })}
              />
            </label>
            <label className="block">
              <span className="mb-0.5 block text-[10px] text-zinc-500">
                layers <span className="text-zinc-700">1-{limits.layers}</span>
              </span>
              <TextInput
                value={formatIndexList(selection.layers)}
                label={`layers, 1 to ${limits.layers}`}
                onCommit={(text) => {
                  const parsed = parseIndexList(text, limits.layers);
                  if (parsed.length > 0) onChange({ ...selection, layers: parsed });
                }}
              />
            </label>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="mb-0.5 flex items-center gap-1 text-[10px] text-zinc-500">
                Rule
                <Hint>
                  Touches takes every cell the shape reaches, which is what a line or a point needs.
                  Centre only takes cells whose middle it covers, which is what an area needs: a
                  cell mostly outside a zone should not take the zone&apos;s properties.
                </Hint>
              </span>
              <Select
                value={selection.rule}
                label="Selection rule"
                options={[
                  { value: "intersects", label: "Touches the cell" },
                  { value: "centroid", label: "Covers the centre" },
                ]}
                onChange={(value) =>
                  onChange({ ...selection, rule: value as "intersects" | "centroid" })
                }
              />
            </label>
            <label className="block">
              <span className="mb-0.5 flex items-center gap-1 text-[10px] text-zinc-500">
                Buffer
                <Hint>
                  Widen the shape by this distance first, in the model&apos;s length units. A river
                  drawn as a line with a 50 m buffer catches its floodplain too.
                </Hint>
              </span>
              <NumberInput
                value={selection.buffer}
                label="Buffer distance"
                onCommit={(value) => onChange({ ...selection, buffer: Math.max(0, value) })}
              />
            </label>
          </div>
        </div>
      )}

      <p className="mt-1.5 text-[10px] text-zinc-500">
        {resolved.status === "loading" && "counting…"}
        {resolved.status === "failed" && <span className="text-amber-500">{resolved.detail}</span>}
        {resolved.status === "ready" && (
          <span className={resolved.count === 0 ? "text-amber-500" : ""}>
            {resolved.count === 0
              ? "selects no cells"
              : `${resolved.count.toLocaleString()} cell${resolved.count === 1 ? "" : "s"}`}
          </span>
        )}
      </p>
    </div>
  );
}

type Resolved =
  { status: "loading" } | { status: "ready"; count: number } | { status: "failed"; detail: string };

/**
 * How many cells a selection actually covers, asked of the server.
 *
 * A range could be counted here, and is — but a shape cannot be, and having
 * two answers to the same question is how a preview ends up disagreeing with
 * what gets written. The server resolves both with the code that writes the
 * model, so the number under the control is the number MODFLOW will see.
 */
function useResolvedCount(path: string | null, selection: CellSelection | null): Resolved {
  const [state, setState] = useState<Resolved>({ status: "loading" });
  const key = JSON.stringify(selection);

  useEffect(() => {
    if (!path || !selection) return;

    let cancelled = false;
    setState({ status: "loading" });

    // Typing in a range field fires on every commit; a shape resolve reads a
    // file and reprojects it, so a short wait keeps that off the keystroke.
    const timer = setTimeout(() => {
      fetch(`/api/v1/projects/selection/resolve?path=${encodeURIComponent(path)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ selection: JSON.parse(key) }),
      })
        .then(async (response) => {
          if (!response.ok) throw new Error(await response.text());
          return response.json();
        })
        .then((result) => {
          if (cancelled) return;
          setState(
            result.problem
              ? { status: "failed", detail: result.problem }
              : { status: "ready", count: result.count },
          );
        })
        .catch((error) => {
          if (!cancelled) setState({ status: "failed", detail: String(error.message ?? error) });
        });
    }, 250);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // `key` is the selection's content: a fresh object with the same values
    // must not re-fetch, and a changed value must.
  }, [path, key]); // eslint-disable-line react-hooks/exhaustive-deps

  return state;
}
