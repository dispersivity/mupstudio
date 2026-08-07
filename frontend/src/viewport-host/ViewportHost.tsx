import { useCallback, useEffect, useRef, useState } from "react";
import { createViewport } from "@/viewport";
import type { CameraView, Viewport } from "@/viewport/types";
import { fetchCatalog, ViewportClient, type DatasetCatalog } from "@/net/viewportClient";
import type { DatasetListing } from "@/results/DatasetPicker";
import { Colorbar } from "./Colorbar";
import { TimeControls } from "./TimeControls";
import { ViewportInspector, type ViewSettings } from "./ViewportInspector";
import { AxisTriad } from "./AxisTriad";
import { CellPicker, TimeSeriesPanel } from "@/results/TimeSeriesPanel";
import { useCellSeries } from "@/results/useCellSeries";

type Phase =
  | { status: "loading"; detail: string }
  | { status: "ready" }
  | { status: "failed"; detail: string };

export interface ViewportHostProps {
  /** "demo" for the synthetic grid, or a run id. */
  datasetId?: string;
  /** Only used by the demo dataset, which is generated to order. */
  ncpl?: number;
  nlay?: number;
  ntimes?: number;
  playbackFps?: number;
  /** Lets the shell render this viewport's controls in its own inspector pane. */
  onInspector?: (panel: React.ReactNode) => void;
  /** The dataset list and switcher, rendered inside the inspector. */
  listing?: DatasetListing | null;
  onSelectDataset?: (datasetId: string) => void;
}

/**
 * Mounts the viewport module on a canvas and renders panels around it.
 *
 * React owns the canvas element and the metadata shown beside it. It does not
 * take part in drawing: after setup, every interaction reaches the GPU through
 * the viewport's imperative API.
 */
export function ViewportHost({
  datasetId = "demo",
  ncpl = 20_000,
  nlay = 6,
  ntimes = 40,
  playbackFps = 12,
  onInspector,
  listing = null,
  onSelectDataset,
}: ViewportHostProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewportRef = useRef<Viewport | null>(null);
  const dragOrigin = useRef<{ x: number; y: number } | null>(null);

  const [phase, setPhase] = useState<Phase>({ status: "loading", detail: "connecting" });
  const [catalog, setCatalog] = useState<DatasetCatalog | null>(null);
  const [times, setTimes] = useState<number[]>([]);
  const [timeStride, setTimeStride] = useState(1);
  const [timestep, setTimestep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [component, setComponent] = useState<string | null>(null);
  const [dataRange, setDataRange] = useState<[number, number]>([0, 1]);
  const [view, setView] = useState<ViewSettings>({
    colormap: "viridis",
    vmin: 0,
    vmax: 1,
    autoRange: true,
    logScale: false,
    verticalExaggeration: 1,
    xExaggeration: 1,
    yExaggeration: 1,
    showEdges: false,
  });
  const [camera, setCamera] = useState<CameraView | null>(null);
  // Cells whose history is plotted, as the tokens the series endpoint reads.
  const [cellTokens, setCellTokens] = useState<string[]>([]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let disposed = false;
    let viewport: Viewport | null = null;
    const params = new URLSearchParams({
      dataset: datasetId,
      ncpl: String(ncpl),
      nlay: String(nlay),
      ntimes: String(ntimes),
    });
    const client = new ViewportClient(params);

    (async () => {
      try {
        setPhase({ status: "loading", detail: "starting WebGPU" });
        viewport = await createViewport(canvas);
        if (disposed) {
          viewport.destroy();
          return;
        }
        viewportRef.current = viewport;

        setPhase({ status: "loading", detail: "fetching catalog" });
        const loaded = await fetchCatalog(datasetId, params);
        if (disposed) return;
        setCatalog(loaded);

        await client.connect();
        if (disposed) return;

        setPhase({ status: "loading", detail: `loading ${loaded.ncells.toLocaleString()} cells` });
        viewport.setGrid(await client.getGeometry(loaded));
        if (disposed) return;

        // Keep the chosen component across a reload when the new dataset also
        // has it, so switching runs does not silently change what you compare.
        const available = loaded.components.map((entry) => entry.name);
        const chosen =
          component && available.includes(component)
            ? component
            : (available[0] ?? "concentration");
        setComponent(chosen);

        setPhase({ status: "loading", detail: `loading ${chosen}` });
        const scalars = await client.getScalars(chosen, loaded);
        if (disposed) return;

        viewport.setScalars(scalars);
        setTimes(scalars.times);
        setTimeStride(scalars.timeStride);
        setDataRange([scalars.vmin, scalars.vmax]);
        setView((current) => ({
          ...current,
          // Axis scaling belongs to one grid, so it does not follow you to another.
          xExaggeration: 1,
          yExaggeration: 1,
          verticalExaggeration: 1,
          ...(current.autoRange ? { vmin: scalars.vmin, vmax: scalars.vmax } : {}),
        }));
        setPhase({ status: "ready" });
      } catch (error) {
        if (!disposed) {
          setPhase({
            status: "failed",
            detail: error instanceof Error ? error.message : String(error),
          });
        }
      }
    })();

    return () => {
      disposed = true;
      client.close();
      viewport?.destroy();
      viewportRef.current = null;
    };
    // component is deliberately not a dependency: it is read to preserve the
    // selection, and changing it goes through reloadComponent below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, ncpl, nlay, ntimes]);

  // A new dataset has a different grid, so cells picked on the old one mean
  // nothing on it.
  useEffect(() => setCellTokens([]), [datasetId]);

  // Keep the drawing buffer matched to the element's pixel size.
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

  // Push display settings to the GPU. Each of these is one call and one
  // redraw; none of them re-uploads data.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || phase.status !== "ready") return;

    viewport.setColormap(view.colormap);
    viewport.setRange(view.vmin, view.vmax);
    viewport.setLogScale(view.logScale);
    viewport.setShowEdges(view.showEdges);

    viewport.setAxisScale(view.xExaggeration, view.yExaggeration, view.verticalExaggeration);
  }, [view, phase.status]);

  // Follow the camera so the orientation gizmo can be drawn in HTML.
  useEffect(() => {
    if (phase.status !== "ready") return;
    return viewportRef.current?.onCamera(setCamera);
  }, [phase.status]);

  const addCell = useCallback((token: string) => {
    setCellTokens((current) => (current.includes(token) ? current : [...current, token]));
  }, []);

  /** Click a cell to plot it; clicking one already plotted removes it. */
  const pickCell = useCallback(async (event: React.MouseEvent<HTMLCanvasElement>) => {
    const viewport = viewportRef.current;
    const canvas = canvasRef.current;
    if (!viewport || !canvas) return;

    const box = canvas.getBoundingClientRect();
    const scale = canvas.width / box.width;
    const picked = await viewport.pick(
      (event.clientX - box.left) * scale,
      (event.clientY - box.top) * scale,
    );
    if (!picked) return;

    const token = `${picked.layer + 1}:${picked.cell + 1}`;
    setCellTokens((current) =>
      current.includes(token) ? current.filter((item) => item !== token) : [...current, token],
    );
  }, []);

  const seek = useCallback((index: number) => {
    viewportRef.current?.setTimestep(index);
    setTimestep(index);
  }, []);

  const updateView = useCallback((next: Partial<ViewSettings>) => {
    setView((current) => ({ ...current, ...next }));
  }, []);

  /** Load a different component into the same grid, reusing the geometry. */
  const selectComponent = useCallback(
    async (next: string) => {
      const viewport = viewportRef.current;
      if (!viewport || !catalog || next === component) return;

      setPhase({ status: "loading", detail: `loading ${next}` });
      const params = new URLSearchParams({
        dataset: datasetId,
        ncpl: String(ncpl),
        nlay: String(nlay),
        ntimes: String(ntimes),
      });
      const client = new ViewportClient(params);
      try {
        await client.connect();
        const scalars = await client.getScalars(next, catalog);
        viewport.setScalars(scalars);
        setComponent(next);
        setTimes(scalars.times);
        setTimeStride(scalars.timeStride);
        setDataRange([scalars.vmin, scalars.vmax]);
        setView((current) =>
          current.autoRange ? { ...current, vmin: scalars.vmin, vmax: scalars.vmax } : current,
        );
        setPhase({ status: "ready" });
      } catch (error) {
        setPhase({
          status: "failed",
          detail: error instanceof Error ? error.message : String(error),
        });
      } finally {
        client.close();
      }
    },
    [catalog, component, datasetId, ncpl, nlay, ntimes],
  );

  const seriesParams = new URLSearchParams({
    ncpl: String(ncpl),
    nlay: String(nlay),
    ntimes: String(ntimes),
  });
  const seriesData = useCellSeries(datasetId, component, cellTokens, seriesParams);

  // Hand the shell this viewport's controls so they render in its inspector.
  useEffect(() => {
    if (!onInspector) return;
    if (phase.status !== "ready" || !catalog) {
      onInspector(null);
      return;
    }
    onInspector(
      <ViewportInspector
        settings={view}
        dataRange={dataRange}
        catalog={catalog}
        component={component ?? catalog.components[0]?.name ?? "—"}
        listing={listing}
        onChange={updateView}
        onSelectComponent={selectComponent}
        onSelectDataset={onSelectDataset}
        cellPicker={<CellPicker structured={seriesData.data?.structured ?? true} onAdd={addCell} />}
      />,
    );
  }, [
    onInspector,
    phase.status,
    catalog,
    view,
    dataRange,
    updateView,
    component,
    listing,
    selectComponent,
    onSelectDataset,
    addCell,
    seriesData.data?.structured,
  ]);

  useEffect(() => {
    if (!playing || times.length < 2) return;
    const timer = window.setInterval(() => {
      setTimestep((current) => {
        const next = (current + 1) % times.length;
        viewportRef.current?.setTimestep(next);
        return next;
      });
    }, 1000 / playbackFps);
    return () => window.clearInterval(timer);
  }, [playing, times.length, playbackFps]);

  return (
    <div className="relative h-full w-full bg-zinc-950">
      <canvas
        ref={canvasRef}
        className="block h-full w-full touch-none"
        onPointerDown={(event) => {
          dragOrigin.current = { x: event.clientX, y: event.clientY };
        }}
        onClick={(event) => {
          // Orbiting ends in a click too, so a pick only counts if the pointer
          // barely moved.
          const origin = dragOrigin.current;
          const moved =
            origin && Math.hypot(event.clientX - origin.x, event.clientY - origin.y) > 4;
          if (!moved) void pickCell(event);
        }}
      />

      {phase.status !== "ready" && (
        <div className="absolute inset-0 flex items-center justify-center bg-zinc-950/80">
          <div className="max-w-md text-center">
            {phase.status === "loading" ? (
              <p className="text-sm text-zinc-400">{phase.detail}…</p>
            ) : (
              <>
                <p className="text-sm font-medium text-red-400">Viewport failed to start</p>
                <pre className="mt-2 overflow-x-auto rounded bg-zinc-900 p-3 text-left text-xs text-zinc-300">
                  {phase.detail}
                </pre>
              </>
            )}
          </div>
        </div>
      )}

      {phase.status === "ready" && catalog && (
        <>
          <div className="pointer-events-none absolute left-4 top-4 rounded bg-black/40 px-3 py-2 text-xs text-zinc-300 backdrop-blur-sm">
            <div className="font-medium text-zinc-100">
              {component ?? catalog.components[0]?.name}
            </div>
            <div className="tabular-nums">
              {catalog.ncells.toLocaleString()} cells, {catalog.nlay}{" "}
              {catalog.nlay === 1 ? "layer" : "layers"}
            </div>
            <div className="tabular-nums text-zinc-500">{formatExtent(catalog)}</div>
            {catalog.status && catalog.status !== "succeeded" && (
              <div className="mt-1 text-amber-300">
                run {catalog.status}
                {catalog.status === "failed" ? " — partial results" : ""}
              </div>
            )}
          </div>

          <Colorbar
            colormap={view.colormap}
            vmin={view.vmin}
            vmax={view.vmax}
            unit={catalog.components.find((entry) => entry.name === component)?.unit}
            label={component ?? catalog.components[0]?.name}
          />

          <TimeSeriesPanel
            data={seriesData.data}
            loading={seriesData.loading}
            error={seriesData.error}
            timeUnit=""
            onRemove={(index) =>
              setCellTokens((current) => current.filter((_, position) => position !== index))
            }
            onClear={() => setCellTokens([])}
          />

          <AxisTriad
            camera={camera}
            exaggeration={{
              x: view.xExaggeration,
              y: view.yExaggeration,
              z: view.verticalExaggeration,
            }}
          />

          <TimeControls
            timestep={timestep}
            times={times}
            playing={playing}
            timeStride={timeStride}
            onSeek={seek}
            onTogglePlay={() => setPlaying((value) => !value)}
          />
        </>
      )}
    </div>
  );
}

/** The model's true size, whatever scaling the view is using. */
function formatExtent(catalog: DatasetCatalog): string {
  const span = (axis: number) => catalog.bounds.max[axis] - catalog.bounds.min[axis];
  const round = (value: number) =>
    value >= 100 ? value.toFixed(0) : value >= 1 ? value.toFixed(1) : value.toPrecision(2);
  return `${round(span(0))} x ${round(span(1))} x ${round(span(2))}`;
}
