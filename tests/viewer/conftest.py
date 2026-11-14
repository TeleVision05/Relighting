"""Fixtures for the browser tests of the WebGL viewer.

Run them with ``python -m pytest -m browser``. They need Chromium for Playwright, installed
once with ``python -m playwright install chromium``. ``RELIGHTING_GL=gpu`` runs them on the
GPU instead of SwiftShader. When a test fails, the last images it captured are written to
``test-results/viewer/`` (CI uploads that folder).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from camera import VIEWS
from harness import ROOT, Viewer, ViewerServer, gl_mode, launch_browser
from splat_scenes import write_all

RESULTS = ROOT / "test-results" / "viewer"


@pytest.fixture(scope="session")
def scene_files(tmp_path_factory) -> dict[str, Path]:
    return write_all(tmp_path_factory.mktemp("scenes"))


@pytest.fixture(scope="session")
def viewer_server(scene_files):
    server = ViewerServer({f"{name}.ply": path for name, path in scene_files.items()})
    yield server
    server.close()


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import Error, sync_playwright

    with sync_playwright() as playwright:
        try:
            chromium = launch_browser(playwright, gl_mode())
        except Error as exc:
            pytest.fail(
                "Headless Chromium for Playwright is not installed or would not start. "
                f"Install it with: python -m playwright install chromium\n({exc})"
            )
        yield chromium
        chromium.close()


_REPORT_KEY = pytest.StashKey()


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    report = yield
    if report.when == "call":
        item.stash[_REPORT_KEY] = report
    return report


@pytest.fixture()
def viewer(browser, request):
    page = Viewer(browser)
    yield page
    report = request.node.stash.get(_REPORT_KEY, None)
    if report is not None and report.failed:
        _save_captures(request.node.name, page.captures)
    page.close()


@pytest.fixture()
def open_scene(viewer, viewer_server):
    """Open a fixture scene from its test camera and check that it loaded cleanly.

    Light markers are switched off: they are an overlay drawn in both panes, and the
    tests are about the splats underneath. The render loop is then paused, because under
    software GL every idle frame costs as much as a capture; captures still render.
    """

    def _open(name: str, cam=None):
        viewer.open(viewer_server.scene_url(f"{name}.ply", cam or VIEWS[name]))
        state = viewer.state()
        assert state and state["loaded"] and state["n"] > 0, f"scene did not load: {viewer.status()[:300]}"
        assert viewer.errors == [], viewer.errors
        viewer.set_checked("showGizmos", False)
        viewer.pause()
        return viewer

    return _open


def _save_captures(test_name: str, captures: dict) -> None:
    from PIL import Image

    RESULTS.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in test_name)
    for label, panes in captures.items():
        for side, img in zip(("baked", "relit"), panes, strict=True):
            out = RESULTS / f"{safe}-{label}-{side}.png"
            Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).save(out)
