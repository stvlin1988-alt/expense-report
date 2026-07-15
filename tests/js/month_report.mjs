import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatCell, pickCell } from '../../app/static/js/month_report.js';

test('cell shows single combined total (reconciled + pending)', () => {
  const out = formatCell({ reconciled: 100, pending: 50 });
  assert.equal(out.text, '150');
});

test('closed-style cell (pending 0) shows the reconciled amount as the total', () => {
  const out = formatCell({ reconciled: 100, pending: 0 });
  assert.equal(out.text, '100');
});

test('negative total marked red', () => {
  const out = formatCell({ reconciled: -30, pending: 0 });
  assert.equal(out.negative, true);
});

test('total that nets negative is marked red', () => {
  const out = formatCell({ reconciled: 100, pending: -130 });
  assert.equal(out.text, '-30');
  assert.equal(out.negative, true);
});

test('missing/empty cell reads as 0', () => {
  assert.equal(formatCell(undefined).text, '0');
  assert.equal(formatCell({}).text, '0');
});

const ROW = {
  total: { reconciled: 300, pending: 0 },
  per_store: { 1: { reconciled: 100, pending: 0 }, 2: { reconciled: 200, pending: 0 } },
};

test('pickCell with empty storeId returns the combined total', () => {
  assert.equal(formatCell(pickCell(ROW, '')).text, '300');
});

test('pickCell with a store id returns that store amount', () => {
  assert.equal(formatCell(pickCell(ROW, 1)).text, '100');
  assert.equal(formatCell(pickCell(ROW, '2')).text, '200');
});

test('pickCell for a store with no data reads as 0', () => {
  assert.equal(formatCell(pickCell(ROW, 999)).text, '0');
  assert.equal(formatCell(pickCell({}, 1)).text, '0');
});
