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


def radial_quaternions(directions: np.ndarray) -> np.ndarray:
    """Quaternions (w, x, y, z), the 3DGS ``rot_0..rot_3`` order, turning local +z onto each direction.

    The shortest-arc rotation from (0, 0, 1) to d is (1 + d.z, -d.y, d.x, 0), normalised.
    Directions close to -z get a 180 degree turn about x instead.
    """
    d = directions / np.linalg.norm(directions, axis=1, keepdims=True)
    q = np.stack([1.0 + d[:, 2], -d[:, 1], d[:, 0], np.zeros(len(d))], axis=1)
    q[d[:, 2] < -0.9999] = [0.0, 1.0, 0.0, 0.0]
    return q / np.linalg.norm(q, axis=1, keepdims=True)


def write_synthetic_ply(path: Path, n: int = 1500, seed: int = 0) -> None:
    """Write a binary little-endian 3DGS-style PLY: flat splats on a unit sphere.

    Each splat is a disc (two long axes, ``scale_2`` short) whose short axis points away
    from the centre, so its normal is the radial direction. Rotations are stored in the
    3DGS order ``rot_0 = w``; reading them as (x, y, z, w) gives the wrong normals.
    """
    rng = np.random.default_rng(seed)
    pts = rng.normal(size=(n, 3))
    pts /= np.linalg.norm(pts, axis=1, keepdims=True)
    data = np.zeros((n, len(PROPS)), dtype="<f4")
    data[:, 0:3] = pts
    data[:, 3:6] = rng.uniform(-1.0, 1.0, size=(n, 3))  # SH DC colour
    data[:, 6] = 4.0  # logit opacity -> ~0.98
    data[:, 7:10] = [np.log(0.06), np.log(0.06), np.log(0.004)]  # flat disc, normal = axis 2
    data[:, 10:14] = radial_quaternions(pts)
    header = "ply\nformat binary_little_endian 1.0\n"
    header += f"element vertex {n}\n"
    header += "".join(f"property float {p}\n" for p in PROPS)
    header += "end_header\n"
    path.write_bytes(header.encode() + data.tobytes())
