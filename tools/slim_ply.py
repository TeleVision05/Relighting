"""Slim a 3D Gaussian Splatting ``.ply`` so it is small enough to host as a plain Git file.

    python tools/slim_ply.py Buttons.ply demo/buttons-demo.ply --target-mb 11

Method (each step is reported with its splat count and size):

1. Drop what the viewer never reads: the stored normals (``nx``..``nz``, zero in 3DGS exports)
   and every higher-order spherical-harmonic property (``f_rest_*``). The viewer shades from the
   DC term only, so this changes no pixel.
2. Rank the splats by contribution, ``opacity * (largest scale * second largest scale)``: how
   much screen area a splat covers times how opaque it is, with the scales taken out of log
   space. A splat that is both small and faint adds almost nothing to any view.
3. Keep the highest-ranked splats that fit ``--target-mb`` (the 8 to 15 MB budget for a hosted
   demo), in their original order so the file stays reproducible and spatially coherent.

Output properties: x y z f_dc_0..2 opacity scale_0..2 rot_0..3, all float32 (56 bytes a splat).
The input is read through numpy and must be a binary little-endian PLY with those properties.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

KEEP = [
    "x",
    "y",
    "z",
    "f_dc_0",
    "f_dc_1",
    "f_dc_2",
    "opacity",
    "scale_0",
    "scale_1",
    "scale_2",
    "rot_0",
    "rot_1",
    "rot_2",
    "rot_3",
]
LFS_MARK = b"version https://git-lfs"
TYPES = {"float": "<f4", "float32": "<f4", "double": "<f8", "uchar": "u1", "int": "<i4", "uint": "<u4"}


class SlimError(Exception):
    """A problem with the input that the person running the tool can fix."""


def read_ply(path: Path) -> tuple[np.ndarray, list[str]]:
    """Return (structured array of every vertex, property names)."""
    raw = path.read_bytes()
    if raw.startswith(LFS_MARK):
        raise SlimError(f"{path} is a Git LFS pointer, not the scene. Run `git lfs pull` first.")
    end = raw.find(b"end_header\n")
    if end < 0:
        raise SlimError(f"{path} is not a PLY file (no end_header).")
    header = raw[:end].decode("ascii", "replace").split("\n")
    if "format binary_little_endian 1.0" not in header:
        raise SlimError("Only binary little-endian PLY files are supported.")
    count, fields = 0, []
    for line in header:
        parts = line.split()
        if line.startswith("element vertex"):
            count = int(parts[2])
        elif line.startswith("property ") and len(parts) == 3:
            if parts[1] not in TYPES:
                raise SlimError(f"Unsupported property type {parts[1]!r}.")
            fields.append((parts[2], TYPES[parts[1]]))
    data = np.frombuffer(raw, dtype=np.dtype(fields), count=count, offset=end + len(b"end_header\n"))
    return data, [f[0] for f in fields]


def contribution(data: np.ndarray) -> np.ndarray:
    """Opacity times the area of the splat's two largest axes (scales are stored as logs)."""
    opacity = 1.0 / (1.0 + np.exp(-data["opacity"].astype(np.float64)))
    scales = np.sort(np.stack([data[f"scale_{i}"] for i in range(3)]).astype(np.float64), axis=0)
    return opacity * np.exp(scales[2] + scales[1])


def slim(data: np.ndarray, target_bytes: int) -> np.ndarray:
    """The most significant splats that fit ``target_bytes``, in their original order."""
    record = 4 * len(KEEP)
    keep_n = min(len(data), max(1, (target_bytes - 1024) // record))
    if keep_n == len(data):
        return data
    order = np.argsort(contribution(data), kind="stable")[::-1][:keep_n]
    return data[np.sort(order)]


def write_ply(path: Path, data: np.ndarray) -> int:
    out = np.empty(len(data), dtype=np.dtype([(k, "<f4") for k in KEEP]))
    for k in KEEP:
        out[k] = data[k]
    header = f"ply\nformat binary_little_endian 1.0\nelement vertex {len(out)}\n"
    header += "".join(f"property float {k}\n" for k in KEEP) + "end_header\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(header.encode("ascii"))
        f.write(out.tobytes())
    return path.stat().st_size


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source", type=Path)
    ap.add_argument("dest", type=Path)
    ap.add_argument("--target-mb", type=float, default=11.0, help="size budget, 8 to 15 for a hosted demo")
    args = ap.parse_args(argv)
    try:
        data, names = read_ply(args.source)
        missing = [k for k in KEEP if k not in names]
        if missing:
            raise SlimError(f"{args.source} has no {', '.join(missing)}; is it a 3DGS splat file?")
        in_size = args.source.stat().st_size
        print(f"input : {len(data):>8,} splats, {len(names)} properties, {in_size / 1e6:6.1f} MB")
        no_sh = len(data) * 4 * len(KEEP) + 1024
        print(
            f"step 1: {len(data):>8,} splats, {len(KEEP)} properties, about {no_sh / 1e6:6.1f} MB (SH and normals dropped)"
        )
        kept = slim(data, int(args.target_mb * 1e6))
        size = write_ply(args.dest, kept)
        pct = 100 * len(kept) / len(data)
        print(
            f"output: {len(kept):>8,} splats ({pct:.1f}%), {len(KEEP)} properties, {size / 1e6:6.1f} MB -> {args.dest}"
        )
    except SlimError as e:
        print(f"slim_ply: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
