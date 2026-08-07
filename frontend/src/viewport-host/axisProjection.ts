/**
 * Where the world axes point on screen.
 *
 * Separate from the component that draws them so the maths can be tested
 * without a DOM, and so the component file exports only a component.
 */

import type { CameraView } from "@/viewport/types";

// x east, y north, z up — the MODFLOW convention, and the colours ParaView and
// Blender use, so the mapping is already familiar.
const AXES: { label: string; world: [number, number, number]; colour: string }[] = [
  { label: "x", world: [1, 0, 0], colour: "#f87171" },
  { label: "y", world: [0, 1, 0], colour: "#4ade80" },
  { label: "z", world: [0, 0, 1], colour: "#60a5fa" },
];

function dot(a: readonly number[], b: readonly number[]): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

export interface ProjectedAxis {
  label: string;
  colour: string;
  /** Screen offset from the gizmo centre, in the range -1 to 1. */
  screenX: number;
  screenY: number;
  /** Positive when the axis points towards the viewer. */
  depth: number;
}

/**
 * Project the three world axes onto the screen.
 *
 * Uses the camera's screen basis, so this is the true on-screen direction of
 * each axis, not an approximation. Returned back-to-front so a caller drawing
 * in order gets correct overlap.
 */
export function projectAxes(camera: CameraView): ProjectedAxis[] {
  // The direction pointing at the viewer completes the basis.
  const towards: [number, number, number] = [
    camera.right[1] * camera.up[2] - camera.right[2] * camera.up[1],
    camera.right[2] * camera.up[0] - camera.right[0] * camera.up[2],
    camera.right[0] * camera.up[1] - camera.right[1] * camera.up[0],
  ];

  return AXES.map((axis) => ({
    label: axis.label,
    colour: axis.colour,
    screenX: dot(axis.world, camera.right),
    // SVG y grows downward while screen up is positive, hence the negation.
    screenY: -dot(axis.world, camera.up),
    depth: dot(axis.world, towards),
  })).sort((a, b) => a.depth - b.depth);
}
