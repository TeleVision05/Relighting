"""How a scene loads: off the main thread, with a progress bar, and a fallback without workers."""

import pytest
from camera import VIEWS

pytestmark = pytest.mark.browser

# Installed before the page runs: records every state the progress bar shows.
RECORD_PROGRESS_JS = """
window.__progress = [];
new MutationObserver(() => {
  const bar = document.getElementById('loadBar');
  if (bar) window.__progress.push(bar.hidden ? null : Number(bar.getAttribute('aria-valuenow')));
}).observe(document, { subtree: true, attributes: true, attributeFilter: ['hidden', 'aria-valuenow'] });
"""

# Makes `new Worker(...)` fail for the load worker only, as in a browser without module workers.
NO_LOAD_WORKER_JS = """
const RealWorker = window.Worker;
window.Worker = function (url, options) {
  if (String(url).includes('load-worker')) throw new TypeError('module workers are not supported');
  return new RealWorker(url, options);
};
"""


def test_progress_bar_climbs_through_the_load_and_hides_when_done(viewer, viewer_server):
    viewer.page.add_init_script(RECORD_PROGRESS_JS)
    viewer.open(viewer_server.scene_url("sphere.ply", VIEWS["sphere"]))
    seen = viewer.page.evaluate("window.__progress")
    shown = [v for v in seen if v is not None]
    assert shown, f"the progress bar never showed: {seen}"
    assert shown == sorted(shown), f"progress went backwards: {shown}"
    assert shown[-1] >= 90, f"progress stopped at {shown[-1]}%"
    assert seen[-1] is None, "the progress bar is still showing after the load"
    assert viewer.page.is_hidden("#loadBar")
    assert viewer.errors == [], viewer.errors


def test_scene_loads_on_the_main_thread_when_the_load_worker_is_unavailable(viewer, viewer_server):
    viewer.page.add_init_script(NO_LOAD_WORKER_JS)
    viewer.open(viewer_server.scene_url("plane.ply", VIEWS["plane"]))
    state = viewer.state()
    assert state["loaded"] and state["n"] == 3136, viewer.status()
    assert viewer.errors == [], viewer.errors
    baked, relit = viewer.capture()
    assert baked.std() > 0.01 and relit.std() > 0.01, "a pane is blank"


def test_load_times_split_download_from_preprocessing(open_scene):
    times = open_scene("plane").state()["loadTimes"]
    assert times["start"] <= times["fetched"] <= times["end"], times
