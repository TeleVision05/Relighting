"""A tiny synthetic 3DGS PLY, so tests never need the large LFS scenes."""

from pathlib import Path

import numpy as np

PROPS = [
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


def write_synthetic_ply(path: Path, n: int = 1500, seed: int = 0) -> None:
    """Write a binary little-endian 3DGS-style PLY: splats on a unit sphere."""
    rng = np.random.default_rng(seed)
    pts = rng.normal(size=(n, 3)).astype(np.float32)
    pts /= np.linalg.norm(pts, axis=1, keepdims=True)
    data = np.zeros((n, len(PROPS)), dtype="<f4")
    data[:, 0:3] = pts
    data[:, 3:6] = rng.uniform(-1.0, 1.0, size=(n, 3))  # SH DC colour
    data[:, 6] = 4.0  # logit opacity -> ~0.98
    data[:, 7:10] = [1.6, 1.6, -3.0]  # flat disc, normal = axis 2
    data[:, 13] = 1.0  # identity quaternion (x,y,z,w)
    header = "ply\nformat binary_little_endian 1.0\n"
    header += f"element vertex {n}\n"
    header += "".join(f"property float {p}\n" for p in PROPS)
    header += "end_header\n"
    path.write_bytes(header.encode() + data.tobytes())
