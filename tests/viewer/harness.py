"""Drive the real viewer (index.html) in headless Chromium, for the tests and the timing probe.

* ``ViewerServer`` serves the repository root through the same allow-list handler as
  ``serve.py``, plus extra scene files under ``/__fixtures__/<name>`` (test-only).
* ``launch_browser`` starts headless Chromium with software GL (SwiftShader) or the GPU.
* ``Viewer`` opens one scene with ``?test=1&cam=...`` and talks to ``window.__relightTest``.

Nothing here opens a window: Chromium always runs headless.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit

from camera import Camera
from imagestats import decode_pane

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # the timing probe runs as a script, outside pytest's pythonpath
    sys.path.insert(0, str(ROOT))

from static_server import SafeStaticHandler, ViewerHTTPServer  # noqa: E402

FIXTURE_PREFIX = "/__fixtures__/"
# Two panes of about 498 x 720 beside the 300 px sidebar. The page's flex layout always
# makes the left pane 1 px wider than the right, so compare across panes with crop_common().
VIEWPORT = {"width": 1300, "height": 720}

# A hostname that is not "localhost" but still reaches the test server, so tests can open the
# viewer the way a hosted copy (GitHub Pages) is opened: no cache-busting query strings.
HOSTED_NAME = "relighting.test"
HOST_ARGS = [f"--host-resolver-rules=MAP {HOSTED_NAME} 127.0.0.1"]

# SwiftShader is Chromium's CPU implementation of GL; it gives the same answer on any machine.
GL_ARGS = {
    "software": ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
    "gpu": ["--enable-gpu", "--ignore-gpu-blocklist"] + (["--use-angle=metal"] if sys.platform == "darwin" else []),
}


def gl_mode() -> str:
    """GL backend for the tests: ``RELIGHTING_GL=software`` (default) or ``gpu``."""
    mode = os.environ.get("RELIGHTING_GL", "software")
    if mode not in GL_ARGS:
        raise ValueError(f"RELIGHTING_GL must be one of {sorted(GL_ARGS)}, not {mode!r}")
    return mode


def launch_browser(playwright, mode: str):
    return playwright.chromium.launch(headless=True, args=GL_ARGS[mode] + HOST_ARGS)


class _FixtureHandler(SafeStaticHandler):
    fixtures: dict[str, Path] = {}
    requests: list[str] = []  # every fixture request line, query string included

    def send_head(self):
        path = urlsplit(self.path).path
        if path.startswith(FIXTURE_PREFIX):
            self.requests.append(self.path)
            target = self.fixtures.get(path[len(FIXTURE_PREFIX) :])
            if target is None:
                self.send_message(404, "No such test scene.")
                return None
            self._target = target
            return SimpleHTTPRequestHandler.send_head(self)
        return super().send_head()


class ViewerServer:
    """The repository root on a free 127.0.0.1 port, plus named fixture files."""

    def __init__(self, fixtures: dict[str, Path]):
        self.requests: list[str] = []
        handler = type("Handler", (_FixtureHandler,), {"fixtures": dict(fixtures), "requests": self.requests})

        def make(*args, **kwargs):
            return handler(*args, directory=str(ROOT), **kwargs)

        self.httpd = ViewerHTTPServer(("127.0.0.1", 0), make)
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        host, port = self.httpd.server_address[:2]
        self.base_url = f"http://{host}:{port}"

    def scene_url(self, name: str, cam: Camera, hosted: bool = False) -> str:
        """The viewer on one fixture scene. ``hosted`` opens it under HOSTED_NAME instead of 127.0.0.1."""
        base = self.base_url.replace("127.0.0.1", HOSTED_NAME) if hosted else self.base_url
        return f"{base}/index.html?test=1&cam={cam.param}&ply={FIXTURE_PREFIX}{name}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


_SETTLED_OR_FAILED_JS = """() => {
  if (window.__relightTest && window.__relightTest.state().settled) return true;
  const status = document.querySelector('#status');
  return !!status && status.dataset.state === 'error';
}"""


class Viewer:
    """One viewer page. Collects console errors and uncaught exceptions as it goes."""

    def __init__(self, browser):
        self.context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        self.page = self.context.new_page()
        self.errors: list[str] = []
        self.captures: dict[str, object] = {}  # last images, saved by conftest if a test fails
        self.page.on("console", lambda m: m.type == "error" and self.errors.append(f"console: {m.text}"))
        self.page.on("pageerror", lambda e: self.errors.append(f"uncaught: {e}"))

    def open(self, url: str, timeout_ms: int = 60_000) -> float:
        """Load the page and wait until the scene is drawn with a finished sort, or the viewer
        reports an error (status data-state="error": a shader that will not compile, a bad file).
        Returns seconds."""
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        t0 = time.perf_counter()
        self.page.goto(url)
        try:
            self.page.wait_for_function(_SETTLED_OR_FAILED_JS, timeout=timeout_ms)
        except PlaywrightTimeout:
            raise AssertionError(
                f"viewer did not settle in {timeout_ms} ms: state={self.state()} "
                f"status={self.status()!r} errors={self.errors}"
            ) from None
        return time.perf_counter() - t0

    def pause(self, on: bool = True) -> None:
        """Stop the viewer's render loop; ``capture`` still renders. Keeps software GL fast."""
        self.page.evaluate("(on) => window.__relightTest.pause(on)", on)

    def state(self) -> dict | None:
        """The viewer's test state, or None if it stopped before installing the test handle."""
        return self.page.evaluate("() => (window.__relightTest ? window.__relightTest.state() : null)")

    def status(self) -> str:
        return self.page.inner_text("#status")

    def renderer(self) -> str:
        return self.page.evaluate("() => window.__relightTest.renderer()")

    def capture(self, label: str = "capture"):
        """Render both panes now and return (baked, relit) as float RGB arrays."""
        left, right = (decode_pane(p) for p in self.page.evaluate("() => window.__relightTest.capture()"))
        self.captures[label] = (left, right)
        return left, right

    # -- controls, set the way a person would leave them ---------------------------------
    def set_value(self, element_id: str, value) -> None:
        self.page.eval_on_selector(f"#{element_id}", "(el, v) => { el.value = String(v); }", value)

    def set_checked(self, element_id: str, on: bool) -> None:
        self.page.set_checked(f"#{element_id}", on)

    def set_gbuffer(self, mode: int) -> None:
        self.page.select_option("#gbuf", str(mode))

    def clear_lights(self) -> None:
        self.page.click("#clearLights")

    def add_light(self, kind: str = "point", **props) -> None:
        """Add a light with the sidebar button, then set its controls (x, y, z, range, ...)."""
        self.page.click(f"[data-add='{kind}']")
        self.set_light(-1, **props)

    def set_light(self, index: int, **props) -> None:
        classes = {"x": "lx", "y": "ly", "z": "lz", "range": "lrange", "intensity": "lint"}
        classes.update({"az": "laz", "el": "lel", "color": "lcol"})
        values = {classes[k]: v for k, v in props.items()}
        self.page.evaluate(
            """([index, values]) => {
                const all = document.querySelectorAll('#lightList .light');
                const el = all[index < 0 ? all.length + index : index];
                for (const [cls, v] of Object.entries(values)) el.querySelector('.' + cls).value = String(v);
            }""",
            [index, values],
        )

    def close(self) -> None:
        self.context.close()
