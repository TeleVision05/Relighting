// Loading: error kinds and messages, the scene request, and the whole preprocessing pipeline.

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  MESSAGES,
  ViewerError,
  deserializeError,
  errorKind,
  friendlyMessage,
  serializeError,
} from '../../src/errors.js';
import { fetchScene, isLocalHost, readSource, sceneRequest } from '../../src/fetch-scene.js';
import { KEPT_FIELDS, preprocessScene, transferables } from '../../src/pipeline.js';
import { STAGES, overallProgress } from '../../src/stages.js';
import { makePly, rng, splatProps } from './helpers.js';

test('every failure kind has a plain-language message that says what to do', () => {
  const raw = /HTTP|\d{3}|Error|exception|undefined|null|stack|0x/;
  for (const [kind, msg] of Object.entries(MESSAGES)) {
    assert.ok(!raw.test(msg), `${kind}: ${msg}`);
    assert.ok(msg.length > 30 && /\.$/.test(msg), `${kind} should be a sentence or two`);
  }
});

test('errors are classified by kind, by shape when they are not ViewerErrors', () => {
  assert.equal(errorKind(new ViewerError('shader', 'log')), 'shader');
  assert.equal(errorKind(new ViewerError('no-such-kind')), 'unknown');
  assert.equal(errorKind(new RangeError('Array buffer allocation failed')), 'out-of-memory');
  assert.equal(
    errorKind(new RangeError('Invalid typed array length: 99999999999')),
    'out-of-memory',
  );
  assert.equal(errorKind(new TypeError('Failed to fetch')), 'network');
  assert.equal(errorKind(new Error('something else')), 'unknown');
  assert.equal(errorKind(new Error('something else'), 'startup'), 'startup');
  assert.equal(errorKind('a string'), 'unknown');
  assert.equal(friendlyMessage(new ViewerError('webgl2')), MESSAGES.webgl2);
});

test('an error crosses the worker boundary with its kind, message and stack', () => {
  const back = deserializeError(
    structuredClone(serializeError(new RangeError('Array buffer allocation failed'))),
  );
  assert.ok(back instanceof ViewerError);
  assert.equal(back.kind, 'out-of-memory');
  assert.equal(back.message, 'Array buffer allocation failed');
  assert.match(back.stack, /RangeError/);
});

test('local dev servers are recognised; hosted origins are not', () => {
  for (const h of [
    'localhost',
    'LOCALHOST',
    'viewer.localhost',
    '127.0.0.1',
    '127.1.2.3',
    '[::1]',
  ]) {
    assert.ok(isLocalHost(h), h);
  }
  for (const h of [
    'television05.github.io',
    'example.com',
    '10.0.0.5',
    '192.168.1.2',
    '',
    undefined,
  ]) {
    assert.ok(!isLocalHost(h), String(h));
  }
});

test('the scene request busts caches only when asked, and fresh means cache: reload', () => {
  assert.deepEqual(sceneRequest('/a.ply'), { url: '/a.ply', init: {} });
  assert.equal(sceneRequest('/a.ply', { bust: true, now: 5 }).url, '/a.ply?_=5');
  assert.equal(sceneRequest('/a.ply?v=1', { bust: true, now: 5 }).url, '/a.ply?v=1&_=5');
  const fresh = sceneRequest('/a.ply', { fresh: true });
  assert.equal(fresh.url, '/a.ply');
  assert.equal(fresh.init.cache, 'reload');
});

function withFetch(impl, fn) {
  const real = globalThis.fetch;
  globalThis.fetch = impl;
  return fn().finally(() => (globalThis.fetch = real));
}

const kindOfRejection = async (p) => {
  try {
    await p;
  } catch (e) {
    return e.kind;
  }
  assert.fail('expected a rejection');
};

test('fetch: 404 is not-found, other statuses and dropped connections are network', async () => {
  const status = (s) => async () => new Response('nope', { status: s });
  await withFetch(status(404), async () =>
    assert.equal(await kindOfRejection(fetchScene('/x.ply')), 'not-found'),
  );
  await withFetch(status(503), async () =>
    assert.equal(await kindOfRejection(fetchScene('/x.ply')), 'network'),
  );
  const dropped = async () => {
    throw new TypeError('Failed to fetch');
  };
  await withFetch(dropped, async () =>
    assert.equal(await kindOfRejection(fetchScene('/x.ply')), 'network'),
  );
});

test('fetch: the body arrives whole, with progress, even past a wrong Content-Length', async () => {
  const bytes = Uint8Array.from({ length: 5000 }, (_, i) => i % 251);
  for (const length of [5000, 1000]) {
    const respond = async () =>
      new Response(new Blob([bytes]).stream(), { headers: { 'Content-Length': String(length) } });
    const seen = [];
    const buf = await withFetch(respond, () => fetchScene('/x.ply', {}, (f) => seen.push(f)));
    assert.deepEqual(new Uint8Array(buf), bytes, `Content-Length ${length}`);
    assert.equal(seen.at(-1), 1);
  }
  const file = new Blob([bytes]);
  assert.deepEqual(new Uint8Array(await readSource(file)), bytes, 'a File is read directly');
});

function scenePly(n = 3000) {
  const rand = rng(21);
  const rows = Array.from({ length: n }, () => ({
    x: rand(),
    y: rand(),
    z: rand() * 0.01,
    f_dc_0: rand() - 0.5,
    opacity: 2,
    ...{ scale_0: -3, scale_1: -3, scale_2: -8, rot_0: 1 },
  }));
  return makePly(splatProps(), rows);
}

test('pipeline: a PLY becomes the sort arrays plus packed GPU data, in stage order', async () => {
  const stages = [];
  const r = await preprocessScene(scenePly(), (p) => stages.push(p.stage));
  assert.equal(r.N, 3000);
  for (const k of KEPT_FIELDS) assert.equal(r[k].length, 3000, k);
  assert.equal(r.alR, undefined, 'only what the page needs is kept');
  assert.equal(r.packed.N, 3000);
  assert.equal(r.packed.occ.data.length, 96 ** 3);
  assert.deepEqual([...new Set(stages)], ['parse', 'normals', 'lighting', 'pack']);
  const bufs = transferables(r);
  assert.equal(new Set(bufs).size, bufs.length, 'every transferable is its own buffer');
});

test('pipeline: the result survives a transfer to another thread', async () => {
  const r = await preprocessScene(scenePly(200));
  const copy = structuredClone(r, { transfer: transferables(r) });
  assert.equal(r.px.length, 0, 'the sender gave its buffers away');
  assert.equal(copy.px.length, 200);
});

test('stages: overall progress rises from 0 to 1 through the stages', () => {
  let last = -1;
  for (const stage of Object.keys(STAGES)) {
    for (const within of [0, 0.5, 1]) {
      const v = overallProgress(stage, within);
      assert.ok(v >= last && v <= 1, `${stage} ${within}: ${v}`);
      last = v;
    }
  }
  assert.equal(overallProgress('download', 0), 0);
  assert.equal(overallProgress('upload', 1), 1);
});
