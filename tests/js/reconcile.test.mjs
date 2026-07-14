import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fmtAmount, groupTotals } from '../../app/static/js/reconcile.js';

test('負數帶 negative 旗標', () => {
  const r = fmtAmount(-1250.5);
  assert.equal(r.negative, true);
  assert.equal(r.text, '-1,250.5');
});

test('正數不帶旗標', () => {
  const r = fmtAmount(1250);
  assert.equal(r.negative, false);
  assert.equal(r.text, '1,250');
});

test('零視為非負', () => {
  assert.equal(fmtAmount(0).negative, false);
});

test('null 顯示破折號', () => {
  assert.equal(fmtAmount(null).text, '—');
});

test('undefined 顯示破折號', () => {
  assert.equal(fmtAmount(undefined).text, '—');
});

test('groupTotals：reconciled 與 pending(audited+rejected) 分開加總', () => {
  const groups = [
    {
      business_date: '2026-07-01',
      items: [
        { status: 'reconciled', amount: 200 },
        { status: 'audited', amount: 100 },
        { status: 'rejected', amount: 50 },
      ],
    },
    {
      business_date: '2026-07-02',
      items: [
        { status: 'reconciled', amount: -30 },
        { status: 'audited', amount: 10 },
      ],
    },
  ];
  const t = groupTotals(groups);
  assert.equal(t.reconciled, 170); // 200 + (-30)
  assert.equal(t.pending, 160);    // 100 + 50 + 10
  assert.equal(t.count, 5);
});

test('groupTotals：空 groups 回全 0', () => {
  const t = groupTotals([]);
  assert.deepEqual(t, { reconciled: 0, pending: 0, count: 0 });
});

test('groupTotals：amount 缺漏視為 0', () => {
  const groups = [{ business_date: 'x', items: [{ status: 'audited' }] }];
  const t = groupTotals(groups);
  assert.equal(t.pending, 0);
  assert.equal(t.count, 1);
});
