import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatMoney } from '../../app/static/js/audit_util.js';

test('formatMoney thousands', () => {
  assert.equal(formatMoney(1290), '1,290');
  assert.equal(formatMoney(0), '0');
  assert.equal(formatMoney(180.5), '180.5');
});
