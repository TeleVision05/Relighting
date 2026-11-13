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
- `render_splats.py`: CPU reference renderer in numpy. Writes
  `rendered_neutral.png` and `rendered_relit.png`, or serves `GET /render`
  (plus `/models` and `/reload`, which drops the parsed-PLY cache). It is not
  at feature parity with the viewer: one directional + one point light, no
  shadows, no normal smoothing, float-only PLY properties.
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
```

CPU reference renderer:

```bash
.venv/bin/python render_splats.py            # writes rendered_*.png from father-day.ply
.venv/bin/python render_splats.py --serve    # viewer + GET /render?mode=relit&w=512&h=512
```

`render_splats.py` composites in pure Python per pixel, so use small `w`/`h`
or a `stride` > 1 for previews. `/render` always renders `father-day.ply`
(hard-coded `PLY_PATH`) from a fixed camera; bad query values are not
validated (see ROADMAP M3).

## Test

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The tests build a tiny synthetic splat PLY, so they do not need the LFS
models or a browser. They cover PLY parsing and the derived normals/albedo,
the lighting separation, all three CPU render modes, and both HTTP servers.
The WebGL viewer itself has no automated test yet.

## Licence

The code is released under the [MIT licence](LICENSE), copyright 2026 Tarun
Vadapalli. **The sample scenes (`Buttons.ply`, `father-day.ply` and anything
derived from them) are not covered by that licence.** They are included only
so the viewer has something to show; do not reuse or redistribute them without
checking with the owner.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for current state, known bugs, milestones and
open questions.
