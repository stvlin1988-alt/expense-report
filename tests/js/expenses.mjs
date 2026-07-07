import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatAmount, lightLabel, businessDateDisplay } from '../../app/static/js/expenses_util.js';

test('formatAmount thousands + null', () => {
  assert.equal(formatAmount(1290), '1,290');
  assert.equal(formatAmount(5230.5), '5,230.5');
  assert.equal(formatAmount(null), '—');
});

test('lightLabel maps', () => {
  assert.equal(lightLabel('green'), '🟢');
  assert.equal(lightLabel('yellow'), '🟡');
  assert.equal(lightLabel('red'), '🔴');
});

test('businessDateDisplay taiwan', () => {
  // 台灣 07:59 的 UTC = 2026-07-06T23:59Z → 顯示日期 2026-07-07（此函式只格式化日期，不做 08:00 分界）
  assert.equal(businessDateDisplay('2026-07-06T23:59:00+00:00'), '2026-07-07');
});
