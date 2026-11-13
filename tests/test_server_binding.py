"""Where the servers listen: loopback by default, wider only when asked."""

import socket

import pytest

import render_server
import render_splats
import serve
import static_server


class _Recorder:
    """Stands in for bind_server: records the address and stops the server from starting."""

    def __init__(self):
        self.calls = []

    def __call__(self, handler, host, port):
        self.calls.append((host, port))
        raise static_server.ServerStartError("stopped by test")


@pytest.fixture()
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(serve, "bind_server", rec)
    monkeypatch.setattr(render_server, "bind_server", rec)
    return rec


def test_default_host_is_loopback():
    assert static_server.DEFAULT_HOST == "127.0.0.1"


def test_bind_server_really_listens_on_loopback_only():
    httpd = static_server.bind_server(serve.ViewerHandler, static_server.DEFAULT_HOST, 0)
    try:
        assert httpd.server_address[0] == "127.0.0.1"
    finally:
        httpd.server_close()


def test_viewer_server_defaults_to_loopback(recorder):
    assert serve.main(["--no-browser"]) == 1
    assert recorder.calls == [("127.0.0.1", 8000)]


def test_viewer_server_host_flag_widens(recorder):
    serve.main(["9000", "--host", "0.0.0.0", "--no-browser"])
    assert recorder.calls == [("0.0.0.0", 9000)]


def test_render_server_defaults_to_loopback(recorder):
    assert render_server.main([]) == 1
    assert recorder.calls == [("127.0.0.1", 8000)]


def test_render_splats_serve_flag_defaults_to_loopback(recorder):
    assert render_splats.main(["--serve", "--port", "8123"]) == 1
    assert recorder.calls == [("127.0.0.1", 8123)]


def test_render_splats_host_flag_widens(recorder):
    render_splats.main(["--serve", "--host", "0.0.0.0"])
    assert recorder.calls == [("0.0.0.0", 8000)]


def test_widening_prints_a_warning(monkeypatch, capsys):
    class _FakeServer:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def serve_forever(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(serve, "bind_server", lambda handler, host, port: _FakeServer())
    serve.main(["--host", "0.0.0.0", "--no-browser"])
    assert "WARNING" in capsys.readouterr().out
    serve.main(["--no-browser"])
    assert "WARNING" not in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["0", "70000", "-1", "abc", "80.5"])
def test_bad_port_is_a_plain_message(bad, capsys):
    with pytest.raises(SystemExit):
        serve.main([bad, "--no-browser"])
    err = capsys.readouterr().err
    assert "is not a valid port" in err
    assert "Traceback" not in err


def test_port_in_use_is_a_plain_message(capsys):
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen(1)
    try:
        code = serve.main([str(busy.getsockname()[1]), "--no-browser"])
    finally:
        busy.close()
    err = capsys.readouterr().err
    assert code == 1
    assert "Try a different port" in err
    assert "Errno" not in err and "Traceback" not in err
