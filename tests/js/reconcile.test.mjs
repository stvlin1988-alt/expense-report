import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fmtAmount, groupTotals, applyAmountEdit, showResubmitBadge } from '../../app/static/js/reconcile.js';
import { parseAmountInput } from '../../app/static/js/expenses_util.js';

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

// F2：新增單據 的金額欄要跟行內編輯走同一支 parseAmountInput（去千分位逗號/$/NT$/空白），
// 否則同畫面「新增單據」打 1,250 會被後端判 amount_invalid、行內編輯卻能存 —— 前後矛盾。
test('parseAmountInput：新增單據會用到的輸入樣式都要能解析', () => {
  assert.deepEqual(parseAmountInput('1,250'), { value: 1250, valid: true });
  assert.deepEqual(parseAmountInput('NT$1,250'), { value: 1250, valid: true });
  assert.deepEqual(parseAmountInput('-500'), { value: -500, valid: true }); // 負數合法，留給後端判
  assert.deepEqual(parseAmountInput('0'), { value: 0, valid: true });       // 0 語法上有效，交後端 amount_zero 擋
  assert.deepEqual(parseAmountInput(''), { value: null, valid: false });    // 空字串
  assert.deepEqual(parseAmountInput('十元'), { value: null, valid: false }); // 非數字
});

// F1：行內編輯金額後，合計/小計要立刻反映新數字（回歸：之前這兩個 handler 存完不重繪，
// 合計/小計停留在舊值）。applyAmountEdit 是純函式，供 wireRows 呼叫端更新 DOM 用。
test('applyAmountEdit：改一筆金額後，該 group 小計與整體合計都要跟著變', () => {
  const groups = [
    {
      business_date: '2026-07-01',
      subtotal: 300,
      items: [
        { id: 1, status: 'audited', amount: 100 },
        { id: 2, status: 'reconciled', amount: 200 },
      ],
    },
    {
      business_date: '2026-07-02',
      subtotal: 10,
      items: [{ id: 3, status: 'audited', amount: 10 }],
    },
  ];
  const result = applyAmountEdit(groups, 1, 150);
  assert.ok(result);
  assert.equal(groups[0].items[0].amount, 150);      // 該筆本身更新
  assert.equal(result.group.subtotal, 350);          // 150 + 200，該 group 小計更新
  assert.equal(groups[1].subtotal, 10);               // 沒動到的 group 小計不變
  assert.equal(result.total.pending, 160);            // 150(audited) + 10(audited)
  assert.equal(result.total.reconciled, 200);         // 不受影響
  assert.equal(result.total.count, 3);
});

test('applyAmountEdit：rejected 的金額也算進所屬 group 小計（對齊後端 pending() 算法）', () => {
  const groups = [{
    business_date: '2026-07-01',
    subtotal: 60,
    items: [
      { id: 1, status: 'rejected', amount: 50 },
      { id: 2, status: 'audited', amount: 10 },
    ],
  }];
  const result = applyAmountEdit(groups, 1, 80);
  assert.equal(result.group.subtotal, 90); // 80 + 10，含 rejected
  assert.equal(result.total.pending, 90);  // pending = audited + rejected
});

test('applyAmountEdit：找不到對應 id 回傳 null，不動原資料', () => {
  const groups = [{ business_date: '2026-07-01', subtotal: 10, items: [{ id: 1, amount: 10, status: 'audited' }] }];
  assert.equal(applyAmountEdit(groups, 999, 5), null);
  assert.equal(groups[0].subtotal, 10);
});

// Addendum 10.1：重送標記徽章只在「已重送且尚未核銷」期間出現（gate 在 status==='audited'，
// 核銷/退回都不顯示，欄位本身不清空由後端負責）。
test('showResubmitBadge：audited + 有 resubmitted_at → true', () => {
  assert.equal(showResubmitBadge({ status: 'audited', resubmitted_at: '2026-07-10T03:00:00+00:00' }), true);
});

test('showResubmitBadge：audited + resubmitted_at 為 null → false', () => {
  assert.equal(showResubmitBadge({ status: 'audited', resubmitted_at: null }), false);
});

test('showResubmitBadge：reconciled + 有 resubmitted_at → false（核銷後徽章消失）', () => {
  assert.equal(showResubmitBadge({ status: 'reconciled', resubmitted_at: '2026-07-10T03:00:00+00:00' }), false);
});

test('showResubmitBadge：rejected + 有 resubmitted_at → false', () => {
  assert.equal(showResubmitBadge({ status: 'rejected', resubmitted_at: '2026-07-10T03:00:00+00:00' }), false);
});
