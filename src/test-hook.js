// ?test=1 only: window.__relightTest lets the browser tests (tests/viewer/) read the panes
// back. capture() renders both panes and reads their pixels in the same task, so the
// result never depends on when the compositor last presented a frame.

import { getUI } from './ui.js';

// Set by __relightTest.pause(): the render loop then skips drawing and captures do it all.
export const testControl = { paused: false };

function bytesToBase64(bytes) {
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000)
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

function readPane(r, w = r.canvas.width, h = r.canvas.height) {
  const px = new Uint8Array(w * h * 4);
  r.gl.readPixels(0, 0, w, h, r.gl.RGBA, r.gl.UNSIGNED_BYTE, px);
  return { w: r.canvas.width, h: r.canvas.height, rgba: bytesToBase64(px) };
}

// panes: [[renderer, camera], ...]; state(): { loaded, n, sorted, settled, status, loadTimes }.
export function installTestHook(panes, state) {
  const renderAll = () => {
    const ui = getUI();
    for (const [r, cam] of panes) r.render(cam, ui);
  };
  const syncAll = () => panes.forEach(([r]) => readPane(r, 1, 1)); // waits for the GPU
  window.__relightTest = {
    state,
    // Stops the render loop from drawing, so software-GL test runs only pay for captures.
    pause(on = true) {
      testControl.paused = on;
    },
    capture() {
      renderAll();
      return panes.map(([r]) => readPane(r));
    },
    renderer() {
      const gl = panes[0][0].gl;
      const ext = gl.getExtension('WEBGL_debug_renderer_info');
      return gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER);
    },
    // Mean milliseconds to render both panes once, waiting for the GPU each time.
    renderMs(n = 10) {
      renderAll();
      syncAll();
      const t0 = performance.now();
      for (let i = 0; i < n; i++) {
        renderAll();
        syncAll();
      }
      return (performance.now() - t0) / n;
    },
  };
}
