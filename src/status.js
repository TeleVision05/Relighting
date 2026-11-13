// The status line at the bottom of the sidebar, the load progress bar, and the notice shown
// over the panes when there is nothing to look at.

import { MESSAGES, errorKind } from './errors.js';

const COLORS = { busy: '#94a3b8', ok: '#34d399', error: '#f87171' };

export const statusEl = () => document.getElementById('status');

// `state` is 'busy', 'ok' or 'error'; it sets the colour and data-state (tests read it).
export function setStatus(text, state) {
  const el = statusEl();
  el.textContent = text;
  if (state) {
    el.style.color = COLORS[state];
    el.dataset.state = state;
  }
}

// Status text for a stage of the load (see STAGES in stages.js).
export function stageLabel(p) {
  switch (p.stage) {
    case 'download': {
      const pct = p.within > 0 ? ` ${Math.round(p.within * 100)}%` : '';
      return (p.local ? `Reading ${p.name}…` : `Downloading ${p.name}…`) + pct;
    }
    case 'parse':
      return `Parsing ${p.n.toLocaleString()} splats (${p.stride} B/vertex)…`;
    case 'normals':
      return 'Fitting surface normals…';
    case 'lighting':
      return 'Separating baked lighting from albedo…';
    case 'pack':
      return 'Building the shadow volume…';
    default:
      return 'Uploading to GPU…';
  }
}

// The bar under the status line: a fraction 0–1 shows it, null hides it.
export function setProgress(fraction) {
  const bar = document.getElementById('loadBar');
  if (!bar) return;
  bar.hidden = fraction == null;
  if (fraction == null) return;
  const pct = Math.round(Math.max(0, Math.min(1, fraction)) * 100);
  bar.firstElementChild.style.width = pct + '%';
  bar.setAttribute('aria-valuenow', String(pct));
}

// The card over the panes: text shows it, null hides it.
export function setNotice(text) {
  const el = document.getElementById('notice');
  if (!el) return;
  el.hidden = text == null;
  el.querySelector('p').textContent = text || '';
}

// Tell the person what went wrong in plain language; the raw error goes to the console only.
// `notice` also puts the message over the panes (when there is no scene to show).
export function showError(err, { fallback = 'unknown', notice = false } = {}) {
  const kind = errorKind(err, fallback);
  console.error(`[relighting] ${kind}:`, err);
  setStatus(MESSAGES[kind], 'error');
  setNotice(notice ? MESSAGES[kind] : null);
  return kind;
}
