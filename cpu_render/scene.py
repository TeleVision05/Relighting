"""Load a 3DGS ``.ply`` into the per-splat arrays the renderer uses, in the viewer's frame."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .frame import (
    baked_from_sh,
    orient_outward,
    sigmoid_opacity,
    splat_normals,
    world_positions,
    world_quaternions,
)
from .lighting import separate_lighting
from .plyio import PlyFormatError, column, is_byte, read_vertices

_COLOR_NAMES = (("f_dc_0", "red", "r"), ("f_dc_1", "green", "g"), ("f_dc_2", "blue", "b"))
_OPACITY_NAMES = ("opacity", "alpha")


def _required(table: np.ndarray, *names: str) -> np.ndarray:
    values = column(table, *names)
    if values is None:
        raise PlyFormatError(f"the PLY has no {names[0]!r} property")
    return values


def _appearance(table: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Baked colour (N, 3) and opacity (N,), from float SH or byte-encoded properties."""
    dc = np.stack([_required(table, *names) for names in _COLOR_NAMES], axis=1)
    baked = dc / 255.0 if is_byte(table, *_COLOR_NAMES[0]) else baked_from_sh(dc)
    raw = _required(table, *_OPACITY_NAMES)
    opacity = raw / 255.0 if is_byte(table, *_OPACITY_NAMES) else sigmoid_opacity(raw)
    return baked, opacity


def load_ply(path: Path) -> dict[str, np.ndarray]:
    """Per-splat arrays, all in the viewer's world frame (y up):

    positions (N, 3), quats (N, 4) unit (w, x, y, z), log_scales (N, 3), opacity (N,),
    baked (N, 3) SH-DC appearance, normals (N, 3) unit and oriented outward,
    albedo (N, 3) and irradiance (N,) from the Retinex split.
    Raises PlyFormatError (a RuntimeError) for a file it cannot read.
    """
    table = read_vertices(path)
    xyz = np.stack([_required(table, n) for n in ("x", "y", "z")], axis=1)
    rot = np.stack([_required(table, f"rot_{k}") for k in range(4)], axis=1)
    log_scales = np.stack([_required(table, f"scale_{k}") for k in range(3)], axis=1)
    baked, opacity = _appearance(table)

    positions = world_positions(xyz)
    quats = world_quaternions(rot)
    normals = orient_outward(splat_normals(quats, log_scales), positions, opacity)
    albedo, irradiance = separate_lighting(positions, baked.astype(np.float32), opacity)
    return {
        "positions": positions,
        "quats": quats,
        "log_scales": log_scales,
        "opacity": opacity,
        "baked": baked,
        "normals": normals,
        "albedo": albedo.astype(np.float64),
        "irradiance": irradiance.astype(np.float64),
    }
