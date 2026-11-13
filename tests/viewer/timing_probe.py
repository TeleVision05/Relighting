"""Print how long the viewer takes to load, preprocess and draw scenes. Prints; asserts nothing.

    python tests/viewer/timing_probe.py                    # the synthetic test scenes
    python tests/viewer/timing_probe.py --ply PATH ...     # plus real scenes, e.g. Buttons.ply
    python tests/viewer/timing_probe.py --gl software      # auto (default), gpu or software

``auto`` tries the GPU first and falls back to software GL (SwiftShader). Every row names
the GL renderer it came from, because the two differ by an order of magnitude.

Columns:
  fetch       request start to last byte of the .ply, from the browser's resource timing
  preprocess  last byte to "Loaded": PLY parse, normals, albedo split, packing, GPU upload
  ready       page navigation until the first depth sort is drawn (wall clock)
  frame       mean interval between the viewer's own animation frames over about 2 s
  draw        mean time to render both panes once and wait for the GPU, loop paused
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from camera import VIEWS
from harness import Viewer, ViewerServer, launch_browser
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
from splat_scenes import write_all

FRAME_INTERVAL_JS = """async () => {
  const t0 = performance.now();
  let frames = 0;
  await new Promise((done) => {
    const tick = () => {
      frames++;
      if (performance.now() - t0 < 2000 || frames < 3) requestAnimationFrame(tick);
      else done();
    };
    requestAnimationFrame(tick);
  });
  return (performance.now() - t0) / frames;
}"""

FETCH_END_JS = """() => {
  const e = performance.getEntriesByType('resource').filter((r) => r.name.includes('.ply'));
  const last = e[e.length - 1];
  return last ? { start: last.startTime, end: last.responseEnd } : null;
}"""


def is_real_ply(path: Path) -> bool:
    """False for a missing file or a Git LFS pointer that was never downloaded."""
    try:
        with path.open("rb") as f:
            return f.read(4) == b"ply\n"
    except OSError:
        return False


def measure(viewer: Viewer, url: str) -> dict:
    ready_s = viewer.open(url, timeout_ms=600_000)
    state = viewer.state()
    fetch = viewer.page.evaluate(FETCH_END_JS)
    loaded = state["loadTimes"]
    frame_ms = viewer.page.evaluate(FRAME_INTERVAL_JS)
    viewer.pause()
    draw_ms = viewer.page.evaluate("(n) => window.__relightTest.renderMs(n)", 3 if state["n"] > 50_000 else 10)
    return {
        "splats": state["n"],
        "fetch_ms": fetch["end"] - fetch["start"],
        "preprocess_ms": loaded["end"] - fetch["end"],
        "ready_s": ready_s,
        "frame_ms": frame_ms,
        "draw_ms": draw_ms,
        "errors": list(viewer.errors),
    }


def renderer_kind(renderer: str) -> str:
    return "software" if "swiftshader" in renderer.lower() else "gpu"


def run_mode(playwright, mode: str, server: ViewerServer, scenes: dict[str, Path]) -> list[dict]:
    browser = launch_browser(playwright, mode)
    rows = []
    try:
        for name, path in scenes.items():
            viewer = Viewer(browser)
            try:
                cam = VIEWS.get(Path(name).stem)
                url = f"{server.base_url}/index.html?test=1&ply=/__fixtures__/{name}"
                url += f"&cam={cam.param}" if cam else ""
                row = measure(viewer, url)
                row.update(scene=name, mb=path.stat().st_size / 1e6, renderer=viewer.renderer())
                rows.append(row)
            finally:
                viewer.close()
    finally:
        browser.close()
    return rows


def print_rows(rows: list[dict]) -> None:
    head = f"{'gl':9} {'scene':16} {'splats':>8} {'MB':>6} {'fetch':>9} {'preprocess':>11} {'ready':>8} {'frame':>9} {'draw':>9}"
    print(head)
    for r in rows:
        print(
            f"{renderer_kind(r['renderer']):9} {r['scene']:16} {r['splats']:>8,} {r['mb']:>6.1f} "
            f"{r['fetch_ms']:>7.0f}ms {r['preprocess_ms']:>9.0f}ms {r['ready_s']:>7.2f}s "
            f"{r['frame_ms']:>7.1f}ms {r['draw_ms']:>7.1f}ms"
        )
        if r["errors"]:
            print(f"          page errors: {r['errors']}")
    for renderer in sorted({r["renderer"] for r in rows}):
        print(f"renderer ({renderer_kind(renderer)}): {renderer}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ply", type=Path, action="append", default=[], help="a real scene to time as well")
    parser.add_argument("--gl", choices=["auto", "gpu", "software"], default="auto")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        scenes = {f"{k}.ply": v for k, v in write_all(Path(tmp)).items()}
        for path in args.ply:
            if not is_real_ply(path):
                print(f"Skipping {path}: not a .ply file (missing, or a Git LFS pointer; run git lfs pull).")
                continue
            scenes[path.name] = path
        server = ViewerServer(scenes)
        try:
            with sync_playwright() as playwright:
                rows = timed_rows(playwright, args.gl, server, scenes)
        finally:
            server.close()
    print_rows(rows)
    return 0


def timed_rows(playwright, gl: str, server: ViewerServer, scenes: dict[str, Path]) -> list[dict]:
    if gl != "auto":
        return run_mode(playwright, gl, server, scenes)
    try:
        rows = run_mode(playwright, "gpu", server, scenes)
        if rows and renderer_kind(rows[0]["renderer"]) == "gpu":
            return rows
        print("No GPU-backed WebGL in headless Chromium here; timing software GL instead.")
    except PlaywrightError as exc:
        print(f"GPU-backed headless Chromium failed ({str(exc).splitlines()[0]}); timing software GL instead.")
    return run_mode(playwright, "software", server, scenes)


if __name__ == "__main__":
    raise SystemExit(main())
