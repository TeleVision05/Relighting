// What the viewer tells a person when something fails.
//
// Every failure becomes a ViewerError with a `kind`. The person sees only the plain-language
// message for that kind; the raw detail (HTTP status, parser wording, shader log, stack) goes
// to the console. Pure module: safe to import from the page, the load worker and Node tests.

export const MESSAGES = {
  'not-found':
    'That scene file could not be found. Check the file name, or pick a scene from the list.',
  network:
    'The scene could not be downloaded. Check that the viewer’s server is still running, then press Reload.',
  'lfs-pointer':
    'This scene has not been downloaded yet: the file is only a Git LFS placeholder. ' +
    'Run “git lfs pull” in the repository, then press Reload.',
  'unsupported-ply':
    'This file is not a 3D Gaussian Splatting scene the viewer can read. It needs a binary .ply ' +
    'with a position, colour, opacity, scale and rotation for every splat. Pick another file.',
  webgl2:
    'This browser could not start WebGL2, which the viewer needs. Try a recent version of ' +
    'Chrome, Edge, Firefox or Safari, and check that hardware acceleration is turned on.',
  'out-of-memory':
    'This scene is too large for the memory available to this tab. Close other tabs and press ' +
    'Reload, or try a smaller scene.',
  'too-large':
    'This scene has more splats than this device’s graphics card can hold. Try a smaller scene.',
  shader:
    'The viewer could not set up its graphics on this device. Update your browser or graphics ' +
    'driver, or try another browser.',
  unknown:
    'Something went wrong while loading the scene. Press Reload to try again; if it keeps ' +
    'happening, try another scene.',
  startup: 'The viewer could not start. Reload the page to try again.',
};

export class ViewerError extends Error {
  // `detail` is for developers (console only); never show it to the person.
  constructor(kind, detail = '') {
    super(detail || kind);
    this.name = 'ViewerError';
    this.kind = kind in MESSAGES ? kind : 'unknown';
    this.detail = detail;
  }
}

const OOM = /allocation failed|out of memory|invalid (typed )?array length|array buffer/i;

// The kind of any thrown value. Errors that are not ViewerErrors are recognised by shape.
export function errorKind(err, fallback = 'unknown') {
  if (err instanceof ViewerError) return err.kind;
  if (err && typeof err === 'object' && typeof err.kind === 'string' && err.kind in MESSAGES) {
    return err.kind; // a ViewerError that crossed a worker boundary as plain data
  }
  const name = err && err.name;
  const text = String((err && err.message) || err || '');
  if (name === 'RangeError' && OOM.test(text)) return 'out-of-memory';
  if (OOM.test(text)) return 'out-of-memory';
  if (name === 'TypeError' && /fetch|network|load failed/i.test(text)) return 'network';
  return fallback;
}

export function friendlyMessage(err, fallback = 'unknown') {
  return MESSAGES[errorKind(err, fallback)];
}

// Plain data for postMessage: Error subclasses do not survive structured cloning intact.
export function serializeError(err) {
  return {
    kind: errorKind(err),
    name: (err && err.name) || 'Error',
    message: String((err && err.message) || err),
    stack: (err && err.stack) || '',
  };
}

// Back to a ViewerError on the receiving side, keeping the original message and stack.
export function deserializeError(data) {
  const e = new ViewerError(data.kind, data.message);
  if (data.stack) e.stack = data.stack;
  return e;
}
