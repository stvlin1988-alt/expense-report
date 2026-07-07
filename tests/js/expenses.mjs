import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  formatAmount, lightLabel, businessDateDisplay, parseAmountInput, categoryOptionsHtml,
} from '../../app/static/js/expenses_util.js';

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

test('parseAmountInput strips commas / currency / blanks', () => {
  assert.deepEqual(parseAmountInput('1,200'), { value: 1200, valid: true });
  assert.deepEqual(parseAmountInput('1200'), { value: 1200, valid: true });
  assert.deepEqual(parseAmountInput('NT$ 5,230'), { value: 5230, valid: true });
  assert.deepEqual(parseAmountInput(''), { value: null, valid: false });
  assert.deepEqual(parseAmountInput('abc'), { value: null, valid: false });
});

test('businessDateDisplay taiwan', () => {
  // 台灣 07:59 的 UTC = 2026-07-06T23:59Z → 顯示日期 2026-07-07（此函式只做格式化日期，不做 08:00 分界）
  assert.equal(businessDateDisplay('2026-07-06T23:59:00+00:00'), '2026-07-07');
});

test('categoryOptionsHtml builds optgroups + selected + 未分類', () => {
  const tree = [{ id: 1, name: '廚房支出', items: [{ id: 3, name: '食材' }, { id: 4, name: '中廚物料' }] }];
  const html = categoryOptionsHtml(tree, 4);
  assert.ok(html.includes('<option value="">未分類</option>'));
  assert.ok(html.includes('<optgroup label="廚房支出">'));
  assert.ok(html.includes('<option value="3">食材</option>'));
  assert.ok(html.includes('<option value="4" selected>中廚物料</option>'));
});

test('categoryOptionsHtml empty tree still has 未分類', () => {
  const html = categoryOptionsHtml([], null);
  assert.ok(html.includes('<option value="">未分類</option>'));
  assert.ok(!html.includes('<optgroup'));
});
