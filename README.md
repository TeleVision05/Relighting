# Relighting

Interactive relighting of 3D Gaussian Splatting scenes from a single baked
`.ply`. A standard 3DGS file stores baked radiance (albedo x lighting) in its
SH DC terms, so the tool first splits that into a smooth irradiance field and
an intrinsic albedo (Retinex-style), estimates per-splat normals from each
Gaussian's shortest axis, and re-shades the scene with new lights using a
Cook-Torrance/GGX BRDF.

**Status: experimental.** The WebGL viewer works and is used by hand; the CPU
reference renderer is tested but slow and does not yet match the viewer's
geometry (see [ROADMAP.md](ROADMAP.md) for the concrete gaps).

## Layout

- `index.html`: the WebGL2 viewer (main UI). Split view: left pane is the
  baked SH appearance (reference), right pane is the relit result. Up to 8
  lights (directional / point / spot, `MAX_LIGHTS = 8`) with ray-marched
  shadows through a per-model density volume, four presets (studio, sunset,
  cyber, day), material sliders, `Separate` / `Keep AO` / `N Smooth`, six
  G-buffer modes (relit, intrinsic albedo, baked SH DC, baked irradiance/AO,
  surface normals, specular only) and a model picker. Loads
  `father-day.ply` by default; `?ply=Buttons.ply` picks another.
- `serve.py`: stdlib-only static server for the viewer, with a `/models`
  endpoint and no-cache headers. Opens a browser on start.
- `static_server.py`: the file policy both servers share (see Servers below).
- `render_splats.py`: CPU reference renderer in numpy. Writes
  `rendered_neutral.png` and `rendered_relit.png`, or with `--serve` starts
  `render_server.py`, which serves `GET /render` (plus `/models` and
  `/reload`, which drops the parsed-PLY cache). Query validation lives in
  `render_params.py`. It is not at feature parity with the viewer: one
  directional + one point light, no shadows, no normal smoothing, float-only
  PLY properties.
- `Relighting 3D Gaussian Splatting.md`: design notes and implementation
  status.
- `Buttons.ply`, `father-day.ply`: sample scenes, stored in Git LFS.
- `tests/`: headless smoke tests on a synthetic PLY.

## Install

```bash
git lfs install && git lfs pull                     # sample scenes (~158 MB)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

The viewer (`serve.py` + `index.html`) needs only Python 3 (stdlib) and a
WebGL2 browser. The venv is only for `render_splats.py` (numpy, pillow) and
the tests, which need **Python 3.10+** (`render_splats.py` uses a `X | None`
annotation at module level); verified on 3.12, 3.13 and 3.14.5 on 2026-09-25.

## Configure

Nothing to configure: no environment variables, no config file. Drop any
`*.ply` into the repo root and it appears in the model picker.

## Run

```bash
python3 serve.py                 # http://127.0.0.1:8000/index.html
python3 serve.py 8080            # pick a port
python3 serve.py --no-browser    # do not open a browser window
```

CPU reference renderer:

```bash
.venv/bin/python render_splats.py            # writes rendered_*.png from father-day.ply
.venv/bin/python render_splats.py --serve    # viewer + GET /render?mode=relit&w=512&h=512
```

`render_splats.py` composites in pure Python per pixel, so use small `w`/`h`
or a `stride` > 1 for previews. `/render` always renders `father-day.ply`
(hard-coded `PLY_PATH`) from a fixed camera.

### Servers: what they expose

Both servers listen on `127.0.0.1` (this computer only). To let another device
connect, pass `--host 0.0.0.0`; the server then prints a warning, because
anyone who can reach your machine can open the viewer and download the scenes.

They serve an explicit allow-list, nothing else: `index.html`, the `*.ply`
files in the repo root, and files with web suffixes (`.js`, `.css`, images,
...) inside the `src/` and `assets/` folders. Dotfiles, `.git`, source and
notes, `..` paths, symlinks that leave the repo and directory listings all
answer "not found". If you add a new folder of viewer files, add its name to
`PUBLIC_DIRS` in `static_server.py`.

`GET /render` checks every setting (`mode`, `w`, `h`, `stride`, light and
material values) against a range. A bad value gets a `400` whose JSON `error`
text says which setting is wrong and what is allowed, for example `Image width
(w) must be a whole number between 16 and 2048`. At most two renders run at
once; extra requests get a `503` asking to try again.

## Test

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The tests build a tiny synthetic splat PLY, so they do not need the LFS
models or a browser. They cover PLY parsing and the derived normals/albedo,
the lighting separation, all three CPU render modes, both HTTP servers (the
file allow-list, loopback binding, `/render` validation and limits).
The WebGL viewer itself has no automated test yet.

## Lint and format

```bash
.venv/bin/pre-commit install     # once per clone: runs the checks below on every commit
npm ci                           # eslint + prettier
.venv/bin/ruff check . && .venv/bin/ruff format --check .
npx eslint . && npx prettier --check .
```

The same checks run in CI (`.github/workflows/ci.yml`).

## Licence

The code is released under the [MIT licence](LICENSE), copyright 2026 Tarun
Vadapalli. **The sample scenes (`Buttons.ply`, `father-day.ply` and anything
derived from them) are not covered by that licence.** They are included only
so the viewer has something to show; do not reuse or redistribute them without
checking with the owner.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for current state, known bugs, milestones and
open questions.
