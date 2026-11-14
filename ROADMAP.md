# Roadmap

## Current state (2026-09-25)

Status: **experimental**. Interactive relighting of a single baked 3D Gaussian
Splatting `.ply`, no training loop, no GPU dependency.

What works, and how it was verified:

| Piece | What it does | Verified by |
| --- | --- | --- |
| `serve.py` | stdlib static server for the viewer: `/models` lists `*.ply`, no-cache headers, opens a browser | `tests/test_smoke.py::test_static_viewer_server_lists_models` |
| `index.html` + `src/` (ES modules) | WebGL2 viewer, split pane (left: baked reference, right: relit). Parses the PLY client-side by header (float or byte-encoded colour/opacity, `nxx` typo tolerated), Retinex albedo/irradiance split, shortest-axis normals blended toward a voxel-smoothed field (`N Smooth`), Cook-Torrance/GGX on intrinsic albedo, up to 8 dir/point/spot lights (`MAX_LIGHTS = 8`), ray-marched shadows through a per-model density volume (`traceShadow`, Shadows panel: reach/quality/bias/strength), six G-buffer modes, four presets, `Separate` / `Keep AO` sliders, model picker | ~~manual only; no automated test loads the page in a browser~~ Corrected 2026-11-13: browser tests in `tests/viewer/` (headless Chromium) and Node unit tests of the pure modules in `tests/js/` (`npm test`) |
| `render_splats.py` + `cpu_render/` | numpy CPU reference: `load_ply`, `separate_lighting`, `render_png` in `relit` / `neutral` / `albedo` / `normals` modes (one directional + one point light, no shadows, no normal smoothing), viewer frame and orbit camera, EWA projection of the full covariance, tile-based front-to-back compositing; `--serve` adds `GET /render`, `/models`, `/reload` | `tests/test_smoke.py`, `tests/test_cpu_render.py`, `tests/viewer/test_cpu_reference.py`, and `tests/viewer/test_cpu_parity.py` (CPU against the viewer, same camera; added 2026-11-13) |
| Sample scenes | `Buttons.ply` (249,973 splats, 41 MB), `father-day.ply` (471,299 splats, 117 MB) in Git LFS | `git lfs ls-files --size` shows both; `git lfs push --dry-run origin main` is empty (objects are on the remote) |

Test run on 2026-09-25 (`.venv/bin/python -m pytest -q`, Python 3.14.5):
`8 passed in 3.47s`.
The suite renders 1,500 synthetic splats at 256x256; it never touches the LFS
scenes and never opens a browser.

Repo hygiene: README, ROADMAP, requirements, pytest.ini, smoke tests and
.gitignore landed 2026-09-25 (`git log --oneline -3`). No linter, no
pre-commit hook (the only non-sample files in `.git/hooks` are git-lfs's
pre-push / post-commit / post-checkout / post-merge), no `.github/`, no CI.

## Known gaps and bugs

1. ~~**Quaternion component order disagrees between the two renderers.**~~
   Corrected 2026-11-13: `cpu_render/frame.py` reads `rot_0 = w` and applies the
   same 180 degree X turn as the viewer; `tests/synthetic.py` stores real
   `rot_0 = w` rotations; `tests/viewer/test_cpu_reference.py` checks CPU normals
   against analytic ones and fails under the old order (checked by mutation).
   Evidence for the order on a real file: on `Buttons.ply`, thin-axis normals
   agree with local surface fits at a median 27.5 degrees reading `rot_0 = w`
   and 58.8 degrees reading `rot_3 = w` (142 flat splats; random is about 60).
   The original finding, for the record:
   The viewer (`src/frame.js` `worldQuaternion`; was `index.html:952` before the
   2026-11-13 module split) reads `rot_0=w, rot_1=x, rot_2=y, rot_3=z` (the standard
   3DGS export convention). `render_splats.py::load_ply` unpacks
   `qx, qy, qz, qw = rot_0..rot_3` and `render_png` calls
   `quat_to_matrix(rot0, rot1, rot2, rot3)` whose signature is `(qx, qy, qz, qw)`.
   On a real export the CPU normals and splat orientations are therefore
   rotated wrongly. The test fixture (`tests/test_smoke.py::write_synthetic_ply`,
   `data[:, 13] = 1.0` with the comment "identity quaternion (x,y,z,w)") encodes
   the CPU convention, so the tests cannot catch this.
2. ~~**CPU 2D covariance uses only `scale_0`.**~~ Corrected 2026-11-13:
   `cpu_render/project.py` builds `R diag(s^2) R^T` from all three scales and
   projects it with the full perspective Jacobian. Doing so exposed the
   matching bug in the viewer: its shader used a scaled orthographic Jacobian
   (no depth column), 40-80% off for off-axis splats against sampled points.
   The shader now uses the full Jacobian too. Original finding: `render_png` builds `cov00/01/11`
   from `basis_xv` and `s0 = exp(clamp(scale_0)) * 0.0025 * scale2d`; `basis_yv`
   is computed and never used, `scale_1`/`scale_2` are never read. The shader
   (`src/shaders/splat-vert.js`, `VERT`, `fd2 * dot(m0*m0, sc2)`) uses all three. Every CPU
   splat is a scaled disc aligned to one axis, not the real ellipse.
3. ~~**Per-pixel Python loop.**~~ Corrected 2026-11-13: `cpu_render/raster.py`
   composites front to back in 16 px tiles with NumPy. `Buttons.ply` at
   800x600 went from 24.9 s (neutral) and 40.3 s (relit) to about 4.3 s each,
   and, timed back to back at a load average near 200, from 109.3 s and 99.8 s
   to 7.1 s and 7.3 s (Apple M2 Max, 2026-11-13). Original finding: The compositing in `render_png` is a nested
   `for j / for k` over every pixel of every splat's bounding box. Full-size
   renders (default 1600x1600) of the sample scenes take minutes; that is what
   the `_RENDER_TIMEOUT = 300` guard exists for. The README already tells
   users to pass small `w`/`h` or `stride`.
4. ~~**Different world convention.**~~ Corrected 2026-11-13: the CPU renderer
   uses the viewer's frame, orbit camera and focal length, and `yaw`, `pitch`,
   `zoom` are on `render_png`, `/render` and the command line. The parity test
   measured at most 0.39/255 mean difference on the fixtures and 0.56/255 on
   `Buttons.ply` at the default view. Original finding: The viewer negates Y and Z at load
   (`src/frame.js` `worldPosition`; was `index.html:931-932`) and composes a 180 degree X rotation into the
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
7. ~~**WebGL viewer is untested.** `test_static_viewer_server_lists_models`
   serves a stub `<html></html>`, not the real page. Shader compile errors or a
   broken PLY parse in `index.html` would not fail any test.~~ Corrected
   2026-11-13: `tests/viewer/` loads the real page in headless Chromium and
   checks images against scenes with known geometry, and `tests/js/` unit-tests
   the parser, frame conversion, lighting split and normals directly. Breaking
   the quaternion remap or the Y/Z flip fails both suites (checked by mutation).
8. **Higher-order SH bands (`f_rest_*`) are ignored** by both renderers; only
   DC is used for appearance (documented in the design notes as intentional
   for albedo, but it also throws away the view-dependent signal that could
   help separate specular from diffuse).
9. **No lint or pre-commit hook.** The house rule requires one; nothing in
   this repo enforces formatting or catches unused code such as `basis_yv`.
10. **CPU renderer is far behind the viewer in features.** The viewer has up
    to 8 lights of three types, ray-marched shadows, voxel-smoothed normals,
    six G-buffer modes and byte-encoded PLY support; `render_splats.py` has
    one directional + one point light, no shadows, raw normals, three modes,
    and `load_ply` collects only `property float` lines then reshapes the
    whole body as float32, so any PLY with a `uchar` property is mis-read.
    "Reference renderer" therefore means reference for geometry and the
    Retinex split only, not for the lit result.
    Corrected 2026-11-13 in part: `cpu_render/plyio.py` reads the PLY by the
    header's property types (byte colours and opacity, doubles), and there are
    four modes (`normals` added). Lights, shadows and normal smoothing are still
    behind the viewer, so the lit result is still not a reference.

## Milestones

### M1. Make the two renderers agree on geometry (done 2026-11-13)

- [x] Switch the CPU renderer to `rot_0 = w`, matching the viewer
      (`cpu_render/frame.py` `world_quaternions`, `src/frame.js` `worldQuaternion`).
- [x] Fix `write_synthetic_ply`: it now stores real `rot_0 = w` rotations whose
      thin axis is radial, and `tests/viewer/test_cpu_reference.py` asserts CPU
      normals against the analytic normals of fixtures with awkward quaternions.
- [x] Use all three scales: full 3D covariance, projected with the perspective
      Jacobian (`cpu_render/project.py`); the `0.0025` factor and `basis_yv` are gone.
- [x] Apply the viewer's Y/Z negation in the CPU path and expose `yaw`, `pitch`,
      `zoom` on `render_png`, `/render` and the command line.
- Done when: ~~a CPU render and a viewer screenshot of `Buttons.ply` are committed
  side by side under `docs/`~~ replaced by `tests/viewer/test_cpu_parity.py`,
  which compares the two on every browser-test run, within a stated tolerance (mean
  difference under 1 and 99th percentile under 4, of 255). Renders of the demo scene
  (a slimmed `Buttons.ply`, published with the owner's permission, not MIT) are committed
  under `docs/media/`; renders of the other sample scene are not.
  The elongated-splat orientation test is
  `tests/test_cpu_render.py::test_elongated_splat_lands_with_the_projected_orientation`.

### M2. Make the CPU renderer usable at full resolution (done 2026-11-13)

- [x] Replace the per-pixel compositing: tile-based front-to-back NumPy
      compositing (`cpu_render/raster.py`).
- [x] Vectorize projection, culling and inverse covariance across all splats.
- [x] ~~Golden test: PNG hash unchanged by the rewrite~~ not possible, because the
      geometry fixes change the output on purpose. Instead
      `test_tile_rasteriser_equals_back_to_front_over` checks the tiles against a
      plain far-to-near blend of every splat at every pixel.
- [x] Timing for `Buttons.ply` in the README: about 4 to 7 s per image at
      800x600 and 10 to 13 s at 1600x1600 (Apple M2 Max, 2026-11-13).

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
- [ ] Golden-image comparison per G-buffer mode (relit, intrinsic albedo,
      baked SH DC, baked irradiance/AO, surface normals, specular only; the
      six `<option>`s of `#gbuf` in `index.html`) on the synthetic sphere.
- [ ] GitHub Actions workflow running `pytest` including the viewer test on
      `ubuntu-latest`, with `git lfs` skipped (the tests do not need the
      scenes).
- Done when: `tests/test_viewer.py` passes in CI and the run uploads the six
  mode screenshots as an artifact.

### M5. Better separation from a single PLY

- [ ] Expose `separate_lighting(grid_res, blur passes)` as parameters and map
      a "Retinex strength" slider to them in the viewer.
- [ ] Use the `f_rest_*` SH bands to estimate a view-independent diffuse term
      instead of DC only, and feed the residual into the specular estimate.
- [ ] Port the viewer's dynamic shadows to the CPU renderer. The viewer
      already has them (`src/occupancy.js`: density volume
      baked once per model, `traceShadow` marches it toward each light in the
      vertex shader); `render_splats.py` has none, so `/render` output can
      never match the viewer under a new light.
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
   standard `rot_0 = w` layout that the viewer uses; confirming the exporter
   settles it without guessing from renders.
2. Is the CPU renderer meant to stay a reference for the shader, or to become
   the offline high-resolution path? If reference only, M2 can be deprioritized
   and `stride` is enough.
3. The two LFS scenes total about 158 MB. Is GitHub LFS bandwidth acceptable
   for this, or should the scenes move to a release asset or external bucket
   with a download script?
4. ~~Should the viewer be published (GitHub Pages)?~~ Decided 2026-11-13: yes. The `Pages`
   workflow publishes the viewer and `demo/buttons-demo.ply` on every push to `main`;
   CI runs the browser tests in headless Chromium.
5. `Relighting 3D Gaussian Splatting.md` is 130 KB, mostly inline base64
   images. Keep it as is, or move it to `docs/` with the images extracted to
   files?
