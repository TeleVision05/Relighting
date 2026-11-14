"""Static server for the relighting viewer — stdlib only, no numpy needed.

    python serve.py              # http://127.0.0.1:8000, opens a browser
    python serve.py 8080         # pick a port
    python serve.py --no-browser # do not open a browser (scripts, CI)
    python serve.py --host 0.0.0.0   # let other devices on your network connect (see below)

Why not `python -m http.server`:
  * it serves the directory you happen to be standing in, not this one;
  * it has no /models endpoint, so the model dropdown 404s;
  * it lets the browser cache index.html, so edits appear not to take effect;
  * it serves every file, including .git, and lists directories.

This serves only an allow-list (index.html, the *.ply scenes, and the src/ and assets/
folders; see static_server.py), listens on 127.0.0.1 only unless --host says otherwise,
and sends no-cache headers. render_splats.py --serve does the same and adds the
server-side /render endpoint, but that one needs numpy.
"""

import argparse
import logging
import sys
import threading
import webbrowser
from pathlib import Path

from static_server import (
    SafeStaticHandler,
    ServerStartError,
    add_host_argument,
    bind_server,
    exposure_warning,
    list_models,
    port_arg,
)

ROOT = Path(__file__).resolve().parent


class ViewerHandler(SafeStaticHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the relighting viewer.")
    parser.add_argument("port", nargs="?", type=port_arg, default=8000, help="port to listen on (default 8000)")
    add_host_argument(parser)
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)
    try:
        httpd = bind_server(ViewerHandler, args.host, args.port)
    except ServerStartError as exc:
        print(exc, file=sys.stderr)
        return 1
    plys = list_models(ROOT)
    url = f"http://{args.host if args.host != '0.0.0.0' else '127.0.0.1'}:{args.port}/index.html"
    with httpd:
        print(f"Serving {ROOT}")
        print(f"Models: {', '.join(plys) if plys else '(none found)'}")
        warning = exposure_warning(args.host)
        if warning:
            print(f"\nWARNING: {warning}")
        print(f"\n  {url}\n\nCtrl+C to stop.")
        if not args.no_browser:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
