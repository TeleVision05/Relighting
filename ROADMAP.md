# Roadmap

## Current state (2026-09-25)

Status: **experimental**. Interactive relighting of a single baked 3D Gaussian
Splatting `.ply`, no training loop, no GPU dependency.

What works, and how it was verified:

| Piece | What it does | Verified by |
| --- | --- | --- |
| `serve.py` | stdlib static server for the viewer: `/models` lists `*.ply`, no-cache headers, opens a browser | `tests/test_smoke.py::test_static_viewer_server_lists_models` |
| `index.html` | WebGL2 viewer: parses the PLY client-side, Retinex albedo/irradiance split, shortest-axis normals with an `N Smooth` blend, Cook-Torrance relighting, G-buffer modes, `Separate` / `Keep AO` sliders, model picker | manual only; no automated test loads the page in a browser |
| `render_splats.py` | numpy CPU reference: `load_ply`, `separate_lighting`, `render_png` in `relit` / `neutral` / `albedo` modes, `--serve` adds `GET /render` | `tests/test_smoke.py` (PLY parse and derived fields, garbage PLY rejected, uniform-scene separation is identity, all three modes at 256x256, `/models` + `/render` over HTTP) |
| Sample scenes | `Buttons.ply` (249,973 splats, 41 MB), `father-day.ply` (117 MB) in Git LFS | `git lfs ls-files` shows both present |

Test run on 2026-09-25 (`.venv/bin/python -m pytest -q`): `8 passed in 1.81s`.
The suite renders 1,500 synthetic splats at 256x256; it never touches the LFS
scenes and never opens a browser.

Repo hygiene: `main` at `486f11a` (README, requirements, pytest.ini, smoke
tests, rank-1 covariance fix). No linter, no pre-commit hook (only the git-lfs
hooks in `.git/hooks`), no CI.

## Known gaps and bugs

1. **Quaternion component order disagrees between the two renderers.**
   `index.html:952` reads `rot_0=w, rot_1=x, rot_2=y, rot_3=z` (the standard
   3DGS export convention). `render_splats.py::load_ply` unpacks
   `qx, qy, qz, qw = rot_0..rot_3` and `render_png` calls
   `quat_to_matrix(rot0, rot1, rot2, rot3)` whose signature is `(qx, qy, qz, qw)`.
   On a real export the CPU normals and splat orientations are therefore
   rotated wrongly. The test fixture (`tests/test_smoke.py::write_synthetic_ply`,
   `data[:, 13] = 1.0` with the comment "identity quaternion (x,y,z,w)") encodes
   the CPU convention, so the tests cannot catch this.
2. **CPU 2D covariance uses only `scale_0`.** `render_png` builds `cov00/01/11`
   from `basis_xv` and `s0 = exp(clamp(scale_0)) * 0.0025 * scale2d`; `basis_yv`
   is computed and never used, `scale_1`/`scale_2` are never read. The shader
   (`index.html`, `VERT`, `fd2 * dot(m0*m0, sc2)`) uses all three. Every CPU
   splat is a scaled disc aligned to one axis, not the real ellipse.
3. **Per-pixel Python loop.** The compositing in `render_png` is a nested
   `for j / for k` over every pixel of every splat's bounding box. Full-size
   renders (default 1600x1600) of the sample scenes take minutes; that is what
   the `_RENDER_TIMEOUT = 300` guard exists for. The README already tells
   users to pass small `w`/`h` or `stride`.
4. **Different world convention.** The viewer negates Y and Z at load
   (`index.html:931-932`) and composes a 180 degree X rotation into the
   quaternion; the CPU renderer uses raw PLY coordinates with a hard-coded
   camera (`yaw=-0.45`, `pitch=-0.15`, distance `5.5`, `focal = 0.75 * min(w,h)`)
   that nothing can change from `/render`. The two outputs cannot be compared
   pixel-for-pixel.
5. **`/render` is unvalidated and pinned to one file.** `RenderHandler.do_GET`
   does `float(params[...])` with no error handling (a bad value raises inside
   the handler and drops the connection), an unknown `mode` silently falls into
   the neutral branch, and it always renders `PLY_PATH` (`father-day.ply`) even
   though `/models` lists every scene.
6. **`render_splats.py --serve` binds `0.0.0.0`** (`serve()`), exposing the
   directory listing, the LFS scenes and a CPU-bound endpoint on every
   interface; `serve.py` correctly binds `127.0.0.1`.
7. **WebGL viewer is untested.** `test_static_viewer_server_lists_models`
   serves a stub `<html></html>`, not the real page. Shader compile errors or a
   broken PLY parse in `index.html` would not fail any test.
8. **Higher-order SH bands (`f_rest_*`) are ignored** by both renderers; only
   DC is used for appearance (documented in the design notes as intentional
   for albedo, but it also throws away the view-dependent signal that could
   help separate specular from diffuse).
9. **No lint or pre-commit hook.** The house rule requires one; nothing in
   this repo enforces formatting or catches unused code such as `basis_yv`.

## Milestones

### M1. Make the two renderers agree on geometry

- [ ] Switch `render_splats.py` to `rot_0 = w` in both `load_ply` and the
      `quat_to_matrix` call, matching `index.html:952`.
- [ ] Fix `write_synthetic_ply` so the identity quaternion sets `rot_0 = 1`,
      and add a test with a non-identity quaternion and anisotropic scales
      whose expected normal (the rotation matrix column of the shortest axis)
      is asserted numerically.
- [ ] Use all three scales in the CPU 2D covariance (port the shader's
      `fd2 * dot(m0*m0, sc2)` form), delete the `0.0025` magic factor and the
      unused `basis_yv`.
- [ ] Apply the viewer's Y/Z negation in the CPU path (or remove it from the
      viewer) and expose `yaw`, `pitch`, `dist` on `render_png` and `/render`.
- Done when: a new test renders one elongated synthetic splat through
  `render_png` and asserts the orientation of its screen-space ellipse;
  `pytest -q` passes; a CPU render and a viewer screenshot of `Buttons.ply`
  from the same camera are committed side by side under `docs/` and match by
  eye.

### M2. Make the CPU renderer usable at full resolution

- [ ] Replace the per-pixel `for j / for k` compositing with a vectorized
      "over" on the `image[y0:y1, x0:x1]` slice per splat.
- [ ] Vectorize projection, culling and inverse-covariance across all splats
      (one numpy pass, no per-splat Python loop before compositing).
- [ ] Add a golden test: hash of the synthetic-scene PNG before and after the
      rewrite must match, so the speedup is provably output-neutral.
- [ ] Record the timing for `Buttons.ply` at 512x512 and 1600x1600 in the
      README.
- Done when: `python render_splats.py` writes both PNGs for `Buttons.ply` at
  1600x1600 in under 60 s on the owner's machine, with the measured number in
  the README, and the golden test passes.

### M3. Harden both servers and add lint

- [ ] Validate `/render` query params: bad value or unknown `mode` returns a
      400 JSON body with a plain-language message, never a traceback.
- [ ] Add `model=<name>` to `/render`, restricted to the names `/models`
      returns, so the endpoint is no longer pinned to `father-day.ply`.
- [ ] Bind `render_splats.serve` to `127.0.0.1` by default with a `--host`
      flag for opting in to LAN access.
- [ ] Add `ruff` config and a pre-commit hook that runs it; fix what it finds.
- Done when: tests cover bad-param -> 400, `model=` selection and the default
  bind address; `pre-commit run --all-files` is clean and the hook is
  installed from a committed `.pre-commit-config.yaml`.

### M4. Test the WebGL viewer headlessly

- [ ] Playwright + Chromium (SwiftShader) test: start `serve.py` on a temp dir
      with the synthetic PLY and the real `index.html`, load the page, select
      the model, wait for a frame, assert non-blank canvas pixels and zero
      console errors.
- [ ] Golden-image comparison per G-buffer mode (albedo, baked, irradiance,
      normals, relit) on the synthetic sphere.
- [ ] GitHub Actions workflow running `pytest` including the viewer test on
      `ubuntu-latest`, with `git lfs` skipped (the tests do not need the
      scenes).
- Done when: `tests/test_viewer.py` passes in CI and the run uploads the five
  mode screenshots as an artifact.

### M5. Better separation from a single PLY

- [ ] Expose `separate_lighting(grid_res, blur passes)` as parameters and map
      a "Retinex strength" slider to them in the viewer.
- [ ] Use the `f_rest_*` SH bands to estimate a view-independent diffuse term
      instead of DC only, and feed the residual into the specular estimate.
- [ ] Add a dynamic occlusion term for the new lights (voxel-grid opacity
      accumulation along the light direction) so baked shadows are not the
      only shadows.
- Done when: side-by-side renders of `Buttons.ply` under two opposite light
  directions, committed under `docs/`, show no residual capture-time shadow
  direction, with the owner's sign-off recorded in this file.

## Won't do / out of scope

- Full inverse rendering (GS-IR, GaussianShader, IRGS): needs the original
  multi-view captures and a GPU training loop. Per the design notes, that is a
  separate pipeline whose output this viewer would consume as Stage 4.
- HDR environment-map recovery and per-Gaussian roughness/metallic
  optimization (globals only, by design of the single-asset path).
- GPU acceleration of the Python renderer (CuPy, Taichi). It is a reference
  implementation; numpy vectorization (M2) is the ceiling.
- Committing render outputs. `rendered_*.png` and `test_out.png` stay
  gitignored.
- Moving the sample scenes off Git LFS unless the owner answers question 3.

## Open questions for the owner

1. Which tool exported `Buttons.ply` and `father-day.ply`? M1 assumes the
   standard `rot_0 = w` layout that `index.html` uses; confirming the exporter
   settles it without guessing from renders.
2. Is the CPU renderer meant to stay a reference for the shader, or to become
   the offline high-resolution path? If reference only, M2 can be deprioritized
   and `stride` is enough.
3. The two LFS scenes total about 158 MB. Is GitHub LFS bandwidth acceptable
   for this, or should the scenes move to a release asset or external bucket
   with a download script?
4. Should the viewer be published (GitHub Pages)? That decides whether M4 needs
   a real CI browser or a local-only test.
5. `Relighting 3D Gaussian Splatting.md` is 130 KB, mostly inline base64
   images. Keep it as is, or move it to `docs/` with the images extracted to
   files?
