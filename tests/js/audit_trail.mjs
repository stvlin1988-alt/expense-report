import { test } from 'node:test';
import assert from 'node:assert/strict';
import { action_label, status_label, renderTrailRows } from '../../app/static/js/audit_util.js';

test('action_label 對映', () => {
  assert.equal(action_label('edit'), '修改');
  assert.equal(action_label('check'), '簽核');
  assert.equal(action_label('weird'), 'weird');
  assert.equal(action_label(''), '');
});

test('status_label 對映（總表查詢新狀態不再全部顯示「待稽核」）', () => {
  assert.equal(status_label('submitted'), '待稽核');
  assert.equal(status_label('audited'), '已稽核');
  assert.equal(status_label('reconciled'), '已核銷');
  assert.equal(status_label('rejected'), '會計退回');
  assert.equal(status_label('weird'), 'weird');
  assert.equal(status_label(''), '');
  assert.equal(status_label(undefined), '');
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

test('renderTrailRows 顯示改動內容 A→B', () => {
  const html = renderTrailRows([
    { actor_name: '小明', ts: '2026-07-09T02:00:00+00:00', action: 'edit',
      changes: [{ field: '金額', from: 100, to: 250 }, { field: '分類', from: '餐飲', to: '交通' }] },
  ]);
  assert.match(html, /金額 100→250/);
  assert.match(html, /分類 餐飲→交通/);
});

test('renderTrailRows 空值顯示（空）', () => {
  const html = renderTrailRows([
    { actor_name: '小明', ts: '2026-07-09T02:00:00+00:00', action: 'edit',
      changes: [{ field: '分類', from: null, to: '交通' }] },
  ]);
  assert.match(html, /分類 （空）→交通/);
});
