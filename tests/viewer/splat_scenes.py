"""Synthetic 3DGS scenes with known geometry, for the viewer's browser tests.

Each scene is described in the viewer's world frame (y up), because that is the frame the
tests reason about. It is written to disk the way a real 3DGS export is:

* the same vertex layout as ``Buttons.ply`` (x y z, nx ny nz, f_dc_0..2, 24 f_rest, opacity,
  scale_0..2, rot_0..3), binary little endian;
* positions in the exporter's frame, which the viewer turns 180 degrees about X on load,
  ``(x, y, z) -> (x, -y, -z)``;
* quaternions built in the exporter's frame with the 3DGS convention ``rot_0..3 = w, x, y, z``,
  deliberately left unnormalised, with a random sign, a random twist about the normal and a
  random choice of which axis is the thin one. A wrong component order, a missing frame flip
  or a wrong axis pick in the viewer therefore cannot pass by luck.

Run it directly to write the scenes somewhere for a manual look:
``python tests/viewer/splat_scenes.py OUT_DIR`` then open ``index.html?ply=...``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SH_C0 = 0.28209479177387814
N_REST = 24  # SH degree 1, as in Buttons.ply
FLIP = np.array([1.0, -1.0, -1.0])  # viewer world <-> exporter frame (its own inverse)

PROPS = (
    ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"]
    + [f"f_rest_{i}" for i in range(N_REST)]
    + ["opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
)


@dataclass
class Scene:
    """Splats in the viewer's world frame, plus the facts the tests check against."""

    name: str
    pos: np.ndarray  # (N, 3)
    normal: np.ndarray  # (N, 3), unit
    color: np.ndarray  # (N, 3), baked linear colour in 0..1
    sigma: np.ndarray  # (N,), in-surface standard deviation in world units
    thin: float = 0.002  # standard deviation along the normal
    opacity: float = 0.98
    info: dict = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.pos)


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def _qmul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product of (N, 4) quaternions in (w, x, y, z) order."""
    aw, av = a[:, :1], a[:, 1:]
    bw, bv = b[:, :1], b[:, 1:]
    w = aw * bw - np.sum(av * bv, axis=1, keepdims=True)
    v = aw * bv + bw * av + np.cross(av, bv)
    return np.hstack([w, v])


def quat_to_matrix(q: np.ndarray) -> np.ndarray:
    """(N, 4) quaternions (w, x, y, z), any length, to (N, 3, 3) rotation matrices."""
    w, x, y, z = _unit(q).T
    return np.stack(
        [
            np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)], axis=1),
            np.stack([2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)], axis=1),
            np.stack([2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], axis=1),
        ],
        axis=1,
    )


def quats_for_normals(normals: np.ndarray, thin_axis: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Quaternions (w, x, y, z) whose rotation takes local axis ``thin_axis[i]`` onto ``normals[i]``.

    Each one also carries a random twist about the normal, a random overall sign and a
    random length, as real optimiser output does.
    """
    n = len(normals)
    a = np.eye(3)[thin_axis]
    b = _unit(normals)
    dot = np.sum(a * b, axis=1)
    align = np.hstack([(1.0 + dot)[:, None], np.cross(a, b)])
    opposite = dot < -0.9999
    if opposite.any():  # 180 degrees about any axis perpendicular to a
        helper = np.where(np.abs(a[:, :1]) < 0.9, [[1.0, 0, 0]], [[0, 1.0, 0]])
        perp = _unit(np.cross(a, helper))
        align[opposite] = np.hstack([np.zeros((n, 1)), perp])[opposite]
    align = _unit(align)
    theta = rng.uniform(0, 2 * np.pi, n)
    twist = np.hstack([np.cos(theta / 2)[:, None], b * np.sin(theta / 2)[:, None]])
    q = _qmul(twist, align)
    q *= rng.choice([-1.0, 1.0], n)[:, None] * rng.uniform(0.5, 2.0, n)[:, None]
    return q


def scene_arrays(scene: Scene, seed: int = 0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The vertex table as written (N, len(PROPS)), plus the thin axis and quaternion per splat."""
    rng = np.random.default_rng(seed)
    n = scene.n
    thin_axis = rng.integers(0, 3, n)
    normal_ply = scene.normal * FLIP
    quats = quats_for_normals(normal_ply, thin_axis, rng)
    log_scales = np.repeat(np.log(scene.sigma)[:, None], 3, axis=1)
    log_scales[np.arange(n), thin_axis] = np.log(scene.thin)

    data = np.zeros((n, len(PROPS)), dtype="<f4")
    data[:, 0:3] = scene.pos * FLIP
    # nx, ny, nz stay zero, as in real exports.
    data[:, 6:9] = (scene.color - 0.5) / SH_C0
    col = 9 + N_REST
    data[:, col] = np.log(scene.opacity / (1.0 - scene.opacity))  # stored as a logit
    data[:, col + 1 : col + 4] = log_scales
    data[:, col + 4 : col + 8] = quats
    return data, thin_axis, quats


def write_ply(scene: Scene, path: Path, seed: int = 0) -> Path:
    data, _, _ = scene_arrays(scene, seed)
    header = "ply\nformat binary_little_endian 1.0\n"
    header += f"element vertex {scene.n}\n"
    header += "".join(f"property float {p}\n" for p in PROPS)
    header += "end_header\n"
    path.write_bytes(header.encode() + data.tobytes())
    return path


# -- geometry ------------------------------------------------------------------------------
def _grid_on_plane(center, normal, half_size, count, rng):
    """Jittered grid of ``count x count`` points on a square, plus its in-plane basis."""
    normal = _unit(np.asarray(normal, dtype=float))
    helper = np.array([0.0, 1.0, 0.0]) if abs(normal[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = _unit(np.cross(helper, normal))
    v = np.cross(normal, u)
    step = 2 * half_size / count
    s = (np.arange(count) + 0.5) * step - half_size
    gu, gv = np.meshgrid(s, s, indexing="ij")
    gu = gu.ravel() + rng.uniform(-0.3, 0.3, gu.size) * step
    gv = gv.ravel() + rng.uniform(-0.3, 0.3, gv.size) * step
    pos = np.asarray(center, dtype=float) + gu[:, None] * u + gv[:, None] * v
    return pos, np.tile(normal, (len(pos), 1)), step


def _fibonacci_sphere(center, radius, count):
    i = np.arange(count) + 0.5
    phi = np.arccos(1 - 2 * i / count)
    theta = np.pi * (1 + 5**0.5) * i
    d = np.stack([np.cos(theta) * np.sin(phi), np.cos(phi), np.sin(theta) * np.sin(phi)], axis=1)
    spacing = radius * np.sqrt(4 * np.pi / count)
    return np.asarray(center, dtype=float) + radius * d, d, spacing


def plane_scene() -> Scene:
    """A tilted square whose colour encodes world position: red grows with y, green with x."""
    rng = np.random.default_rng(1)
    normal = _unit(np.array([0.55, 0.5, 0.67]))
    half = 1.2
    pos, nrm, step = _grid_on_plane([0, 0, 0], normal, half, 56, rng)
    color = np.empty_like(pos)
    color[:, 0] = 0.5 + 0.3 * np.clip(pos[:, 1] / half, -1, 1)
    color[:, 1] = 0.5 + 0.3 * np.clip(pos[:, 0] / half, -1, 1)
    color[:, 2] = 0.45
    sigma = np.full(len(pos), 0.7 * step)
    return Scene("plane", pos, nrm, color, sigma, info={"normal": normal.tolist(), "half_size": half})


def sphere_scene() -> Scene:
    """A grey unit sphere at the origin, with soft lighting from straight above baked in.

    The baked shading depends only on height, so it gives the albedo/irradiance split
    something to remove without favouring either side for the left/right lighting tests.
    """
    pos, nrm, spacing = _fibonacci_sphere([0, 0, 0], 1.0, 4000)
    albedo = 0.8
    shade = 0.15 + 0.85 * (0.5 + 0.5 * nrm[:, 1])
    color = np.repeat((albedo * shade)[:, None], 3, axis=1)
    sigma = np.full(len(pos), 0.7 * spacing)
    info = {"center": [0.0, 0.0, 0.0], "radius": 1.0, "albedo": albedo, "baked_light": [0.0, 1.0, 0.0]}
    return Scene("sphere", pos, nrm, color, sigma, info=info)


def shadow_scene() -> Scene:
    """A horizontal ground square with a small sphere floating above its centre."""
    rng = np.random.default_rng(3)
    ground_y, half = -0.8, 2.0
    gpos, gnrm, gstep = _grid_on_plane([0, ground_y, 0], [0, 1, 0], half, 64, rng)
    center, radius = [0.0, 0.15, 0.0], 0.45
    spos, snrm, sspacing = _fibonacci_sphere(center, radius, 1500)
    pos = np.vstack([gpos, spos])
    nrm = np.vstack([gnrm, snrm])
    sigma = np.concatenate([np.full(len(gpos), 0.7 * gstep), np.full(len(spos), 0.7 * sspacing)])
    color = np.full_like(pos, 0.75)
    info = {"ground_y": ground_y, "ground_half": half, "occluder_center": center, "occluder_radius": radius}
    return Scene("shadow", pos, nrm, color, sigma, info=info)


SCENES = {"plane": plane_scene, "sphere": sphere_scene, "shadow": shadow_scene}


def write_all(out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    return {name: write_ply(make(), out_dir / f"{name}.ply") for name, make in SCENES.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the synthetic test scenes as .ply files.")
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args(argv)
    for name, path in write_all(args.out_dir).items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
