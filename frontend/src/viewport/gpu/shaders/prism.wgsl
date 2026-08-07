// Prism extrusion and colormap.
//
// The whole model draws in two instanced calls: one for the top and bottom
// caps, one for the side walls. Geometry for a SINGLE layer is uploaded once;
// instance_index selects the layer, and the vertex shader looks up that
// layer's elevation for the cell to place the vertex in z. Nothing is
// duplicated per layer on the CPU and nothing is re-uploaded when the layer
// count or the elevations change.
//
// Each vertex carries the cell it belongs to (within a layer) and which face
// it is on, top or bottom. That pair plus the layer is enough to find both the
// elevation and the scalar value, so vertex attributes stay at 16 bytes.

struct Frame {
  viewProj: mat4x4<f32>,
  // x: vertical exaggeration, y: scalar range min, z: scalar range max,
  // w: 1 when the colour scale is logarithmic.
  params: vec4<f32>,
  // x: cells per layer, y: active layer or -1 for all, z: nodata sentinel,
  // w: unused.
  gridInfo: vec4<f32>,
  lightDir: vec4<f32>,
};

@group(0) @binding(0) var<uniform> frame: Frame;
// Elevations for every cell in every layer, layer-major: [layer * ncpl + cell].
@group(0) @binding(1) var<storage, read> topElev: array<f32>;
@group(0) @binding(2) var<storage, read> botElev: array<f32>;
@group(0) @binding(3) var colormap: texture_2d<f32>;
@group(0) @binding(4) var colormapSampler: sampler;

// Swapped per timestep. Its own group so changing time rebinds one thing.
@group(1) @binding(0) var<storage, read> scalars: array<f32>;

struct VertexIn {
  @location(0) position: vec2<f32>,
  // Cell index within a layer. u32 in spirit; f32 keeps the attribute layout
  // uniform and 2^24 is far beyond any grid we will draw.
  @location(1) cellInLayer: f32,
  // 0 = this vertex sits on the cell top, 1 = on the bottom.
  @location(2) face: f32,
};

struct VertexOut {
  @builtin(position) clipPosition: vec4<f32>,
  @location(0) @interpolate(flat) value: f32,
  @location(1) @interpolate(flat) shade: f32,
};

fn cellIndex(cellInLayer: f32, layer: u32) -> u32 {
  return layer * u32(frame.gridInfo.x) + u32(cellInLayer);
}

@vertex
fn vertexMain(input: VertexIn, @builtin(instance_index) layer: u32) -> VertexOut {
  let cell = cellIndex(input.cellInLayer, layer);

  // This is the extrusion: xy comes from the flat footprint, z is fetched per
  // cell per layer. The 2D mesh is never expanded into a 3D one.
  let elevation = select(botElev[cell], topElev[cell], input.face < 0.5);
  let world = vec3<f32>(input.position, elevation * frame.params.x);

  var out: VertexOut;
  out.clipPosition = frame.viewProj * vec4<f32>(world, 1.0);
  out.value = scalars[cell];

  // Flat faces get a fixed shade so the prisms read as solid without normals.
  // Walls are darker than caps, which is enough to see the layering.
  out.shade = select(0.72, 1.0, input.face < 0.5);
  return out;
}

fn normalise(value: f32) -> f32 {
  let lo = frame.params.y;
  let hi = frame.params.z;
  if (frame.params.w > 0.5) {
    // Log scale. Values at or below zero clamp to the bottom of the ramp
    // rather than producing NaN.
    let safeLo = max(lo, 1e-12);
    let safeValue = max(value, safeLo);
    let logLo = log(safeLo);
    let logHi = log(max(hi, safeLo * 1.0000001));
    return clamp((log(safeValue) - logLo) / (logHi - logLo), 0.0, 1.0);
  }
  let span = max(hi - lo, 1e-12);
  return clamp((value - lo) / span, 0.0, 1.0);
}

@fragment
fn fragmentMain(input: VertexOut) -> @location(0) vec4<f32> {
  // Inactive cells carry a sentinel; drop them so holes in the grid are holes
  // on screen rather than an arbitrary colour.
  if (input.value == frame.gridInfo.z) {
    discard;
  }

  let t = normalise(input.value);
  let colour = textureSampleLevel(colormap, colormapSampler, vec2<f32>(t, 0.5), 0.0);
  return vec4<f32>(colour.rgb * input.shade, 1.0);
}
