"""CPU renderer normals against the fixture scenes' analytic normals. No browser needed.

The fixtures (splat_scenes.py) store quaternions the way real 3DGS exports do,
``rot_0..rot_3 = w, x, y, z``, unnormalised, with a random sign, a random twist about the
normal and a random choice of thin axis. Reading them in any other order, or skipping the
export-frame flip, cannot land on the analytic normals by luck.
"""

import numpy as np
import pytest
from splat_scenes import plane_scene, sphere_scene, write_ply

from cpu_render import load_ply


def _angles_deg(a: np.ndarray, b: np.ndarray, signed: bool) -> np.ndarray:
    cos = np.sum(a * b, axis=1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1))
    return np.degrees(np.arccos(np.clip(cos if signed else np.abs(cos), -1.0, 1.0)))


def test_cpu_normals_match_the_analytic_sphere_normals(tmp_path):
    """Oriented outward from the centroid, every splat normal is the radial direction."""
    scene = sphere_scene()
    loaded = load_ply(write_ply(scene, tmp_path / "sphere.ply"))
    assert np.allclose(loaded["positions"], scene.pos, atol=1e-6)
    errors = _angles_deg(loaded["normals"], scene.normal, signed=True)
    assert errors.max() < 0.05, f"worst normal {errors.max():.3f} deg off"


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_cpu_normals_match_the_tilted_plane(tmp_path, seed):
    """A flat plane has no inside, so only the axis is checked, not the sign."""
    scene = plane_scene()
    loaded = load_ply(write_ply(scene, tmp_path / "plane.ply", seed=seed))
    errors = _angles_deg(loaded["normals"], scene.normal, signed=False)
    assert errors.max() < 0.05, f"worst normal {errors.max():.3f} deg off"


def test_cpu_world_quaternions_rebuild_the_splat_axes(tmp_path):
    """The thin axis of the loaded rotation, not just the normal, is the analytic normal."""
    from cpu_render.frame import quat_to_matrix, thin_axis

    scene = sphere_scene()
    loaded = load_ply(write_ply(scene, tmp_path / "sphere.ply"))
    rot = quat_to_matrix(loaded["quats"])
    thin = rot[np.arange(scene.n), :, thin_axis(loaded["log_scales"])]
    errors = _angles_deg(thin, scene.normal, signed=False)
    assert errors.max() < 0.05
