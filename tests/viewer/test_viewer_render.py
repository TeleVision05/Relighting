"""The viewer loads a scene cleanly, draws it the right way up, and each G-buffer mode differs."""

import itertools
import re

import numpy as np
import pytest
from imagestats import covered, crop_common, erode, luminance, mean_abs_diff
from splat_scenes import SCENES

pytestmark = pytest.mark.browser

GBUFFER_MODES = {0: "relit", 1: "albedo", 2: "baked", 3: "irradiance", 4: "normals", 5: "specular"}


@pytest.mark.parametrize("name", sorted(SCENES))
def test_scene_loads_without_errors_and_both_panes_draw(open_scene, name):
    viewer = open_scene(name)
    viewer.pause(False)  # let the real render loop run a while: errors can come from any frame
    viewer.page.wait_for_function("() => document.querySelector('#status').textContent.includes('FPS')")
    viewer.pause()
    state = viewer.state()
    assert state["n"] == SCENES[name]().n
    assert state["sorted"] == state["n"], "every splat is in front of the camera"
    assert viewer.errors == [], viewer.errors
    assert re.match(r"(Loaded [\d,]+ splats|[\d,]+/[\d,]+ splats \|)", viewer.status()), viewer.status()

    for pane, img in zip(("baked", "relit"), viewer.capture(), strict=True):
        share = covered(img).mean()
        assert 0.03 < share < 0.6, f"{pane} pane: {share:.1%} of pixels drawn"
        assert luminance(img)[covered(img)].std() > 0.01, f"{pane} pane is a flat colour"


def test_scene_is_drawn_the_right_way_up(open_scene):
    """The plane's red channel grows with world height and green with world x.

    The viewer flips the export frame (y down) on load; without that flip, or with the flip
    applied twice, red would grow towards the bottom of the image.
    """
    viewer = open_scene("plane")
    baked, _ = viewer.capture()
    mask = erode(covered(baked), 2)
    rows, cols = np.nonzero(mask)
    red, green = baked[mask][:, 0], baked[mask][:, 1]
    assert np.corrcoef(red, -rows)[0, 1] > 0.7, "red should increase towards the top"
    assert np.corrcoef(green, cols)[0, 1] > 0.7, "green should increase towards the right"


def test_every_gbuffer_mode_gives_a_different_image(open_scene):
    viewer = open_scene("sphere")
    images = {}
    for mode in GBUFFER_MODES:
        viewer.set_gbuffer(mode)
        baked, images[mode] = viewer.capture(GBUFFER_MODES[mode])
    mask = erode(covered(images[2]), 2)
    for a, b in itertools.combinations(GBUFFER_MODES, 2):
        diff = np.abs(images[a][mask] - images[b][mask]).mean() * 255
        assert diff > 2.0, f"{GBUFFER_MODES[a]} and {GBUFFER_MODES[b]} look the same (mean diff {diff:.2f})"
    # The baked debug mode of the relit pane is the reference pane's own colour.
    assert mean_abs_diff(*crop_common(images[2], baked)) < 1.0


def test_albedo_has_less_baked_shading_than_the_baked_colour(open_scene):
    """The sphere was baked lit from above; separating the lighting must flatten that."""
    viewer = open_scene("sphere")
    ratios = {}
    for mode in (1, 2):
        viewer.set_gbuffer(mode)
        _, img = viewer.capture(GBUFFER_MODES[mode])
        mask = erode(covered(img), 2)
        row = np.arange(img.shape[0])[:, None]
        rows = np.nonzero(mask)[0]
        top = mask & (row < np.percentile(rows, 30))
        bottom = mask & (row > np.percentile(rows, 70))
        lum = luminance(img)
        ratios[mode] = lum[top].mean() / lum[bottom].mean()
    assert ratios[2] > 1.5, f"baked top/bottom brightness {ratios[2]:.2f}: the fixture lost its shading"
    assert ratios[1] < ratios[2] - 0.08, f"albedo {ratios[1]:.3f} vs baked {ratios[2]:.3f}"
