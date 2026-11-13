// Small WebGL2 helpers. Failures throw ViewerError('shader'); the GLSL log and numbered
// source go in the error's detail, which only the console sees.

import { ViewerError } from './errors.js';

// Logs and returns the pending GL error code (gl.NO_ERROR when there is none).
export function glCheck(gl, label) {
  const e = gl.getError();
  if (e !== gl.NO_ERROR) console.error(`GL error ${label}: 0x${e.toString(16)}`);
  return e;
}

function numbered(src) {
  return src
    .split('\n')
    .map((l, i) => `${i + 1}: ${l}`)
    .join('\n');
}

export function mkShader(gl, type, src) {
  const s = gl.createShader(type);
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
    throw new ViewerError(
      'shader',
      `Shader compile: ${gl.getShaderInfoLog(s)}\n---\n${numbered(src)}`,
    );
  }
  return s;
}

export function mkProg(gl, vs, fs) {
  const p = gl.createProgram();
  gl.attachShader(p, mkShader(gl, gl.VERTEX_SHADER, vs));
  gl.attachShader(p, mkShader(gl, gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
    throw new ViewerError('shader', `Link: ${gl.getProgramInfoLog(p)}`);
  }
  return p;
}
