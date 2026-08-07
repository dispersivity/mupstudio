import { describe, expect, it } from "vitest";
import { ArcballCamera } from "@/viewport/camera/arcball";
import { projectAxes } from "./axisProjection";
import type { CameraView } from "@/viewport/types";

/** Looking down the -y axis with z up: x right, z up, y into the screen. */
const LOOKING_NORTH: CameraView = {
  right: [1, 0, 0],
  up: [0, 0, 1],
};

function byLabel(camera: CameraView) {
  return new Map(projectAxes(camera).map((axis) => [axis.label, axis]));
}

describe("projectAxes", () => {
  it("puts x to the right when the camera looks north", () => {
    const x = byLabel(LOOKING_NORTH).get("x")!;

    expect(x.screenX).toBeCloseTo(1);
    expect(x.screenY).toBeCloseTo(0);
  });

  it("puts z up the screen, which is negative in SVG coordinates", () => {
    const z = byLabel(LOOKING_NORTH).get("z")!;

    expect(z.screenY).toBeCloseTo(-1);
    expect(z.screenX).toBeCloseTo(0);
  });

  it("shows an axis pointing away from the viewer as having negative depth", () => {
    const y = byLabel(LOOKING_NORTH).get("y")!;

    // Looking north means +y goes into the screen.
    expect(y.depth).toBeLessThan(0);
    expect(y.screenX).toBeCloseTo(0);
    expect(y.screenY).toBeCloseTo(0);
  });

  it("returns axes back to front so drawing in order overlaps correctly", () => {
    const depths = projectAxes(LOOKING_NORTH).map((axis) => axis.depth);

    expect(depths).toEqual([...depths].sort((a, b) => a - b));
  });

  it("always describes all three axes", () => {
    const labels = projectAxes(LOOKING_NORTH).map((axis) => axis.label);

    expect(labels.sort()).toEqual(["x", "y", "z"]);
  });

  it("keeps screen offsets within the unit range", () => {
    for (const axis of projectAxes(LOOKING_NORTH)) {
      expect(Math.abs(axis.screenX)).toBeLessThanOrEqual(1.0001);
      expect(Math.abs(axis.screenY)).toBeLessThanOrEqual(1.0001);
    }
  });

  it("follows a real camera as it orbits", () => {
    const camera = new ArcballCamera({ yaw: 0, pitch: 0 });
    const before = byLabel(camera.screenBasis()).get("x")!;

    camera.orbit(400, 0); // a large horizontal drag
    const after = byLabel(camera.screenBasis()).get("x")!;

    expect(after.screenX).not.toBeCloseTo(before.screenX);
  });

  it("keeps z pointing up the screen at any orbit angle", () => {
    const camera = new ArcballCamera({ yaw: 0, pitch: 0.5 });

    for (const drag of [0, 120, 240, 360]) {
      camera.orbit(drag, 0);
      const z = byLabel(camera.screenBasis()).get("z")!;
      // Never below the horizon: the camera keeps world z as screen up.
      expect(z.screenY).toBeLessThan(0);
    }
  });
});

describe("ArcballCamera.screenBasis", () => {
  it("returns perpendicular unit vectors", () => {
    const { right, up } = new ArcballCamera({ yaw: 0.7, pitch: 0.4 }).screenBasis();
    const length = (v: number[]) => Math.hypot(v[0], v[1], v[2]);
    const dot = right[0] * up[0] + right[1] * up[1] + right[2] * up[2];

    expect(length(right)).toBeCloseTo(1);
    expect(length(up)).toBeCloseTo(1);
    expect(dot).toBeCloseTo(0);
  });

  it("keeps the horizon level: right stays in the xy plane", () => {
    const { right } = new ArcballCamera({ yaw: 1.1, pitch: 0.9 }).screenBasis();

    expect(right[2]).toBeCloseTo(0);
  });
});
