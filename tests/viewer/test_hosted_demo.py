"""The hosted demo: the assembled site, served under a sub-path like GitHub Pages does.

GitHub Pages serves a project site at ``/<repository>/``. These tests build the same folder the
Pages workflow publishes, serve it under ``/Relighting/`` from a server that knows nothing
outside that prefix (so an absolute ``/src/...`` URL would 404), and open it the way a visitor
would: no ``?ply=``, from a host name that is not localhost.
"""

import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

import numpy as np
import pytest
from harness import HOSTED_NAME, ROOT, Viewer
from imagestats import covered, crop_common

from static_server import ViewerHTTPServer

sys.path.insert(0, str(ROOT / "demo"))
from assemble_site import assemble  # noqa: E402

pytestmark = pytest.mark.browser

PREFIX = "/Relighting/"


class _SubPathHandler(SimpleHTTPRequestHandler):
    """Serves ``directory`` only under PREFIX, like a Pages project site. No listings."""

    log: list[tuple[str, int]] = []

    def translate_path(self, path):
        path = path.split("?", 1)[0].split("#", 1)[0]
        if not path.startswith(PREFIX):
            return str(Path(self.directory) / "__outside_the_prefix__")
        return super().translate_path("/" + path[len(PREFIX) :])

    def list_directory(self, path):
        self.send_error(404)

    def log_request(self, code="-", size="-"):
        self.log.append((self.path, int(code)))

    def log_message(self, *args):
        pass


class _Site:
    def __init__(self, directory: Path):
        self.log: list[tuple[str, int]] = []
        handler = type("Handler", (_SubPathHandler,), {"log": self.log})
        self.httpd = ViewerHTTPServer(("127.0.0.1", 0), partial(handler, directory=str(directory)))
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        self.url = f"http://{HOSTED_NAME}:{self.httpd.server_address[1]}{PREFIX}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def site(tmp_path):
    assemble(tmp_path / "site")
    server = _Site(tmp_path / "site")
    server.dir = tmp_path / "site"
    yield server
    server.close()


def test_the_site_holds_the_viewer_and_the_demo_scene_only(site):
    names = {p.relative_to(site.dir).as_posix() for p in site.dir.rglob("*") if p.is_file()}
    assert {"index.html", "src/app.js", "src/load-worker.js", "demo/demo-scene.ply", "demo/NOTICE"} <= names
    assert not [n for n in names if n.endswith(".ply") and n != "demo/demo-scene.ply"], names
    assert (site.dir / "demo" / "demo-scene.ply").stat().st_size < 15_000_000


def test_the_demo_scene_loads_by_default_from_a_sub_path_and_renders(browser, site):
    viewer = Viewer(browser)
    try:
        viewer.open(site.url + "?test=1")
        state = viewer.state()
        assert state["loaded"] and state["n"] > 30_000, viewer.status()
        # The only miss is the model picker asking for the optional /models list, which a
        # static host does not have; the browser logs that 404 as a console error.
        assert [r for r in site.log if r[1] >= 400] == [(PREFIX + "models", 404)], site.log
        assert len(viewer.errors) == 1 and "404" in viewer.errors[0], viewer.errors
        viewer.set_checked("showGizmos", False)
        viewer.pause()
        baked, relit = viewer.capture("hosted-demo")
        for name, pane in (("baked", baked), ("relit", relit)):
            assert covered(pane).mean() > 0.25, f"{name} pane is mostly empty"
            assert pane.std() > 0.05, f"{name} pane is flat"
        assert abs(np.subtract(*crop_common(baked, relit))).mean() > 0.01, "relighting changed nothing"
        # Every file came from under the prefix.
        assert site.log, "the server saw no requests"
        assert all(path.startswith(PREFIX) for path, _ in site.log), site.log
        assert any(path.startswith(PREFIX + "demo/demo-scene.ply") for path, _ in site.log)
        assert any("load-worker.js" in path for path, _ in site.log), "the load worker did not run"
    finally:
        viewer.close()


def test_a_missing_demo_scene_gives_a_plain_message(browser, site):
    (site.dir / "demo" / "demo-scene.ply").unlink()
    viewer = Viewer(browser)
    try:
        viewer.open(site.url + "?test=1")
        status = viewer.status()
        assert viewer.page.get_attribute("#status", "data-state") == "error"
        assert "could not be found" in status and "404" not in status, status
        assert viewer.page.is_visible("#notice")
    finally:
        viewer.close()
