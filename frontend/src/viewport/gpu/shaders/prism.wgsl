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
  // x: unused (axis scaling moved to axisScale), y: scalar range min,
  // z: scalar range max, w: 1 when the colour scale is logarithmic.
  params: vec4<f32>,
  // x: cells per layer, y: active layer or -1 for all, z: nodata sentinel,
  // w: unused.
  gridInfo: vec4<f32>,
  // Per-axis world scale. z is vertical exaggeration; x and y let a model with
  // a single row or column be squashed so it reads as the 1D profile it is
  // rather than as a slab.
  axisScale: vec4<f32>,
  // Which part of the model to draw: see inSlice below.
  slice: vec4<f32>,
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
  // Which cell this fragment belongs to, for picking. Flat: a cell is one
  // colour and one identity, so interpolating either would be wrong.
  @location(2) @interpolate(flat) cellId: u32,
};

fn cellIndex(cellInLayer: f32, layer: u32) -> u32 {
  return layer * u32(frame.gridInfo.x) + u32(cellInLayer);
}

// Whether a cell is part of the slice currently on show.
//
// Checking input means answering "which cells", and an oblique view of a solid
// block cannot: the front faces hide the ones behind. One layer seen from above,
// or one row seen from the side, has nothing hidden in it. So the whole model is
// one of four views rather than the only one.
//
// slice = (mode, index, columns per row, unused).
//   0  the whole model
//   1  one layer, seen in plan
//   2  one row of cells, seen from the front
//   3  one column of cells, seen from the side
fn inSlice(cellInLayer: f32, layer: u32) -> bool {
  let mode = i32(frame.slice.x);
  if (mode == 0) {
    return true;
  }
  if (mode == 1) {
    return layer == u32(frame.slice.y);
  }

  // Row and column need the grid's shape, which only a structured grid has.
  let columns = u32(frame.slice.z);
  if (columns == 0u) {
    return true;
  }
  let cell = u32(cellInLayer);
  if (mode == 2) {
    return cell / columns == u32(frame.slice.y);
  }
  return cell % columns == u32(frame.slice.y);
}

@vertex
fn vertexMain(input: VertexIn, @builtin(instance_index) layer: u32) -> VertexOut {
  let cell = cellIndex(input.cellInLayer, layer);

  // This is the extrusion: xy comes from the flat footprint, z is fetched per
  // cell per layer. The 2D mesh is never expanded into a 3D one.
  let elevation = select(botElev[cell], topElev[cell], input.face < 0.5);
  let world = vec3<f32>(input.position, elevation) * frame.axisScale.xyz;

  var out: VertexOut;
  if (!inSlice(input.cellInLayer, layer)) {
    // Collapsed to a point, so its triangles have no area and nothing is
    // rasterised. Cheaper than discarding every fragment, and it keeps the
    // cell out of the pick buffer too.
    out.clipPosition = vec4<f32>(0.0, 0.0, 0.0, 0.0);
    out.value = frame.gridInfo.z;
    out.shade = 1.0;
    out.cellId = cell;
    return out;
  }
  out.clipPosition = frame.viewProj * vec4<f32>(world, 1.0);
  out.value = scalars[cell];

  // Flat faces get a fixed shade so the prisms read as solid without normals.
  // Walls are darker than caps, which is enough to see the layering.
  out.shade = select(0.72, 1.0, input.face < 0.5);
  out.cellId = cell;
  return out;
}

// Whether a cell has a value at all.
//
// Two ways of saying "nothing here". A grid hole carries the nodata sentinel,
// which is an ordinary number and compares equal. A field that only applies to
// some cells — where a boundary acts, which minerals a zone holds — carries
// not-a-number in the rest, and NaN compares equal to nothing, including
// itself. That inequality is the only portable test for it: WGSL has no isnan.
fn isAbsent(value: f32) -> bool {
  return value != value || value == frame.gridInfo.z;
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
  if (isAbsent(input.value)) {
    // A field that applies to a handful of cells needs the rest for context: a
    // single bright cell floating in space says nothing about where it is. Drawn
    // as a dim shell, the grid is still there and the cells that carry a value
    // stand out of it. Off, absent cells are holes, which is what a grid with
    // inactive regions wants.
    if (frame.gridInfo.w > 0.5) {
      return vec4<f32>(vec3<f32>(0.10, 0.11, 0.13) * input.shade, 1.0);
    }
    discard;
  }

  let t = normalise(input.value);
  let colour = textureSampleLevel(colormap, colormapSampler, vec2<f32>(t, 0.5), 0.0);
  return vec4<f32>(colour.rgb * input.shade, 1.0);
}

// Cell outlines. Shares vertexMain, so edges sit exactly on the extruded faces
// whatever the axis scaling is, and needs no geometry of its own.
@fragment
fn fragmentEdge(input: VertexOut) -> @location(0) vec4<f32> {
  if (isAbsent(input.value)) {
    // Ghosted cells keep their outlines. Without them the shell is a
    // featureless block, and a section drawn as one solid grey rectangle hides
    // exactly what a section is for: which layer, and how thick.
    if (frame.gridInfo.w > 0.5) {
      return vec4<f32>(0.16, 0.17, 0.20, 1.0);
    }
    discard;
  }
  return vec4<f32>(0.06, 0.07, 0.09, 1.0);
}

// Cell identity, rendered to an offscreen integer target and read back a pixel
// at a time. Ids are offset by one so zero can mean "nothing here": the target
// is cleared to zero and a click on the background must be distinguishable
// from a click on cell 0.
@fragment
fn fragmentPick(input: VertexOut) -> @location(0) u32 {
  if (isAbsent(input.value)) {
    discard;
  }
  return input.cellId + 1u;
}
