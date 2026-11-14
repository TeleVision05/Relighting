"""Assemble the static site that GitHub Pages serves: the viewer plus the demo scene.

    python demo/assemble_site.py OUT_DIR

Only the viewer is copied (``index.html`` and the web files in ``src/``) with the demo scene
and its NOTICE. The sample scenes (``*.ply`` in the repository root), the Python code and the
notes are not published. Every URL in the viewer is relative to the page, so the folder works
from any sub-path (for example /Relighting/) without server-side code.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_SUFFIXES = {".js", ".css"}


def assemble(out: Path) -> list[Path]:
    """Write the site into ``out`` (created, or emptied first) and return the files written."""
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    copies = [(ROOT / "index.html", out / "index.html")]
    for src in sorted((ROOT / "src").rglob("*")):
        if src.is_file() and src.suffix in WEB_SUFFIXES:
            copies.append((src, out / src.relative_to(ROOT)))
    copies += [(ROOT / "demo" / name, out / "demo" / name) for name in ("buttons-demo.ply", "NOTICE")]
    for source, target in copies:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (out / ".nojekyll").write_text("")  # serve the folder as it is
    return [target for _, target in copies]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out", type=Path)
    args = parser.parse_args(argv)
    files = assemble(args.out)
    print(f"{args.out}: {len(files)} files, {sum(f.stat().st_size for f in files) / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
