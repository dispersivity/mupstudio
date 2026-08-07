"""Binary frame format for shipping arrays to the browser.

One frame carries one array. The layout is::

    offset  size  field
    0       4     magic b"MUPB"
    4       2     version (uint16 LE)
    6       2     flags (uint16 LE), bit 0 = payload is zstd compressed
    8       4     header length in bytes (uint32 LE)
    12      ...   header, UTF-8 JSON
    ...     ...   payload, C-order array bytes

Everything is little-endian: WebGPU wants little-endian buffers and every
platform we target is little-endian, so no byte swapping ever happens.

The header is padded with spaces so the payload always starts on an 8-byte
boundary. JavaScript cannot create a typed-array view at an unaligned offset,
and copying to realign would defeat the whole point of sending raw arrays —
these payloads reach hundreds of megabytes and go straight to the GPU. JSON
ignores the trailing whitespace, so decoders need no special handling.

The header describes the payload well enough for the client to upload it to the
GPU without a second request: dtype, shape, and the value range needed to set
up a colormap. Keeping it JSON means new fields can be added without a version
bump, as long as old clients can ignore them.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

MAGIC = b"MUPB"
VERSION = 1
FLAG_ZSTD = 1 << 0
_PREFIX = struct.Struct("<4sHHI")
HEADER_OFFSET = _PREFIX.size
# Payload alignment. 8 rather than 4 so the format stays usable if a 64-bit
# dtype is ever added without another padding change.
PAYLOAD_ALIGNMENT = 8

FrameKind = Literal[
    "mesh_vertices",
    "mesh_cell_offsets",
    "mesh_cell_indices",
    "mesh_cell_centers",
    "cell_elevations",
    "scalar",
    "scalar_block",
]

# numpy dtypes the client knows how to read; anything else is a bug on our side.
_ALLOWED_DTYPES = {"float32", "int32", "uint32", "uint8"}


@dataclass(frozen=True)
class Frame:
    """A decoded frame: its header and the array it carried."""

    header: dict[str, Any]
    array: np.ndarray

    @property
    def kind(self) -> str:
        return str(self.header["kind"])


def encode(
    kind: FrameKind,
    array: np.ndarray,
    *,
    compress: bool = False,
    **header_fields: Any,
) -> bytes:
    """Pack an array into a frame.

    The array is made contiguous if it isn't already; ``shape`` and ``dtype``
    in the header always describe what the payload actually contains.
    """
    array = np.ascontiguousarray(array)
    dtype = array.dtype.name
    if dtype not in _ALLOWED_DTYPES:
        raise ValueError(f"dtype {dtype!r} is not one the client can read: {_ALLOWED_DTYPES}")

    payload = array.tobytes()
    flags = 0
    if compress:
        import zstandard

        payload = zstandard.ZstdCompressor(level=3).compress(payload)
        flags |= FLAG_ZSTD

    header = {"kind": kind, "dtype": dtype, "shape": list(array.shape), **header_fields}
    header_bytes = json.dumps(header, separators=(",", ":"), allow_nan=False).encode()
    padding = -(HEADER_OFFSET + len(header_bytes)) % PAYLOAD_ALIGNMENT
    header_bytes += b" " * padding

    return _PREFIX.pack(MAGIC, VERSION, flags, len(header_bytes)) + header_bytes + payload


def decode(frame: bytes) -> Frame:
    """Unpack a frame. Mirrors the TypeScript decoder in frontend/src/net/frames.ts."""
    if len(frame) < HEADER_OFFSET:
        raise ValueError(f"frame is {len(frame)} bytes, too short to hold a header")

    magic, version, flags, header_len = _PREFIX.unpack_from(frame, 0)
    if magic != MAGIC:
        raise ValueError(f"expected magic {MAGIC!r}, got {magic!r}")
    if version != VERSION:
        raise ValueError(f"frame version {version} is not supported (this build speaks {VERSION})")

    header_end = HEADER_OFFSET + header_len
    if len(frame) < header_end:
        raise ValueError(f"header claims {header_len} bytes but the frame ends early")

    header = json.loads(frame[HEADER_OFFSET:header_end].decode())
    payload = frame[header_end:]

    if flags & FLAG_ZSTD:
        import zstandard

        payload = zstandard.ZstdDecompressor().decompress(payload)

    array = np.frombuffer(payload, dtype=np.dtype(header["dtype"])).reshape(header["shape"])
    return Frame(header=header, array=array)
