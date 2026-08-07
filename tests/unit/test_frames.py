from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mupstudio.server.ws.frames import (
    FLAG_ZSTD,
    HEADER_OFFSET,
    MAGIC,
    PAYLOAD_ALIGNMENT,
    decode,
    encode,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "frames"


def test_round_trips_a_float_array() -> None:
    values = np.arange(12, dtype=np.float32).reshape(3, 4)

    frame = decode(encode("scalar", values, component="Ca", timeIdx=2))

    assert frame.kind == "scalar"
    assert frame.header["component"] == "Ca"
    assert frame.header["timeIdx"] == 2
    np.testing.assert_array_equal(frame.array, values)


def test_round_trips_integers() -> None:
    values = np.array([0, 4, 9, 15], dtype=np.int32)

    frame = decode(encode("mesh_cell_offsets", values))

    assert frame.array.dtype == np.int32
    np.testing.assert_array_equal(frame.array, values)


def test_round_trips_an_empty_array() -> None:
    frame = decode(encode("scalar", np.zeros(0, dtype=np.float32)))

    assert frame.array.shape == (0,)


def test_compression_round_trips_and_sets_the_flag() -> None:
    values = np.zeros(10_000, dtype=np.float32)  # compresses well

    raw = encode("scalar_block", values)
    packed = encode("scalar_block", values, compress=True)

    assert len(packed) < len(raw)
    assert int.from_bytes(packed[6:8], "little") & FLAG_ZSTD
    np.testing.assert_array_equal(decode(packed).array, values)


def test_non_contiguous_input_is_encoded_as_described() -> None:
    values = np.arange(12, dtype=np.float32).reshape(3, 4)[:, ::2]
    assert not values.flags["C_CONTIGUOUS"]

    frame = decode(encode("scalar", values))

    assert frame.header["shape"] == [3, 2]
    np.testing.assert_array_equal(frame.array, values)


def test_rejects_a_dtype_the_client_cannot_read() -> None:
    with pytest.raises(ValueError, match="not one the client can read"):
        encode("scalar", np.zeros(3, dtype=np.float64))


def test_rejects_a_bad_magic() -> None:
    frame = bytearray(encode("scalar", np.zeros(2, dtype=np.float32)))
    frame[0:4] = b"XXXX"

    with pytest.raises(ValueError, match="magic"):
        decode(bytes(frame))


def test_rejects_a_future_version() -> None:
    frame = bytearray(encode("scalar", np.zeros(2, dtype=np.float32)))
    frame[4:6] = (99).to_bytes(2, "little")

    with pytest.raises(ValueError, match="version 99"):
        decode(bytes(frame))


def test_rejects_a_truncated_frame() -> None:
    frame = encode("scalar", np.zeros(2, dtype=np.float32))

    with pytest.raises(ValueError, match="too short"):
        decode(frame[:8])


@pytest.mark.parametrize("component", ["a", "Ca", "Calcite", "a" * 37, "a" * 200])
def test_payload_is_always_aligned_whatever_the_header_length(component: str) -> None:
    """JavaScript cannot view an unaligned payload, so the header is padded.

    Header length varies with its content, so this is checked across several
    lengths rather than one.
    """
    frame = encode("scalar", np.zeros(4, dtype=np.float32), component=component)

    header_len = int.from_bytes(frame[8:12], "little")
    assert (HEADER_OFFSET + header_len) % PAYLOAD_ALIGNMENT == 0
    assert decode(frame).header["component"] == component


def test_prefix_layout_is_what_the_client_expects() -> None:
    frame = encode("scalar", np.zeros(1, dtype=np.float32))

    assert frame[:4] == MAGIC
    assert int.from_bytes(frame[4:6], "little") == 1
    header_len = int.from_bytes(frame[8:12], "little")
    assert json.loads(frame[HEADER_OFFSET : HEADER_OFFSET + header_len])["kind"] == "scalar"


@pytest.mark.parametrize("case", json.loads((FIXTURES / "manifest.json").read_text()))
def test_fixtures_decode_as_the_manifest_says(case: dict) -> None:
    """The same fixtures vitest reads. If these drift, the two decoders disagree."""
    frame = decode((FIXTURES / case["file"]).read_bytes())

    assert frame.kind == case["kind"]
    assert frame.header["dtype"] == case["dtype"]
    assert frame.header["shape"] == case["shape"]
    np.testing.assert_allclose(frame.array.ravel(), case["values"], rtol=1e-6)
