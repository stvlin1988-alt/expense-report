import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatCell } from '../../app/static/js/month_report.js';

test('open period shows reconciled/pending split', () => {
  const out = formatCell({ reconciled: 100, pending: 50 }, 'open');
  assert.equal(out.text, '100 / 50');
});

test('closed period shows single number', () => {
  const out = formatCell({ reconciled: 100, pending: 0 }, 'closed');
  assert.equal(out.text, '100');
});

test('negative total marked red', () => {
  const out = formatCell({ reconciled: -30, pending: 0 }, 'closed');
  assert.equal(out.negative, true);
});
