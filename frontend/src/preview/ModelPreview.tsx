import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchCatalog, ViewportClient, type DatasetCatalog } from "@/net/viewportClient";
import { createViewport } from "@/viewport";
import type { Viewport } from "@/viewport/types";
import { Colorbar } from "@/viewport-host/Colorbar";

/**
 * The model being edited, drawn.
 *
 * Results answer what happened; this answers what you just said. A boundary on
 * the wrong row, a zone one cell short, a conductivity that never got applied —
 * all of those are invisible in a form and obvious here, and until now the only
 * way to see them was to run the model and read the output.
 *
 * It shares the viewport module and the frame protocol with the results view.
 * The difference is only which dataset the socket is pointed at: a project path
 * rather than a run id, served from the compiled inputs.
 */

interface Field {
  name: string;
  label: string;
  kind: "property" | "boundary" | "chemistry";
  unit: string;
  /** How many cells carry a value. The rest are drawn as a dim shell. */
  setCells: number;
}

const GROUPS: { kind: Field["kind"]; label: string }[] = [
  { kind: "property", label: "Properties" },
  { kind: "boundary", label: "Boundaries" },
  { kind: "chemistry", label: "Chemistry" },
];

export function ModelPreview({
  path,
  /** Bumped after a save, so the picture follows the edit. */
  revision = 0,
  /** Field to select when the preview opens, if it exists. */
  initialField,
  /**
   * What to draw, when the surrounding step decides rather than the picker.
   *
   * Selecting a boundary package in a list should show that package, so the
   * step drives the picture and the picker becomes a readout of its choice.
   */
  field: controlled,
  onFieldChange,
  className = "",
}: {
  path: string | null;
  revision?: number;
  initialField?: string;
  field?: string | null;
  onFieldChange?: (field: string) => void;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewportRef = useRef<Viewport | null>(null);
  // Held in a ref as well so the loader can preserve the selection without
  // making itself depend on it and reconnect on every change.
  const chosen = useRef<string | undefined>(initialField);

  const [status, setStatus] = useState<"loading" | "ready" | "failed">("loading");
  const [detail, setDetail] = useState("connecting");
  const [catalog, setCatalog] = useState<DatasetCatalog | null>(null);
  const [ownField, setOwnField] = useState<string | null>(null);
  const field = controlled !== undefined ? controlled : ownField;

  const notify = useRef(onFieldChange);
  notify.current = onFieldChange;
  // Stable, so effects that report a field do not re-run whenever the parent
  // happens to pass a fresh callback.
  const setField = useCallback((next: string) => {
    setOwnField(next);
    notify.current?.(next);
  }, []);
  const [range, setRange] = useState<[number, number]>([0, 1]);
  const [showEdges, setShowEdges] = useState(true);

  const datasetId = path ? `preview:${path}` : null;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !datasetId) return;

    let disposed = false;
    let viewport: Viewport | null = null;
    const params = new URLSearchParams({ dataset: datasetId });
    const client = new ViewportClient(params);

    (async () => {
      try {
        setStatus("loading");
        setDetail("starting WebGPU");
        viewport = await createViewport(canvas);
        if (disposed) {
          viewport.destroy();
          return;
        }
        viewportRef.current = viewport;

        setDetail("compiling the project");
        const loaded = await fetchCatalog(datasetId, params);
        if (disposed) return;
        setCatalog(loaded);

        await client.connect();
        if (disposed) return;

        viewport.setGrid(await client.getGeometry(loaded));
        if (disposed) return;

        const available = loaded.components.map((entry) => entry.name);
        const wanted =
          chosen.current && available.includes(chosen.current)
            ? chosen.current
            : (available[0] ?? null);
        if (!wanted) throw new Error("this project has nothing to draw yet");

        const scalars = await client.getScalars(wanted, loaded);
        if (disposed) return;

        viewport.setScalars(scalars);
        setDrawRange(viewport, scalars.vmin, scalars.vmax);
        viewport.setShowEdges(true);
        // A column is one cell across, and at true scale it draws as a slab
        // with the interesting axis hidden inside it. Squashing the thin axis
        // is what makes a 1D model look like one.
        applyThinAxis(viewport, loaded);
        setField(wanted);
        chosen.current = wanted;
        setRange([scalars.vmin, scalars.vmax]);
        setStatus("ready");
      } catch (error) {
        if (disposed) return;
        setStatus("failed");
        setDetail(error instanceof Error ? error.message : String(error));
      }
    })();

    return () => {
      disposed = true;
      client.close();
      viewport?.destroy();
      viewportRef.current = null;
    };
    // `field` is deliberately absent: it is read through a ref to preserve the
    // selection, and changing it reloads through the effect below instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, revision, setField]);

  // Switching field re-fetches one array. The geometry is already on the GPU
  // and is not touched.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || !catalog || !field || status !== "ready" || !datasetId) return;
    if (field === chosen.current) return;

    let disposed = false;
    const client = new ViewportClient(new URLSearchParams({ dataset: datasetId }));

    (async () => {
      try {
        await client.connect();
        const scalars = await client.getScalars(field, catalog);
        if (disposed) return;
        viewport.setScalars(scalars);
        setDrawRange(viewport, scalars.vmin, scalars.vmax);
        setRange([scalars.vmin, scalars.vmax]);
        chosen.current = field;
      } catch {
        // Keeping the previous field drawn is better than an empty canvas: the
        // selection failed, the model did not.
      } finally {
        client.close();
      }
    })();

    return () => {
      disposed = true;
      client.close();
    };
  }, [field, catalog, status, datasetId]);

  useEffect(() => {
    viewportRef.current?.setShowEdges(showEdges);
  }, [showEdges]);

  const fields = useMemo<Field[]>(() => {
    if (catalog?.fields) return catalog.fields as Field[];
    // A catalog without the field descriptions still lists components, so the
    // picker works with names alone rather than not at all.
    return (catalog?.components ?? []).map((entry) => ({
      name: entry.name,
      label: entry.name,
      kind: "property" as const,
      unit: entry.unit ?? "",
      setCells: 0,
    }));
  }, [catalog]);

  const current = fields.find((item) => item.name === field);

  // A field covering part of the grid needs the rest drawn faintly behind it: a
  // single bright cell floating in space says nothing about where it is. Decided
  // from the coverage the dataset reports rather than from the field's name,
  // because a zone painted over every cell needs no shell either.
  const sparse = current !== undefined && current.setCells < (catalog?.ncells ?? 0);
  useEffect(() => {
    viewportRef.current?.setGhostAbsent(sparse);
  }, [sparse, field]);

  // Match the drawing buffer to the element, which changes size when the
  // surrounding form does.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const observer = new ResizeObserver(([entry]) => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.floor(entry.contentRect.width * dpr));
      canvas.height = Math.max(1, Math.floor(entry.contentRect.height * dpr));
      viewportRef.current?.requestRender();
    });
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);

  if (!path) {
    return (
      <Frame className={className}>
        <p className="p-3 text-[11px] text-zinc-600">Open a project to see it drawn.</p>
      </Frame>
    );
  }

  return (
    <Frame className={className}>
      <div className="flex items-center gap-2 border-b border-zinc-800 px-2 py-1.5">
        <select
          value={field ?? ""}
          aria-label="What to draw"
          onChange={(event) => setField(event.target.value)}
          disabled={status !== "ready"}
          className="min-w-0 flex-1 rounded border border-zinc-700 bg-zinc-900 px-1.5 py-1 text-[11px] text-zinc-100 focus:border-sky-600 focus:outline-none disabled:opacity-50"
        >
          {GROUPS.map((group) => {
            const members = fields.filter((item) => item.kind === group.kind);
            if (members.length === 0) return null;
            return (
              <optgroup key={group.kind} label={group.label}>
                {members.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.label}
                  </option>
                ))}
              </optgroup>
            );
          })}
        </select>

        <button
          type="button"
          onClick={() => setShowEdges(!showEdges)}
          title="Show cell edges"
          className={`rounded px-1.5 py-1 text-[10px] ${
            showEdges ? "bg-zinc-800 text-zinc-200" : "text-zinc-500 hover:text-zinc-300"
          }`}
        >
          grid
        </button>
      </div>

      <div className="relative min-h-0 flex-1">
        {/* Orbit, pan and zoom are handled inside the viewport module, which
            owns the arcball; the canvas needs no handlers of its own. */}
        <canvas ref={canvasRef} className="block h-full w-full touch-none" />

        {status !== "ready" && (
          <div className="absolute inset-0 flex items-center justify-center p-4">
            <p
              className={`max-w-xs text-center text-[11px] leading-relaxed ${
                status === "failed" ? "text-amber-300" : "text-zinc-500"
              }`}
            >
              {status === "failed" ? detail : `${detail}…`}
            </p>
          </div>
        )}

        {status === "ready" && current && (
          <div className="pointer-events-none absolute bottom-3 left-3 w-56 rounded bg-black/70 p-2 backdrop-blur-sm">
            {range[0] === range[1] ? (
              // A single value has no ramp to read, so the number is said once
              // and the coverage says whether it is the whole grid or one cell.
              <p className="text-[10px] leading-relaxed text-zinc-300">
                <span className="text-zinc-500">{current.label}</span>{" "}
                <span className="tabular-nums">{formatValue(range[0])}</span>
                {current.unit && <span className="text-zinc-500"> {current.unit}</span>}
                <span className="mt-0.5 block text-zinc-600">{coverage(current, catalog)}</span>
              </p>
            ) : (
              <Colorbar
                colormap="viridis"
                vmin={range[0]}
                vmax={range[1]}
                label={current.label}
                unit={current.unit}
              />
            )}
          </div>
        )}
      </div>

      {status === "ready" && catalog && (
        <p className="border-t border-zinc-800 px-2 py-1 text-[10px] text-zinc-600">
          {catalog.ncells.toLocaleString()} cells · not run, this is the input
        </p>
      )}
    </Frame>
  );
}

/**
 * Flatten an axis the grid is one cell across.
 *
 * Column benchmarks use a unit width so that cell volume equals cell length,
 * which is convenient arithmetic and a bad picture: the model is half a metre
 * long and a metre wide, so it draws as a block. Scaling that axis down leaves
 * the geometry alone and makes the length visible.
 */
function applyThinAxis(viewport: Viewport, catalog: DatasetCatalog): void {
  const squash = 0.02;
  if (catalog.thinAxis === "x") viewport.setAxisScale(squash, 1, 1);
  else if (catalog.thinAxis === "y") viewport.setAxisScale(1, squash, 1);
  else viewport.setAxisScale(1, 1, 1);
}

/**
 * Point the colour scale at the values, and centre a single one.
 *
 * A field where every cell holds the same number has an empty range, and
 * normalising within it puts that number at the bottom of the ramp — which in
 * viridis is nearly black and, against a dark shell, invisible. Widening the
 * range around the value puts it in the middle of the ramp instead, so a
 * boundary on one cell reads as one bright cell.
 */
function setDrawRange(viewport: Viewport, vmin: number, vmax: number): void {
  if (vmin !== vmax) {
    viewport.setRange(vmin, vmax);
    return;
  }
  const pad = Math.abs(vmin) || 1;
  viewport.setRange(vmin - pad, vmax + pad);
}

/** How much of the grid a field covers, in words. */
function coverage(field: Field, catalog: DatasetCatalog | null): string {
  const total = catalog?.ncells ?? 0;
  if (!total || field.setCells >= total) return "every cell";
  if (field.setCells === 0) return "no cells — nothing is set";
  return `${field.setCells.toLocaleString()} of ${total.toLocaleString()} cells`;
}

/** Concise but not rounded away, for a value read off a legend. */
function formatValue(value: number): string {
  if (!Number.isFinite(value)) return "\u2014";
  if (value === 0) return "0";
  const magnitude = Math.abs(value);
  if (magnitude < 1e-3 || magnitude >= 1e5) return value.toExponential(3);
  return String(Number(value.toPrecision(6)));
}

function Frame({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={`flex min-h-0 flex-col overflow-hidden rounded border border-zinc-800 bg-zinc-950 ${className}`}
    >
      {children}
    </div>
  );
}
