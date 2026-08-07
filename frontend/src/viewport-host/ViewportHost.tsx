import { useCallback, useEffect, useRef, useState } from "react";
import { createViewport } from "@/viewport";
import type { Viewport } from "@/viewport/types";
import { fetchCatalog, ViewportClient, type DatasetCatalog } from "@/net/viewportClient";
import type { DatasetListing } from "@/results/DatasetPicker";
import { Colorbar } from "./Colorbar";
import { TimeControls } from "./TimeControls";
import { ViewportInspector, type ViewSettings } from "./ViewportInspector";

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
  });

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
        setView((current) =>
          current.autoRange ? { ...current, vmin: scalars.vmin, vmax: scalars.vmax } : current,
        );
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
    viewport.setVerticalExaggeration(view.verticalExaggeration);
  }, [view, phase.status]);

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
      <canvas ref={canvasRef} className="block h-full w-full touch-none" />

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
