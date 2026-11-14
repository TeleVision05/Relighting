"""Record the README hero clip and the portfolio media with headless Chromium. No window opens.

    python tools/record_hero.py OUT_DIR [--gl gpu|software]

The page is driven like a visitor would: the scripted orbit is a real mouse drag on the canvas,
the light is a point light whose position fields are moved a little each frame, and the
G-buffer menu is switched. Frames are screenshots taken one by one, so the clip is a smooth
30 fps however slow the machine is. ffmpeg (H.264, yuv420p) turns them into the clips.

Writes into OUT_DIR: ``hero.mp4`` (1280x720, 30 fps, 12 s), ``hero-poster.jpg`` and three still
frames ``still-1.jpg`` to ``still-3.jpg``.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "viewer"))

from harness import Viewer, ViewerServer, launch_browser  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

FPS = 30
SIZE = {"width": 1280, "height": 720}
# Seconds: orbit with the studio lights, light sweep, then the three G-buffer views.
ORBIT_S, SWEEP_S, VIEWS_S = 4, 4, 4
START_CAM = (3.14, 0.1, 3.0)


def sweep_position(t: float) -> dict:
    """A warm sun swinging from the left of the scene to the right, t in 0..1."""
    return {"az": round(-80 + 160 * t, 1), "el": 15, "intensity": 4.0}


def drag(page, dx: float, dy: float = 0.0) -> None:
    box = page.locator("#pR canvas").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy)
    page.mouse.up()


def settle(page, frames: int = 3) -> None:
    """Let the viewer draw a few animation frames so a change is on screen before a screenshot."""
    page.evaluate(
        "(n) => new Promise((done) => { const t = () => (--n <= 0 ? done() : requestAnimationFrame(t)); t(); })",
        frames,
    )


def frame_plan() -> list[tuple[str, float]]:
    """(phase, progress 0..1) for every frame of the clip."""
    plan = []
    for phase, seconds in (("orbit", ORBIT_S), ("sweep", SWEEP_S), ("views", VIEWS_S)):
        n = seconds * FPS
        plan += [(phase, i / (n - 1)) for i in range(n)]
    return plan


def apply_frame(viewer: Viewer, phase: str, p: float, state: dict) -> None:
    page = viewer.page
    if phase == "orbit":
        drag(page, -2.0 if p < 0.5 else 2.0)  # sways left then back right
    elif phase == "sweep":
        if not state.get("light"):
            viewer.clear_lights()
            viewer.add_light("dir", **sweep_position(0), color="#ffc98a")
            state["light"] = True
        viewer.set_light(0, **sweep_position(p))
    else:
        mode = 1 if p < 1 / 3 else 3 if p < 2 / 3 else 4
        if state.get("mode") != mode:
            viewer.set_gbuffer(mode)
            state["mode"] = mode
    page.evaluate("() => document.getElementById('sidebar').scrollTo({ top: 0, behavior: 'instant' })")
    settle(page)


def capture_frames(gl: str, out: Path) -> list[Path]:
    server = ViewerServer({})
    out.mkdir(parents=True, exist_ok=True)
    files = []
    with sync_playwright() as playwright:
        browser = launch_browser(playwright, gl)
        viewer = Viewer(browser)
        viewer.context.close()
        viewer.context = browser.new_context(viewport=SIZE, device_scale_factor=1)
        viewer.page = viewer.context.new_page()
        try:
            cam = ",".join(str(v) for v in START_CAM)
            viewer.open(f"{server.base_url}/index.html?test=1&cam={cam}", timeout_ms=300_000)
            viewer.page.click("text=Daylight")
            viewer.set_value("expo", 1.8)  # the capture is dim; brighten the relit pane for the clip
            viewer.set_checked("showGizmos", True)
            state: dict = {}
            for i, (phase, p) in enumerate(frame_plan()):
                apply_frame(viewer, phase, p, state)
                path = out / f"f{i:04d}.png"
                viewer.page.screenshot(path=str(path))
                files.append(path)
            print("renderer:", viewer.renderer())
        finally:
            viewer.close()
            browser.close()
            server.close()
    return files


def encode(frames: Path, dest: Path, width: int, crf: int) -> None:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(frames / "f%04d.png")]
    cmd += ["-vf", f"scale={width}:-2:flags=lanczos,format=yuv420p", "-c:v", "libx264", "-preset", "slow"]
    cmd += ["-crf", str(crf), "-r", str(FPS), "-movflags", "+faststart", "-an", str(dest)]
    subprocess.run(cmd, check=True)


def jpeg(src: Path, dest: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-q:v", "3", str(dest)], check=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--gl", choices=["gpu", "software"], default="gpu")
    ap.add_argument("--crf", type=int, default=26)
    args = ap.parse_args(argv)
    if not shutil.which("ffmpeg"):
        print("record_hero: ffmpeg is needed to make the clip. Install it and run this again.", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        frames = Path(tmp)
        files = capture_frames(args.gl, frames)
        encode(frames, args.out / "hero.mp4", 1280, args.crf)
        # Stills: relit during the orbit, mid light sweep, and the normals view.
        total = len(files)
        picks = (ORBIT_S * FPS // 4, (ORBIT_S + SWEEP_S // 2) * FPS, total - 1)
        for n, i in enumerate(picks, 1):
            jpeg(files[i], args.out / f"still-{n}.jpg")
        jpeg(files[(ORBIT_S + SWEEP_S // 2) * FPS], args.out / "hero-poster.jpg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
