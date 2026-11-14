"""The fixture generator itself: no browser needed, so these run in the ordinary test job."""

import numpy as np
import pytest
from splat_scenes import FLIP, PROPS, SCENES, SH_C0, quat_to_matrix, scene_arrays, write_ply

# The vertex layout of the real Buttons.ply export, read from its header.
BUTTONS_LAYOUT = (
    ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"]
    + [f"f_rest_{i}" for i in range(24)]
    + ["opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
)


def read_ply(path):
    raw = path.read_bytes()
    end = raw.index(b"end_header\n") + len(b"end_header\n")
    lines = raw[:end].decode().splitlines()
    props = [ln.split()[2] for ln in lines if ln.startswith("property")]
    count = int(next(ln for ln in lines if ln.startswith("element vertex")).split()[2])
    assert "format binary_little_endian 1.0" in lines
    table = np.frombuffer(raw[end:], dtype="<f4").reshape(count, len(props))
    return props, table


@pytest.mark.parametrize("name", sorted(SCENES))
def test_written_file_matches_the_real_export_layout(tmp_path, name):
    scene = SCENES[name]()
    props, table = read_ply(write_ply(scene, tmp_path / f"{name}.ply"))
    assert props == BUTTONS_LAYOUT == PROPS
    assert table.shape == (scene.n, 41)
    assert 2000 <= scene.n <= 6000
    np.testing.assert_allclose(table[:, 0:3] * FLIP, scene.pos, atol=1e-6)
    np.testing.assert_allclose(0.5 + table[:, 6:9] * SH_C0, scene.color, atol=1e-5)


@pytest.mark.parametrize("name", sorted(SCENES))
def test_thin_axis_of_each_splat_is_its_surface_normal_in_the_export_frame(name):
    scene = SCENES[name]()
    data, thin_axis, quats = scene_arrays(scene)
    rot = quat_to_matrix(data[:, -4:].astype(float))  # rot_0..3 = w, x, y, z
    axis_world = rot[np.arange(scene.n), :, thin_axis]  # column k = where local axis k goes
    dots = np.sum(axis_world * (scene.normal * FLIP), axis=1)
    assert np.all(dots > 0.9999)
    log_scales = data[:, 34:37]
    assert np.all(np.argmin(log_scales, axis=1) == thin_axis)


def test_quaternions_are_deliberately_awkward():
    _, thin_axis, quats = scene_arrays(SCENES["sphere"]())
    lengths = np.linalg.norm(quats, axis=1)
    assert lengths.min() < 0.7 and lengths.max() > 1.5  # not normalised
    assert (quats[:, 0] < 0).any() and (quats[:, 0] > 0).any()  # both signs
    assert set(np.unique(thin_axis)) == {0, 1, 2}  # every axis is the thin one somewhere


@pytest.mark.parametrize("name", sorted(SCENES))
def test_viewer_quaternion_remap_turns_export_normals_into_world_normals(name):
    """Pins the maths of the remap the viewer applies on load: (w, x, y, z) -> (-x, w, -z, y).

    That is the 180 degree rotation about X, composed on the left. Applied to the stored
    quaternion it must carry each splat's thin axis onto the world-frame normal.
    """
    scene = SCENES[name]()
    data, thin_axis, _ = scene_arrays(scene)
    w, x, y, z = data[:, -4:].astype(float).T
    remapped = np.stack([-x, w, -z, y], axis=1)
    rot = quat_to_matrix(remapped)
    axis_world = rot[np.arange(scene.n), :, thin_axis]
    assert np.all(np.sum(axis_world * scene.normal, axis=1) > 0.9999)
