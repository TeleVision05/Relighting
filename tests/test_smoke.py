"""Headless smoke tests: render a tiny synthetic splat set, no big .ply files needed."""
import json
import threading
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import render_splats
import serve

PROPS = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
         "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]


def write_synthetic_ply(path: Path, n: int = 1500, seed: int = 0) -> None:
    """Write a binary little-endian 3DGS-style PLY: splats on a unit sphere."""
    rng = np.random.default_rng(seed)
    pts = rng.normal(size=(n, 3)).astype(np.float32)
    pts /= np.linalg.norm(pts, axis=1, keepdims=True)
    data = np.zeros((n, len(PROPS)), dtype="<f4")
    data[:, 0:3] = pts
    data[:, 3:6] = rng.uniform(-1.0, 1.0, size=(n, 3))  # SH DC colour
    data[:, 6] = 4.0                                    # logit opacity -> ~0.98
    data[:, 7:10] = [1.6, 1.6, -3.0]                    # flat disc, normal = axis 2
    data[:, 13] = 1.0                                   # identity quaternion (x,y,z,w)
    header = "ply\nformat binary_little_endian 1.0\n"
    header += f"element vertex {n}\n"
    header += "".join(f"property float {p}\n" for p in PROPS)
    header += "end_header\n"
    path.write_bytes(header.encode() + data.tobytes())


@pytest.fixture()
def synthetic_ply(tmp_path, monkeypatch):
    ply = tmp_path / "synthetic.ply"
    write_synthetic_ply(ply)
    monkeypatch.setattr(render_splats, "PLY_PATH", ply)
    render_splats.invalidate_ply_cache()
    yield ply
    render_splats.invalidate_ply_cache()


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


def _serve(handler):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def test_render_server_models_and_render(synthetic_ply):
    handler = partial(render_splats.RenderHandler, directory=str(synthetic_ply.parent))
    httpd, base = _serve(handler)
    try:
        with urllib.request.urlopen(f"{base}/models", timeout=10) as r:
            assert json.loads(r.read()) == ["synthetic.ply"]
        with urllib.request.urlopen(f"{base}/render?mode=neutral&w=64&h=64", timeout=60) as r:
            assert r.headers["Content-Type"] == "image/png"
            assert Image.open(BytesIO(r.read())).size == (64, 64)
    finally:
        httpd.shutdown()


def test_static_viewer_server_lists_models(tmp_path, monkeypatch):
    write_synthetic_ply(tmp_path / "a.ply", n=4)
    (tmp_path / "index.html").write_text("<html></html>")
    monkeypatch.setattr(serve, "ROOT", tmp_path)
    httpd, base = _serve(serve.ViewerHandler)
    try:
        with urllib.request.urlopen(f"{base}/models", timeout=10) as r:
            assert json.loads(r.read()) == ["a.ply"]
        with urllib.request.urlopen(f"{base}/index.html", timeout=10) as r:
            assert "no-store" in r.headers["Cache-Control"]
    finally:
        httpd.shutdown()
