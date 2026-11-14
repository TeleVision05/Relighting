/* Sidebar controls: sliders, presets and the light list.
 *
 * Lights live in `rig.lights`; the DOM is rebuilt from it on add/remove and read back
 * every frame by getUI().
 */

import { MAX_LIGHTS, TYPE_LABEL, hexRGB, makeLight, packLights } from './lights.js';
import { PRESETS } from './presets.js';

const $ = (id) => document.getElementById(id);

export const SLIDERS = {
  rough: { v: 'roughV', f: (v) => v.toFixed(2) },
  metal: { v: 'metalV', f: (v) => v.toFixed(2) },
  spec: { v: 'specV', f: (v) => v.toFixed(2) },
  aInt: { v: 'aIntV', f: (v) => v.toFixed(2) },
  expo: { v: 'expoV', f: (v) => v.toFixed(2) },
  shStrength: { v: 'shStrengthV', f: (v) => v.toFixed(1) },
  shSteps: { v: 'shStepsV', f: (v) => v.toFixed(0) },
  shReach: { v: 'shReachV', f: (v) => v.toFixed(2) },
  shBias: { v: 'shBiasV', f: (v) => v.toFixed(2) },
  sep: { v: 'sepV', f: (v) => v.toFixed(2) },
  keepAO: { v: 'keepAOV', f: (v) => v.toFixed(2) },
  nSmooth: { v: 'nSmoothV', f: (v) => v.toFixed(2) },
};

export const rig = { lights: [] };

function row(label, cls, min, max, step, val, fmt) {
  return (
    `<div class="row"><label>${label}</label>` +
    `<input type=range class="${cls}" min=${min} max=${max} step=${step} value=${val}>` +
    `<span class="val">${fmt}</span></div>`
  );
}

function lightRows(l) {
  const deg = (v) => v.toFixed(0) + '°';
  const pos =
    l.type !== 'dir'
      ? row('X', 'lx', -12, 12, 0.1, l.x, l.x.toFixed(1)) +
        row('Y', 'ly', -12, 12, 0.1, l.y, l.y.toFixed(1)) +
        row('Z', 'lz', -12, 12, 0.1, l.z, l.z.toFixed(1)) +
        row('Range', 'lrange', 0.2, 20, 0.1, l.range, l.range.toFixed(1))
      : '';
  const dir = l.type === 'dir';
  const aim =
    l.type !== 'point'
      ? row(dir ? 'Azimuth' : 'Aim az', 'laz', -180, 180, 1, l.az, deg(l.az)) +
        row(dir ? 'Elevation' : 'Aim el', 'lel', -90, 90, 1, l.el, deg(l.el))
      : '';
  const spot =
    l.type === 'spot'
      ? row('Cone', 'lcone', 3, 80, 1, l.cone, deg(l.cone)) +
        row('Softness', 'lsoft', 0, 1, 0.01, l.soft, l.soft.toFixed(2))
      : '';
  return pos + aim + spot;
}

export function lightMarkup(l) {
  return `<div class="light${l.on ? '' : ' off'}" data-id="${l.id}">
    <div class="lhead">
      <input type=checkbox class="len"${l.on ? ' checked' : ''} title="Enable">
      <span class="ltype">${TYPE_LABEL[l.type]}</span>
      <input type=color class="lcol" value="${l.color}">
      <button class="lrm" title="Remove">×</button>
    </div>
    ${row('Intensity', 'lint', 0, 8, 0.05, l.intensity, l.intensity.toFixed(2))}
    ${lightRows(l)}
    <div class="row"><label>Shadow</label><input type=checkbox class="lsh"${l.shadow ? ' checked' : ''}></div>
  </div>`;
}

function setAddButtons(full) {
  for (const b of document.querySelectorAll('[data-add]')) {
    b.disabled = full;
    b.style.opacity = full ? 0.4 : 1;
    b.style.cursor = full ? 'not-allowed' : 'pointer';
    b.title = full ? `Limit is ${MAX_LIGHTS} lights` : '';
  }
}

export function renderLightList() {
  const host = $('lightList');
  host.innerHTML = rig.lights.map(lightMarkup).join('');
  $('lightCountV').textContent = `${rig.lights.length}/${MAX_LIGHTS}`;
  $('noLightsHint').style.display = rig.lights.length ? 'none' : '';
  setAddButtons(rig.lights.length >= MAX_LIGHTS);
  for (const btn of host.querySelectorAll('.lrm')) {
    btn.addEventListener('click', (e) => {
      const id = +e.target.closest('.light').dataset.id;
      rig.lights = rig.lights.filter((l) => l.id !== id);
      renderLightList();
    });
  }
  for (const cb of host.querySelectorAll('.len')) {
    cb.addEventListener('change', (e) =>
      e.target.closest('.light').classList.toggle('off', !e.target.checked),
    );
  }
}

const LIGHT_NUMBERS = [
  ['lint', 'intensity'],
  ['lx', 'x'],
  ['ly', 'y'],
  ['lz', 'z'],
  ['lrange', 'range'],
  ['laz', 'az'],
  ['lel', 'el'],
  ['lcone', 'cone'],
  ['lsoft', 'soft'],
];

function formatLightValue(cls, v) {
  if (cls === 'laz' || cls === 'lel' || cls === 'lcone') return v.toFixed(0) + '°';
  return v.toFixed(cls === 'lint' || cls === 'lsoft' ? 2 : 1);
}

// Read the DOM back into `rig.lights` and return the lights in list order.
export function readLights() {
  const out = [];
  for (const el of $('lightList').querySelectorAll('.light')) {
    const l = rig.lights.find((x) => x.id === +el.dataset.id);
    if (!l) continue;
    l.on = el.querySelector('.len').checked;
    l.shadow = el.querySelector('.lsh').checked;
    l.color = el.querySelector('.lcol').value;
    for (const [cls, key] of LIGHT_NUMBERS) {
      const inp = el.querySelector('.' + cls);
      if (!inp) continue;
      l[key] = parseFloat(inp.value);
      inp.nextElementSibling.textContent = formatLightValue(cls, l[key]);
    }
    out.push(l);
  }
  return out;
}

export function addLight(type) {
  if (rig.lights.length >= MAX_LIGHTS) return;
  readLights(); // keep edits already made
  rig.lights.push(makeLight(type));
  renderLightList();
}

// Every control's current value, with the light rig packed for the shaders.
export function getUI() {
  const s = {};
  for (const [k, m] of Object.entries(SLIDERS)) {
    const val = parseFloat($(k).value);
    s[k] = val;
    $(m.v).textContent = m.f(val);
  }
  s.aCol = hexRGB($('aCol').value);
  s.gbuf = parseInt($('gbuf').value);
  s.showGizmos = $('showGizmos').checked;
  // Markers are drawn for every enabled light, including ones turned down to zero — you
  // need to see where a light is before you can turn it up.
  const enabled = readLights().filter((l) => l.on);
  s.lights = packLights(enabled);
  s.lightList = enabled;
  s.shadows = $('shadows').checked;
  return s;
}

export function applyPreset(name) {
  const p = PRESETS[name];
  if (!p) return;
  for (const [k, v] of Object.entries(p)) {
    if (k === 'lights') continue;
    const el = $(k);
    if (el) el.value = v;
  }
  rig.lights = (p.lights || []).map((cfg) => makeLight(cfg.type, cfg));
  renderLightList();
}

// Wire the preset and light buttons, and start with the studio rig.
export function initControls() {
  for (const b of document.querySelectorAll('[data-add]')) {
    b.addEventListener('click', () => addLight(b.dataset.add));
  }
  $('clearLights').addEventListener('click', () => {
    rig.lights = [];
    renderLightList();
  });
  for (const btn of document.querySelectorAll('[data-p]')) {
    btn.addEventListener('click', () => applyPreset(btn.dataset.p));
  }
  applyPreset('studio');
}
