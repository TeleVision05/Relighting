// Light locators: a halo at each light, plus a beam line for spots and suns. Drawn in both
// panes: the cameras are synchronised, so seeing the lights against the untouched
// reference is what makes their positions legible relative to the geometry.

import { getCamPos, viewRot, focalFor } from './camera.js';
import { DIR_GIZMO_DIST, hexRGB, lightAim, lightGizmoPos } from './lights.js';

// Uniform setter for `prog` with the camera uniforms already set; returns the lookup.
export function setCameraUniforms(gl, prog, cam, w, h) {
  const u = (n) => gl.getUniformLocation(prog, n);
  const R = viewRot(cam);
  gl.uniform2f(u('uViewport'), w, h);
  gl.uniform3fv(u('uCamPos'), getCamPos(cam));
  gl.uniform3f(u('uR0'), R[0], R[1], R[2]);
  gl.uniform3f(u('uR1'), R[3], R[4], R[5]);
  gl.uniform3f(u('uR2'), R[6], R[7], R[8]);
  gl.uniform1f(u('uFocal'), focalFor(w, h));
  return u;
}

function drawBeams(gl, r, cam, lights, w, h) {
  gl.useProgram(r.lineProg);
  gl.bindVertexArray(r.lineVao);
  const u = setCameraUniforms(gl, r.lineProg, cam, w, h);
  for (const l of lights) {
    if (l.type === 'point') continue;
    const p = lightGizmoPos(l),
      a = lightAim(l);
    const len = l.type === 'dir' ? DIR_GIZMO_DIST : Math.max(0.6, l.range);
    gl.uniform3f(u('uA'), p[0], p[1], p[2]);
    gl.uniform3f(u('uB'), p[0] + a[0] * len, p[1] + a[1] * len, p[2] + a[2] * len);
    gl.uniform1f(u('uWidth'), 1.6);
    gl.uniform3fv(u('uColor'), hexRGB(l.color));
    gl.uniform1f(u('uDim'), 0.45 + 0.55 * Math.min(1, l.intensity));
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }
}

function drawHalos(gl, r, cam, lights, w, h) {
  gl.useProgram(r.gizProg);
  gl.bindVertexArray(r.gizVao);
  const u = setCameraUniforms(gl, r.gizProg, cam, w, h);
  for (const l of lights) {
    const p = lightGizmoPos(l);
    gl.uniform3f(u('uLightPos'), p[0], p[1], p[2]);
    gl.uniform1f(u('uWorldRadius'), l.type === 'dir' ? 0.5 : 0.35);
    gl.uniform3fv(u('uColor'), hexRGB(l.color));
    // Still visible (dimmed) at low intensity so you can place it first.
    gl.uniform1f(u('uDim'), 0.4 + 0.6 * Math.min(1, l.intensity));
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }
}

// `r` is a Renderer (it owns the programs and VAOs).
export function drawGizmos(r, cam, ui, w, h) {
  if (!ui || !ui.showGizmos || !ui.lightList.length) return;
  const gl = r.gl;
  gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA); // premultiplied, additive-ish
  // Beam lines first so the halo sits on top of its own line.
  drawBeams(gl, r, cam, ui.lightList, w, h);
  drawHalos(gl, r, cam, ui.lightList, w, h);
  gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
  gl.bindVertexArray(null);
}
