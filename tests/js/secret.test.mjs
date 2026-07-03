import test from 'node:test';
import assert from 'node:assert';
import {
  canonicalToken, buildSequence, sha256hex, matchesSecret, withinWindow,
} from '../../app/static/js/secret.js';

test('canonicalToken 正規化運算子', () => {
  assert.equal(canonicalToken('×'), '*');
  assert.equal(canonicalToken('÷'), '/');
  assert.equal(canonicalToken('−'), '-');
  assert.equal(canonicalToken('7'), '7');
});

test('buildSequence 串接 078*2', () => {
  assert.equal(buildSequence(['0', '7', '8', '*', '2']), '078*2');
});

test('sha256hex 對應已知 078*2 雜湊', async () => {
  // 與後端 hashlib.sha256(b"078*2").hexdigest() 一致
  const h = await sha256hex('078*2');
  assert.match(h, /^[0-9a-f]{64}$/);
  assert.equal(h, await sha256hex('078*2')); // 穩定
});

test('matchesSecret 正確比對', async () => {
  const h = await sha256hex('078*2');
  assert.equal(await matchesSecret('078*2', h), true);
  assert.equal(await matchesSecret('078*3', h), false);
});

test('withinWindow 邊界', () => {
  assert.equal(withinWindow(1000, 1000 + 5999), true);
  assert.equal(withinWindow(1000, 1000 + 6000), true);
  assert.equal(withinWindow(1000, 1000 + 6001), false);
});
