// The Model card: dropdown, path box, Reload and "Open file…".

// Always offered in the dropdown, even without the /models endpoint.
export const KNOWN_PLYS = ['father-day.ply', 'Buttons.ply'];

const $ = (id) => document.getElementById(id);

// Populate the dropdown: known models always listed, plus whatever the server's /models
// endpoint reports (serve.py and render_server.py provide it), so the list stays useful
// under a plain static file server too.
export async function refreshModelList(selected) {
  const pathEl = $('plyPath'),
    pickEl = $('plyPick');
  let files = KNOWN_PLYS.slice();
  try {
    const r = await fetch('./models?_=' + Date.now(), { cache: 'no-store' });
    if (r.ok) {
      const served = await r.json();
      for (const f of served) if (!files.includes(f)) files.push(f);
    }
  } catch (e) {
    /* no /models endpoint — keep the known list */
  }

  const want = (selected || pathEl.value || '').replace(/^\.\//, '');
  if (want && !want.endsWith('(local)') && !files.includes(want)) files.push(want);

  pickEl.innerHTML = '';
  for (const f of files) {
    const o = document.createElement('option');
    o.value = './' + f;
    o.textContent = f;
    pickEl.appendChild(o);
  }
  if (files.includes(want)) pickEl.value = './' + want;
}

// `load(source)` loads a URL string or a File. Reload repeats the last choice.
export function bindModelControls(initial, load) {
  const pathEl = $('plyPath'),
    pickEl = $('plyPick'),
    fileEl = $('plyFile'),
    reloadBtn = $('reloadBtn');
  pathEl.value = initial;
  let localFile = null; // set when a file was opened from disk
  reloadBtn.addEventListener('click', () => {
    if (localFile) return void load(localFile);
    const p = pathEl.value.trim();
    if (p) {
      refreshModelList(p);
      load(p);
    }
  });
  pickEl.addEventListener('change', () => {
    if (!pickEl.value) return;
    localFile = null;
    pathEl.value = pickEl.value;
    load(pickEl.value);
  });
  pathEl.addEventListener('input', () => (localFile = null));
  pathEl.addEventListener('keydown', (e) => e.key === 'Enter' && reloadBtn.click());
  $('browseBtn').addEventListener('click', () => fileEl.click());
  fileEl.addEventListener('change', () => {
    const f = fileEl.files && fileEl.files[0];
    if (f) {
      localFile = f;
      pathEl.value = f.name + ' (local)';
      load(f);
    }
    fileEl.value = ''; // allow re-picking the same file
  });
}

// Shows that a load is running on the Reload button.
export function setLoadingButton(on) {
  $('reloadBtn').textContent = on ? '⏳ Loading…' : '🔄 Reload';
}
