import test from 'node:test';
import assert from 'node:assert';
import { cross, convertAll } from '../../app/static/js/currency.js';

const R = { TWD: 32, JPY: 150, USD: 1, THB: 36, EUR: 0.9 };

test('USD→TWD：10 USD = 320 TWD', () => {
  assert.equal(cross(10, 'USD', 'TWD', R), 320);
});

test('交叉 TWD→JPY：320 TWD = 1500 JPY', () => {
  assert.ok(Math.abs(cross(320, 'TWD', 'JPY', R) - 1500) < 1e-9);
});

test('缺率回 null', () => {
  assert.equal(cross(1, 'USD', 'GBP', R), null);
});

test('convertAll 不含 from、涵蓋其他幣', () => {
  const out = convertAll(1, 'USD', ['TWD', 'JPY', 'USD', 'THB', 'EUR'], R);
  assert.equal(out.USD, undefined);
  assert.equal(out.TWD, 32);
  assert.equal(out.JPY, 150);
  assert.equal(out.THB, 36);
  assert.equal(out.EUR, 0.9);
});
