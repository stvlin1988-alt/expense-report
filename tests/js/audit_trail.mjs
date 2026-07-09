import { test } from 'node:test';
import assert from 'node:assert/strict';
import { action_label, renderTrailRows } from '../../app/static/js/audit_util.js';

test('action_label 對映', () => {
  assert.equal(action_label('edit'), '修改');
  assert.equal(action_label('check'), '簽核');
  assert.equal(action_label('weird'), 'weird');
  assert.equal(action_label(''), '');
});

test('renderTrailRows 空陣列', () => {
  assert.match(renderTrailRows([]), /無修改記錄/);
  assert.match(renderTrailRows(null), /無修改記錄/);
});

test('renderTrailRows 多筆保留順序 + 含動作中文', () => {
  const html = renderTrailRows([
    { actor_name: '小明', ts: '2026-07-09T02:00:00+00:00', action: 'edit' },
    { actor_name: '主管', ts: '2026-07-09T03:00:00+00:00', action: 'check' },
  ]);
  assert.ok(html.indexOf('小明') < html.indexOf('主管'));  // 順序保留
  assert.match(html, /修改/);
  assert.match(html, /簽核/);
});
