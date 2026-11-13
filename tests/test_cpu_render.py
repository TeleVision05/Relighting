"""The CPU reference renderer's geometry and compositing, checked against first principles.

* EWA projection: the screen covariance must match the spread of projected samples.
* One elongated splat must land on screen with the orientation its long axis projects to.
* The tile rasteriser must equal a plain back-to-front "over" of every splat.
"""

import numpy as np
import pytest

from cpu_render import OrbitCamera, render_rgba
from cpu_render.frame import quat_to_matrix
from cpu_render.project import Projected, screen_covariances
from cpu_render.raster import rasterize

W, H = 320, 240


def _project_samples(cam, pts, w, h):
    v = (pts - cam.position) @ cam.rotation.T
    d = -v[:, 2]
    f = cam.focal(w, h)
    return np.stack([w / 2 + f * v[:, 0] / d, h / 2 - f * v[:, 1] / d], axis=1)


@pytest.mark.parametrize("centre_view", [[0.0, 0.0, -3.0], [1.0, 0.8, -3.0], [1.5, -1.0, -2.0]])
def test_screen_covariance_matches_projected_samples(centre_view):
    """Linearising the projection (EWA) must reproduce the covariance of projected points.

    The affine shortcut the viewer used to take (no depth column in the Jacobian) is
    right only on the optical axis; off-axis it is 40-80% off, which this test also pins.
    """
    rng = np.random.default_rng(0)
    cam = OrbitCamera(0.3, 0.2, 5.0)
    w, h = 800, 600
    f = cam.focal(w, h)
    cv = np.array(centre_view)
    a = rng.normal(size=(3, 3))
    cov_world = a @ a.T * 0.0025  # small enough that the linearisation error is about 1%
    pts = rng.multivariate_normal(cam.position + cam.rotation.T @ cv, cov_world, 200_000)
    sampled = np.cov(_project_samples(cam, pts, w, h).T)
    view_cov = cam.rotation @ cov_world @ cam.rotation.T

    def rel_error(affine):
        c = screen_covariances(cv[None], view_cov[None], f, w, h, affine)[0] - 0.3 * np.eye(2)
        return np.linalg.norm(c - sampled) / np.linalg.norm(sampled)

    assert rel_error(False) < 0.05
    if np.hypot(cv[0], cv[1]) > 0.5:
        assert rel_error(True) > 0.3, "the affine shortcut should be visibly wrong off-axis"


def _one_splat_scene(position, quat_wxyz, log_scales, color=(0.9, 0.2, 0.1)):
    """A one-splat scene dict in the viewer frame, as cpu_render.scene.load_ply returns."""
    q = np.asarray(quat_wxyz, dtype=float)[None] / np.linalg.norm(quat_wxyz)
    return {
        "positions": np.asarray(position, dtype=float)[None],
        "quats": q,
        "log_scales": np.asarray(log_scales, dtype=float)[None],
        "opacity": np.array([0.99]),
        "baked": np.asarray(color, dtype=float)[None],
        "normals": quat_to_matrix(q)[:, :, 2],
        "albedo": np.asarray(color, dtype=float)[None],
        "irradiance": np.ones(1),
    }


def test_elongated_splat_lands_with_the_projected_orientation():
    """All three scales and the rotation reach the screen: the ellipse lies along the long axis."""
    angle = np.radians(35.0)
    quat = [np.cos(angle / 2), 0.0, 0.0, np.sin(angle / 2)]  # 35 degrees about world z
    scene = _one_splat_scene([0.2, -0.1, 0.0], quat, np.log([0.30, 0.03, 0.06]))
    cam = OrbitCamera(0.0, 0.0, 4.0)  # looking down -z: world x is right, world y is up
    img = render_rgba(scene, W, H, mode="neutral", camera=cam)
    alpha = img[..., 3]
    rows, cols = np.mgrid[0:H, 0:W] + 0.5
    total = alpha.sum()
    mx, my = (alpha * cols).sum() / total, (alpha * rows).sum() / total
    cxx = (alpha * (cols - mx) ** 2).sum() / total
    cyy = (alpha * (rows - my) ** 2).sum() / total
    cxy = (alpha * (cols - mx) * (rows - my)).sum() / total
    major = np.degrees(0.5 * np.arctan2(2 * cxy, cxx - cyy))
    # Screen y points down, so a 35 degree turn counter-clockwise in the world is -35 on screen.
    assert major == pytest.approx(-35.0, abs=1.0)
    expected_centre = _project_samples(cam, np.array([[0.2, -0.1, 0.0]]), W, H)[0]
    assert (mx, my) == pytest.approx(tuple(expected_centre), abs=0.5)
    lo, hi = np.linalg.eigvalsh([[cxx, cxy], [cxy, cyy]])
    assert np.sqrt(hi / lo) > 4.0, "a 10:1 splat seen face-on should stay clearly elongated"


def test_tiny_scales_are_not_inflated():
    """No hidden scale factor: a splat with a 0.01 sigma at distance 4 stays a few pixels wide."""
    scene = _one_splat_scene([0.0, 0.0, 0.0], [1, 0, 0, 0], np.log([0.01, 0.01, 0.01]))
    img = render_rgba(scene, W, H, mode="neutral", camera=OrbitCamera(0.0, 0.0, 4.0))
    sigma_px = 0.01 * OrbitCamera.focal(W, H) / 4.0  # 0.48 px
    expected_sigma = np.sqrt(sigma_px**2 + 0.3)  # plus the low-pass
    covered = (img[..., 3] > 0).sum()
    assert covered <= np.pi * (3 * expected_sigma + 1) ** 2


def _naive_over(proj: Projected, colors, opacity, w, h):
    """Every splat, far to near, blended over the image at every pixel (no tiles, no early stop)."""
    rows, cols = np.mgrid[0:h, 0:w] + 0.5
    rgb = np.zeros((h, w, 3))
    alpha_acc = np.zeros((h, w))
    for i in np.argsort(-proj.depth, kind="stable"):
        dx, dy = cols - proj.mean[i, 0], rows - proj.mean[i, 1]
        a, b, c = proj.conic[i]
        maha = a * dx * dx + 2 * b * dx * dy + c * dy * dy
        alpha = opacity[i] * np.exp(-0.5 * maha)
        alpha[(maha > 9.0) | (alpha < 0.003)] = 0.0
        rgb = rgb * (1 - alpha[..., None]) + colors[i] * alpha[..., None]
        alpha_acc = alpha_acc * (1 - alpha) + alpha
    return rgb, alpha_acc


def test_tile_rasteriser_equals_back_to_front_over():
    rng = np.random.default_rng(3)
    n, w, h = 300, 96, 80
    sigma = rng.uniform(1.0, 14.0, (n, 2))
    theta = rng.uniform(0, np.pi, n)
    cos, sin = np.cos(theta), np.sin(theta)
    cov = np.empty((n, 2, 2))
    cov[:, 0, 0] = (cos * sigma[:, 0]) ** 2 + (sin * sigma[:, 1]) ** 2
    cov[:, 1, 1] = (sin * sigma[:, 0]) ** 2 + (cos * sigma[:, 1]) ** 2
    cov[:, 0, 1] = cov[:, 1, 0] = cos * sin * (sigma[:, 0] ** 2 - sigma[:, 1] ** 2)
    inv = np.linalg.inv(cov)
    radius = 3.0 * np.sqrt(np.linalg.eigvalsh(cov)[:, 1])
    proj = Projected(
        index=np.arange(n),
        mean=rng.uniform([-10, -10], [w + 10, h + 10], (n, 2)),
        conic=np.stack([inv[:, 0, 0], inv[:, 0, 1], inv[:, 1, 1]], axis=1),
        radius=radius,
        depth=rng.uniform(1.0, 5.0, n),
    )
    colors = rng.uniform(0, 1, (n, 3))
    opacity = rng.uniform(0.05, 0.95, n)
    img = rasterize(proj, colors, opacity, w, h, tile=16)
    rgb_ref, alpha_ref = _naive_over(proj, colors, opacity, w, h)
    assert np.abs(img[..., 3] - alpha_ref).max() < 1e-4
    premult = img[..., :3] * img[..., 3:4]
    assert np.abs(premult - rgb_ref).max() < 2e-4
