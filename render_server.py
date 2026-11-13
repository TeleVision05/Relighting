"""HTTP server for the CPU reference renderer: the viewer files plus ``GET /render``.

Started with ``python render_splats.py --serve`` (or ``python render_server.py``).

    /index.html, /*.ply, /models   same allow-listed files as serve.py
    /render?mode=relit&w=512&h=512 PNG from the CPU renderer; every setting is validated
    /reload                        drop the parsed-PLY cache after swapping the scene on disk

Listens on 127.0.0.1 unless --host says otherwise. Bad settings get a 400 that explains
what to change; at most MAX_CONCURRENT_RENDERS renders run at once, extra requests get a
503 so a burst cannot exhaust memory.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit

import render_splats
from render_params import RenderParamError, parse_render_query
from static_server import (
    SafeStaticHandler,
    ServerStartError,
    add_host_argument,
    bind_server,
    exposure_warning,
    port_arg,
)

log = logging.getLogger("relighting.server")

ROOT = Path(__file__).resolve().parent
MAX_CONCURRENT_RENDERS = 2
_render_slots = threading.BoundedSemaphore(MAX_CONCURRENT_RENDERS)

BUSY_MESSAGE = "The renderer is busy with other images. Wait a minute and try again."
TIMEOUT_MESSAGE = (
    "That image took too long to render. Try a smaller width and height (w, h) or a larger stride, then try again."
)
SCENE_MESSAGE = (
    "The scene file could not be loaded. Check that the .ply file is present and complete, "
    "then open /reload and try again."
)
RENDER_FAILED_MESSAGE = (
    "Something went wrong while rendering. Try again; if it keeps happening, check the server terminal."
)


class RenderHandler(SafeStaticHandler):
    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/reload":
            render_splats.invalidate_ply_cache()
            self.send_json(200, {"ok": True, "ply": render_splats.PLY_PATH.name})
        elif parsed.path == "/render":
            self._handle_render(parsed.query)
        else:
            super().do_GET()

    def _handle_render(self, query: str) -> None:
        try:
            kwargs = parse_render_query(query)
        except RenderParamError as exc:
            self.send_message(400, str(exc))
            return
        if not _render_slots.acquire(blocking=False):
            self.send_message(503, BUSY_MESSAGE, {"Retry-After": "30"})
            return
        try:
            png = render_splats.render_png(**kwargs)
        except render_splats.RenderTimeoutError:
            log.warning("render timed out for %s", query)
            self.send_message(504, TIMEOUT_MESSAGE)
            return
        except (OSError, RuntimeError, ValueError):
            log.exception("could not load or render the scene")
            self.send_message(500, SCENE_MESSAGE)
            return
        except Exception:
            log.exception("render failed")
            self.send_message(500, RENDER_FAILED_MESSAGE)
            return
        finally:
            _render_slots.release()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(png)))
        self.end_headers()
        self.wfile.write(png)


def serve(host: str = "127.0.0.1", port: int = 8000) -> int:
    handler = partial(RenderHandler, directory=str(ROOT))
    try:
        httpd = bind_server(handler, host, port)
    except ServerStartError as exc:
        print(exc, file=sys.stderr)
        return 1
    with httpd:
        print(f"Serving on http://{host if host != '0.0.0.0' else '127.0.0.1'}:{port}")
        warning = exposure_warning(host)
        if warning:
            print(f"WARNING: {warning}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Serve the viewer and the CPU /render endpoint.")
    parser.add_argument("--port", type=port_arg, default=8000, help="port to listen on (default 8000)")
    add_host_argument(parser)
    args = parser.parse_args(argv)
    return serve(args.host, args.port)


if __name__ == "__main__":
    sys.exit(main())
