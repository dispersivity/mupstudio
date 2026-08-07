import { useCallback, useEffect, useRef, useState } from "react";
import { createViewport } from "@/viewport";
import type { Viewport } from "@/viewport/types";
import { fetchCatalog, ViewportClient, type DatasetCatalog } from "@/net/viewportClient";
import { Colorbar } from "./Colorbar";
import { TimeControls } from "./TimeControls";
import { ViewportInspector, type ViewSettings } from "./ViewportInspector";

type Phase =
  | { status: "loading"; detail: string }
  | { status: "ready" }
  | { status: "failed"; detail: string };

export interface ViewportHostProps {
  ncpl?: number;
  nlay?: number;
  ntimes?: number;
  playbackFps?: number;
  /** Lets the shell render this viewport's controls in its own inspector pane. */
  onInspector?: (panel: React.ReactNode) => void;
}

/**
 * Mounts the viewport module on a canvas and renders panels around it.
 *
 * React owns the canvas element and the metadata shown beside it. It does not
 * take part in drawing: after setup, every interaction reaches the GPU through
 * the viewport's imperative API.
 */
export function ViewportHost({
  ncpl = 20_000,
  nlay = 6,
  ntimes = 40,
  playbackFps = 12,
  onInspector,
}: ViewportHostProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewportRef = useRef<Viewport | null>(null);

  const [phase, setPhase] = useState<Phase>({ status: "loading", detail: "connecting" });
  const [catalog, setCatalog] = useState<DatasetCatalog | null>(null);
  const [times, setTimes] = useState<number[]>([]);
  const [timeStride, setTimeStride] = useState(1);
  const [timestep, setTimestep] = useState(0);
  const [playing, setPlaying] = useState(false);
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
    const client = new ViewportClient(
      new URLSearchParams({ ncpl: String(ncpl), nlay: String(nlay), ntimes: String(ntimes) }),
    );

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
        const params = new URLSearchParams({
          ncpl: String(ncpl),
          nlay: String(nlay),
          ntimes: String(ntimes),
        });
        const loaded = await fetchCatalog(params);
        if (disposed) return;
        setCatalog(loaded);

        await client.connect();
        if (disposed) return;

        setPhase({ status: "loading", detail: `loading ${loaded.ncells.toLocaleString()} cells` });
        viewport.setGrid(await client.getGeometry(loaded));
        if (disposed) return;

        const component = loaded.components[0]?.name ?? "concentration";
        setPhase({ status: "loading", detail: "loading timesteps" });
        const scalars = await client.getScalars(component, loaded);
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
  }, [ncpl, nlay, ntimes]);

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
        cells={catalog.ncells}
        layers={catalog.nlay}
        component={catalog.components[0]?.name ?? "—"}
        unit={catalog.components[0]?.unit ?? ""}
        onChange={updateView}
      />,
    );
  }, [onInspector, phase.status, catalog, view, dataRange, updateView]);

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
            <div className="font-medium text-zinc-100">{catalog.ncells.toLocaleString()} cells</div>
            <div className="tabular-nums">
              {catalog.ncpl.toLocaleString()} per layer × {catalog.nlay} layers
            </div>
          </div>

          <Colorbar
            colormap={view.colormap}
            vmin={view.vmin}
            vmax={view.vmax}
            unit={catalog.components[0]?.unit}
            label={catalog.components[0]?.name}
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
