"""Headless smoke tests: render a tiny synthetic splat set, no big .ply files needed."""

from io import BytesIO

import numpy as np
import pytest
from PIL import Image

import render_splats

FLIP = np.array([1.0, -1.0, -1.0])  # export frame <-> viewer frame


def test_load_ply_derives_fields(synthetic_ply):
    scene = render_splats.load_ply(synthetic_ply)
    assert scene["positions"].shape == (1500, 3)
    assert np.allclose(np.linalg.norm(scene["normals"], axis=1), 1.0, atol=1e-6)
    assert np.allclose(np.linalg.norm(scene["quats"], axis=1), 1.0, atol=1e-6)
    for key in ("albedo", "baked"):
        assert scene[key].min() >= 0.0 and scene[key].max() <= 1.0
    assert np.all(scene["irradiance"] > 0)


def test_load_ply_puts_the_scene_in_the_viewer_frame(synthetic_ply):
    """Y and Z are negated on load, as src/frame.js worldPosition does."""
    table = np.frombuffer(synthetic_ply.read_bytes().split(b"end_header\n", 1)[1], dtype="<f4").reshape(-1, 14)
    scene = render_splats.load_ply(synthetic_ply)
    assert np.allclose(scene["positions"], table[:, 0:3] * FLIP, atol=1e-6)


def test_synthetic_sphere_normals_are_radial(synthetic_ply):
    """The fixture stores rot_0 = w. Read as (x, y, z, w) these normals are off by tens of degrees."""
    scene = render_splats.load_ply(synthetic_ply)
    radial = scene["positions"] / np.linalg.norm(scene["positions"], axis=1, keepdims=True)
    cos = np.sum(scene["normals"] * radial, axis=1)
    assert cos.min() > 0.9999, f"worst normal is {np.degrees(np.arccos(cos.min())):.2f} deg off radial"


def test_load_ply_rejects_garbage(tmp_path):
    bad = tmp_path / "bad.ply"
    bad.write_bytes(b"not a ply")
    with pytest.raises(RuntimeError):
        render_splats.load_ply(bad)


def test_load_ply_rejects_an_lfs_pointer(tmp_path):
    pointer = tmp_path / "pointer.ply"
    pointer.write_bytes(b"version https://git-lfs.github.com/spec/v1\noid sha256:00\nsize 1\n")
    with pytest.raises(RuntimeError, match="LFS"):
        render_splats.load_ply(pointer)


def test_separate_lighting_uniform_scene_is_identity():
    pos = np.random.default_rng(1).uniform(size=(200, 3)).astype(np.float32)
    app = np.full((200, 3), 0.5, dtype=np.float32)
    albedo, irr = render_splats.separate_lighting(pos, app, np.ones(200, dtype=np.float32))
    assert np.allclose(irr, 1.0, atol=1e-3)
    assert np.allclose(albedo, 0.5, atol=1e-3)


@pytest.mark.parametrize("mode", ["relit", "neutral", "albedo", "normals"])
def test_render_png_produces_visible_image(synthetic_ply, mode):
    png = render_splats.render_png(width=256, height=256, mode=mode, zoom=3.0)
    img = Image.open(BytesIO(png))
    assert img.size == (256, 256)
    assert img.mode == "RGBA"
    alpha = np.asarray(img)[:, :, 3]
    assert (alpha > 0).sum() > 12_000, "the sphere should cover a good part of the image"
    assert alpha[0, 0] == 0, "the corners are empty"
