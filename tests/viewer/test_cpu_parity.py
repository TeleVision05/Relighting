"""The CPU reference renderer and the WebGL viewer draw the same image from the same camera.

Each fixture scene is rendered by the viewer (headless Chromium) and by cpu_render at the
pane's exact size, then the CPU image is laid over the viewer's clear colour. The baked
pane is compared with the CPU ``neutral`` mode, and the normals G-buffer (mode 4, N Smooth
0) with the CPU ``normals`` mode.

Tolerance, in 0..255 units: mean absolute difference under 1.0 and the 99th percentile
of the per-pixel worst channel under 4. Measured 2026-11-13, identical on Metal and on
SwiftShader: at most 0.39 mean and 1.5 p99 over every case below. What is left is
rounding: the viewer stores colours, opacities and normals as half floats, writes 8-bit
pixels and blends in GPU float order. The affine Jacobian the viewer used until
2026-11-13 (no depth column) fails 6 of the 8 comparisons: p99 4.7 to 10.3 on most, and
a mean of 4.7 with p99 126 on sphere-close.
"""

import numpy as np
import pytest
from camera import VIEWS, Camera
from imagestats import BACKGROUND

from cpu_render import OrbitCamera, load_ply, over_background, render_rgba

pytestmark = pytest.mark.browser

NORMALS_MODE = 4
MEAN_LIMIT = 1.0  # mean |viewer - cpu|, 0..255
P99_LIMIT = 4.0  # 99th percentile of the worst channel per pixel, 0..255

# The fixture views, plus close views where most splats are well off the optical axis.
CASES = {
    "plane": ("plane", VIEWS["plane"]),
    "sphere": ("sphere", VIEWS["sphere"]),
    "plane-close": ("plane", Camera(yaw=0.9, pitch=0.5, zoom=1.8)),
    "sphere-close": ("sphere", Camera(yaw=0.6, pitch=-0.4, zoom=1.9)),
}


def cpu_pane(scene: dict, cam: Camera, shape, mode: str) -> np.ndarray:
    h, w = shape[:2]
    rgba = render_rgba(scene, w, h, mode=mode, camera=OrbitCamera(cam.yaw, cam.pitch, cam.zoom))
    return over_background(rgba, BACKGROUND).astype(np.float64)


def difference(viewer_img: np.ndarray, cpu_img: np.ndarray) -> tuple[float, float]:
    diff = np.abs(viewer_img - cpu_img) * 255.0
    return float(diff.mean()), float(np.percentile(diff.max(axis=-1), 99))


@pytest.fixture(scope="module")
def cpu_scenes(scene_files):
    return {name: load_ply(path) for name, path in scene_files.items()}


@pytest.mark.parametrize("case", list(CASES))
def test_cpu_and_viewer_agree(open_scene, cpu_scenes, case):
    name, cam = CASES[case]
    viewer = open_scene(name, cam)
    baked, _ = viewer.capture("baked")
    viewer.set_value("nSmooth", 0)
    viewer.set_gbuffer(NORMALS_MODE)
    _, normals = viewer.capture("normals")

    scene = cpu_scenes[name]
    cpu_baked = cpu_pane(scene, cam, baked.shape, "neutral")
    cpu_normals = cpu_pane(scene, cam, normals.shape, "normals")
    viewer.captures["cpu"] = (cpu_baked, cpu_normals)  # saved next to the viewer's on failure

    for label, got, want in (("baked", baked, cpu_baked), ("normals", normals, cpu_normals)):
        mean, p99 = difference(got, want)
        detail = f"{case} {label}: mean {mean:.2f}/255, p99 {p99:.1f}/255"
        assert mean < MEAN_LIMIT, detail
        assert p99 < P99_LIMIT, detail
    assert (np.abs(baked - BACKGROUND).max(axis=-1) > 0.06).mean() > 0.05, "the scene should fill part of the pane"
