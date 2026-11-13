"""CPU reference renderer: command-line entry point and the backend of ``GET /render``.

The renderer itself is the ``cpu_render`` package. This module keeps the parsed-scene
cache (``PLY_PATH`` is read at call time, so tests and the server can swap it) and turns a
render into PNG bytes.

    python render_splats.py                     # rendered_neutral.png + rendered_relit.png
    python render_splats.py --ply Buttons.ply --width 800 --height 600
    python render_splats.py --serve             # viewer + GET /render (see render_server.py)
"""

from __future__ import annotations

import argparse
import threading
import time
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

from cpu_render import (
    LightRig,
    Material,
    OrbitCamera,
    load_ply,
    quat_to_matrix,
    render_rgba,
    separate_lighting,
)
from cpu_render.camera import DEFAULT_PITCH, DEFAULT_YAW, DEFAULT_ZOOM

__all__ = ["load_ply", "quat_to_matrix", "render_png", "separate_lighting"]

PLY_PATH = Path(__file__).with_name("father-day.ply")
_RENDER_TIMEOUT = 300  # seconds; abort renders that take longer than this

_cached_ply: dict[str, np.ndarray] | None = None
_cached_path: Path | None = None
_ply_cache_lock = threading.Lock()


def invalidate_ply_cache() -> None:
    """Drop the parsed-PLY cache so the next render re-reads PLY_PATH from disk."""
    global _cached_ply, _cached_path
    with _ply_cache_lock:
        _cached_ply = None
        _cached_path = None


def _load_cached_ply() -> dict[str, np.ndarray]:
    """The parsed PLY_PATH. A failed load is not cached, so fixing the file needs no restart."""
    global _cached_ply, _cached_path
    with _ply_cache_lock:
        path = Path(PLY_PATH)
        if _cached_ply is None or _cached_path != path:
            _cached_ply = load_ply(path)
            _cached_path = path
        return _cached_ply


class RenderTimeoutError(Exception):
    """Raised when a render operation exceeds the timeout limit."""


class TimeoutGuard:
    """``check()`` raises RenderTimeoutError once the render has run longer than the limit."""

    def __init__(self, start_time: float, limit: float | None = None):
        self.start_time = start_time
        self.limit = _RENDER_TIMEOUT if limit is None else limit

    def check(self) -> None:
        if time.monotonic() - self.start_time > self.limit:
            raise RenderTimeoutError(f"Render timed out after {self.limit}s; reduce splat count or resolution")


def to_png(rgba: np.ndarray) -> bytes:
    pil = Image.fromarray((np.clip(rgba, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8), mode="RGBA")
    buffer = BytesIO()
    pil.save(buffer, format="PNG")
    return buffer.getvalue()


def render_png(
    width: int = 1600,
    height: int = 1600,
    mode: str = "relit",
    ambient: float = 0.20,
    ambient_color: tuple[float, float, float] = (0.8, 0.84, 0.88),
    dir_intensity: float = 1.5,
    dir_x: float = 0.5,
    dir_y: float = 0.7,
    dir_z: float = 0.5,
    dir_color: tuple[float, float, float] = (1.0, 1.0, 1.0),
    point_intensity: float = 1.0,
    point_x: float = 1.2,
    point_y: float = 1.5,
    point_z: float = 0.8,
    point_color: tuple[float, float, float] = (0.22, 0.74, 0.97),
    roughness: float = 0.30,
    metallic: float = 0.10,
    specular_gain: float = 1.2,
    separation: float = 1.0,
    keep_ao: float = 0.0,
    stride: int = 1,
    yaw: float = DEFAULT_YAW,
    pitch: float = DEFAULT_PITCH,
    zoom: float = DEFAULT_ZOOM,
) -> bytes:
    """Render PLY_PATH to PNG bytes. Positions, lights and camera are in the viewer's frame (y up)."""
    guard = TimeoutGuard(time.monotonic())
    rig = LightRig(
        ambient=ambient,
        ambient_color=ambient_color,
        dir_intensity=dir_intensity,
        dir_towards=(dir_x, dir_y, dir_z),
        dir_color=dir_color,
        point_intensity=point_intensity,
        point_pos=(point_x, point_y, point_z),
        point_color=point_color,
        keep_ao=keep_ao,
    )
    rgba = render_rgba(
        _load_cached_ply(),
        width,
        height,
        mode=mode,
        camera=OrbitCamera(yaw, pitch, zoom),
        rig=rig,
        material=Material(roughness, metallic, specular_gain),
        separation=separation,
        stride=stride,
        check=guard.check,
    )
    return to_png(rgba)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CPU reference renderer for the relighting viewer.")
    parser.add_argument("--serve", action="store_true", help="serve the viewer and GET /render instead of writing PNGs")
    parser.add_argument("--port", type=int, default=8000, help="port for --serve (default 8000)")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="address for --serve (default 127.0.0.1, this computer only; 0.0.0.0 exposes it to your network)",
    )
    parser.add_argument("--ply", type=Path, help=f"scene to render (default {PLY_PATH.name})")
    parser.add_argument("--width", type=int, default=1600, help="image width in pixels (default 1600)")
    parser.add_argument("--height", type=int, default=1600, help="image height in pixels (default 1600)")
    parser.add_argument("--yaw", type=float, default=DEFAULT_YAW, help="camera yaw in radians, as ?cam= in the viewer")
    parser.add_argument("--pitch", type=float, default=DEFAULT_PITCH, help="camera pitch in radians")
    parser.add_argument("--zoom", type=float, default=DEFAULT_ZOOM, help="camera distance from the origin")
    return parser


def main(argv: list[str] | None = None) -> int:
    global PLY_PATH
    args = _parser().parse_args(argv)
    if args.serve:
        from render_server import serve  # imported here: render_server imports this module

        return serve(args.host, args.port)
    if args.ply is not None:
        PLY_PATH = args.ply
    view = {"width": args.width, "height": args.height, "yaw": args.yaw, "pitch": args.pitch, "zoom": args.zoom}
    written = []
    for mode in ("neutral", "relit"):
        t0 = time.perf_counter()
        out = Path(f"rendered_{mode}.png")
        out.write_bytes(render_png(mode=mode, **view))
        written.append(f"{out} ({time.perf_counter() - t0:.1f} s)")
    print("Rendered:", ", ".join(written))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
