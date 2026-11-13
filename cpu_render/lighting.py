"""Lighting: the Retinex albedo/irradiance split, and Cook-Torrance relighting per splat.

The BRDF is the one in the viewer's relit fragment shader (``cookTorrance`` in
src/shaders/splat-frag.js). Shading depends only on per-splat values there too (world
position, normal and albedo are flat across a splat), so shading once per splat here gives
the same colour the viewer gives every fragment of that splat.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _blur_log(src: np.ndarray, grid_res: int) -> np.ndarray:
    vol = src.reshape(grid_res, grid_res, grid_res)
    pad = np.pad(vol, 2, mode="edge")
    out = np.zeros_like(vol)
    for dz in range(5):
        for dy in range(5):
            for dx in range(5):
                out += pad[dz : dz + grid_res, dy : dy + grid_res, dx : dx + grid_res]
    return (out / 125.0).ravel()


def separate_lighting(
    positions: np.ndarray,
    appearance: np.ndarray,
    opacity: np.ndarray,
    grid_res: int = 40,
) -> tuple[np.ndarray, np.ndarray]:
    """Retinex-style baked-irradiance / intrinsic-albedo split for a single PLY.

    Standard 3DGS SH DC stores outgoing radiance (albedo x lighting), not albedo.
    Multiplying new lights onto SH DC only changes intensity of baked lighting.
    Without multi-view images we cannot run full inverse rendering; instead we
    estimate spatially smooth irradiance E and recover albedo ~ appearance / E.
    """
    lum = np.maximum(
        0.2126 * appearance[:, 0] + 0.7152 * appearance[:, 1] + 0.0722 * appearance[:, 2],
        1e-4,
    )
    valid = opacity > 0.05
    if not np.any(valid):
        return appearance.copy(), np.ones(len(appearance), dtype=np.float32)

    global_log = float(np.mean(np.log(lum[valid])))
    mins = positions[valid].min(axis=0)
    maxs = positions[valid].max(axis=0)
    extent = np.maximum(maxs - mins, 1e-6)

    gi = np.clip(((positions - mins) / extent * (grid_res - 1)).astype(np.int32), 0, grid_res - 1)
    flat = gi[:, 0] + grid_res * (gi[:, 1] + grid_res * gi[:, 2])
    cells = grid_res**3
    sum_log = np.zeros(cells, dtype=np.float64)
    count = np.zeros(cells, dtype=np.float64)
    np.add.at(sum_log, flat[valid], np.log(lum[valid]))
    np.add.at(count, flat[valid], 1.0)

    grid = np.full(cells, global_log, dtype=np.float64)
    nz = count > 0
    grid[nz] = sum_log[nz] / count[nz]

    grid = _blur_log(_blur_log(grid, grid_res), grid_res)
    irradiance = np.exp(grid[flat]).astype(np.float64)
    median = float(np.median(irradiance[valid])) or 1.0
    irradiance = np.maximum(irradiance / median, 0.05)
    albedo = np.clip(appearance / irradiance[:, None], 0.0, 1.0).astype(np.float32)
    return albedo, irradiance.astype(np.float32)


@dataclass(frozen=True)
class Material:
    roughness: float = 0.30
    metallic: float = 0.10
    specular_gain: float = 1.2


@dataclass(frozen=True)
class LightRig:
    """The CPU renderer's lights: ambient, one directional and one point light (viewer frame)."""

    ambient: float = 0.20
    ambient_color: tuple = (0.8, 0.84, 0.88)
    dir_intensity: float = 1.5
    dir_towards: tuple = (0.5, 0.7, 0.5)  # direction from the surface towards the light
    dir_color: tuple = (1.0, 1.0, 1.0)
    point_intensity: float = 1.0
    point_pos: tuple = (1.2, 1.5, 0.8)
    point_color: tuple = (0.22, 0.74, 0.97)
    keep_ao: float = 0.0


def _dot(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.sum(a * b, axis=-1, keepdims=True)


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def cook_torrance(n, v, light, albedo, mat: Material) -> np.ndarray:
    """(N, 3) reflected radiance factor, as ``cookTorrance`` in the relit shader."""
    ndl = np.maximum(0.0, _dot(n, light))
    ndv = np.maximum(0.001, _dot(n, v))
    h = _unit(light + v)
    ndh = np.maximum(0.0, _dot(n, h))
    vdh = np.maximum(0.0, _dot(v, h))
    a = max(0.01, mat.roughness * mat.roughness)
    a2 = a * a
    d = ndh * ndh * (a2 - 1.0) + 1.0
    dist = a2 / (np.pi * d * d)
    f0 = (1.0 - mat.metallic) * 0.04 * mat.specular_gain + mat.metallic * albedo
    fres = f0 + (1.0 - f0) * (1.0 - vdh) ** 5
    k = (mat.roughness + 1.0) ** 2 / 8.0
    geo = (ndv / (ndv * (1.0 - k) + k)) * (ndl / (ndl * (1.0 - k) + k))
    spec = dist * geo * fres / (4.0 * ndv * ndl + 0.001)
    kd = (1.0 - fres) * (1.0 - mat.metallic)
    return np.where(ndl > 0.0, (kd * albedo / np.pi + spec) * ndl, 0.0)


def shade_relit(positions, normals, albedo, irradiance, cam_pos, rig: LightRig, mat: Material) -> np.ndarray:
    """Relit colour per splat in [0, 1]. Normals are turned to face the camera first."""
    v = _unit(cam_pos - positions)
    n = np.where(_dot(normals, v) < 0.0, -normals, normals)
    color = albedo * np.asarray(rig.ambient_color) * rig.ambient
    if rig.dir_intensity > 0:
        light = np.broadcast_to(_unit(np.asarray(rig.dir_towards, dtype=np.float64)), positions.shape)
        color = color + cook_torrance(n, v, light, albedo, mat) * np.asarray(rig.dir_color) * rig.dir_intensity * np.pi
    if rig.point_intensity > 0:
        to_light = np.asarray(rig.point_pos) - positions
        dist2 = np.sum(to_light * to_light, axis=1, keepdims=True)
        atten = 1.0 / (0.25 + dist2 * 0.12)
        brdf = cook_torrance(n, v, _unit(to_light), albedo, mat)
        color = color + brdf * np.asarray(rig.point_color) * rig.point_intensity * np.pi * atten
    if rig.keep_ao > 0:
        color = color * ((1.0 - rig.keep_ao) + rig.keep_ao * irradiance[:, None])
    return np.clip(color, 0.0, 1.0)
