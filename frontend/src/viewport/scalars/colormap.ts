/**
 * Colormap lookup tables, built as 256x1 RGBA textures.
 *
 * Control points are sampled from the standard matplotlib ramps at eight stops
 * and interpolated between; eight stops is enough that a 256-entry ramp is
 * visually indistinguishable from the real thing, and it keeps the table small
 * enough to read.
 */

export const COLORMAP_SIZE = 256;

export type ColormapName = "viridis" | "turbo" | "magma" | "rdbu";

type Stop = readonly [number, number, number];

const RAMPS: Record<ColormapName, readonly Stop[]> = {
  // Perceptually uniform, colourblind-safe: the right default for scalar fields.
  viridis: [
    [0.267, 0.005, 0.329],
    [0.283, 0.141, 0.458],
    [0.254, 0.265, 0.53],
    [0.207, 0.372, 0.553],
    [0.164, 0.471, 0.558],
    [0.128, 0.567, 0.551],
    [0.135, 0.659, 0.518],
    [0.267, 0.749, 0.441],
  ],
  turbo: [
    [0.19, 0.072, 0.232],
    [0.276, 0.44, 0.94],
    [0.147, 0.75, 0.93],
    [0.181, 0.936, 0.605],
    [0.626, 0.995, 0.234],
    [0.947, 0.809, 0.176],
    [0.983, 0.478, 0.144],
    [0.729, 0.128, 0.017],
  ],
  magma: [
    [0.001, 0.0, 0.014],
    [0.135, 0.068, 0.315],
    [0.343, 0.086, 0.498],
    [0.551, 0.161, 0.506],
    [0.767, 0.234, 0.457],
    [0.936, 0.375, 0.372],
    [0.99, 0.62, 0.494],
    [0.987, 0.868, 0.72],
  ],
  // Diverging: for differences, where the midpoint is meaningful.
  rdbu: [
    [0.404, 0.0, 0.121],
    [0.698, 0.094, 0.168],
    [0.839, 0.376, 0.302],
    [0.957, 0.647, 0.51],
    [0.82, 0.898, 0.941],
    [0.573, 0.773, 0.871],
    [0.262, 0.576, 0.765],
    [0.019, 0.188, 0.38],
  ],
};

export const COLORMAP_NAMES = Object.keys(RAMPS) as ColormapName[];

/** Build the RGBA8 bytes for a ramp, ready to write into a texture. */
export function colormapTexels(name: ColormapName): Uint8Array<ArrayBuffer> {
  const stops = RAMPS[name];
  if (!stops) {
    throw new Error(`unknown colormap ${name}; have ${COLORMAP_NAMES.join(", ")}`);
  }

  const texels = new Uint8Array(new ArrayBuffer(COLORMAP_SIZE * 4));
  const lastStop = stops.length - 1;

  for (let index = 0; index < COLORMAP_SIZE; index++) {
    const position = (index / (COLORMAP_SIZE - 1)) * lastStop;
    const low = Math.min(Math.floor(position), lastStop - 1);
    const blend = position - low;

    for (let channel = 0; channel < 3; channel++) {
      const value = stops[low][channel] * (1 - blend) + stops[low + 1][channel] * blend;
      texels[index * 4 + channel] = Math.round(clamp01(value) * 255);
    }
    texels[index * 4 + 3] = 255;
  }

  return texels;
}

/**
 * Sample a ramp at t in [0, 1] as CSS rgb(). Used by the colorbar so the HTML
 * legend and the GPU rendering come from one definition.
 */
export function colormapCss(name: ColormapName, t: number): string {
  const texels = colormapTexels(name);
  const index = Math.round(clamp01(t) * (COLORMAP_SIZE - 1)) * 4;
  return `rgb(${texels[index]}, ${texels[index + 1]}, ${texels[index + 2]})`;
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}
