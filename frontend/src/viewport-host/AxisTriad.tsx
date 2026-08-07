import type { CameraView } from "@/viewport/types";
import { projectAxes } from "./axisProjection";

const SIZE = 92;
const CENTRE = SIZE / 2;
const ARM = 31;

/**
 * Which way is x, y and z, from where the camera is now.
 *
 * Drawn as SVG over the canvas rather than in the render pass: it changes only
 * when the camera moves, and keeping it out of the frame loop is the point of
 * the overlay layer.
 *
 * Each world axis is projected onto the screen basis. An axis pointing away
 * from the viewer is drawn faded, so an ambiguous view still reads correctly.
 */
export function AxisTriad({
  camera,
  exaggeration,
}: {
  camera: CameraView | null;
  /** Shown when any axis is scaled, since the picture is then not to scale. */
  exaggeration?: { x: number; y: number; z: number };
}) {
  if (!camera) return null;

  const ordered = projectAxes(camera);
  const distorted =
    exaggeration !== undefined &&
    (exaggeration.x !== 1 || exaggeration.y !== 1 || exaggeration.z !== 1);

  return (
    <div className="pointer-events-none absolute bottom-20 left-4 rounded bg-black/40 p-1 backdrop-blur-sm">
      <svg width={SIZE} height={SIZE} aria-label="Orientation" role="img">
        {ordered.map((axis) => {
          const tipX = CENTRE + axis.screenX * ARM;
          const tipY = CENTRE + axis.screenY * ARM;
          const away = axis.depth < 0;
          return (
            <g key={axis.label} opacity={away ? 0.35 : 1}>
              <line
                x1={CENTRE}
                y1={CENTRE}
                x2={tipX}
                y2={tipY}
                stroke={axis.colour}
                strokeWidth={1.5}
                strokeLinecap="round"
              />
              <circle cx={tipX} cy={tipY} r={8} fill={axis.colour} opacity={away ? 0.5 : 0.9} />
              <text
                x={tipX}
                y={tipY + 3.5}
                textAnchor="middle"
                fontSize={10}
                fontWeight={600}
                fill="#18181b"
              >
                {axis.label}
              </text>
            </g>
          );
        })}
      </svg>

      {distorted && (
        <div
          className="px-1 pb-0.5 text-center text-[9px] text-amber-300"
          title="One or more axes are scaled, so the view is not to scale."
        >
          not to scale
        </div>
      )}
    </div>
  );
}
