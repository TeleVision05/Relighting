"""Generate the demo scene for the hosted viewer: ``demo/demo-scene.ply``.

The scene is computed, not captured: a chequered floor, a large sphere, a small sphere and a
column, written as a 3D Gaussian Splatting file with the same layout as a real export. It
contains no photographed or third-party data, so it may be redistributed under the repository's
MIT licence (see ``demo/NOTICE``). The output is deterministic: the same command always writes
the same bytes.

    python demo/make_demo_scene.py            # rewrites demo/demo-scene.ply
    python demo/make_demo_scene.py OUT.ply    # somewhere else
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "viewer"))

from splat_scenes import Scene, _fibonacci_sphere, _grid_on_plane, write_ply  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parent / "demo-scene.ply"


def _baked_shade(normal: np.ndarray) -> np.ndarray:
    """Soft light from above, baked in the way a real capture bakes it (0.2 to 1)."""
    return 0.2 + 0.8 * (0.5 + 0.5 * normal[:, 1])


def _floor() -> Scene:
    rng = np.random.default_rng(11)
    half = 3.0
    pos, nrm, step = _grid_on_plane([0.0, -1.0, 0.0], [0, 1, 0], half, 110, rng)
    tile = (np.floor((pos[:, 0] + half) / 0.75) + np.floor((pos[:, 2] + half) / 0.75)) % 2
    color = np.where(tile[:, None] == 0, [0.78, 0.74, 0.66], [0.28, 0.33, 0.40])
    sigma = np.full(len(pos), 0.7 * step)
    return Scene("floor", pos, nrm, color, sigma)


def _ball(center, radius, count, albedo) -> Scene:
    pos, nrm, spacing = _fibonacci_sphere(center, radius, count)
    color = np.asarray(albedo)[None, :] * _baked_shade(nrm)[:, None]
    return Scene("ball", pos, nrm, color, np.full(len(pos), 0.7 * spacing))


def _column(center_xz, radius, y0, y1, rings, per_ring, albedo) -> Scene:
    ys = np.linspace(y0, y1, rings)
    theta = np.linspace(0, 2 * np.pi, per_ring, endpoint=False)
    # Stagger alternate rings so the splats tile the side without lines.
    angle = theta[None, :] + (np.arange(rings)[:, None] % 2) * (theta[1] / 2)
    nrm = np.stack([np.cos(angle), np.zeros_like(angle), np.sin(angle)], axis=-1).reshape(-1, 3)
    pos = np.stack(
        [
            center_xz[0] + radius * np.cos(angle),
            np.repeat(ys[:, None], per_ring, 1),
            center_xz[1] + radius * np.sin(angle),
        ],
        axis=-1,
    ).reshape(-1, 3)
    spacing = max(2 * np.pi * radius / per_ring, (y1 - y0) / (rings - 1))
    color = np.asarray(albedo)[None, :] * _baked_shade(nrm)[:, None]
    return Scene("column", pos, nrm, color, np.full(len(pos), 0.7 * spacing))


def demo_scene() -> Scene:
    parts = [
        _floor(),
        _ball([-0.5, 0.0, 0.0], 1.0, 14000, [0.85, 0.45, 0.32]),
        _ball([1.3, -0.55, 0.9], 0.45, 3500, [0.30, 0.65, 0.62]),
        _column([-2.0, -1.8], 0.35, -1.0, 1.4, 70, 60, [0.62, 0.58, 0.82]),
    ]
    return Scene(
        "demo",
        np.vstack([p.pos for p in parts]),
        np.vstack([p.normal for p in parts]),
        np.vstack([p.color for p in parts]),
        np.concatenate([p.sigma for p in parts]),
        thin=0.004,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out", nargs="?", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    scene = demo_scene()
    write_ply(scene, args.out)
    print(f"{args.out}: {scene.n:,} splats, {args.out.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
