"""New lights change the relit pane only, light the side they are on, and cast shadows."""

import numpy as np
import pytest
from camera import VIEWS
from imagestats import covered, crop_common, disc, erode, luminance, mean_abs_diff
from splat_scenes import shadow_scene

pytestmark = pytest.mark.browser

WHITE_POINT = {"color": "#ffffff", "intensity": 3, "range": 8}


def test_adding_a_light_changes_the_relit_pane_and_not_the_baked_one(open_scene):
    viewer = open_scene("sphere")
    viewer.clear_lights()
    baked_before, relit_before = viewer.capture("no-lights")
    viewer.add_light("point", x=2, y=1, z=2)
    baked_after, relit_after = viewer.capture("one-light")
    assert mean_abs_diff(relit_before, relit_after) > 1.0
    assert mean_abs_diff(baked_before, baked_after) < 0.05


def bright_side_offset(viewer, light_x: float) -> float:
    """How far right of the sphere's centre its brightness is centred, as a share of its width."""
    viewer.set_light(0, x=light_x, y=0.5, z=2.5)
    baked, relit = crop_common(*viewer.capture(f"light-x{light_x:+g}"))
    mask = erode(covered(baked), 2)  # the relit pane is dark on its unlit side
    cols = np.nonzero(mask)[1]
    weight = luminance(relit) * mask
    centroid = (weight * np.arange(relit.shape[1])[None, :]).sum() / weight.sum()
    return (centroid - cols.mean()) / np.ptp(cols)


def test_bright_side_follows_the_light(open_scene):
    """The sphere camera looks down -z with +x to the right, so a light at +x lights the right."""
    viewer = open_scene("sphere")
    viewer.set_checked("shadows", False)
    viewer.set_value("aInt", 0)  # no ambient: all brightness comes from the one light
    viewer.clear_lights()
    viewer.add_light("point", x=3, y=0.5, z=2.5, **WHITE_POINT)
    right = bright_side_offset(viewer, 3.0)
    left = bright_side_offset(viewer, -3.0)
    assert right > 0.08, f"light on the right, brightness centred at {right:+.2f} of the width"
    assert left < -0.08, f"light on the left, brightness centred at {left:+.2f} of the width"


def shadow_and_control_points(light: np.ndarray):
    """Where the occluder's shadow falls on the ground, and two lit ground points as far from the light."""
    info = shadow_scene().info
    occluder, ground_y = np.array(info["occluder_center"]), info["ground_y"]
    t = (light[1] - ground_y) / (light[1] - occluder[1])
    shadow = light + t * (occluder - light)
    reach = np.hypot(*(shadow - light)[[0, 2]])
    side = 1.3  # well outside the shadow, which is about 0.7 wide
    dx = np.sqrt(reach**2 - side**2)
    controls = [np.array([light[0] - dx, ground_y, z]) for z in (side, -side)]
    return shadow, controls


def test_a_light_behind_an_occluder_casts_a_shadow(open_scene):
    viewer = open_scene("shadow")
    viewer.clear_lights()
    viewer.set_value("aInt", 0.05)
    viewer.set_value("shReach", 1.0)
    viewer.set_value("shSteps", 32)
    light = np.array([2.2, 1.8, 0.0])
    viewer.add_light("point", x=light[0], y=light[1], z=light[2], **{**WHITE_POINT, "intensity": 4, "range": 10})
    _, lit = viewer.capture("shadows-on")
    viewer.set_checked("shadows", False)
    _, unshadowed = viewer.capture("shadows-off")

    shadow, controls = shadow_and_control_points(light)
    h, w, _ = lit.shape
    ratios = []
    for point in [shadow, *controls]:
        centre = VIEWS["shadow"].project(point, w, h)[0]
        region = disc((h, w), centre, 12) & covered(unshadowed)
        assert region.sum() > 300, f"ground point {point} is not on screen"
        ratios.append(luminance(lit)[region].mean() / luminance(unshadowed)[region].mean())
    in_shadow, *lit_ratios = ratios
    assert in_shadow < 0.75, f"shadowed ground keeps {in_shadow:.0%} of its light"
    assert min(lit_ratios) > 0.9, f"unshadowed ground keeps only {min(lit_ratios):.0%} of its light"
