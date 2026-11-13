"""Read the vertex table of a binary 3DGS ``.ply`` into named NumPy arrays.

The header decides the layout: property types and order are read from it, so a file with
byte colours, doubles or extra properties is read correctly instead of being reshaped as a
block of float32. Only the ``vertex`` element is kept; the viewer's parser (src/ply.js)
accepts the same files.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

_TYPES = {
    "char": "i1",
    "int8": "i1",
    "uchar": "u1",
    "uint8": "u1",
    "short": "i2",
    "int16": "i2",
    "ushort": "u2",
    "uint16": "u2",
    "int": "i4",
    "int32": "i4",
    "uint": "u4",
    "uint32": "u4",
    "float": "f4",
    "float32": "f4",
    "double": "f8",
    "float64": "f8",
}
_MARKER = b"end_header"


class PlyFormatError(RuntimeError):
    """The file is not a binary 3DGS PLY this renderer can read."""


def _header(data: bytes) -> tuple[str, int]:
    """Header text and the offset of the first vertex byte."""
    if data.startswith(b"version https://git-lfs"):
        raise PlyFormatError("this is a Git LFS pointer, not the scene; run git lfs pull")
    idx = data.find(_MARKER, 0, 1 << 16)
    if idx < 0:
        raise PlyFormatError("no end_header in the first 64 KiB")
    start = idx + len(_MARKER)
    while start < len(data) and data[start : start + 1] in (b"\r", b"\n"):
        start += 1
    return data[:idx].decode("latin1", "ignore"), start


def _vertex_dtype(header: str) -> tuple[np.dtype, int]:
    """Structured dtype of one vertex record, and the vertex count."""
    endian, count, fields, in_vertex = "<", None, [], False
    for raw in header.splitlines():
        words = raw.split()
        if not words:
            continue
        if words[0] == "format":
            if words[1] == "ascii":
                raise PlyFormatError("ASCII PLY is not supported; export as binary")
            endian = ">" if words[1] == "binary_big_endian" else "<"
        elif words[0] == "element":
            in_vertex = words[1] == "vertex"
            if in_vertex:
                count = int(words[2])
        elif words[0] == "property" and in_vertex:
            if words[1] == "list":
                raise PlyFormatError("list properties in the vertex element are not supported")
            if words[1] not in _TYPES:
                raise PlyFormatError(f"unknown property type {words[1]!r}")
            fields.append((words[2], endian + _TYPES[words[1]]))
    if not count or not fields:
        raise PlyFormatError("no vertex element in the header")
    return np.dtype(fields), count


def read_vertices(path: Path) -> np.ndarray:
    """The vertex records as a structured array (field names from the header)."""
    data = Path(path).read_bytes()
    header, start = _header(data)
    dtype, count = _vertex_dtype(header)
    available = (len(data) - start) // dtype.itemsize
    if available < count:
        raise PlyFormatError(f"PLY payload is too short: expected {count} vertices, found {available}")
    return np.frombuffer(data, dtype=dtype, count=count, offset=start)


def column(table: np.ndarray, *names: str) -> np.ndarray | None:
    """The first named property present, as float64, or None."""
    for name in names:
        if name in table.dtype.names:
            return table[name].astype(np.float64)
    return None


def is_byte(table: np.ndarray, *names: str) -> bool:
    """True when the first named property present is stored as a byte (0..255)."""
    for name in names:
        if name in table.dtype.names:
            return table.dtype[name].itemsize == 1
    return False
