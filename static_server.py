"""Safe static file serving shared by serve.py and ``render_splats.py --serve``. Stdlib only.

Why this exists: ``SimpleHTTPRequestHandler`` serves the whole directory it is pointed at,
including ``.git`` and any ``.env`` that happens to be there, and lists directories. This
handler serves an explicit allow-list instead:

* ``index.html`` and any ``*.ply`` directly in the repo root;
* files with a known web suffix inside the directories named in ``PUBLIC_DIRS``.

Everything else (dotfiles, ``.git``, source, notes, ``..`` tricks, symlinks that lead out of
the root, directory listings) answers 404. If a new directory of viewer files is added to
the repo, add its name to ``PUBLIC_DIRS``; nothing outside the list is ever served.

Servers bind to 127.0.0.1 unless the person starting them passes ``--host``.
"""

from __future__ import annotations

import argparse
import json
import logging
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

log = logging.getLogger("relighting.server")

DEFAULT_HOST = "127.0.0.1"

PUBLIC_ROOT_FILES = frozenset({"index.html"})
PUBLIC_ROOT_SUFFIXES = frozenset({".ply"})
PUBLIC_DIRS = frozenset({"src", "assets"})
PUBLIC_DIR_SUFFIXES = frozenset(
    {".js", ".mjs", ".css", ".json", ".ply", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".woff2"}
)

NOT_FOUND_MESSAGE = (
    "That file is not shared by this server. Open /index.html, or choose a scene from the model list in the viewer."
)

_FRIENDLY_ERRORS = {
    400: "The server could not understand that request. Check the address and try again.",
    404: NOT_FOUND_MESSAGE,
    405: "This server only supports opening pages and files.",
    501: "This server only supports opening pages and files.",
}
_GENERIC_ERROR = "Something went wrong on the server. Try again; if it keeps happening, check the terminal running it."


def _has_hidden_part(parts) -> bool:
    return any(part.startswith(".") for part in parts)


def _is_public(rel: Path) -> bool:
    """True if the path (relative to the root, already resolved) is on the allow-list."""
    parts = rel.parts
    suffix = rel.suffix.lower()
    if len(parts) == 1:
        return parts[0] in PUBLIC_ROOT_FILES or suffix in PUBLIC_ROOT_SUFFIXES
    return parts[0] in PUBLIC_DIRS and suffix in PUBLIC_DIR_SUFFIXES


def resolve_public_file(root: Path, url_path: str) -> Path | None:
    """Map a request path to a file under ``root`` that may be served, or None."""
    path = unquote(urlsplit(url_path).path)
    if "\x00" in path or "\\" in path:
        return None
    segments = [s for s in path.split("/") if s]
    if not segments:
        segments = ["index.html"]
    if "." in segments or ".." in segments or _has_hidden_part(segments):
        return None
    root_real = root.resolve()
    try:
        real = root_real.joinpath(*segments).resolve(strict=True)
        rel = real.relative_to(root_real)
    except (OSError, ValueError):
        return None
    if not real.is_file() or _has_hidden_part(rel.parts) or not _is_public(rel):
        return None
    return real


def list_models(root: Path) -> list[str]:
    """Names of the scenes a visitor may load: the servable ``*.ply`` files in the root."""
    names = []
    for entry in root.glob("*.ply"):
        if resolve_public_file(root, "/" + entry.name) is not None:
            names.append(entry.name)
    return sorted(names)


class SafeStaticHandler(SimpleHTTPRequestHandler):
    """Serves only allow-listed files, plus ``GET /models``. Errors are JSON with plain-language text."""

    server_version = "RelightingServer"
    sys_version = ""
    _sent_headers: set = set()
    _target: Path | None = None

    # -- responses ---------------------------------------------------------------------------
    def send_response(self, code, message=None):
        self._sent_headers = set()
        super().send_response(code, message)

    def send_header(self, keyword, value):
        self._sent_headers.add(keyword.lower())
        super().send_header(keyword, value)

    def end_headers(self) -> None:
        # A cached index.html or scene is indistinguishable from "my changes did nothing".
        if "cache-control" not in self._sent_headers:
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def send_json(self, status: int, payload, headers: dict | None = None) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if getattr(self, "command", None) != "HEAD":
            self.wfile.write(body)

    def send_message(self, status: int, message: str, headers: dict | None = None) -> None:
        """Answer with a plain-language ``{"error": ...}`` body. Never put raw exceptions here."""
        self.send_json(status, {"error": message}, headers)

    def send_error(self, code, message=None, explain=None) -> None:
        # The default error page shows the status code and Python's wording. Log the raw
        # detail, show the person something they can act on.
        log.warning("HTTP %s for %r: %s", code, getattr(self, "path", "?"), message)
        self.send_message(code, _FRIENDLY_ERRORS.get(code, _GENERIC_ERROR))

    # -- routing -----------------------------------------------------------------------------
    def _root(self) -> Path:
        return Path(self.directory)

    def do_GET(self) -> None:
        if urlsplit(self.path).path == "/models":
            self.send_json(200, list_models(self._root()))
            return
        super().do_GET()

    def send_head(self):
        self._target = resolve_public_file(self._root(), self.path)
        if self._target is None:
            self.send_message(404, NOT_FOUND_MESSAGE)
            return None
        return super().send_head()

    def translate_path(self, path: str) -> str:
        return str(self._target)

    def list_directory(self, path):
        self.send_message(404, NOT_FOUND_MESSAGE)
        return None

    def log_message(self, format: str, *args) -> None:
        log.debug(format, *args)

    def log_error(self, format: str, *args) -> None:
        log.warning(format, *args)


# -- starting a server -----------------------------------------------------------------------
class ServerStartError(Exception):
    """The server could not start; the message is written for the person who ran the command."""


def port_arg(text: str) -> int:
    try:
        port = int(text)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"'{text}' is not a valid port. Use a whole number from 1 to 65535.")
    return port


def add_host_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=(
            f"address to listen on (default {DEFAULT_HOST}, this computer only). "
            "Use 0.0.0.0 to let other devices on your network connect; they will be able to open the viewer and "
            "download the scene files."
        ),
    )


def exposure_warning(host: str) -> str | None:
    if host in ("127.0.0.1", "localhost"):
        return None
    return (
        f"Listening on {host}: other devices that can reach this computer can open the viewer and "
        "download the scene files. Use the default (127.0.0.1) to keep it to this computer."
    )


def bind_server(handler, host: str, port: int) -> ThreadingHTTPServer:
    try:
        return ThreadingHTTPServer((host, port), handler)
    except (OSError, OverflowError) as exc:
        log.error("Could not bind %s:%s: %s", host, port, exc)
        raise ServerStartError(
            f"Could not start the server on {host}:{port}. The port may already be in use, or the address "
            "is not available on this computer. Try a different port (for example 8080) or leave --host unset."
        ) from exc
