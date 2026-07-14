import { rcApi } from './reconcile_api.js';
import { api as adminApi } from './admin_api.js';
import { escapeHtml, isValidPin } from './admin_util.js';
import { categoryOptionsHtml, parseAmountInput, lightLabel } from './expenses_util.js';
import { openImageLightbox } from './lightbox.js';
import { formatDateTimeTW } from './audit_util.js';

const root = () => document.getElementById('modal-root');

const STATUS_LABEL = { audited: '待核銷', reconciled: '已核銷', rejected: '已退回' };

const ERR_MSG = {
  amount_zero: '金額不可為 0',
  amount_invalid: '金額格式不正確',
  'amount required': '請輸入金額',
  'store required': '請選擇店別',
  'business_date required': '請選擇營業日',
  summary_invalid: '摘要格式不正確',
  reason_required: '請填寫退回原因',
  reason_too_long: '原因不可超過 200 字',
  not_reconcilable: '狀態已變更，請重新整理',
  not_editable: '此單無法編輯',
  not_rejectable: '此單無法退回',
};

function errMsg(code) {
  return ERR_MSG[code] || '操作失敗，請重試';
}

/** 金額格式化：回 {text, negative}。負數要紅字。 */
export function fmtAmount(n) {
  if (n === null || n === undefined) return { text: '—', negative: false };
  const num = Number(n);
  return {
    text: num.toLocaleString('en-US', { maximumFractionDigits: 2 }),
    negative: num < 0,
  };
}

/** 從 groups 算合計（後端也算，這支供前端即時篩選後重算用）。 */
export function groupTotals(groups) {
  let reconciled = 0, pending = 0, count = 0;
  groups.forEach((g) => g.items.forEach((i) => {
    count += 1;
    const a = Number(i.amount || 0);
    if (i.status === 'reconciled') reconciled += a;
    else pending += a;
  }));
  return { reconciled, pending, count };
}

// 該 group 的小計＝組內所有項目金額加總（不分狀態，含 rejected —— 對齊後端
// app/reconcile/routes.py pending() 的算法：sum(amount for x in items if amount is not None)）。
function groupSubtotal(items) {
  return (items || []).reduce((acc, it) => {
    const a = it.amount;
    return acc + (a !== null && a !== undefined ? Number(a) : 0);
  }, 0);
}

/**
 * 行內編輯金額成功後，就地更新 groups 裡對應那筆的金額、重算其所屬 group 小計與整體合計。
 * 純函式（除了必要的 item.amount 賦值副作用），不碰 DOM —— 呼叫端只需把回傳的
 * group/total 拿去更新對應的顯示節點，不必整頁重繪，才不會蓋掉其他列使用者尚未
 * 儲存的半輸入內容（做法對齊 admin_audit.js 的 refreshSubtotal：只更新數字，不重繪列表）。
 * 找不到對應 id 時回傳 null（呼叫端可略過）。
 */
export function applyAmountEdit(groups, id, newAmount) {
  for (const g of groups) {
    const item = (g.items || []).find((it) => it.id === id);
    if (item) {
      item.amount = newAmount;
      g.subtotal = groupSubtotal(g.items);
      return { group: g, total: groupTotals(groups) };
    }
  }
  return null;
}

// Addendum 10.1：重送標記徽章的顯示條件——只在「主管已重新打勾（audited）且
// 這次是被會計退回後重送的（resubmitted_at 有值）」時顯示。gate 在 status === 'audited'，
// 核銷後 status 變 reconciled 徽章自然消失，不必清空 resubmitted_at 欄位。
export function showResubmitBadge(item) {
  return item.status === 'audited' && !!item.resubmitted_at;
}

function amountCell(n) {
  const { text, negative } = fmtAmount(n);
  return `<span class="rc-amt${negative ? ' rc-neg' : ''}">${text}</span>`;
}

// 分類樹攤平成 {id, name} 清單，供篩選列用（categoryOptionsHtml 是給「編輯單筆分類」用，
// 首列固定「未分類」，語意跟篩選列的「全部分類」不同，這裡另外做一份給篩選用）。
function flattenCategories(tree) {
  const out = [];
  (tree || []).forEach((grp) => {
    const items = grp.items || [];
    if (items.length === 0) out.push({ id: grp.id, name: grp.name });
    else items.forEach((it) => out.push({ id: it.id, name: `${grp.name}／${it.name}` }));
  });
  return out;
}

export async function showReconcilePanel(identity) {
  const state = {
    tab: 'reconcile',
    stores: [],
    categories: [],
    filters: { status: '', store_id: '', category_id: '', date_from: '', date_to: '' },
    groups: [],
    total: { reconciled: 0, pending: 0, count: 0 },
    batchMsg: '',
  };

  try {
    const { status, data } = await rcApi.stores();
    if (status === 200 && data.status === 'ok') state.stores = data.stores;
  } catch (e) { /* 靜默：篩選/新增單下拉自行處理空清單 */ }
  try {
    const { status, data } = await rcApi.categories();
    if (status === 200 && data.status === 'ok') state.categories = data.categories;
  } catch (e) { /* 靜默 */ }

  const tabs = [
    { key: 'reconcile', label: '核銷' },
    { key: 'mypw', label: '我的密碼' },
  ];

  function shellHtml() {
    const tabBtns = tabs.map((t) =>
      `<button class="ap-tab${t.key === state.tab ? ' active' : ''}" data-tab="${t.key}" type="button">${t.label}</button>`
    ).join('');
    return `
      <div class="admin-panel">
        <header class="ap-head"><div class="ap-inner ap-head-inner">
          <span class="ap-title">會計核銷</span>
          <span class="ap-who">${escapeHtml(identity.name)}</span>
          <button class="ap-btn ap-logout" id="rc-logout" type="button">登出</button>
        </div></header>
        <nav class="ap-tabs"><div class="ap-inner ap-tabs-inner">${tabBtns}</div></nav>
        <section class="ap-body"><div class="ap-inner" id="rc-body"></div></section>
      </div>`;
  }

  // ---- 我的密碼（/admin/me/password 對任何登入者開放，非 admin-only，沿用既有 api） ----
  function renderMyPassword(container) {
    container.innerHTML = `
      <div class="ap-form">
        <input type="password" id="mp-old" placeholder="舊密碼" inputmode="numeric" maxlength="4" autocomplete="off">
        <input type="password" id="mp-new" placeholder="新密碼(4位)" inputmode="numeric" maxlength="4" autocomplete="off">
        <button class="ap-btn" id="mp-submit" type="button">變更密碼</button>
        <div class="ap-msg" id="mp-msg"></div>
      </div>`;
    const old = container.querySelector('#mp-old');
    const neu = container.querySelector('#mp-new');
    const msg = container.querySelector('#mp-msg');
    [old, neu].forEach((el) => el.addEventListener('input', () => {
      el.value = el.value.replace(/\D/g, '').slice(0, 4);
    }));
    container.querySelector('#mp-submit').addEventListener('click', async () => {
      msg.textContent = '';
      if (!isValidPin(neu.value)) { msg.textContent = '新密碼需為 4 位數字'; return; }
      try {
        const { status, data } = await adminApi.changeMyPassword(old.value, neu.value);
        if (status === 200 && data.status === 'ok') {
          msg.style.color = '#2e7d32'; msg.textContent = '已變更';
          old.value = ''; neu.value = '';
        } else if (data.message === 'wrong old password' || status === 400) {
          msg.style.color = '#c62828'; msg.textContent = '舊密碼錯誤或格式不符';
        } else {
          msg.style.color = '#c62828'; msg.textContent = '變更失敗';
        }
      } catch (e) {
        msg.style.color = '#c62828'; msg.textContent = '變更失敗，請重試';
      }
    });
  }

  // ---- 核銷清單 ----
  function filtersToQuery(f) {
    const q = {};
    if (f.status) q.status = f.status;
    if (f.store_id !== '') q.store_id = f.store_id;
    if (f.category_id !== '') q.category_id = f.category_id;
    if (f.date_from) q.date_from = f.date_from;
    if (f.date_to) q.date_to = f.date_to;
    return q;
  }

  async function loadData() {
    const { data } = await rcApi.pending(filtersToQuery(state.filters));
    state.groups = (data && data.groups) || [];
    state.total = groupTotals(state.groups);
  }

  function statusOptionsHtml(sel) {
    const opts = [['', '全部狀態'], ['audited', '待核銷'], ['reconciled', '已核銷'], ['rejected', '已退回']];
    return opts.map(([v, l]) => `<option value="${v}"${v === sel ? ' selected' : ''}>${l}</option>`).join('');
  }

  function storeOptionsHtml(sel) {
    return `<option value=""${sel === '' ? ' selected' : ''}>全部店</option>` +
      state.stores.map((s) =>
        `<option value="${s.id}"${String(s.id) === String(sel) ? ' selected' : ''}>${escapeHtml(s.name)}</option>`
      ).join('');
  }

  function catFilterOptionsHtml(sel) {
    const flat = flattenCategories(state.categories);
    return `<option value=""${sel === '' ? ' selected' : ''}>全部分類</option>` +
      flat.map((c) =>
        `<option value="${c.id}"${String(c.id) === String(sel) ? ' selected' : ''}>${escapeHtml(c.name)}</option>`
      ).join('');
  }

  function storeSelectForManualHtml() {
    if (!state.stores.length) return '<option value="">（無店別可選）</option>';
    return `<option value="">請選店別</option>` +
      state.stores.map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join('');
  }

  function rowHtml(e) {
    const editable = e.status === 'audited' || e.status === 'reconciled';
    const canApprove = e.status === 'audited';
    const canReject = editable;
    const thumb = e.thumb_url
      ? `<img src="${e.thumb_url}" loading="lazy" width="48" class="au-thumb" data-zoom="${e.image_url || ''}">`
      : '—';
    const { negative } = fmtAmount(e.amount);
    const rejectInfo = (e.status === 'rejected' && e.reject_reason)
      ? `<div class="rc-reject-reason">${escapeHtml(e.reject_reason)}</div>` : '';
    const resubmitBadge = showResubmitBadge(e)
      ? `<div class="rc-resubmit">🔄 主管已重送　${escapeHtml(formatDateTimeTW(e.resubmitted_at))}</div>` : '';
    return `<tr data-id="${e.id}" data-status="${e.status}">
      <td>${canApprove ? '<input type="checkbox" class="rc-sel">' : ''}</td>
      <td class="au-docno">${escapeHtml(e.doc_no || `#${e.id}`)}</td>
      <td>${thumb}</td>
      <td>${escapeHtml(e.store_name || '')}</td>
      <td>${escapeHtml(e.created_by_name || '')}</td>
      <td>${escapeHtml(e.summary || '')}${e.is_no_receipt ? ' <span class="au-mod">無單據</span>' : ''}</td>
      <td>${editable
        ? `<select data-f="category">${categoryOptionsHtml(state.categories, e.category_id)}</select>`
        : escapeHtml(e.category_name || '')}</td>
      <td>${editable
        ? `<input value="${e.amount ?? ''}" inputmode="decimal" data-f="amount" class="rc-amt-input${negative ? ' rc-neg' : ''}" style="width:90px">`
        : amountCell(e.amount)}</td>
      <td>${lightLabel(e.light)}</td>
      <td>${escapeHtml(STATUS_LABEL[e.status] || e.status)}${rejectInfo}${resubmitBadge}</td>
      <td class="rc-rowbtns">
        ${canApprove ? '<button data-act="approve" type="button">核銷</button>' : ''}
        ${canReject ? '<button data-act="reject" type="button">退回</button>' : ''}
        <div class="pd-row-err" data-f="err"></div>
      </td>
    </tr>`;
  }

  function groupsHtml() {
    if (!state.groups.length) return '<div class="ap-empty">沒有符合條件的單據</div>';
    return state.groups.map((g, idx) => {
      const sub = amountCell(g.subtotal);
      return `
      <div class="au-group">
        <div class="au-group-head">${escapeHtml(g.business_date)}　日小計 <span id="rc-subtotal-${idx}">${sub}</span></div>
        <div class="pd-table-wrap">
        <table class="pd-table"><thead><tr>
          <th><input type="checkbox" class="rc-selall"></th>
          <th>單號</th><th>圖</th><th>店別</th><th>建立者</th><th>摘要</th><th>分類</th><th>金額</th><th>燈</th><th>狀態</th><th>操作</th>
        </tr></thead><tbody>${g.items.map(rowHtml).join('')}</tbody></table>
        </div>
      </div>`;
    }).join('');
  }

  function reconcileHtml() {
    const f = state.filters;
    return `
      <div class="rc-filters">
        <select id="rc-f-status">${statusOptionsHtml(f.status)}</select>
        <select id="rc-f-store">${storeOptionsHtml(f.store_id)}</select>
        <select id="rc-f-cat">${catFilterOptionsHtml(f.category_id)}</select>
        <input type="date" id="rc-f-from" value="${f.date_from}">
        ～
        <input type="date" id="rc-f-to" value="${f.date_to}">
        <button class="ap-btn" id="rc-f-apply" type="button">套用</button>
        <button class="ap-btn secondary" id="rc-refresh" type="button">↻ 重整</button>
        <button class="ap-btn" id="rc-manual-open" type="button">新增單據</button>
      </div>
      <div id="rc-manual-box"></div>
      <div class="rc-totals">
        待核銷 <span id="rc-total-pending">${amountCell(state.total.pending)}</span>
        已核銷 <span id="rc-total-reconciled">${amountCell(state.total.reconciled)}</span>
        共 <span id="rc-total-count">${state.total.count}</span> 筆
      </div>
      <div class="rc-batchbar">
        <button class="ap-btn" id="rc-batch-approve" type="button">一鍵核銷勾選</button>
        <span class="rc-msg" id="rc-batch-msg">${escapeHtml(state.batchMsg)}</span>
      </div>
      <div id="rc-groups">${groupsHtml()}</div>`;
  }

  function manualFormHtml() {
    return `
      <div class="ap-form rc-manual-form">
        <select id="rc-m-store">${storeSelectForManualHtml()}</select>
        <input type="date" id="rc-m-date">
        <input type="text" id="rc-m-summary" placeholder="摘要">
        <input type="text" id="rc-m-amount" placeholder="金額" inputmode="decimal">
        <select id="rc-m-cat">${categoryOptionsHtml(state.categories, null)}</select>
        <button class="ap-btn" id="rc-m-submit" type="button">送出</button>
        <div class="ap-msg" id="rc-m-msg"></div>
      </div>`;
  }

  function toggleManualForm(body) {
    const box = body.querySelector('#rc-manual-box');
    if (box.dataset.open === '1') { box.innerHTML = ''; box.dataset.open = ''; return; }
    box.dataset.open = '1';
    box.innerHTML = manualFormHtml();
    const msg = box.querySelector('#rc-m-msg');
    box.querySelector('#rc-m-submit').addEventListener('click', async () => {
      msg.textContent = '';
      const storeSel = box.querySelector('#rc-m-store');
      const store_id = storeSel.value ? Number(storeSel.value) : null;
      const business_date = box.querySelector('#rc-m-date').value;
      const summary = box.querySelector('#rc-m-summary').value;
      const rawAmount = box.querySelector('#rc-m-amount').value;
      const catSel = box.querySelector('#rc-m-cat');
      const category_id = catSel.value === '' ? null : Number(catSel.value);
      if (!store_id) { msg.textContent = '請選擇店別'; return; }
      if (!business_date) { msg.textContent = '請選擇營業日'; return; }
      // 與行內編輯一致：先過 parseAmountInput 去千分位逗號/$/NT$/空白，
      // 否則同一畫面「新增單據」打 1,250 會被後端 parse_amount 判 amount_invalid，
      // 行內編輯打同樣的字卻能存 —— 對使用者是矛盾行為。0/負數仍交後端判（parse_amount 拒 0、允許負數）。
      const parsed = parseAmountInput(rawAmount);
      if (!parsed.valid) { msg.textContent = '金額格式不正確'; return; }
      try {
        const { status, data } = await rcApi.manual({
          store_id, business_date, summary, amount: parsed.value, category_id,
        });
        if (status === 200) {
          box.innerHTML = ''; box.dataset.open = '';
          await renderReconcile(body);
        } else {
          msg.textContent = errMsg(data && data.message);
        }
      } catch (e) {
        msg.textContent = '送出失敗，請重試';
      }
    });
  }

  function wireRows(body) {
    body.querySelectorAll('tr[data-id]').forEach((tr) => {
      const id = Number(tr.dataset.id);
      const err = tr.querySelector('[data-f="err"]');
      const cat = tr.querySelector('[data-f="category"]');
      const amt = tr.querySelector('[data-f="amount"]');
      const thumbEl = tr.querySelector('.au-thumb');
      if (thumbEl) thumbEl.addEventListener('click', () => openImageLightbox(thumbEl.dataset.zoom));
      if (cat) cat.addEventListener('change', async () => {
        err.textContent = '';
        const category_id = cat.value === '' ? null : Number(cat.value);
        try {
          const { status, data } = await rcApi.edit(id, { category_id });
          if (status === 200) {
            // 分類不影響合計/小計金額，只同步本機 state，不必重繪畫面。
            const found = state.groups.flatMap((g) => g.items).find((it) => it.id === id);
            if (found) found.category_id = category_id;
          } else {
            err.textContent = errMsg(data && data.message);
          }
        } catch (e) { err.textContent = '分類儲存失敗，請重試'; }
      });
      if (amt) {
        amt.addEventListener('input', () => {
          const parsed = parseAmountInput(amt.value);
          amt.classList.toggle('rc-neg', parsed.valid && parsed.value < 0);
        });
        amt.addEventListener('blur', async () => {
          err.textContent = '';
          const parsed = parseAmountInput(amt.value);
          if (!parsed.valid) { err.textContent = '金額格式不正確'; return; }
          try {
            const { status, data } = await rcApi.edit(id, { amount: parsed.value });
            if (status === 200) {
              // 只更新合計/小計數字，不整頁重繪 —— 避免蓋掉其他列使用者尚未
              // blur 儲存的半輸入內容（做法對齊 admin_audit.js 的 refreshSubtotal）。
              const patched = applyAmountEdit(state.groups, id, parsed.value);
              if (patched) {
                state.total = patched.total;
                const idx = state.groups.indexOf(patched.group);
                const subEl = body.querySelector(`#rc-subtotal-${idx}`);
                if (subEl) subEl.innerHTML = amountCell(patched.group.subtotal);
                const pendEl = body.querySelector('#rc-total-pending');
                if (pendEl) pendEl.innerHTML = amountCell(state.total.pending);
                const recEl = body.querySelector('#rc-total-reconciled');
                if (recEl) recEl.innerHTML = amountCell(state.total.reconciled);
                const cntEl = body.querySelector('#rc-total-count');
                if (cntEl) cntEl.textContent = state.total.count;
              }
            } else {
              err.textContent = errMsg(data && data.message);
            }
          } catch (e) { err.textContent = '金額儲存失敗，請重試'; }
        });
      }
      const approveBtn = tr.querySelector('[data-act="approve"]');
      if (approveBtn) approveBtn.addEventListener('click', async () => {
        err.textContent = '';
        try {
          const { status, data } = await rcApi.approve(id);
          if (status === 200) { state.batchMsg = ''; await renderReconcile(body); }
          else err.textContent = errMsg(data && data.message);
        } catch (e) { err.textContent = '核銷失敗，請重試'; }
      });
      const rejectBtn = tr.querySelector('[data-act="reject"]');
      if (rejectBtn) rejectBtn.addEventListener('click', async () => {
        err.textContent = '';
        const reason = window.prompt('請輸入退回原因（必填，200 字以內）');
        if (reason === null) return; // 使用者取消
        try {
          const { status, data } = await rcApi.reject(id, reason);
          if (status === 200) { state.batchMsg = ''; await renderReconcile(body); }
          else err.textContent = errMsg(data && data.message);
        } catch (e) { err.textContent = '退回失敗，請重試'; }
      });
    });
  }

  async function doBatchApprove(body) {
    const ids = Array.from(body.querySelectorAll('.rc-sel:checked'))
      .map((cb) => Number(cb.closest('tr').dataset.id));
    if (!ids.length) { state.batchMsg = '請先勾選要核銷的單據'; await renderReconcile(body); return; }
    try {
      const { status, data } = await rcApi.approveBatch(ids);
      if (status !== 200) { state.batchMsg = '批次核銷失敗，請重試'; await renderReconcile(body); return; }
      const approved = (data.approved || []).length;
      const skipped = data.skipped || [];
      state.batchMsg = skipped.length
        ? `已核銷 ${approved} 筆；${skipped.length} 筆未核銷（狀態已變更或不存在）`
        : `已核銷 ${approved} 筆`;
    } catch (e) {
      state.batchMsg = '批次核銷失敗，請重試';
    }
    await renderReconcile(body);
  }

  function wireReconcile(body) {
    body.querySelector('#rc-f-apply').addEventListener('click', () => {
      state.filters.status = body.querySelector('#rc-f-status').value;
      state.filters.store_id = body.querySelector('#rc-f-store').value;
      state.filters.category_id = body.querySelector('#rc-f-cat').value;
      state.filters.date_from = body.querySelector('#rc-f-from').value;
      state.filters.date_to = body.querySelector('#rc-f-to').value;
      state.batchMsg = '';
      renderReconcile(body);
    });
    body.querySelector('#rc-refresh').addEventListener('click', () => {
      state.batchMsg = '';
      renderReconcile(body);
    });
    body.querySelector('#rc-manual-open').addEventListener('click', () => toggleManualForm(body));

    // 每組（依營業日分組）各有一顆全選 checkbox，只影響同一張表格內的列
    body.querySelectorAll('.rc-selall').forEach((el) => {
      el.addEventListener('change', () => {
        el.closest('table').querySelectorAll('.rc-sel').forEach((cb) => { cb.checked = el.checked; });
      });
    });

    body.querySelector('#rc-batch-approve').addEventListener('click', () => doBatchApprove(body));

    wireRows(body);
  }

  async function renderReconcile(body) {
    body.innerHTML = '載入中…';
    await loadData();
    body.innerHTML = reconcileHtml();
    wireReconcile(body);
  }

  async function renderActiveTab() {
    const body = document.getElementById('rc-body');
    if (!body) return;
    body.innerHTML = '';
    if (state.tab === 'reconcile') await renderReconcile(body);
    else renderMyPassword(body);
  }

  function mount() {
    root().innerHTML = shellHtml();
    document.getElementById('rc-logout').addEventListener('click', async () => {
      try { await fetch('/auth/logout', { method: 'POST' }); } catch (e) { /* ignore */ }
      location.reload();
    });
    root().querySelectorAll('.ap-tab').forEach((btn) => {
      btn.addEventListener('click', () => {
        state.tab = btn.dataset.tab;
        root().querySelectorAll('.ap-tab').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        renderActiveTab();
      });
    });
    renderActiveTab();
  }

  mount();
}
