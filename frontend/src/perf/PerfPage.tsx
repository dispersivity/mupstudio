import { useEffect, useRef, useState } from "react";
import { createViewport } from "@/viewport";
import { fetchCatalog, ViewportClient } from "@/net/viewportClient";
import { FRAME_BUDGET_MS, measureFrameTimes, summarise, type PerfResult } from "./harness";

/**
 * The M1 gate, as a page you can load.
 *
 * Loads a grid of the requested size, orbits the camera and advances time on a
 * fixed schedule, then reports frame-time percentiles. Camera motion is
 * deterministic so two runs measure the same work.
 */
export function PerfPage({ ncpl, nlay, ntimes, frames }: {
  ncpl: number;
  nlay: number;
  ntimes: number;
  frames: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [status, setStatus] = useState("preparing");
  const [result, setResult] = useState<PerfResult | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let disposed = false;
    const params = new URLSearchParams({
      ncpl: String(ncpl),
      nlay: String(nlay),
      ntimes: String(ntimes),
    });
    const client = new ViewportClient(params);

    (async () => {
      try {
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.floor(canvas.clientWidth * dpr);
        canvas.height = Math.floor(canvas.clientHeight * dpr);

        setStatus("starting WebGPU");
        const viewport = await createViewport(canvas);

        setStatus("building grid on the server");
        const catalog = await fetchCatalog(params);
        await client.connect();

        setStatus(`uploading ${catalog.ncells.toLocaleString()} cells`);
        viewport.setGrid(await client.getGeometry(catalog));

        setStatus("uploading timesteps");
        const scalars = await client.getScalars(catalog.components[0].name, catalog);
        viewport.setScalars(scalars);
        if (disposed) return;

        setStatus(`measuring ${frames} frames`);
        const framesBefore = viewport.stats().frames;
        const samples = await measureFrameTimes(
          {
            step(frame) {
              // Fixed time schedule: the same work every run.
              viewport.setTimestep(frame % scalars.timesteps.length);
            },
            renderAndWait: () => viewport.renderAndWait(),
          },
          { frames },
        );
        if (disposed) return;

        const finalStats = viewport.stats();
        const summary = summarise(samples, {
          ncpl: catalog.ncpl,
          nlay: catalog.nlay,
          triangles: finalStats.triangles,
          framesDrawn: finalStats.frames - framesBefore,
          canvasWidth: canvas.width,
          canvasHeight: canvas.height,
          adapter: finalStats.adapter,
        });
        window.__mupPerf = summary;
        setResult(summary);
        setStatus("done");
        console.info("[mupstudio perf]", summary);
      } catch (error) {
        if (!disposed) {
          setStatus(`failed: ${error instanceof Error ? error.message : String(error)}`);
        }
      }
    })();

    return () => {
      disposed = true;
      client.close();
    };
  }, [ncpl, nlay, ntimes, frames]);

  return (
    <div className="flex h-full w-full flex-col bg-zinc-950 text-zinc-200">
      <canvas ref={canvasRef} className="min-h-0 flex-1" />
      <div className="border-t border-zinc-800 p-4 font-mono text-xs">
        <div data-testid="perf-status">{status}</div>
        {result && (
          <table className="mt-3" data-testid="perf-result">
            <tbody>
              <Row label="adapter" value={result.adapter} />
              <Row label="canvas" value={`${result.canvasWidth}x${result.canvasHeight}`} />
              <Row label="cells" value={result.cells.toLocaleString()} />
              <Row label="triangles" value={result.triangles.toLocaleString()} />
              <Row
                label="frames"
                value={`${result.framesDrawn} drawn / ${result.framesMeasured} measured`}
                highlight={result.valid ? undefined : "fail"}
              />
              <Row label="p50" value={`${result.p50Ms} ms`} />
              <Row
                label="p95"
                value={`${result.p95Ms} ms (budget ${FRAME_BUDGET_MS.toFixed(2)})`}
                highlight={result.passed ? "pass" : "fail"}
              />
              <Row label="p99" value={`${result.p99Ms} ms`} />
              <Row label="max" value={`${result.maxMs} ms`} />
              <Row label="mean fps" value={String(result.impliedFps)} />
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: "pass" | "fail";
}) {
  const colour =
    highlight === "pass" ? "text-emerald-400" : highlight === "fail" ? "text-red-400" : "";
  return (
    <tr>
      <td className="pr-6 text-zinc-500">{label}</td>
      <td className={colour}>{value}</td>
    </tr>
  );
}
