import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatMoney, formatDateTimeTW } from '../../app/static/js/audit_util.js';

test('formatMoney thousands', () => {
  assert.equal(formatMoney(1290), '1,290');
  assert.equal(formatMoney(0), '0');
  assert.equal(formatMoney(180.5), '180.5');
});

test('formatDateTimeTW Asia/Taipei', () => {
  // 2026-07-08T06:23:00Z = 台灣 14:23
  assert.equal(formatDateTimeTW('2026-07-08T06:23:00Z'), '07/08 14:23');
});
test('formatDateTimeTW null/空', () => {
  assert.equal(formatDateTimeTW(null), '—');
  assert.equal(formatDateTimeTW(''), '—');
});
