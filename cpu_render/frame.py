"""Export frame to viewer frame, and the per-splat geometry derived from it. Vectorised.

This mirrors src/frame.js line for line, because the CPU renderer is the reference the
viewer is checked against:

* 3DGS exports are Y-down. Positions turn 180 degrees about X on load: (x, y, z) -> (x, -y, -z).
* Rotations are stored ``rot_0..rot_3 = w, x, y, z`` (graphdeco ``build_rotation`` reads
  ``q[:, 0]`` as the real part). The same 180 degree X turn is composed on the left:
  (w, x, y, z) -> (-x, w, -z, y).
* A splat's normal is its shortest principal axis, oriented away from the scene centroid.
"""

from __future__ import annotations

import numpy as np

SH_C0 = 0.28209479177387814
OPAQUE = 0.05  # opacity above which a splat counts for the centroid (src/bounds.js OPAQUE)


def world_positions(xyz: np.ndarray) -> np.ndarray:
    """(N, 3) export positions -> viewer world positions."""
    return xyz * np.array([1.0, -1.0, -1.0])


def world_quaternions(rot: np.ndarray) -> np.ndarray:
    """(N, 4) raw ``rot_0..rot_3`` (w, x, y, z, any length) -> unit world quaternions (w, x, y, z)."""
    length = np.linalg.norm(rot, axis=1, keepdims=True)
    length[length == 0] = 1.0
    w, x, y, z = (rot / length).T
    return np.stack([-x, w, -z, y], axis=1)


def quat_to_matrix(q: np.ndarray) -> np.ndarray:
    """(N, 4) unit quaternions (w, x, y, z) -> (N, 3, 3) rotation matrices.

    Column k is the Gaussian's k-th principal axis in world space.
    """
    w, x, y, z = np.asarray(q, dtype=np.float64).T
    return np.stack(
        [
            np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)], axis=-1),
            np.stack([2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)], axis=-1),
            np.stack([2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], axis=-1),
        ],
        axis=-2,
    )


def thin_axis(log_scales: np.ndarray) -> np.ndarray:
    """Index of the shortest axis per splat, with the viewer's tie-breaking (thinAxis)."""
    s0, s1, s2 = log_scales.T
    return np.where((s1 <= s0) & (s1 <= s2), 1, np.where((s2 <= s0) & (s2 <= s1), 2, 0))


def splat_normals(quats: np.ndarray, log_scales: np.ndarray) -> np.ndarray:
    """Unit normal per splat: the rotation column of its shortest axis. Sign is arbitrary."""
    rot = quat_to_matrix(quats)
    n = rot[np.arange(len(rot)), :, thin_axis(log_scales)]
    length = np.linalg.norm(n, axis=1, keepdims=True)
    length[length == 0] = 1.0
    return n / length


def orient_outward(normals: np.ndarray, positions: np.ndarray, opacity: np.ndarray) -> np.ndarray:
    """Flip normals that point towards the centroid of the opaque splats (orientOutward)."""
    opaque = opacity > OPAQUE
    if not np.any(opaque):
        return normals
    centre = positions[opaque].mean(axis=0)
    inward = np.sum(normals * (positions - centre), axis=1) < 0
    return np.where(inward[:, None], -normals, normals)


def baked_from_sh(dc: np.ndarray) -> np.ndarray:
    """SH degree-0 coefficients -> baked linear appearance in [0, 1] (lighting still inside)."""
    return np.clip(0.5 + dc * SH_C0, 0.0, 1.0)


def sigmoid_opacity(raw: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(raw, -20.0, 20.0)))
