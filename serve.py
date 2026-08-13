"""Static server for the relighting viewer — stdlib only, no numpy needed.

    python serve.py            # http://127.0.0.1:8000, opens a browser
    python serve.py 8080       # pick a port

Why not `python -m http.server`:
  * it serves the directory you happen to be standing in, not this one;
  * it has no /models endpoint, so the model dropdown 404s;
  * it lets the browser cache index.html, so edits appear not to take effect.

This fixes all three. render_splats.py --serve does the same and adds the
server-side /render endpoint, but that one needs numpy.
"""
import json
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent


class ViewerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        # A cached index.html is indistinguishable from "my changes did nothing".
        if not any(h.lower().startswith(b"cache-control")
                   for h in (self._headers_buffer or [])):
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/models":
            body = json.dumps(sorted(p.name for p in ROOT.glob("*.ply"))).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    plys = sorted(p.name for p in ROOT.glob("*.ply"))
    url = f"http://127.0.0.1:{port}/index.html"
    with ThreadingHTTPServer(("127.0.0.1", port), ViewerHandler) as httpd:
        print(f"Serving {ROOT}")
        print(f"Models: {', '.join(plys) if plys else '(none found)'}")
        print(f"\n  {url}\n\nCtrl+C to stop.")
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
