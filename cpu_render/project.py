"""Project every splat to a screen-space Gaussian in one vectorised pass (EWA splatting).

For each splat the full 3D covariance ``R diag(s^2) R^T`` (all three scales, world frame)
is turned into the view frame and pushed through the Jacobian of the perspective
projection, as in Zwicker et al. 2001 and the 3DGS rasteriser. Image coordinates are
pixels with x to the right and y down; pixel (col, row) has its centre at (col + 0.5, row + 0.5).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .camera import OrbitCamera
from .frame import quat_to_matrix

LOWPASS_PX2 = 0.3  # screen-space dilation (px^2), the same +0.3 as the viewer and 3DGS
NEAR = 0.05  # splats closer than this to the camera are dropped (viewer: depth < 0.05)
MIN_OPACITY = 0.003  # the viewer's cull and discard threshold
SIGMA_CUTOFF = 3.0  # footprint radius in standard deviations (viewer: maha > 9 discarded)
FOV_GUARD = 1.3  # clamp x/z, y/z to 1.3 x the half field of view in the Jacobian, as 3DGS does


@dataclass
class Projected:
    """Screen-space Gaussians of the splats that can touch the image, in input order."""

    index: np.ndarray  # (M,) indices into the scene's splats
    mean: np.ndarray  # (M, 2) centre in pixels (x right, y down)
    conic: np.ndarray  # (M, 3) inverse 2D covariance as (a, b, c): maha = a dx^2 + 2b dx dy + c dy^2
    radius: np.ndarray  # (M,) footprint half-size in pixels (SIGMA_CUTOFF standard deviations)
    depth: np.ndarray  # (M,) distance along the view axis


def world_covariances(quats: np.ndarray, log_scales: np.ndarray) -> np.ndarray:
    """(N, 3, 3) world-space covariances R diag(exp(2 log_s)) R^T."""
    m = quat_to_matrix(quats) * np.exp(log_scales)[:, None, :]  # scale each column (axis)
    return m @ np.transpose(m, (0, 2, 1))


def _jacobian(view: np.ndarray, depth: np.ndarray, focal: float, lim: np.ndarray) -> np.ndarray:
    """(N, 2, 3) Jacobian of (x, y, z)_view -> pixel (x right, y down), with the 3DGS clamp."""
    tx = np.clip(view[:, 0] / depth, -lim[0], lim[0]) * depth
    ty = np.clip(view[:, 1] / depth, -lim[1], lim[1]) * depth
    j = np.zeros((len(depth), 2, 3))
    j[:, 0, 0] = focal / depth
    j[:, 0, 2] = focal * tx / depth**2
    j[:, 1, 1] = -focal / depth
    j[:, 1, 2] = -focal * ty / depth**2
    return j


def screen_covariances(view_pos, view_cov, focal: float, width: int, height: int, affine: bool = False):
    """(N, 2, 2) pixel-space covariances, low-pass included.

    ``affine=True`` drops the depth column of the Jacobian (a scaled orthographic
    projection per splat), the approximation the viewer's vertex shader used until
    2026-11-13. It exists only so tests can show it is wrong off-axis; renders never use it.
    """
    depth = -view_pos[:, 2]
    lim = FOV_GUARD * np.array([0.5 * width, 0.5 * height]) / focal
    j = _jacobian(view_pos, depth, focal, lim)
    if affine:
        j[:, :, 2] = 0.0
    cov = j @ view_cov @ np.transpose(j, (0, 2, 1))
    cov[:, 0, 0] += LOWPASS_PX2
    cov[:, 1, 1] += LOWPASS_PX2
    return cov


def project(scene, camera: OrbitCamera, width: int, height: int, subset=None) -> Projected:
    """Project the splats of ``scene`` (see cpu_render.scene) for one camera and image size."""
    idx = np.arange(len(scene["opacity"])) if subset is None else np.asarray(subset)
    rot = camera.rotation
    view = (scene["positions"][idx] - camera.position) @ rot.T
    depth = -view[:, 2]
    keep = (scene["opacity"][idx] >= MIN_OPACITY) & (depth >= NEAR)
    idx, view, depth = idx[keep], view[keep], depth[keep]

    focal = camera.focal(width, height)
    world_cov = world_covariances(scene["quats"][idx], scene["log_scales"][idx])
    view_cov = rot @ world_cov @ rot.T
    cov = screen_covariances(view, view_cov, focal, width, height)
    a, b, c = cov[:, 0, 0], cov[:, 0, 1], cov[:, 1, 1]
    det = a * c - b * b
    ok = det >= 1e-6
    half_trace = 0.5 * (a + c)
    lam_max = half_trace + np.sqrt(np.maximum(0.0, half_trace * half_trace - det))
    radius = SIGMA_CUTOFF * np.sqrt(lam_max)
    mean = np.stack([0.5 * width + focal * view[:, 0] / depth, 0.5 * height - focal * view[:, 1] / depth], axis=1)
    on_screen = (
        (mean[:, 0] + radius > 0)
        & (mean[:, 0] - radius < width)
        & (mean[:, 1] + radius > 0)
        & (mean[:, 1] - radius < height)
    )
    ok &= on_screen
    det_ok = np.where(ok, det, 1.0)
    conic = np.stack([c, -b, a], axis=1)[ok] / det_ok[ok, None]
    return Projected(idx[ok], mean[ok], conic, radius[ok], depth[ok])
