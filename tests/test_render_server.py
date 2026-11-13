"""GET /render over HTTP: validation answers 400, failures answer plain messages, load is capped."""

import json
import threading
import urllib.error
import urllib.request
from functools import partial
from io import BytesIO

import pytest
from PIL import Image

import render_server
import render_splats

JARGON = ("Traceback", "ValueError", "RuntimeError", "Exception", "numpy", ".py", "line ")


@pytest.fixture()
def base(synthetic_ply, start_server):
    host, port = start_server(partial(render_server.RenderHandler, directory=str(synthetic_ply.parent)))
    return f"http://{host}:{port}"


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read()


def error_of(body: bytes) -> str:
    return json.loads(body)["error"]


@pytest.fixture()
def render_calls(monkeypatch):
    """Counts calls to the real renderer so tests can prove bad input never reaches it."""
    calls = []
    real = render_splats.render_png

    def counting(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(render_splats, "render_png", counting)
    return calls


def test_models_and_render(base):
    status, _, body = get(f"{base}/models")
    assert status == 200 and json.loads(body) == ["synthetic.ply"]
    status, headers, body = get(f"{base}/render?mode=neutral&w=64&h=64")
    assert status == 200
    assert headers["Content-Type"] == "image/png"
    assert Image.open(BytesIO(body)).size == (64, 64)


def test_cache_buster_and_defaults_work(base, render_calls):
    status, _, _ = get(f"{base}/render?w=16&h=16&_=1699999999")
    assert status == 200
    assert render_calls[0]["stride"] == 1 and render_calls[0]["mode"] == "relit"


@pytest.mark.parametrize(
    "query, expect",
    [
        ("w=abc", "Image width (w) must be a whole number between 16 and 2048"),
        ("w=5000", "between 16 and 2048"),
        ("h=-5", "Image height (h)"),
        ("w=64.5", "whole number"),
        ("stride=0", "Stride"),
        ("mode=sepia", "must be one of: relit, neutral, albedo, normals"),
        ("zoom=0", "Camera distance (zoom) must be a number between 1 and 50"),
        ("roughness=nan", "Roughness (roughness) must be a number between 0 and 1"),
        ("metallic=2", "Metallic"),
        ("dirX=1e999", "Directional light X"),
        ("pointInt=-1", "Point light intensity"),
        ("bogus=1", "Unknown setting 'bogus'"),
        ("w=64&w=65", "more than once"),
    ],
)
def test_bad_input_is_a_400_with_a_plain_message_and_no_render(base, render_calls, query, expect):
    status, headers, body = get(f"{base}/render?{query}")
    assert status == 400
    assert headers["Content-Type"] == "application/json"
    message = error_of(body)
    assert expect in message
    assert not any(word in message for word in JARGON)
    assert render_calls == [], "invalid input must be rejected before any rendering starts"


def test_server_survives_bad_requests(base):
    for _ in range(3):
        assert get(f"{base}/render?w=abc")[0] == 400
    assert get(f"{base}/render?w=32&h=32")[0] == 200


def test_busy_renderer_answers_503(base, render_calls, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    slots.acquire()  # the only slot is taken by "another render"
    monkeypatch.setattr(render_server, "_render_slots", slots)
    status, headers, body = get(f"{base}/render?w=16&h=16")
    assert status == 503
    assert headers["Retry-After"]
    assert error_of(body) == render_server.BUSY_MESSAGE
    assert render_calls == []


def test_concurrent_renders_are_capped(base, monkeypatch):
    assert render_server.MAX_CONCURRENT_RENDERS >= 1
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(render_server, "_render_slots", threading.BoundedSemaphore(1))

    def slow(**kwargs):
        entered.set()
        release.wait(30)
        return b"\x89PNG"

    monkeypatch.setattr(render_splats, "render_png", slow)
    first = threading.Thread(target=get, args=(f"{base}/render?w=16&h=16",))
    first.start()
    try:
        assert entered.wait(10)
        assert get(f"{base}/render?w=16&h=16")[0] == 503
    finally:
        release.set()
        first.join(10)
    assert get(f"{base}/render?w=16&h=16")[0] == 200  # slot was released


@pytest.mark.parametrize(
    "exc, status, message",
    [
        (render_splats.RenderTimeoutError("render took 300s in render_splats.py"), 504, render_server.TIMEOUT_MESSAGE),
        (RuntimeError("Unable to find end_header in PLY"), 500, render_server.SCENE_MESSAGE),
        (FileNotFoundError("/some/private/path.ply"), 500, render_server.SCENE_MESSAGE),
        (ZeroDivisionError("boom"), 500, render_server.RENDER_FAILED_MESSAGE),
    ],
)
def test_render_failures_are_plain_and_release_the_slot(base, monkeypatch, exc, status, message):
    def fail(**kwargs):
        raise exc

    monkeypatch.setattr(render_splats, "render_png", fail)
    code, _, body = get(f"{base}/render?w=16&h=16")
    assert code == status
    assert error_of(body) == message
    assert str(exc) not in body.decode()
    for _ in range(render_server.MAX_CONCURRENT_RENDERS):  # every slot is free again
        assert render_server._render_slots.acquire(blocking=False)
    for _ in range(render_server.MAX_CONCURRENT_RENDERS):
        render_server._render_slots.release()


def test_missing_scene_gives_the_scene_message(base, monkeypatch, tmp_path):
    monkeypatch.setattr(render_splats, "PLY_PATH", tmp_path / "gone.ply")
    render_splats.invalidate_ply_cache()
    code, _, body = get(f"{base}/render?w=16&h=16")
    assert code == 500
    assert error_of(body) == render_server.SCENE_MESSAGE
    assert "gone.ply" not in body.decode()


def test_reload_clears_a_failed_load(base, synthetic_ply, monkeypatch, tmp_path):
    monkeypatch.setattr(render_splats, "PLY_PATH", tmp_path / "gone.ply")
    render_splats.invalidate_ply_cache()
    assert get(f"{base}/render?w=16&h=16")[0] == 500
    monkeypatch.setattr(render_splats, "PLY_PATH", synthetic_ply)
    status, _, body = get(f"{base}/reload")
    assert status == 200 and json.loads(body)["ok"] is True
    assert get(f"{base}/render?w=16&h=16")[0] == 200
