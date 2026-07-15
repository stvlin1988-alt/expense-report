import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatCell } from '../../app/static/js/month_report.js';

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
