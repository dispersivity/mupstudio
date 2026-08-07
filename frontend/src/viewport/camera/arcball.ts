/**
 * Arcball camera: orbit, pan and dolly around a target point.
 *
 * Orientation is held as spherical angles rather than a quaternion. It is the
 * same thing for an arcball constrained to keep z up, and it makes the horizon
 * stay level, which is what you want looking at a geological model.
 */

import { mat4, vec3 } from "wgpu-matrix";

const MIN_PITCH = -Math.PI / 2 + 0.01;
const MAX_PITCH = Math.PI / 2 - 0.01;
const MIN_DISTANCE = 1e-4;

export interface CameraState {
  target: [number, number, number];
  distance: number;
  /** Rotation about the z axis, radians. */
  yaw: number;
  /** Elevation above the xy plane, radians, clamped short of the poles. */
  pitch: number;
  fovY: number;
  near: number;
  far: number;
}

export class ArcballCamera {
  private state: CameraState;
  private aspect = 1;

  constructor(initial?: Partial<CameraState>) {
    this.state = {
      target: [0, 0, 0],
      distance: 10,
      yaw: -Math.PI / 4,
      pitch: 0.6,
      fovY: (50 * Math.PI) / 180,
      near: 0.1,
      far: 10_000,
      ...initial,
    };
  }

  get snapshot(): Readonly<CameraState> {
    return { ...this.state, target: [...this.state.target] };
  }

  setAspect(width: number, height: number) {
    this.aspect = height > 0 ? width / height : 1;
  }

  /** Drag to orbit. Pixels in, radians applied. */
  orbit(deltaX: number, deltaY: number, radiansPerPixel = 0.008) {
    this.state.yaw -= deltaX * radiansPerPixel;
    this.state.pitch = clamp(this.state.pitch + deltaY * radiansPerPixel, MIN_PITCH, MAX_PITCH);
  }

  /**
   * Drag to pan. The move is scaled by distance so a drag shifts the model by
   * the same on-screen amount however far out the camera is.
   */
  pan(deltaX: number, deltaY: number, viewportHeight: number) {
    const worldPerPixel =
      (2 * this.state.distance * Math.tan(this.state.fovY / 2)) / viewportHeight;
    const { right, up } = this.basis();

    for (let axis = 0; axis < 3; axis++) {
      this.state.target[axis] +=
        -right[axis] * deltaX * worldPerPixel + up[axis] * deltaY * worldPerPixel;
    }
  }

  /** Wheel to dolly. Multiplicative so each notch feels the same at any zoom. */
  dolly(scrollDelta: number, sensitivity = 0.0015) {
    this.state.distance = Math.max(
      MIN_DISTANCE,
      this.state.distance * Math.exp(scrollDelta * sensitivity),
    );
  }

  /** Frame an axis-aligned box, leaving a little margin around it. */
  frameBounds(min: readonly number[], max: readonly number[], margin = 1.25) {
    this.state.target = [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2];

    const radius =
      Math.max(Math.hypot(max[0] - min[0], max[1] - min[1], max[2] - min[2]) / 2, MIN_DISTANCE) *
      margin;

    this.state.distance = radius / Math.sin(this.state.fovY / 2);
    // Keep the whole model inside the frustum whatever its scale.
    this.state.near = Math.max(this.state.distance / 1000, 1e-3);
    this.state.far = this.state.distance * 10;
  }

  /** Position in world space, derived from target, distance and angles. */
  get eye(): [number, number, number] {
    const { target, distance, yaw, pitch } = this.state;
    const horizontal = Math.cos(pitch) * distance;
    return [
      target[0] + horizontal * Math.cos(yaw),
      target[1] + horizontal * Math.sin(yaw),
      target[2] + Math.sin(pitch) * distance,
    ];
  }

  viewProjection(): Float32Array {
    const { target, fovY, near, far } = this.state;
    const view = mat4.lookAt(this.eye, target, [0, 0, 1]);
    const projection = mat4.perspective(fovY, this.aspect, near, far);
    return mat4.multiply(projection, view) as Float32Array;
  }

  /**
   * The world directions that point right and up on screen.
   *
   * Public because an orientation gizmo needs them: projecting the three world
   * axes onto these gives their screen directions without exposing matrices.
   */
  screenBasis(): { right: [number, number, number]; up: [number, number, number] } {
    const { right, up } = this.basis();
    return {
      right: [right[0], right[1], right[2]],
      up: [up[0], up[1], up[2]],
    };
  }

  /** Screen-space right and up axes, used to turn a drag into a world move. */
  private basis() {
    const forward = vec3.normalize(vec3.subtract(this.state.target, this.eye));
    const right = vec3.normalize(vec3.cross(forward, [0, 0, 1]));
    const up = vec3.normalize(vec3.cross(right, forward));
    return { right, up };
  }
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}
