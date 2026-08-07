# Viewport performance baseline

The M1 gate: p95 frame time at or under 8.33 ms (120 fps) on a real Ranger-scale
grid of ~500k cells.

## How to reproduce

Start both servers, then run the harness:

```bash
just dev                       # uvicorn on :8000, vite on :5173
cd frontend
node scripts/perf.mjs --url http://localhost:5173 \
  --ncpl 50000 --nlay 10 --frames 200 --channel chromium
```

`--channel chromium` matters. Playwright's default headless shell has no GPU
access and silently falls back to SwiftShader; the run still completes and
still reports numbers, they are just measuring a software rasterizer. Check the
`adapter` line in the output — it must name a real GPU.

The harness times each frame from the start of encoding until
`queue.onSubmittedWorkDone()` resolves. Timing around `submit()` alone measures
how fast commands are written, which is a small fraction of the work and gives
frame times around 0.1 ms regardless of scene size.

Results are also written to `window.__mupPerf` and printed to the console, and
the page reports whether the run was valid: frames actually drawn, canvas size,
and adapter. An invalid run never reports a pass.

## Baseline, 2026-08-07

MacBook (Apple Silicon), Apple M-series GPU reporting `apple metal-3`,
Chromium 1600x851 at devicePixelRatio 2, 20 output timesteps preloaded.

| Cells | Layers | Triangles | p50 | p95 | p99 | Verdict |
|---|---|---|---|---|---|---|
| 499,200 | 10 | 9.98 M | 3.8 ms | **4.1–4.5 ms** | 4.4–15.2 ms | pass, ~2x headroom |
| 998,400 | 20 | 19.97 M | 6.5 ms | 8.1 ms | 9.0 ms | pass, at the limit |
| 1,999,200 | 20 | 39.98 M | 10.9 ms | 13.1 ms | 13.4 ms | fail (76 fps) |

The 500k figure is the gate and it passes with roughly twice the budget to
spare, repeatably across runs. Cost scales linearly with triangle count, which
is what the layer-instanced design predicts: one draw call per mesh regardless
of layer count, so the GPU is the only thing that grows.

Practical ceiling for 120 fps is about 1M cells at this window size. Beyond
that the app still runs, just below 120 fps — 2M cells renders at ~76 fps.

## What this proves

Invariants 1 to 4 hold at scale:

- Python and React are absent from the frame loop. The render loop lives in
  `frontend/src/viewport/`, owns its own scheduling, and is driven through an
  imperative API.
- Geometry uploads once. Scrubbing time rebinds one bind group per frame and
  re-uploads nothing.
- Prisms extrude in the vertex shader. A single layer's footprint is uploaded
  and `instance_index` selects the layer's elevations, so 10 layers of 50k
  cells is two instanced draw calls, not 500k of anything.
- Every timestep sits in its own GPU buffer with a prebuilt bind group.

## Notes

The first 500k run showed p99 of 15.2 ms and a 22.8 ms maximum while later runs
stayed near p50. Those outliers are first-touch costs on buffers the earlier
frames had not yet used; the warmup window (60 frames) covers shader
compilation but not every buffer's first bind. Worth revisiting if stutter
shows up in real use.
