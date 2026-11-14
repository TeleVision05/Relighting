import threading
from http.server import ThreadingHTTPServer

import pytest
from synthetic import write_synthetic_ply

import render_splats


@pytest.fixture()
def synthetic_ply(tmp_path, monkeypatch):
    ply = tmp_path / "synthetic.ply"
    write_synthetic_ply(ply)
    monkeypatch.setattr(render_splats, "PLY_PATH", ply)
    render_splats.invalidate_ply_cache()
    yield ply
    render_splats.invalidate_ply_cache()


@pytest.fixture()
def start_server():
    """Start a handler on a free 127.0.0.1 port; returns (host, port). Stopped after the test."""
    servers = []

    def _start(handler):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        servers.append(httpd)
        return httpd.server_address

    yield _start
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()
