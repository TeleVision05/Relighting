"""What the viewer says when something fails: plain language on screen, raw detail in the console.

Each known failure is provoked for real (a missing file, a file that is not a splat PLY, a Git
LFS placeholder) or by breaking one browser API before the page runs (no WebGL2, a shader that
will not compile, memory running out). The text a person sees must be exactly the message for
that failure in src/errors.js, and must not carry the raw error.
"""

import pytest
from camera import VIEWS
from harness import FIXTURE_PREFIX, ViewerServer

pytestmark = pytest.mark.browser

LOAD_WAIT_MS = 180_000

# Words that only ever come from raw errors, never from the plain-language messages.
RAW = ("HTTP", "404", "Error", "end_header", "Shader compile", "RangeError", "undefined", "0x")

BAD_FILES = {
    "text.ply": b"this is a text file, not a scene\n",
    "ascii.ply": b"ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nend_header\n0.5\n",
    "truncated.ply": (
        b"ply\nformat binary_little_endian 1.0\nelement vertex 1000\nproperty float x\n"
        b"property float y\nproperty float z\nend_header\n"
    ),
    "lfs.ply": b"version https://git-lfs.github.com/spec/v1\noid sha256:0123abcd\nsize 40996578\n",
}

NO_WEBGL2_JS = """
const realGetContext = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function (type, ...rest) {
  return type === 'webgl2' ? null : realGetContext.call(this, type, ...rest);
};
"""

SHADER_FAILS_JS = """
const realParam = WebGL2RenderingContext.prototype.getShaderParameter;
WebGL2RenderingContext.prototype.getShaderParameter = function (shader, pname) {
  return pname === this.COMPILE_STATUS ? false : realParam.call(this, shader, pname);
};
"""

ALLOCATION_FAILS_JS = """
WebGL2RenderingContext.prototype.texImage2D = function () {
  throw new RangeError('Array buffer allocation failed');
};
"""

GL_OUT_OF_MEMORY_JS = """
const realTexImage2D = WebGL2RenderingContext.prototype.texImage2D;
WebGL2RenderingContext.prototype.texImage2D = function (...args) {
  realTexImage2D.apply(this, args);
  this.__oom = true;
};
const realGetError = WebGL2RenderingContext.prototype.getError;
WebGL2RenderingContext.prototype.getError = function () {
  if (this.__oom) { this.__oom = false; return this.OUT_OF_MEMORY; }
  return realGetError.call(this);
};
"""


@pytest.fixture(scope="module")
def bad_server(tmp_path_factory, scene_files):
    folder = tmp_path_factory.mktemp("bad")
    fixtures = {f"{k}.ply": v for k, v in scene_files.items()}
    for name, data in BAD_FILES.items():
        (folder / name).write_bytes(data)
        fixtures[name] = folder / name
    server = ViewerServer(fixtures)
    yield server
    server.close()


def messages(viewer) -> dict:
    return viewer.page.evaluate("async () => (await import('./src/errors.js')).MESSAGES")


def notice(viewer) -> str | None:
    """The text of the card over the panes, or None when it is hidden."""
    if viewer.page.is_hidden("#notice"):
        return None
    return viewer.page.inner_text("#notice p")


def assert_shows(viewer, kind: str, console_has: str, over_panes: bool = True) -> None:
    expected = messages(viewer)[kind]
    status = viewer.status()
    assert status == expected, f"status: {status!r}"
    assert viewer.page.get_attribute("#status", "data-state") == "error"
    assert not [w for w in RAW if w in status], status
    assert notice(viewer) == (expected if over_panes else None)
    assert any(console_has in e for e in viewer.errors), f"raw detail not logged: {viewer.errors}"


@pytest.mark.parametrize(
    ("scene", "kind", "detail"),
    [
        ("missing.ply", "not-found", "404"),
        ("text.ply", "unsupported-ply", "end_header"),
        ("ascii.ply", "unsupported-ply", "ASCII"),
        ("truncated.ply", "unsupported-ply", "No complete vertex records"),
        ("lfs.ply", "lfs-pointer", "LFS"),
    ],
)
def test_a_bad_scene_file_gets_a_plain_message(viewer, bad_server, scene, kind, detail):
    viewer.open(bad_server.scene_url(scene, VIEWS["plane"]))
    assert_shows(viewer, kind, detail)


@pytest.mark.parametrize(
    ("script", "kind", "detail"),
    [
        (NO_WEBGL2_JS, "webgl2", "WebGL2 not available"),
        (SHADER_FAILS_JS, "shader", "Shader compile"),
        (ALLOCATION_FAILS_JS, "out-of-memory", "Array buffer allocation failed"),
        (GL_OUT_OF_MEMORY_JS, "out-of-memory", "OUT_OF_MEMORY"),
    ],
    ids=["no-webgl2", "shader-fails", "allocation-fails", "gl-out-of-memory"],
)
def test_a_browser_failure_gets_a_plain_message(viewer, bad_server, script, kind, detail):
    viewer.page.add_init_script(script)
    viewer.open(bad_server.scene_url("plane.ply", VIEWS["plane"]))
    assert_shows(viewer, kind, detail)


def test_modules_that_cannot_load_get_a_plain_message(viewer, bad_server):
    viewer.page.route("**/src/ui.js", lambda route: route.abort())
    viewer.open(bad_server.scene_url("plane.ply", VIEWS["plane"]))
    expected = "The viewer could not start. Reload the page to try again."
    assert viewer.status() == expected
    assert notice(viewer) == expected


def test_a_failed_load_keeps_the_scene_on_screen_and_reload_recovers(viewer, bad_server):
    viewer.open(bad_server.scene_url("plane.ply", VIEWS["plane"]))
    # Under software GL on a busy machine every drawn frame can starve the page, and the waits
    # below poll on animation frames; stop the render loop (loads and the status line still run)
    # and poll on a timer, with generous timeouts. What is asserted afterwards is unchanged.
    viewer.pause()
    viewer.page.fill("#plyPath", bad_server.fixture_path("missing.ply"))
    viewer.page.click("#reloadBtn")
    viewer.page.wait_for_function(
        "() => document.querySelector('#status').dataset.state === 'error'", timeout=LOAD_WAIT_MS, polling=200
    )
    # The plane is still loaded, so the message stays in the status line, off the panes.
    assert_shows(viewer, "not-found", "404", over_panes=False)
    assert viewer.state()["n"] == 3136

    viewer.page.fill("#plyPath", bad_server.fixture_path("sphere.ply"))
    viewer.page.click("#reloadBtn")
    viewer.page.wait_for_function("() => window.__relightTest.state().n === 4000", timeout=LOAD_WAIT_MS, polling=200)
    viewer.page.wait_for_function(
        "() => document.querySelector('#status').dataset.state === 'ok'", timeout=LOAD_WAIT_MS, polling=200
    )
    assert viewer.page.get_attribute("#status", "data-state") == "ok"
    assert notice(viewer) is None


def test_cache_busting_query_strings_only_on_localhost(viewer, viewer_server, browser):
    viewer.open(viewer_server.scene_url("plane.ply", VIEWS["plane"]))
    assert viewer.errors == [], viewer.errors
    local = viewer_server.requests[-1]
    assert local.startswith(FIXTURE_PREFIX + "plane.ply?_="), local

    hosted = type(viewer)(browser)
    try:
        hosted.open(viewer_server.scene_url("plane.ply", VIEWS["plane"], hosted=True))
        assert hosted.state()["n"] == 3136, hosted.status()
        assert hosted.errors == [], hosted.errors
        assert viewer_server.requests[-1] == FIXTURE_PREFIX + "plane.ply"
    finally:
        hosted.close()
