"""One CPU render: pick splats, colour them for the mode, project, rasterise."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from .camera import OrbitCamera
from .lighting import LightRig, Material, shade_relit
from .project import project
from .raster import rasterize

MODES = ("relit", "neutral", "albedo", "normals")


def _normals_color(scene, idx: np.ndarray, cam_pos: np.ndarray) -> np.ndarray:
    """The viewer's normals G-buffer (mode 4) at N Smooth 0: N turned to face the camera, * 0.5 + 0.5."""
    n = scene["normals"][idx]
    towards = cam_pos - scene["positions"][idx]
    n = np.where(np.sum(n * towards, axis=1, keepdims=True) < 0, -n, n)
    return n * 0.5 + 0.5


def splat_colors(scene, idx, mode, camera, rig, material, separation) -> np.ndarray:
    """(len(idx), 3) colour of each splat in ``mode``."""
    if mode == "neutral":
        return scene["baked"][idx]
    if mode == "albedo":
        return scene["albedo"][idx]
    if mode == "normals":
        return _normals_color(scene, idx, camera.position)
    if mode != "relit":
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
    sep = float(np.clip(separation, 0.0, 1.0))
    albedo = scene["baked"][idx] * (1.0 - sep) + scene["albedo"][idx] * sep
    pos, nrm, irr = scene["positions"][idx], scene["normals"][idx], scene["irradiance"][idx]
    return shade_relit(pos, nrm, albedo, irr, camera.position, rig, material)


def render_rgba(
    scene: dict,
    width: int,
    height: int,
    mode: str = "relit",
    camera: OrbitCamera | None = None,
    rig: LightRig | None = None,
    material: Material | None = None,
    separation: float = 1.0,
    stride: int = 1,
    check: Callable[[], None] | None = None,
) -> np.ndarray:
    """(height, width, 4) float RGBA in [0, 1], straight alpha; transparent where nothing is drawn."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
    camera = camera or OrbitCamera()
    subset = np.arange(0, len(scene["opacity"]), max(1, int(stride)))
    proj = project(scene, camera, width, height, subset=subset)
    colors = splat_colors(scene, proj.index, mode, camera, rig or LightRig(), material or Material(), separation)
    image = rasterize(proj, colors, scene["opacity"][proj.index], width, height, check=check)
    return np.clip(image, 0.0, 1.0)


def over_background(rgba: np.ndarray, background) -> np.ndarray:
    """Composite a straight-alpha image over a solid colour, as the viewer's cleared canvas does."""
    alpha = rgba[..., 3:4]
    return rgba[..., :3] * alpha + np.asarray(background, dtype=np.float32) * (1.0 - alpha)
