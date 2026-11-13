"""Headless smoke tests: render a tiny synthetic splat set, no big .ply files needed."""

from io import BytesIO

import numpy as np
import pytest
from PIL import Image

import render_splats


def test_load_ply_derives_fields(synthetic_ply):
    props = render_splats.load_ply(synthetic_ply)
    assert len(props["x"]) == 1500
    normals = np.column_stack([props["nx"], props["ny"], props["nz"]])
    assert np.allclose(np.linalg.norm(normals, axis=1), 1.0, atol=1e-4)
    for key in ("albedo_r", "albedo_g", "albedo_b", "baked_r"):
        assert props[key].min() >= 0.0 and props[key].max() <= 1.0
    assert np.all(props["irradiance"] > 0)


def test_load_ply_rejects_garbage(tmp_path):
    bad = tmp_path / "bad.ply"
    bad.write_bytes(b"not a ply")
    with pytest.raises(RuntimeError):
        render_splats.load_ply(bad)


def test_separate_lighting_uniform_scene_is_identity():
    pos = np.random.default_rng(1).uniform(size=(200, 3)).astype(np.float32)
    app = np.full((200, 3), 0.5, dtype=np.float32)
    albedo, irr = render_splats.separate_lighting(pos, app, np.ones(200, dtype=np.float32))
    assert np.allclose(irr, 1.0, atol=1e-3)
    assert np.allclose(albedo, 0.5, atol=1e-3)


@pytest.mark.parametrize("mode", ["relit", "neutral", "albedo"])
def test_render_png_produces_visible_image(synthetic_ply, mode):
    png = render_splats.render_png(width=256, height=256, mode=mode)
    img = Image.open(BytesIO(png))
    assert img.size == (256, 256)
    assert img.mode == "RGBA"
    alpha = np.asarray(img)[:, :, 3]
    assert (alpha > 0).sum() > 20, "expected some splats to be composited"
