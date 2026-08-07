"""Regenerate the cross-language frame fixtures.

The .bin files here are decoded by both pytest and vitest, so the Python encoder
and the TypeScript decoder cannot drift apart without a test failing. Run this
after any change to the frame format, and commit the result:

    uv run python tests/fixtures/generate_frames.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from mupstudio.server.ws.frames import encode

OUT = Path(__file__).parent / "frames"


def build() -> list[dict[str, object]]:
    """Each case: a file, plus what a correct decoder must produce from it."""
    cases: list[dict[str, object]] = []

    scalar = np.array([[1.5, -2.25, 0.0], [3.75, 1e-8, -1e8]], dtype=np.float32)
    cases.append(
        {
            "file": "scalar_f32.bin",
            "bytes": encode(
                "scalar",
                scalar,
                reqId=7,
                component="Ca",
                timeIdx=3,
                time=120.5,
                vmin=float(scalar.min()),
                vmax=float(scalar.max()),
            ),
            "expect": {
                "kind": "scalar",
                "dtype": "float32",
                "shape": [2, 3],
                "component": "Ca",
                "timeIdx": 3,
                "values": [float(v) for v in scalar.ravel()],
            },
        }
    )

    offsets = np.array([0, 4, 8, 14], dtype=np.int32)
    cases.append(
        {
            "file": "cell_offsets_i32.bin",
            "bytes": encode("mesh_cell_offsets", offsets, reqId=1),
            "expect": {
                "kind": "mesh_cell_offsets",
                "dtype": "int32",
                "shape": [4],
                "values": [int(v) for v in offsets],
            },
        }
    )

    verts = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], dtype=np.float32)
    cases.append(
        {
            "file": "vertices_f32.bin",
            "bytes": encode("mesh_vertices", verts, reqId=2, gridHash="abc123"),
            "expect": {
                "kind": "mesh_vertices",
                "dtype": "float32",
                "shape": [4, 2],
                "gridHash": "abc123",
                "values": [float(v) for v in verts.ravel()],
            },
        }
    )

    # Empty payload: a legal edge case the decoders must not choke on.
    cases.append(
        {
            "file": "empty_f32.bin",
            "bytes": encode("scalar", np.zeros(0, dtype=np.float32), reqId=3),
            "expect": {"kind": "scalar", "dtype": "float32", "shape": [0], "values": []},
        }
    )

    return cases


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for case in build():
        name = str(case["file"])
        (OUT / name).write_bytes(case["bytes"])  # type: ignore[arg-type]
        manifest.append({"file": name, **case["expect"]})  # type: ignore[dict-item]

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {len(manifest)} fixtures to {OUT}")


if __name__ == "__main__":
    main()
