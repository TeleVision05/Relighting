"""The normals debug view matches the fixtures' known surface normals.

This is the check for the frame flip and quaternion remap the viewer applies on load. With
N Smooth at 0 the normal comes only from each splat's quaternion and scales, so a wrong
component order, a missing remap or a wrong thin-axis pick shows up as a large angle error.
With N Smooth at 1 it comes only from the plane fit over splat positions.

The view shows N * 0.5 + 0.5 after the shader turns N to face the camera, so the expected
colour is the known normal turned towards the camera.
"""

import numpy as np
import pytest
from camera import VIEWS
from imagestats import angle_deg, covered, erode
from splat_scenes import plane_scene, sphere_scene

pytestmark = pytest.mark.browser

NORMALS_MODE = 4


def rendered_normals(viewer, smooth: float):
    viewer.set_gbuffer(NORMALS_MODE)
    viewer.set_value("nSmooth", smooth)
    _, img = viewer.capture(f"normals-smooth{smooth}")
    return img, img * 2.0 - 1.0


def summary(errors: np.ndarray) -> str:
    return f"median {np.median(errors):.1f} deg, p90 {np.percentile(errors, 90):.1f} deg over {errors.size} px"


@pytest.mark.parametrize("smooth", [0.0, 1.0])
def test_tilted_plane_normal_matches(open_scene, smooth):
    viewer = open_scene("plane")
    img, normals = rendered_normals(viewer, smooth)
    expected = np.array(plane_scene().info["normal"])
    if expected @ VIEWS["plane"].position < 0:
        expected = -expected
    mask = erode(covered(img), 3)
    errors = angle_deg(normals[mask], expected[None, :])
    assert mask.sum() > 20_000, "the plane should fill a good part of the pane"
    assert np.median(errors) < 3.0, summary(errors)
    assert np.percentile(errors, 90) < 6.0, summary(errors)


def sphere_hits(cam, h: int, w: int, radius: float):
    """Front-surface normal under each pixel, and which pixels are well inside the outline."""
    rays = cam.pixel_rays(w, h)
    origin = cam.position
    b = rays @ origin
    disc = b * b - (origin @ origin - radius * radius)
    t = -b - np.sqrt(np.maximum(disc, 0.0))
    normal = (origin + rays * t[..., None]) / radius
    miss_distance = np.linalg.norm(np.cross(rays, -origin), axis=-1)  # centre-to-ray distance
    return normal, (disc > 0) & (miss_distance < 0.85 * radius)


# Smoothing 1.0 shows only the plane-fit normals. This sphere is sparse (about three
# splats per fit neighbourhood), and planeNormals used to accept a fit through any three
# splats, which always looks perfectly planar: 1.8% of pixels were off by more than 20
# degrees and p90 needed a 10 degree allowance (measured 2026-11-13). Fits now need
# MIN_FIT_SPLATS splats (src/normals.js), so both settings meet the same bar.
@pytest.mark.parametrize("smooth", [0.0, 1.0])
def test_sphere_normals_point_outwards_everywhere(open_scene, smooth):
    viewer = open_scene("sphere")
    img, normals = rendered_normals(viewer, smooth)
    h, w, _ = img.shape
    expected, inside = sphere_hits(VIEWS["sphere"], h, w, sphere_scene().info["radius"])
    mask = inside & erode(covered(img), 2)
    errors = angle_deg(normals[mask], expected[mask])
    assert mask.sum() > 15_000
    assert np.median(errors) < 5.0, summary(errors)
    assert np.percentile(errors, 90) < 6.0, summary(errors)
    assert np.mean(errors > 20) < 0.002, f"{np.mean(errors > 20):.2%} of pixels off by over 20 deg"
