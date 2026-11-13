// One WebGL2 pane: the baked reference (relit = false) or the relit view (relit = true).

import { ViewerError } from './errors.js';
import { drawGizmos, setCameraUniforms } from './gizmos.js';
import { glCheck, mkProg } from './gl.js';
import { GIZMO_FRAG, GIZMO_VERT, LINE_FRAG, LINE_VERT } from './shaders/overlay.js';
import { FRAG_NEUTRAL, FRAG_RELIT } from './shaders/splat-frag.js';
import { VERT } from './shaders/splat-vert.js';

const CORNERS = new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]);

function contextFor(canvas) {
  const gl = canvas.getContext('webgl2', {
    antialias: false,
    alpha: false,
    premultipliedAlpha: false,
  });
  if (!gl) throw new ViewerError('webgl2', 'WebGL2 not available');
  gl.clearColor(0.01, 0.015, 0.035, 1);
  gl.enable(gl.BLEND);
  gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
  gl.disable(gl.DEPTH_TEST);
  return gl;
}

function setTexParams(gl, target, filter) {
  gl.texParameteri(target, gl.TEXTURE_MIN_FILTER, filter);
  gl.texParameteri(target, gl.TEXTURE_MAG_FILTER, filter);
  gl.texParameteri(target, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(target, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  if (target === gl.TEXTURE_3D) gl.texParameteri(target, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE);
}

// A GL out-of-memory during an upload means the scene does not fit on this GPU.
function checkUpload(gl, label) {
  if (glCheck(gl, label) === gl.OUT_OF_MEMORY) {
    throw new ViewerError('out-of-memory', `GL OUT_OF_MEMORY during ${label}`);
  }
}

export class Renderer {
  constructor(canvas, relit) {
    this.canvas = canvas;
    this.relit = relit;
    const gl = (this.gl = contextFor(canvas));

    this.progN = mkProg(gl, VERT, FRAG_NEUTRAL);
    this.progR = mkProg(gl, VERT, FRAG_RELIT);
    this.prog = relit ? this.progR : this.progN;

    // Quad corner buffer (static)
    this.cornerBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.cornerBuf);
    gl.bufferData(gl.ARRAY_BUFFER, CORNERS, gl.STATIC_DRAW);

    // Light markers: halo + beam line, each its own program over the corner quad
    this.gizProg = mkProg(gl, GIZMO_VERT, GIZMO_FRAG);
    this.gizVao = this._quadVao(this.gizProg);
    this.lineProg = mkProg(gl, LINE_VERT, LINE_FRAG);
    this.lineVao = this._quadVao(this.lineProg);

    // Per-frame instance input: one uint splat id, sorted far→near
    this.idxBuf = gl.createBuffer();
    this.vao = gl.createVertexArray();
    this.texGeom = null;
    this.texShade = null;
    this.geomW = 0;
    this.shadeW = 0;
    this.N = 0; // instances to draw this frame
    this._initVAO();
  }

  // VAO binding just the static corner quad, for the overlay programs.
  _quadVao(prog) {
    const gl = this.gl;
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    this._bindCorners(prog);
    gl.bindVertexArray(null);
    return vao;
  }

  _bindCorners(prog) {
    const gl = this.gl;
    const loc = gl.getAttribLocation(prog, 'aCorner');
    gl.bindBuffer(gl.ARRAY_BUFFER, this.cornerBuf);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    gl.vertexAttribDivisor(loc, 0);
  }

  _initVAO() {
    const gl = this.gl;
    gl.bindVertexArray(this.vao);
    this._bindCorners(this.prog); // quad corners: per-vertex
    // Splat id: per-instance, integer attribute
    const il = gl.getAttribLocation(this.prog, 'aIndex');
    if (il >= 0) {
      gl.bindBuffer(gl.ARRAY_BUFFER, this.idxBuf);
      gl.enableVertexAttribArray(il);
      gl.vertexAttribIPointer(il, 1, gl.UNSIGNED_INT, 0, 0);
      gl.vertexAttribDivisor(il, 1);
    }
    gl.bindVertexArray(null);
  }

  // Build a texture holding `texelsPerSplat` RGBA texels per splat.
  _makeTex(arr, texelsPerSplat, n, internalFormat, type) {
    const gl = this.gl;
    const maxW = gl.getParameter(gl.MAX_TEXTURE_SIZE);
    const w = Math.min(2048, maxW);
    const h = Math.ceil((n * texelsPerSplat) / w);
    if (h > maxW)
      throw new ViewerError('too-large', `Model too large for GPU textures (${n} splats)`);
    // The upload must cover whole rows. pack.js already pads to them; copy only if not.
    const size = w * h * 4;
    let padded = arr;
    if (arr.length !== size) {
      padded = new arr.constructor(size);
      padded.set(arr.subarray(0, Math.min(arr.length, size)));
    }
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    setTexParams(gl, gl.TEXTURE_2D, gl.NEAREST);
    gl.texImage2D(gl.TEXTURE_2D, 0, internalFormat, w, h, 0, gl.RGBA, type, padded);
    checkUpload(gl, 'texImage2D');
    return { tex, w };
  }

  // Shadow density volume — R8, linearly filtered for soft edges.
  _makeOcc(o) {
    const gl = this.gl;
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_3D, tex);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    setTexParams(gl, gl.TEXTURE_3D, gl.LINEAR);
    const R = o.res;
    gl.texImage3D(gl.TEXTURE_3D, 0, gl.R8, R, R, R, 0, gl.RED, gl.UNSIGNED_BYTE, o.data);
    checkUpload(gl, 'texImage3D');
    return tex;
  }

  // Called once per model load. `packed` comes from packSplats().
  uploadStatic(packed) {
    const gl = this.gl;
    for (const t of [this.texGeom, this.texShade, this.texOcc]) if (t) gl.deleteTexture(t);
    const g = this._makeTex(packed.geom, 3, packed.N, gl.RGBA32F, gl.FLOAT);
    const s = this._makeTex(packed.shade, 4, packed.N, gl.RGBA16F, gl.HALF_FLOAT);
    this.texGeom = g.tex;
    this.geomW = g.w;
    this.texShade = s.tex;
    this.shadeW = s.w;
    const o = packed.occ;
    this.texOcc = this._makeOcc(o);
    this.grid = {
      min: o.min,
      invExt: [1 / o.ext[0], 1 / o.ext[1], 1 / o.ext[2]],
      diag: Math.hypot(o.ext[0], o.ext[1], o.ext[2]),
    };
    this.N = 0;
    this._drawChecked = false;
    // Preallocate the index buffer at full size; each frame refills a prefix.
    gl.bindBuffer(gl.ARRAY_BUFFER, this.idxBuf);
    gl.bufferData(gl.ARRAY_BUFFER, packed.N * 4, gl.DYNAMIC_DRAW);
    checkUpload(gl, 'index buffer');
  }

  // Called whenever a new sort arrives — the only per-camera-move upload.
  setOrder(order, count) {
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.idxBuf);
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, order, 0, count);
    this.N = count;
  }

  resize() {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.canvas.width = Math.max(1, Math.floor(rect.width * dpr));
    this.canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  }

  _bindTextures(u) {
    const gl = this.gl;
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.texGeom);
    gl.uniform1i(u('uGeom'), 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.texShade);
    gl.uniform1i(u('uShade'), 1);
    gl.uniform1i(u('uGeomW'), this.geomW);
    gl.uniform1i(u('uShadeW'), this.shadeW);
    // uOcc must ALWAYS point at a unit holding a 3D texture, even when shadows
    // are off. Two samplers of different types on one unit is a draw-time
    // INVALID_OPERATION, and an unset sampler defaults to unit 0 — where uGeom
    // (2D) lives. Leaving this inside the shadow branch silently killed every
    // draw in the reference pane.
    gl.activeTexture(gl.TEXTURE2);
    gl.bindTexture(gl.TEXTURE_3D, this.texOcc);
    gl.uniform1i(u('uOcc'), 2);
  }

  // Shadow volume + march settings (vertex stage). The reference pane keeps
  // uShadowOn = 0, which skips the march entirely.
  _setShadowUniforms(u, ui) {
    const gl = this.gl;
    const shadowOn = this.relit && ui.shadows && ui.lights.n > 0;
    gl.uniform1i(u('uShadowOn'), shadowOn ? 1 : 0);
    if (!shadowOn) return;
    gl.uniform3fv(u('uGridMin'), this.grid.min);
    gl.uniform3fv(u('uGridInvExt'), this.grid.invExt);
    gl.uniform1f(u('uGridDiag'), this.grid.diag);
    gl.uniform1i(u('uShadowSteps'), ui.shSteps);
    gl.uniform1f(u('uShadowStrength'), ui.shStrength);
    gl.uniform1f(u('uShadowBias'), ui.shBias);
    gl.uniform1f(u('uShadowReach'), ui.shReach * this.grid.diag);
    gl.uniform1fv(u('uLShadow[0]'), ui.lights.shadow);
  }

  _setRelitUniforms(u, ui) {
    const gl = this.gl;
    const L = ui.lights;
    gl.uniform3fv(u('uAmbCol'), ui.aCol);
    gl.uniform1f(u('uAmbInt'), ui.aInt);
    gl.uniform1f(u('uExposure'), ui.expo);
    gl.uniform1i(u('uNumLights'), L.n);
    if (L.n > 0) {
      gl.uniform1iv(u('uLType[0]'), L.type);
      gl.uniform3fv(u('uLPos[0]'), L.pos);
      gl.uniform3fv(u('uLDir[0]'), L.dir);
      gl.uniform3fv(u('uLCol[0]'), L.col);
      gl.uniform1fv(u('uLInt[0]'), L.inten);
      gl.uniform1fv(u('uLRange[0]'), L.range);
      gl.uniform2fv(u('uLCone[0]'), L.cone);
    }
    gl.uniform1f(u('uRough'), ui.rough);
    gl.uniform1f(u('uMetal'), ui.metal);
    gl.uniform1f(u('uSpec'), ui.spec);
    gl.uniform1f(u('uSep'), ui.sep);
    gl.uniform1f(u('uKeepAO'), ui.keepAO);
    gl.uniform1f(u('uNSmooth'), ui.nSmooth);
    gl.uniform1i(u('uGBuf'), ui.gbuf);
  }

  render(cam, ui) {
    const gl = this.gl;
    const w = this.canvas.width,
      h = this.canvas.height;
    if (!w || !h) return;
    gl.viewport(0, 0, w, h);
    gl.clear(gl.COLOR_BUFFER_BIT);
    if (this.N && this.texGeom) this._drawSplats(cam, ui, w, h);
    drawGizmos(this, cam, ui, w, h);
  }

  _drawSplats(cam, ui, w, h) {
    const gl = this.gl;
    gl.useProgram(this.prog);
    gl.bindVertexArray(this.vao);
    const u = setCameraUniforms(gl, this.prog, cam, w, h);
    this._bindTextures(u);
    this._setShadowUniforms(u, ui);
    if (this.relit) this._setRelitUniforms(u, ui);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, this.N);
    // Check once per model load: a draw that fails validation renders nothing
    // and reports nothing, which is otherwise invisible until you notice a
    // blank pane. getError stalls the pipeline, so this is not a per-frame cost.
    if (!this._drawChecked) {
      this._drawChecked = true;
      glCheck(gl, `draw (${this.relit ? 'relit' : 'baked'} pane)`);
    }
    gl.bindVertexArray(null);
  }
}
