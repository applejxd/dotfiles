import test from 'node:test';
import assert from 'node:assert/strict';
import { check } from '../src/check.js';

test('ok response', async () => {
  const r = await check('http://x', { fetchImpl: async () => ({ ok: true, status: 200 }) });
  assert.equal(r.ok, true);
  assert.equal(r.status, 200);
});

test('timeout', async () => {
  const slow = (url, { signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(Object.assign(new Error('x'), { name: 'AbortError' }))));
  const r = await check('http://x', { timeoutMs: 10, fetchImpl: slow });
  assert.equal(r.error, 'timeout');
});
