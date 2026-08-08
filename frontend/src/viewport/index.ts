/**
 * The viewport: a plain TypeScript module with its own render loop.
 *
 * Nothing here imports React, and React never calls into it per frame. The
 * host mounts a canvas, hands over geometry and scalars once, and afterwards
 * drives it through this imperative API. Scrubbing time swaps a bind group;
 * it does not re-upload data or re-render any React tree.
 */

import { ArcballCamera } from "./camera/arcball";
import { packDisv, FLOATS_PER_VERTEX, type PackedMesh } from "./geometry/disv";
import { COLORMAP_SIZE, colormapTexels, type ColormapName } from "./scalars/colormap";
import prismShader from "./gpu/shaders/prism.wgsl?raw";
import type {
  CameraView,
  FrameStats,
  GridGeometry,
  PickedCell,
  ScalarSet,
  Viewport,
  ViewportOptions,
} from "./types";

// How far edges are pulled toward the camera, in normalised device depth.
// Large enough to clear the rounding error that makes a wireframe dashed, small
// enough that an edge never shows through the cell in front of it.
const EDGE_DEPTH_NUDGE = 2e-4;

const FRAME_UNIFORM_FLOATS = 16 + 4 + 4 + 4 + 4; // viewProj, params, gridInfo, axisScale, slice
const DEPTH_FORMAT: GPUTextureFormat = "depth24plus";
// Cell identities are rendered to this format: 32-bit unsigned holds any grid
// we will draw, and integer targets do not blend or filter, so the value read
// back is the value written.
const PICK_FORMAT: GPUTextureFormat = "r32uint";

interface GpuGeometry {
  capVertexBuffer: GPUBuffer;
  capIndexBuffer: GPUBuffer;
  capIndexCount: number;
  wallVertexBuffer: GPUBuffer;
  wallIndexBuffer: GPUBuffer;
  wallIndexCount: number;
  edgeIndexBuffer: GPUBuffer;
  edgeIndexCount: number;
  topBuffer: GPUBuffer;
  botBuffer: GPUBuffer;
  nlay: number;
  ncpl: number;
  triangles: number;
}

interface GpuScalars {
  /** One buffer and one prebuilt bind group per timestep: swapping is O(1). */
  buffers: GPUBuffer[];
  bindGroups: GPUBindGroup[];
  set: ScalarSet;
}

/**
 * The viewport currently rendering to each canvas.
 *
 * A canvas can be bound to exactly one GPUDevice: `context.configure` replaces
 * the binding, and the previous viewport's render loop then asks for a texture
 * that belongs to the new device. WebGPU rejects the mismatch on every frame —
 * "is associated with [Device], and cannot be used with [Device]" — and the
 * canvas goes black with no other symptom.
 *
 * That is easy to cause and hard to see: React StrictMode mounts every effect
 * twice, so any call site that forgets to destroy on cleanup gets two devices
 * on one canvas. Rather than rely on each of them remembering, a canvas has
 * one owner and creating a viewport takes ownership of it.
 */
const active = new WeakMap<HTMLCanvasElement, Viewport>();

/**
 * Which attempt to claim each canvas is the current one.
 *
 * Claimed synchronously, before the first await, because requesting a device
 * takes long enough for a second attempt to start and finish first. Evicting
 * "whatever is on the canvas" is not enough on its own: if the older attempt
 * resolves last it evicts the newer one and leaves the canvas owned by a
 * viewport its caller has already abandoned.
 */
const claims = new WeakMap<HTMLCanvasElement, number>();

/** Thrown by the loser of a race for a canvas. Not an error worth showing. */
export class ViewportSuperseded extends Error {
  constructor() {
    super("another viewport took this canvas first");
    this.name = "ViewportSuperseded";
  }
}

export async function createViewport(
  canvas: HTMLCanvasElement,
  options: ViewportOptions = {},
): Promise<Viewport> {
  const claim = (claims.get(canvas) ?? 0) + 1;
  claims.set(canvas, claim);

  const adapter = await navigator.gpu?.requestAdapter();
  if (!adapter) {
    throw new Error("no WebGPU adapter available");
  }
  const device = await adapter.requestDevice();
  const adapterName =
    [adapter.info?.vendor, adapter.info?.architecture, adapter.info?.description]
      .filter(Boolean)
      .join(" ") || "unknown";
  const context = canvas.getContext("webgpu");
  if (!context) {
    throw new Error("could not get a webgpu context from the canvas");
  }

  if (claims.get(canvas) !== claim) {
    // A later call started while this one was waiting for a device. Configuring
    // the context now would bind the canvas to a device whose owner is already
    // gone, and every frame the winner draws would be rejected.
    device.destroy();
    throw new ViewportSuperseded();
  }

  // Before configuring, not after: the moment this canvas is bound to the new
  // device, the previous viewport's next frame is invalid.
  active.get(canvas)?.destroy();

  const format = navigator.gpu.getPreferredCanvasFormat();
  context.configure({ device, format, alphaMode: "opaque" });

  // Without this a validation error is a black rectangle and nothing else:
  // Dawn reports the first failure here and then only says "invalid due to a
  // previous error" on every console message that follows it.
  device.addEventListener("uncapturederror", (event) => {
    console.error("webgpu:", (event as GPUUncapturedErrorEvent).error.message);
  });

  // A lost device invalidates everything it made, including the canvas
  // texture, so every later frame fails with "invalid due to a previous
  // error" and the only visible symptom is a black rectangle. Saying so is
  // the difference between a diagnosable fault and an inexplicable one.
  void device.lost.then((info) => {
    console.error(`webgpu: device lost (${info.reason}): ${info.message}`);
  });

  const camera = new ArcballCamera();
  const module = device.createShaderModule({ code: prismShader, label: "prism" });

  const frameLayout = device.createBindGroupLayout({
    label: "frame",
    entries: [
      {
        binding: 0,
        visibility: GPUShaderStage.VERTEX | GPUShaderStage.FRAGMENT,
        buffer: { type: "uniform" },
      },
      { binding: 1, visibility: GPUShaderStage.VERTEX, buffer: { type: "read-only-storage" } },
      { binding: 2, visibility: GPUShaderStage.VERTEX, buffer: { type: "read-only-storage" } },
      { binding: 3, visibility: GPUShaderStage.FRAGMENT, texture: { sampleType: "float" } },
      { binding: 4, visibility: GPUShaderStage.FRAGMENT, sampler: { type: "filtering" } },
      { binding: 5, visibility: GPUShaderStage.FRAGMENT, buffer: { type: "read-only-storage" } },
    ],
  });

  const scalarLayout = device.createBindGroupLayout({
    label: "scalars",
    entries: [
      { binding: 0, visibility: GPUShaderStage.VERTEX, buffer: { type: "read-only-storage" } },
    ],
  });

  const pipeline = device.createRenderPipeline({
    label: "prism",
    layout: device.createPipelineLayout({ bindGroupLayouts: [frameLayout, scalarLayout] }),
    vertex: {
      module,
      entryPoint: "vertexMain",
      buffers: [
        {
          arrayStride: FLOATS_PER_VERTEX * 4,
          attributes: [
            { shaderLocation: 0, offset: 0, format: "float32x2" }, // position
            { shaderLocation: 1, offset: 8, format: "float32" }, // cellInLayer
            { shaderLocation: 2, offset: 12, format: "float32" }, // face
          ],
        },
      ],
    },
    fragment: { module, entryPoint: "fragmentMain", targets: [{ format }] },
    primitive: { topology: "triangle-list", cullMode: "none" },
    depthStencil: { format: DEPTH_FORMAT, depthWriteEnabled: true, depthCompare: "less" },
  });

  const edgePipeline = device.createRenderPipeline({
    label: "cell edges",
    layout: device.createPipelineLayout({ bindGroupLayouts: [frameLayout, scalarLayout] }),
    vertex: {
      module,
      entryPoint: "vertexMain",
      // Edges sit exactly on the faces they outline. Without this the two
      // depths differ only by rounding, so a line wins the depth test on some
      // pixels and loses on others, and the wireframe comes out dashed.
      constants: { depthNudge: EDGE_DEPTH_NUDGE },
      buffers: [
        {
          arrayStride: FLOATS_PER_VERTEX * 4,
          attributes: [
            { shaderLocation: 0, offset: 0, format: "float32x2" },
            { shaderLocation: 1, offset: 8, format: "float32" },
            { shaderLocation: 2, offset: 12, format: "float32" },
          ],
        },
      ],
    },
    fragment: { module, entryPoint: "fragmentEdge", targets: [{ format }] },
    primitive: { topology: "line-list" },
    depthStencil: {
      format: DEPTH_FORMAT,
      depthWriteEnabled: false,
      depthCompare: "less-equal",
    },
  });

  const pickPipeline = device.createRenderPipeline({
    label: "pick",
    layout: device.createPipelineLayout({ bindGroupLayouts: [frameLayout, scalarLayout] }),
    vertex: {
      module,
      entryPoint: "vertexMain",
      buffers: [
        {
          arrayStride: FLOATS_PER_VERTEX * 4,
          attributes: [
            { shaderLocation: 0, offset: 0, format: "float32x2" },
            { shaderLocation: 1, offset: 8, format: "float32" },
            { shaderLocation: 2, offset: 12, format: "float32" },
          ],
        },
      ],
    },
    fragment: { module, entryPoint: "fragmentPick", targets: [{ format: PICK_FORMAT }] },
    primitive: { topology: "triangle-list", cullMode: "none" },
    depthStencil: { format: DEPTH_FORMAT, depthWriteEnabled: true, depthCompare: "less" },
  });

  const uniformBuffer = device.createBuffer({
    label: "frame uniforms",
    size: FRAME_UNIFORM_FLOATS * 4,
    usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
  });
  const uniformData = new Float32Array(FRAME_UNIFORM_FLOATS);

  const colormapTexture = device.createTexture({
    label: "colormap",
    size: [COLORMAP_SIZE, 1],
    format: "rgba8unorm",
    usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST,
  });
  const sampler = device.createSampler({ magFilter: "linear", minFilter: "linear" });

  let geometry: GpuGeometry | null = null;
  let scalars: GpuScalars | null = null;
  let frameBindGroup: GPUBindGroup | null = null;
  // Which cells are in the selection being edited. One element while nothing is
  // selected: WebGPU requires the binding to be filled either way, and the
  // shader guards on its length.
  let selectionBuffer = device.createBuffer({
    label: "selection",
    size: 4,
    usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
  });
  // Kept alongside so a change writes into the same buffer rather than
  // replacing it; see setSelection for why that matters.
  let selectionFlags = new Uint32Array(0);
  let depthTexture: GPUTexture | null = null;
  let pickTexture: GPUTexture | null = null;
  let pickDepth: GPUTexture | null = null;
  let pickReadback: GPUBuffer | null = null;

  let timestep = 0;
  let colormap: ColormapName = options.colormap ?? "viridis";
  let axisScale: [number, number, number] = [1, 1, options.verticalExaggeration ?? 1];
  let gridBounds: GridGeometry["bounds"] | null = null;
  let range: [number, number] = [0, 1];
  let logScale = false;
  let showEdges = options.showEdges ?? false;
  const nodata = options.nodata ?? -1e30;
  // Whether cells with no value are drawn as a dim shell or not at all.
  let ghostAbsent = false;
  // Which part of the model is on show: mode, index, and the grid's columns per
  // row, which row and column slices need and a vertex grid does not have.
  let slice: [number, number, number] = [0, 0, 0];

  const cameraListeners = new Set<(view: CameraView) => void>();

  function publishCamera() {
    if (cameraListeners.size === 0) return;
    const view = camera.screenBasis();
    for (const listener of cameraListeners) {
      listener(view);
    }
  }

  let dirty = true;
  let running = true;
  let frames = 0;
  let lastFrameMs = 0;

  writeColormap(colormap);

  function writeColormap(name: ColormapName) {
    device.queue.writeTexture(
      { texture: colormapTexture },
      colormapTexels(name),
      { bytesPerRow: COLORMAP_SIZE * 4 },
      { width: COLORMAP_SIZE, height: 1 },
    );
  }

  // Typed arrays are generic over their buffer since TS 5.7; WebGPU only
  // accepts the non-shared ArrayBuffer form, so these are spelled explicitly.
  function storageBuffer(label: string, data: Float32Array<ArrayBuffer>): GPUBuffer {
    const buffer = device.createBuffer({
      label,
      size: Math.max(data.byteLength, 4),
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
    });
    device.queue.writeBuffer(buffer, 0, data);
    return buffer;
  }

  function vertexBuffer(label: string, data: Float32Array<ArrayBuffer>): GPUBuffer {
    const buffer = device.createBuffer({
      label,
      size: data.byteLength,
      usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
    });
    device.queue.writeBuffer(buffer, 0, data);
    return buffer;
  }

  function indexBuffer(label: string, data: Uint32Array<ArrayBuffer>): GPUBuffer {
    const buffer = device.createBuffer({
      label,
      size: data.byteLength,
      usage: GPUBufferUsage.INDEX | GPUBufferUsage.COPY_DST,
    });
    device.queue.writeBuffer(buffer, 0, data);
    return buffer;
  }

  function releaseGeometry() {
    if (!geometry) return;
    for (const buffer of [
      geometry.capVertexBuffer,
      geometry.capIndexBuffer,
      geometry.wallVertexBuffer,
      geometry.wallIndexBuffer,
      geometry.edgeIndexBuffer,
      geometry.topBuffer,
      geometry.botBuffer,
    ]) {
      buffer.destroy();
    }
    geometry = null;
    frameBindGroup = null;
  }

  function releaseScalars() {
    scalars?.buffers.forEach((buffer) => buffer.destroy());
    scalars = null;
  }

  function rebuildFrameBindGroup() {
    if (!geometry) return;
    frameBindGroup = device.createBindGroup({
      label: "frame",
      layout: frameLayout,
      entries: [
        { binding: 0, resource: { buffer: uniformBuffer } },
        { binding: 1, resource: { buffer: geometry.topBuffer } },
        { binding: 2, resource: { buffer: geometry.botBuffer } },
        { binding: 3, resource: colormapTexture.createView() },
        { binding: 4, resource: sampler },
        { binding: 5, resource: { buffer: selectionBuffer } },
      ],
    });
  }

  /**
   * Mark cells as part of the selection being edited.
   *
   * Uploaded as a flag per cell rather than as a list, because the shader asks
   * "is this one selected" per fragment and a list would mean a search there.
   * A megabyte or two per change is nothing at the rate a person clicks.
   *
   * Written in place rather than reallocated. The first version destroyed the
   * buffer and rebuilt the bind group on every call, which invalidated the
   * command buffer of a pick that was still in flight — so clicking a cell
   * cancelled the very readback that was meant to tell us which cell it was.
   */
  function setSelection(cells: Uint32Array | null) {
    if (!geometry) return;

    const total = geometry.ncpl * geometry.nlay;
    if (selectionFlags.length !== total) {
      selectionFlags = new Uint32Array(total);
      selectionBuffer.destroy();
      selectionBuffer = device.createBuffer({
        label: "selection",
        size: Math.max(selectionFlags.byteLength, 4),
        usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
      });
      rebuildFrameBindGroup();
    } else {
      selectionFlags.fill(0);
    }

    for (const cell of cells ?? []) {
      if (cell < total) selectionFlags[cell] = 1;
    }

    device.queue.writeBuffer(selectionBuffer, 0, selectionFlags);
    dirty = true;
  }

  /**
   * Read the cell under one pixel.
   *
   * The whole scene is redrawn to a one-pixel-wide target with the camera
   * unchanged, rather than to a full-size id buffer kept in step with every
   * frame. One extra draw per click is cheaper than maintaining a second
   * render target for the 99.9% of frames nobody clicks on.
   */
  async function pickAt(x: number, y: number): Promise<PickedCell | null> {
    if (!geometry || !scalars || !frameBindGroup) return null;

    const width = canvas.width;
    const height = canvas.height;
    const px = Math.round(x);
    const py = Math.round(y);
    if (px < 0 || py < 0 || px >= width || py >= height) return null;

    if (!pickTexture || pickTexture.width !== width || pickTexture.height !== height) {
      pickTexture?.destroy();
      pickDepth?.destroy();
      pickTexture = device.createTexture({
        label: "pick ids",
        size: [width, height],
        format: PICK_FORMAT,
        usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.COPY_SRC,
      });
      pickDepth = device.createTexture({
        label: "pick depth",
        size: [width, height],
        format: DEPTH_FORMAT,
        usage: GPUTextureUsage.RENDER_ATTACHMENT,
      });
    }
    if (!pickReadback) {
      // 256 bytes is WebGPU's minimum bytesPerRow for a texture copy.
      pickReadback = device.createBuffer({
        label: "pick readback",
        size: 256,
        usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ,
      });
    }

    camera.setAspect(width, height);
    writeUniforms();

    const encoder = device.createCommandEncoder();
    const pass = encoder.beginRenderPass({
      colorAttachments: [
        {
          view: pickTexture.createView(),
          // Zero means nothing was drawn here, which is why ids are offset.
          clearValue: { r: 0, g: 0, b: 0, a: 0 },
          loadOp: "clear",
          storeOp: "store",
        },
      ],
      depthStencilAttachment: {
        view: pickDepth!.createView(),
        depthClearValue: 1,
        depthLoadOp: "clear",
        depthStoreOp: "store",
      },
    });

    pass.setPipeline(pickPipeline);
    pass.setBindGroup(0, frameBindGroup);
    pass.setBindGroup(1, scalars.bindGroups[timestep]);
    pass.setVertexBuffer(0, geometry.capVertexBuffer);
    pass.setIndexBuffer(geometry.capIndexBuffer, "uint32");
    pass.drawIndexed(geometry.capIndexCount, geometry.nlay);
    pass.setVertexBuffer(0, geometry.wallVertexBuffer);
    pass.setIndexBuffer(geometry.wallIndexBuffer, "uint32");
    pass.drawIndexed(geometry.wallIndexCount, geometry.nlay);
    pass.end();

    encoder.copyTextureToBuffer(
      { texture: pickTexture, origin: { x: px, y: py } },
      { buffer: pickReadback, bytesPerRow: 256 },
      { width: 1, height: 1 },
    );
    device.queue.submit([encoder.finish()]);

    await pickReadback.mapAsync(GPUMapMode.READ);
    const raw = new Uint32Array(pickReadback.getMappedRange().slice(0, 4))[0];
    pickReadback.unmap();

    if (raw === 0) return null;
    const index = raw - 1;
    return { layer: Math.floor(index / geometry.ncpl), cell: index % geometry.ncpl };
  }

  function ensureDepthTexture(width: number, height: number) {
    if (depthTexture && depthTexture.width === width && depthTexture.height === height) {
      return;
    }
    depthTexture?.destroy();
    depthTexture = device.createTexture({
      label: "depth",
      size: [width, height],
      format: DEPTH_FORMAT,
      usage: GPUTextureUsage.RENDER_ATTACHMENT,
    });
  }

  function uploadGeometry(input: GridGeometry) {
    releaseGeometry();
    const packed: PackedMesh = packDisv(input);

    geometry = {
      capVertexBuffer: vertexBuffer("cap vertices", packed.capVertices),
      capIndexBuffer: indexBuffer("cap indices", packed.capIndices),
      capIndexCount: packed.capIndices.length,
      wallVertexBuffer: vertexBuffer("wall vertices", packed.wallVertices),
      wallIndexBuffer: indexBuffer("wall indices", packed.wallIndices),
      wallIndexCount: packed.wallIndices.length,
      edgeIndexBuffer: indexBuffer("edge indices", packed.wallEdgeIndices),
      edgeIndexCount: packed.wallEdgeIndices.length,
      topBuffer: storageBuffer("top elevations", input.top),
      botBuffer: storageBuffer("bottom elevations", input.botm),
      nlay: input.nlay,
      ncpl: input.ncpl,
      triangles: packed.triangleCount * input.nlay,
    };

    rebuildFrameBindGroup();
    gridBounds = input.bounds;
    fitCamera();
    dirty = true;
  }

  function uploadScalars(set: ScalarSet) {
    releaseScalars();

    const buffers = set.timesteps.map((values, index) =>
      storageBuffer(`scalars t${index}`, values),
    );
    const bindGroups = buffers.map((buffer) =>
      device.createBindGroup({
        layout: scalarLayout,
        entries: [{ binding: 0, resource: { buffer } }],
      }),
    );

    scalars = { buffers, bindGroups, set };
    timestep = Math.min(timestep, buffers.length - 1);
    range = [set.vmin, set.vmax];
    dirty = true;
  }

  /** Frame the model as it is currently scaled. */
  function fitCamera() {
    if (!gridBounds) return;
    const { min, max } = gridBounds;
    camera.frameBounds(
      [min[0] * axisScale[0], min[1] * axisScale[1], min[2] * axisScale[2]],
      [max[0] * axisScale[0], max[1] * axisScale[1], max[2] * axisScale[2]],
    );
  }

  function writeUniforms() {
    uniformData.set(camera.viewProjection(), 0);
    uniformData.set([0, range[0], range[1], logScale ? 1 : 0], 16);
    uniformData.set([geometry?.ncpl ?? 0, -1, nodata, ghostAbsent ? 1 : 0], 20);
    uniformData.set([...axisScale, 0], 24);
    uniformData.set([...slice, 0], 28);
    device.queue.writeBuffer(uniformBuffer, 0, uniformData);
  }

  function render() {
    if (!geometry || !scalars || !frameBindGroup) return;

    const width = canvas.width;
    const height = canvas.height;
    if (width === 0 || height === 0) return;

    const started = performance.now();
    camera.setAspect(width, height);
    ensureDepthTexture(width, height);
    writeUniforms();

    const encoder = device.createCommandEncoder();
    const pass = encoder.beginRenderPass({
      colorAttachments: [
        {
          view: context!.getCurrentTexture().createView(),
          clearValue: { r: 0.06, g: 0.07, b: 0.09, a: 1 },
          loadOp: "clear",
          storeOp: "store",
        },
      ],
      depthStencilAttachment: {
        view: depthTexture!.createView(),
        depthClearValue: 1,
        depthLoadOp: "clear",
        depthStoreOp: "store",
      },
    });

    pass.setPipeline(pipeline);
    pass.setBindGroup(0, frameBindGroup);
    pass.setBindGroup(1, scalars.bindGroups[timestep]);

    // Two draws for the entire model. Instance count is the layer count; the
    // vertex shader turns instance_index into an elevation lookup.
    pass.setVertexBuffer(0, geometry.capVertexBuffer);
    pass.setIndexBuffer(geometry.capIndexBuffer, "uint32");
    pass.drawIndexed(geometry.capIndexCount, geometry.nlay);

    pass.setVertexBuffer(0, geometry.wallVertexBuffer);
    pass.setIndexBuffer(geometry.wallIndexBuffer, "uint32");
    pass.drawIndexed(geometry.wallIndexCount, geometry.nlay);

    if (showEdges) {
      // Same vertex buffer, drawn as lines: no extra geometry, and the outlines
      // follow the faces exactly under any exaggeration.
      pass.setPipeline(edgePipeline);
      pass.setBindGroup(0, frameBindGroup);
      pass.setBindGroup(1, scalars.bindGroups[timestep]);
      pass.setIndexBuffer(geometry.edgeIndexBuffer, "uint32");
      pass.drawIndexed(geometry.edgeIndexCount, geometry.nlay);
    }

    pass.end();
    device.queue.submit([encoder.finish()]);

    lastFrameMs = performance.now() - started;
    frames++;
  }

  function loop() {
    if (!running) return;
    if (dirty) {
      dirty = false;
      render();
    }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);

  const detachInput = attachPointerControls(canvas, camera, () => {
    dirty = true;
    publishCamera();
  });

  const viewport: Viewport = {
    setGrid(input) {
      uploadGeometry(input);
    },
    setScalars(set) {
      uploadScalars(set);
    },
    setTimestep(index) {
      if (!scalars) return;
      const clamped = Math.min(Math.max(index, 0), scalars.bindGroups.length - 1);
      if (clamped !== timestep) {
        timestep = clamped;
        dirty = true;
      }
    },
    getTimestep: () => timestep,
    setColormap(name) {
      colormap = name;
      writeColormap(name);
      dirty = true;
    },
    setRange(min, max) {
      range = [min, max];
      dirty = true;
    },
    setLogScale(enabled) {
      logScale = enabled;
      dirty = true;
    },
    setShowEdges(enabled) {
      showEdges = enabled;
      dirty = true;
    },
    setGhostAbsent(enabled) {
      ghostAbsent = enabled;
      dirty = true;
    },
    setSlice(mode, index, columns = 0) {
      const modes = { all: 0, layer: 1, row: 2, column: 3 } as const;
      slice = [modes[mode], Math.max(0, Math.floor(index)), Math.max(0, Math.floor(columns))];
      dirty = true;
    },
    setCanonicalView(view) {
      camera.setOrientation(view);
      dirty = true;
    },
    setVerticalExaggeration(factor) {
      axisScale = [axisScale[0], axisScale[1], factor];
      // Rescaling without refitting pushes the model out of view, so the
      // camera follows the extent it is now looking at.
      fitCamera();
      dirty = true;
    },
    setAxisScale(x, y, z) {
      axisScale = [x, y, z];
      fitCamera();
      dirty = true;
      publishCamera();
    },
    pick: pickAt,
    setSelection,
    onCamera(listener) {
      cameraListeners.add(listener);
      // Fire once so a subscriber starts from the current view rather than
      // waiting for the first interaction.
      listener(camera.screenBasis());
      return () => cameraListeners.delete(listener);
    },
    frameAll() {
      fitCamera();
      dirty = true;
    },
    requestRender() {
      dirty = true;
    },
    async renderAndWait() {
      dirty = false;
      render();
      // submit() returns as soon as the work is queued, so timing around
      // render() alone measures encoding. Waiting here makes the caller's
      // elapsed time include the GPU actually drawing.
      await device.queue.onSubmittedWorkDone();
    },
    stats(): FrameStats {
      return {
        frames,
        lastFrameMs,
        triangles: geometry?.triangles ?? 0,
        adapter: adapterName,
      };
    },
    destroy() {
      // Only if this viewport still owns the canvas: a later one may already
      // have taken it, and clearing the entry would lose the newcomer.
      if (active.get(canvas) === viewport) active.delete(canvas);
      running = false;
      detachInput();
      cameraListeners.clear();
      releaseScalars();
      releaseGeometry();
      depthTexture?.destroy();
      pickTexture?.destroy();
      pickDepth?.destroy();
      pickReadback?.destroy();
      uniformBuffer.destroy();
      colormapTexture.destroy();
      device.destroy();
    },
  };

  active.set(canvas, viewport);
  return viewport;
}

/** Mouse and wheel to camera moves. Returns a function that unbinds them. */
function attachPointerControls(
  canvas: HTMLCanvasElement,
  camera: ArcballCamera,
  onChange: () => void,
): () => void {
  let dragging: "orbit" | "pan" | null = null;
  let lastX = 0;
  let lastY = 0;

  const down = (event: PointerEvent) => {
    // Orbiting a flat view would tilt it back into a perspective-like oblique,
    // which is exactly what the plan and section views exist to avoid. There,
    // a left drag pans; the 3D view is the one that turns.
    const orbits = event.button === 0 && !event.shiftKey && !camera.isFlat;
    dragging = orbits ? "orbit" : "pan";
    lastX = event.clientX;
    lastY = event.clientY;
    canvas.setPointerCapture(event.pointerId);
  };

  const move = (event: PointerEvent) => {
    if (!dragging) return;
    const deltaX = event.clientX - lastX;
    const deltaY = event.clientY - lastY;
    lastX = event.clientX;
    lastY = event.clientY;

    if (dragging === "orbit") {
      camera.orbit(deltaX, deltaY);
    } else {
      camera.pan(deltaX, deltaY, canvas.clientHeight);
    }
    onChange();
  };

  const up = (event: PointerEvent) => {
    dragging = null;
    canvas.releasePointerCapture(event.pointerId);
  };

  const wheel = (event: WheelEvent) => {
    event.preventDefault();
    camera.dolly(event.deltaY);
    onChange();
  };

  canvas.addEventListener("pointerdown", down);
  canvas.addEventListener("pointermove", move);
  canvas.addEventListener("pointerup", up);
  canvas.addEventListener("pointercancel", up);
  canvas.addEventListener("wheel", wheel, { passive: false });

  return () => {
    canvas.removeEventListener("pointerdown", down);
    canvas.removeEventListener("pointermove", move);
    canvas.removeEventListener("pointerup", up);
    canvas.removeEventListener("pointercancel", up);
    canvas.removeEventListener("wheel", wheel);
  };
}
