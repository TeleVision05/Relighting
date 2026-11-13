// Entry point: builds the two panes, wires the controls, loads the first scene and runs the
// render loop. index.html loads this as a module; there is no build step.

import {
  DEFAULT_VIEW,
  attachOrbit,
  focalFor,
  getCamPos,
  makeCamera,
  parseCamParam,
  viewRot,
} from './camera.js';
import { bindModelControls, refreshModelList, setLoadingButton } from './model-picker.js';
import { Renderer } from './renderer.js';
import { isLocalHost } from './fetch-scene.js';
import { loadScene, sourceName } from './scene-loader.js';
import { SplatSorter } from './sort.js';
import { overallProgress } from './stages.js';
import { setNotice, setProgress, setStatus, showError, stageLabel, statusEl } from './status.js';
import { installTestHook, testControl } from './test-hook.js';
import { applyPreset, getUI, initControls } from './ui.js';

const URL_PARAMS = new URLSearchParams(location.search);
const TEST_MODE = URL_PARAMS.get('test') === '1';
// Cache-busting query strings only on a local dev server (see isLocalHost).
const LOCAL_DEV = isLocalHost(location.hostname);
// Default model: ?ply=… query param wins. Otherwise a local copy opens its own sample scene,
// and a hosted copy (GitHub Pages) the small demo scene published with it. Both are relative
// to the page, so the viewer works from any sub-path such as /Relighting/.
const DEFAULT_PLY = LOCAL_DEV ? './father-day.ply' : './demo/demo-scene.ply';
const INITIAL_PLY = URL_PARAMS.get('ply') || DEFAULT_PLY;
// The demo scene is small (about 3 units across), so it opens closer than the sample scenes.
const DEMO_CAM = '0.5,0.35,5.5';
const INITIAL_CAM =
  URL_PARAMS.get('cam') || (INITIAL_PLY === DEFAULT_PLY && !LOCAL_DEV ? DEMO_CAM : null);
const nextTask = () => new Promise((r) => setTimeout(r, 0));

function createPanes() {
  const canvL = document.createElement('canvas');
  const canvR = document.createElement('canvas');
  document.getElementById('pL').appendChild(canvL);
  document.getElementById('pR').appendChild(canvR);
  const rL = new Renderer(canvL, false);
  const rR = new Renderer(canvR, true);
  const camL = makeCamera(),
    camR = makeCamera();
  const camParam = parseCamParam(INITIAL_CAM);
  if (camParam) for (const c of [camL, camR]) Object.assign(c, camParam);
  attachOrbit(canvL, camL, camR);
  attachOrbit(canvR, camR, camL);
  return { rL, rR, camL, camR };
}

// Drag the divider between the panes to resize them.
function bindDivider(onResize) {
  const divider = document.getElementById('divider');
  const vbox = document.getElementById('vbox');
  let down = false,
    x0 = 0,
    w0 = 0;
  divider.addEventListener('pointerdown', (e) => {
    down = true;
    x0 = e.clientX;
    w0 = vbox.querySelectorAll('.vpane')[0].offsetWidth;
    divider.classList.add('dragging');
    divider.setPointerCapture(e.pointerId);
  });
  divider.addEventListener('pointermove', (e) => {
    if (!down) return;
    const panes = vbox.querySelectorAll('.vpane');
    const total = vbox.offsetWidth - 4;
    const nw = Math.max(120, Math.min(total - 120, w0 + e.clientX - x0));
    panes[0].style.flex = 'none';
    panes[0].style.width = nw + 'px';
    panes[1].style.flex = '1';
    panes[1].style.width = '';
    onResize();
  });
  divider.addEventListener('pointerup', () => {
    down = false;
    divider.classList.remove('dragging');
  });
}

class Viewer {
  constructor(panes) {
    Object.assign(this, panes);
    this.data = null;
    this.loading = false;
    // { start, fetched, end } of the last successful load, performance.now() ms; fetched is
    // when the bytes were in (the first non-download progress message).
    this.loadTimes = null;
    this.prevHash = '';
    this.frameCount = 0;
    this.lastFPS = performance.now();
    this.sortedCount = 0;
    this.lastSortMs = 0;
    this.sortT0 = performance.now();
    // One sort feeds both panes — the cameras are kept in lockstep.
    this.sorter = new SplatSorter((order, count) => {
      this.lastSortMs = performance.now() - this.sortT0;
      if (count > 0) {
        this.rL.setOrder(order, count);
        this.rR.setOrder(order, count);
      }
      this.sortedCount = count;
    });
    this.frame = this.frame.bind(this);
  }

  resize() {
    this.rL.resize();
    this.rR.resize();
    this.camL.dirty = this.camR.dirty = true;
  }

  resetView() {
    applyPreset('studio');
    for (const c of [this.camL, this.camR]) Object.assign(c, DEFAULT_VIEW, { dirty: true });
  }

  // Status line and progress bar for one progress message from the loader.
  _showProgress(p, source, times) {
    if (p.stage !== 'download' && !times.fetched) times.fetched = performance.now();
    const name = sourceName(source);
    setStatus(stageLabel({ ...p, name, local: typeof source !== 'string' }), 'busy');
    setProgress(overallProgress(p.stage, p.within));
  }

  // Fetch, parse and preprocess in the load worker, then upload to both panes. `reload`
  // (the Reload button) asks the browser for a fresh copy instead of a cached one.
  async loadModel(source, { reload = false } = {}) {
    if (this.loading) return;
    this.loading = true;
    setLoadingButton(true);
    const wasEmpty = !this.data;
    const times = { start: performance.now(), fetched: 0 };
    const onProgress = (p) => this._showProgress(p, source, times);
    try {
      onProgress({ stage: 'download', within: 0 });
      const request = { bust: LOCAL_DEV, fresh: LOCAL_DEV || reload };
      const next = await loadScene(source, { request, onProgress });
      onProgress({ stage: 'upload', within: 0 });
      await nextTask();
      this.rL.uploadStatic(next.packed);
      this.rR.uploadStatic(next.packed);
      this.data = next;
      this.sorter.setModel(next);
      this.prevHash = ''; // force a re-sort
      this.camL.dirty = this.camR.dirty = true;
      this.loadTimes = { ...times, end: performance.now() };
      setStatus(`Loaded ${next.N.toLocaleString()} splats`, 'ok');
      setNotice(null);
      if (wasEmpty) this.frame(); // start the render loop on first success
    } catch (e) {
      // With a scene already on screen, the status line is enough; without one, the panes
      // would be empty, so the message goes over them too.
      showError(e, { notice: !this.data });
    } finally {
      this.loading = false;
      setLoadingButton(false);
      setProgress(null);
    }
  }

  testState() {
    return {
      loaded: !!this.data && !this.loading,
      n: this.data ? this.data.N : 0,
      sorted: this.sortedCount,
      settled:
        !!this.data &&
        !this.loading &&
        !this.sorter.busy &&
        !this.sorter.pending &&
        this.prevHash !== '',
      status: statusEl().textContent,
      loadTimes: this.loadTimes,
    };
  }

  // Only the splat *order* depends on the camera, so a stale order just means slightly
  // wrong blending for a frame or two — never a stall.
  _requestSort(w, h) {
    const cam = this.camL;
    const hash = `${cam.yaw.toFixed(3)},${cam.pitch.toFixed(3)},${cam.zoom.toFixed(3)},${w},${h}`;
    if (hash === this.prevHash && !cam.dirty) return;
    this.sortT0 = performance.now();
    this.sorter.request({ R: viewRot(cam), cp: getCamPos(cam), focal: focalFor(w, h), w, h });
    this.prevHash = hash;
    this.camL.dirty = this.camR.dirty = false;
  }

  _reportFPS() {
    this.frameCount++;
    const now = performance.now();
    if (now - this.lastFPS < 900) return;
    const fps = Math.round((this.frameCount * 1000) / (now - this.lastFPS));
    if (!this.loading) {
      const n = this.data.N.toLocaleString();
      const ms = this.lastSortMs.toFixed(1);
      setStatus(
        `${this.sortedCount.toLocaleString()}/${n} splats | ${fps} FPS | sort ${ms}ms`,
        'ok',
      );
    }
    this.frameCount = 0;
    this.lastFPS = now;
  }

  frame() {
    requestAnimationFrame(this.frame);
    if (!this.data || testControl.paused) return; // nothing loaded / load failed / test paused
    const ui = getUI();
    this._requestSort(this.rL.canvas.width, this.rL.canvas.height);
    this.rL.render(this.camL, ui);
    this.rR.render(this.camR, ui);
    this._reportFPS();
  }
}

async function main() {
  initControls();
  let panes;
  try {
    panes = createPanes();
  } catch (e) {
    showError(e, { fallback: 'webgl2', notice: true });
    return;
  }
  const viewer = new Viewer(panes);
  bindDivider(() => viewer.resize());
  window.addEventListener('resize', () => viewer.resize());
  viewer.resize();
  document.getElementById('resetBtn').addEventListener('click', () => viewer.resetView());
  bindModelControls(INITIAL_PLY, (source, opts) => viewer.loadModel(source, opts));
  if (TEST_MODE) {
    const p = viewer;
    installTestHook(
      [
        [p.rL, p.camL],
        [p.rR, p.camR],
      ],
      () => viewer.testState(),
    );
  }
  refreshModelList(INITIAL_PLY);
  await viewer.loadModel(INITIAL_PLY);
}

main().catch((e) => showError(e, { fallback: 'startup', notice: true }));
