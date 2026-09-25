# Relighting

Interactive relighting of 3D Gaussian Splatting scenes. A standard 3DGS `.ply`
stores baked radiance (albedo x lighting) in its SH DC terms, so the tool first
splits that into a smooth irradiance field and an intrinsic albedo
(Retinex-style), estimates per-splat normals from each Gaussian's shortest
axis, and then re-shades the scene with new lights using a Cook-Torrance/GGX BRDF.

- `index.html`: the WebGL viewer (main UI). Includes light, material,
  separation, AO and normal-smoothing controls, and a model picker.
- `serve.py`: a stdlib-only static server for the viewer, with a `/models`
  endpoint and no-cache headers.
- `render_splats.py`: a CPU reference renderer in numpy. It writes
  `rendered_neutral.png` and `rendered_relit.png`, or serves `/render`.
- `Relighting 3D Gaussian Splatting.md`: the design notes and implementation
  status.
- `*.ply`: sample scenes, stored in Git LFS (`git lfs pull`).

## Run

```bash
python3 serve.py            # http://127.0.0.1:8000/index.html (no deps needed)
```

To run the CPU reference renderer, which needs numpy and pillow:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python render_splats.py            # writes rendered_*.png from father-day.ply
.venv/bin/python render_splats.py --serve    # viewer + GET /render?mode=relit&w=512&h=512
```

The CPU renderer is pure Python per pixel. Use small `w`/`h` or `stride` for
quick previews.

## Test

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The tests are headless and build a tiny synthetic splat PLY, so they do not
need the LFS models. They cover PLY parsing and the derived normals/albedo, the
lighting separation, all three render modes, and both HTTP servers.
