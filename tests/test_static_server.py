"""The static file policy: what the servers will and will not hand out."""

import http.client
import json
import os
from functools import partial

import pytest
from synthetic import write_synthetic_ply

import render_server
import serve
import static_server


@pytest.fixture()
def site(tmp_path):
    """A fake repo root with public files, private files and traps."""
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text("[core]\nsecret-remote = https://token@example.invalid/\n")
    (root / ".env").write_text("TOKEN=hunter2\n")
    (root / "index.html").write_text("<html>viewer</html>")
    (root / "notes.txt").write_text("private notes")
    (root / "render_splats.py").write_text("# source")
    write_synthetic_ply(root / "scene.ply", n=4)
    write_synthetic_ply(root / ".hidden.ply", n=4)
    (root / "src").mkdir()
    (root / "src" / "app.js").write_text("export const ok = true;")
    (root / "src" / ".secret.js").write_text("export const secret = 1;")
    (root / "src" / "notes.md").write_text("not a web file")
    (root / "assets").mkdir()
    (root / "assets" / "logo.png").write_bytes(b"\x89PNG")
    (root / "docs").mkdir()
    (root / "docs" / "page.html").write_text("not on the allow-list")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "stolen.ply").write_text("outside the repo")
    os.symlink(outside / "stolen.ply", root / "link-out.ply")
    os.symlink(root / ".git" / "config", root / "link-git.ply")
    os.symlink(outside, root / "src" / "escape")
    return root


@pytest.fixture(params=["viewer", "render"])
def server(request, site, monkeypatch, start_server):
    """Both servers must enforce the same policy."""
    if request.param == "viewer":
        monkeypatch.setattr(serve, "ROOT", site)
        return start_server(serve.ViewerHandler)
    return start_server(partial(render_server.RenderHandler, directory=str(site)))


def fetch(server, raw_path, method="GET"):
    """Send the path exactly as given (http.client does not normalise it)."""
    conn = http.client.HTTPConnection(*server, timeout=10)
    conn.request(method, raw_path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp, body


@pytest.mark.parametrize("path", ["/", "/index.html", "/index.html?x=1"])
def test_serves_the_viewer(server, path):
    resp, body = fetch(server, path)
    assert resp.status == 200
    assert body == b"<html>viewer</html>"
    assert "no-store" in resp.getheader("Cache-Control")


def test_serves_scenes_and_allowed_dirs(server):
    assert fetch(server, "/scene.ply")[0].status == 200
    resp, body = fetch(server, "/src/app.js")
    assert resp.status == 200 and body == b"export const ok = true;"
    assert "javascript" in resp.getheader("Content-Type")
    assert fetch(server, "/assets/logo.png")[0].status == 200


def test_models_lists_only_servable_scenes(server):
    resp, body = fetch(server, "/models")
    assert resp.status == 200
    assert json.loads(body) == ["scene.ply"]  # no dotfile scene, no symlinks that leave the root


@pytest.mark.parametrize(
    "path",
    [
        "/.git/config",
        "/.git/",
        "/.git",
        "/.%67it/config",  # url-encoded 'g'
        "/%2egit/config",
        "/.env",
        "/%2eenv",
        "/.hidden.ply",
        "/src/.secret.js",
        "/src/../.env",
        "/src/%2e%2e/.env",
        "/../etc/passwd",
        "/..%2f..%2fetc/passwd",
        "/%2e%2e/%2e%2e/etc/passwd",
        "//etc/passwd",
        "/src\\..\\.env",
        "/notes.txt",
        "/render_splats.py",
        "/docs/page.html",
        "/src/notes.md",
        "/src/",
        "/src",
        "/assets/",
        "/link-out.ply",
        "/link-git.ply",
        "/src/escape/stolen.ply",
        "/index.html%00.png",
    ],
)
def test_refuses_everything_else(server, path):
    resp, body = fetch(server, path)
    assert resp.status == 404, path
    message = json.loads(body)["error"]
    assert "not shared by this server" in message
    for leaked in (b"secret-remote", b"hunter2", b"private notes", b"# source", b"outside the repo"):
        assert leaked not in body


def test_head_does_not_leak_either(server):
    assert fetch(server, "/.git/config", "HEAD")[0].status == 404
    assert fetch(server, "/index.html", "HEAD")[0].status == 200


def test_unsupported_methods_get_a_plain_answer(server):
    resp, body = fetch(server, "/index.html", "POST")
    assert resp.status == 501
    message = json.loads(body)["error"]
    assert "only supports opening pages and files" in message
    assert "Python" not in message and "501" not in message


def test_server_header_hides_python_version(server):
    resp, _ = fetch(server, "/index.html")
    assert "Python" not in (resp.getheader("Server") or "")


def test_resolve_public_file_unit(site):
    assert static_server.resolve_public_file(site, "/index.html") == (site / "index.html").resolve()
    assert static_server.resolve_public_file(site, "/missing.ply") is None
    assert static_server.resolve_public_file(site, "/.git/config") is None
