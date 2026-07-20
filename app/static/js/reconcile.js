import { rcApi } from './reconcile_api.js';
import { api as adminApi } from './admin_api.js';
import { periodsApi } from './periods_api.js';
import { renderMonthReport } from './month_report.js';
import { escapeHtml, isValidPin } from './admin_util.js';
import { categoryOptionsHtml, parseAmountInput, lightLabel } from './expenses_util.js';
import { openImageLightbox } from './lightbox.js';
import { formatDateTimeTW } from './audit_util.js';
import { wkConfirm, wkPrompt } from './wk_modal.js';

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
  // Task 17：期間篩選／挪期／提前封月／月結設定
  period_closed: '此期已封月',
  next_period_closed: '下一期已封月',
  no_period: '此單尚未歸期',
  already_closed: '已封月',
  period_not_ended: '期間還在進行中，請先「調整結束日」把本期縮到今天／昨天，再提前封月',
  bad_close_day: '月結日需 1–28',
  bad_offset: '鎖定偏移需 0–168 小時',
  end_before_start: '結束日不可早於起始日',
  would_invert_next: '會使下一期起訖顛倒',
  bad_date: '日期格式不正確',
};

// 期間狀態 → 徽章文案（純函式，供測試）。
export function periodBadge(status) {
  return { open: '進行中', closing: '寬限期', closed: '已封月' }[status] || status || '';
}

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

// 就地更新一個 `.num` 金額節點（不整頁重繪）：文字＋負數紅字 class 都跟著換。
// 給核銷表 sticky 工具列合計 / 日小計節點用（那三個節點本身就是 <span class="num">，
// 不像 amountCell() 是「另包一層」給舊 .pd-table 用的）。
function setNumEl(el, n) {
  if (!el) return;
  const { text, negative } = fmtAmount(n);
  el.textContent = text;
  el.classList.toggle('neg', negative);
}

function periodBadgeHtml(period) {
  if (!period) return '';
  const cls = period.status === 'closed' ? 'closed' : period.status === 'closing' ? 'closing' : 'open';
  return `<span class="ap-badge ${cls}">${escapeHtml(periodBadge(period.status))}</span>`;
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
    filters: { status: '', store_id: '', category_id: '', date_from: '', date_to: '', period_id: '' },
    groups: [],
    total: { reconciled: 0, pending: 0, count: 0 },
    batchMsg: '',
    period: null, // 最近一次 pending() 回傳的 {id, label, status}（給期間抬頭 + 月結管理 tab 共用）
    periods: [],  // 所有會計期間清單（新到舊），供月份下拉 / 月報表選期
    reportPeriodId: '', // 月報表分頁目前選的期間 id（''＝當期）
  };

  try {
    const { status, data } = await rcApi.stores();
    if (status === 200 && data.status === 'ok') state.stores = data.stores;
  } catch (e) { /* 靜默：篩選/新增單下拉自行處理空清單 */ }
  try {
    const { status, data } = await rcApi.categories();
    if (status === 200 && data.status === 'ok') state.categories = data.categories;
  } catch (e) { /* 靜默 */ }

  async function loadPeriods() {
    try {
      const { status, data } = await periodsApi.list();
      if (status === 200 && data.status === 'ok') state.periods = data.periods || [];
    } catch (e) { /* 靜默：下拉自行處理空清單 */ }
  }
  await loadPeriods();

  // 月份下拉共用選項：value=期間 id，label 帶狀態（已封月/寬限期）。sel 為目前選中的 id 字串。
  // includeCurrent=true 時最前面補一個「目前期間」空值選項（核銷頁切期用）。
  function periodOptionsHtml(sel, includeCurrent) {
    const badge = { closed: '（已封月）', closing: '（寬限期）', open: '' };
    const head = includeCurrent
      ? `<option value=""${String(sel) === '' ? ' selected' : ''}>目前期間</option>` : '';
    return head + state.periods.map((p) =>
      `<option value="${p.id}"${String(p.id) === String(sel) ? ' selected' : ''}>${escapeHtml(p.label)}${badge[p.status] || ''}</option>`
    ).join('');
  }

  const tabs = [
    { key: 'reconcile', label: '核銷' },
    { key: 'period', label: '月結管理' },
    { key: 'report', label: '月報表' },
    { key: 'mypw', label: '我的密碼' },
  ];

  function shellHtml() {
    const navBtns = tabs.map((t) =>
      `<button class="wk-nav-item"${t.key === state.tab ? ' aria-current="page"' : ''} data-tab="${t.key}" type="button">${t.label}</button>`
    ).join('');
    return `
      <div class="wk-app">
        <aside class="wk-sidebar">
          <div class="wk-brand"><div class="wk-brand-name">會計核銷</div><div class="wk-brand-sub">核銷工作台</div></div>
          <nav class="wk-nav">${navBtns}</nav>
          <div class="wk-side-foot">
            <div class="wk-side-user"><span class="wk-avatar">${escapeHtml(identity.name.slice(0, 1))}</span>
              <div><div class="wk-side-user-name">${escapeHtml(identity.name)}</div><div class="wk-side-user-role">會計</div></div></div>
            <button class="wk-btn wk-btn-secondary" id="rc-logout" type="button">登出</button>
          </div>
        </aside>
        <main class="wk-main"><div id="rc-body"></div></main>
      </div>`;
  }

  // ---- 我的密碼（/admin/me/password 對任何登入者開放，非 admin-only，沿用既有 api） ----
  function renderMyPassword(container) {
    container.innerHTML = `
      <div class="wk-page-body">
      <div class="ap-form">
        <input type="password" id="mp-old" placeholder="舊密碼" inputmode="numeric" maxlength="4" autocomplete="off">
        <input type="password" id="mp-new" placeholder="新密碼(4位)" inputmode="numeric" maxlength="4" autocomplete="off">
        <button class="ap-btn" id="mp-submit" type="button">變更密碼</button>
        <div class="ap-msg" id="mp-msg"></div>
      </div>
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
    if (f.period_id !== '') q.period_id = f.period_id;
    return q;
  }

  async function loadData() {
    const { data } = await rcApi.pending(filtersToQuery(state.filters));
    state.groups = (data && data.groups) || [];
    state.total = groupTotals(state.groups);
    state.period = (data && data.period) || null;
  }

  // 「月結管理」tab 用：確保 state.period 有值（若尚未進過核銷 tab 就直接切過來，先補抓一次當期）。
  async function ensurePeriod() {
    if (state.period) return state.period;
    await refreshPeriod();
    return state.period;
  }

  // 用指定 pid（或省略＝當期）重抓一次 period 資訊，更新 state.period（不動 groups/filters）。
  async function refreshPeriod(pid) {
    try {
      const { data } = await rcApi.pending(pid ? { period_id: pid } : {});
      if (data && data.period) state.period = data.period;
    } catch (e) { /* 靜默 */ }
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
    const thumb = e.thumb_url
      ? `<img src="${e.thumb_url}" loading="lazy" class="wk-rcp-thumb au-thumb" data-zoom="${e.image_url || ''}" alt="收據">`
      : '<span class="wk-rcp-none">—</span>';
    const { negative } = fmtAmount(e.amount);
    // Step 0 結論：item 沒有 created_at 欄位（見 app/reconcile/serialize.py 白名單），
    // 單據格只放單號／建立者，不放時間；store_name 後端已經是英文代號（_maps 用 s.code），
    // 直接用即可，不必另建 client helper 查 code。
    const meta = `${escapeHtml(e.doc_no || `#${e.id}`)} · ${escapeHtml(e.created_by_name || '')}`;
    const rejectInfo = (e.status === 'rejected' && e.reject_reason) ? `<div class="rc-reject-reason">${escapeHtml(e.reject_reason)}</div>` : '';
    const resubmitBadge = showResubmitBadge(e) ? `<div class="rc-resubmit">🔄 主管已重送 ${escapeHtml(formatDateTimeTW(e.resubmitted_at))}</div>` : '';
    return `<tr data-id="${e.id}" data-status="${e.status}">
      <td class="wk-rc-sel">${canApprove ? '<input type="checkbox" class="rc-sel">' : ''}</td>
      <td><div class="wk-doc-cell">${thumb}
        <div class="wk-doc-meta"><span class="wk-doc-summary">${escapeHtml(e.summary || '')}${e.is_no_receipt ? ' <span class="au-mod">無單據</span>' : ''}</span>
          <span class="wk-doc-sub">${meta}</span></div></div></td>
      <td><span class="wk-store-tag">${escapeHtml(e.store_code || e.store_name || '')}</span></td>
      <td>${editable ? `<select data-f="category">${categoryOptionsHtml(state.categories, e.category_id)}</select>` : escapeHtml(e.category_name || '')}</td>
      <td class="num${negative ? ' neg' : ''}">${editable
        ? `<input value="${e.amount ?? ''}" inputmode="decimal" data-f="amount" class="wk-amt-input${negative ? ' neg' : ''}">`
        : fmtAmount(e.amount).text}</td>
      <td><div class="wk-lamp-cell">${lightLabel(e.light)}<span class="wk-status">${escapeHtml(STATUS_LABEL[e.status] || e.status)}</span>${rejectInfo}${resubmitBadge}</div></td>
      <td class="rc-rowbtns">
        ${canApprove ? '<button class="wk-btn wk-btn-sm wk-btn-primary" data-act="approve" type="button">核銷</button>' : ''}
        ${editable ? '<button class="wk-btn wk-btn-sm wk-btn-secondary" data-act="reject" type="button">退回</button>' : ''}
        ${(e.status === 'audited' || e.status === 'rejected') ? '<button class="wk-btn wk-btn-sm wk-btn-ghost" data-act="movenext" type="button">挪下期</button>' : ''}
        <div class="pd-row-err" data-f="err"></div>
      </td>
    </tr>`;
  }

  function groupsHtml() {
    if (!state.groups.length) return '<div class="wk-empty">沒有符合條件的單據</div>';
    return state.groups.map((g, idx) => `
      <div class="wk-card wk-rc-group">
        <div class="wk-rc-dayhead">${escapeHtml(g.business_date)}<span class="wk-rc-daysub">日小計 <span id="rc-subtotal-${idx}" class="num${fmtAmount(g.subtotal).negative ? ' neg' : ''}">${fmtAmount(g.subtotal).text}</span></span></div>
        <div class="table-wrap"><table class="wk-rc-table">
          <thead><tr><th><input type="checkbox" class="rc-selall"></th><th>單據</th><th>店別</th><th>分類</th><th class="num-h">金額</th><th>燈號／狀態</th><th>操作</th></tr></thead>
          <tbody>${g.items.map(rowHtml).join('')}</tbody>
        </table></div>
      </div>`).join('');
  }

  function periodBarHtml() {
    const p = state.period;
    return `
      <div class="wk-toolbar-row">
        <label class="rc-period-label">檢視期間：
          <select id="rc-period-select" class="wk-select" style="margin-left:6px">${periodOptionsHtml(state.filters.period_id, true)}</select>
        </label>
        ${periodBadgeHtml(p)}
      </div>`;
  }

  function reconcileHtml() {
    const f = state.filters;
    return `
      <div class="wk-toolbar">
        ${periodBarHtml()}
        <div class="wk-toolbar-row">
          <select id="rc-f-status" class="wk-select">${statusOptionsHtml(f.status)}</select>
          <select id="rc-f-store" class="wk-select">${storeOptionsHtml(f.store_id)}</select>
          <select id="rc-f-cat" class="wk-select">${catFilterOptionsHtml(f.category_id)}</select>
          <input type="date" id="rc-f-from" class="wk-input" value="${f.date_from}">
          ～
          <input type="date" id="rc-f-to" class="wk-input" value="${f.date_to}">
          <button class="wk-btn wk-btn-sm wk-btn-primary" id="rc-f-apply" type="button">套用</button>
          <button class="wk-btn wk-btn-sm wk-btn-secondary" id="rc-refresh" type="button">↻ 重整</button>
          <button class="wk-btn wk-btn-sm wk-btn-secondary" id="rc-manual-open" type="button">新增單據</button>
        </div>
        <div class="wk-toolbar-row">
          待核銷 <span id="rc-total-pending" class="num${fmtAmount(state.total.pending).negative ? ' neg' : ''}">${fmtAmount(state.total.pending).text}</span>
          已核銷 <span id="rc-total-reconciled" class="num${fmtAmount(state.total.reconciled).negative ? ' neg' : ''}">${fmtAmount(state.total.reconciled).text}</span>
          共 <span id="rc-total-count">${state.total.count}</span> 筆
        </div>
      </div>
      <div class="wk-page-body">
        <div id="rc-manual-box"></div>
        <div class="rc-batchbar">
          <button class="wk-btn wk-btn-primary" id="rc-batch-approve" type="button">一鍵核銷勾選</button>
          <span class="rc-msg" id="rc-batch-msg">${escapeHtml(state.batchMsg)}</span>
        </div>
        <div id="rc-groups">${groupsHtml()}</div>
      </div>`;
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
          amt.classList.toggle('neg', parsed.valid && parsed.value < 0);
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
                setNumEl(subEl, patched.group.subtotal);
                const pendEl = body.querySelector('#rc-total-pending');
                setNumEl(pendEl, state.total.pending);
                const recEl = body.querySelector('#rc-total-reconciled');
                setNumEl(recEl, state.total.reconciled);
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
        const reason = await wkPrompt({
          title: '退回單據',
          desc: '請輸入退回原因（必填，200 字內）',
          okLabel: '退回',
          validate: (v) => (v && v.trim()) ? '' : '請填寫退回原因',
        });
        if (reason === null) return; // 使用者取消
        try {
          const { status, data } = await rcApi.reject(id, reason);
          if (status === 200) { state.batchMsg = ''; await renderReconcile(body); }
          else err.textContent = errMsg(data && data.message);
        } catch (e) { err.textContent = '退回失敗，請重試'; }
      });
      const moveNextBtn = tr.querySelector('[data-act="movenext"]');
      if (moveNextBtn) moveNextBtn.addEventListener('click', async () => {
        err.textContent = '';
        try {
          const { status, data } = await rcApi.moveNext(id);
          if (status === 200) { state.batchMsg = ''; await renderReconcile(body); }
          else err.textContent = errMsg(data && data.message);
        } catch (e) { err.textContent = '挪期失敗，請重試'; }
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

    body.querySelector('#rc-period-select').addEventListener('change', (e) => {
      const v = e.target.value;
      state.filters.period_id = v ? Number(v) : '';
      state.batchMsg = '';
      renderReconcile(body);
    });

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

  // ---- 月結管理（會計權限：調整結束日／提前封月／上期未處理單／月結設定／月報表） ----
  function unprocessedTableHtml(items) {
    if (!items.length) return '<div class="ap-empty">目前無上期未處理單</div>';
    const rows = items.map((it) => {
      const thumb = it.image_url
        ? `<img src="${it.image_url}" loading="lazy" width="48" class="au-thumb" data-zoom="${it.image_url}">`
        : '—';
      return `<tr>
        <td>${thumb}</td>
        <td>${escapeHtml(it.store_name || '')}</td>
        <td>${escapeHtml(it.business_date || '')}</td>
        <td>${amountCell(it.amount)}</td>
        <td>${escapeHtml(it.summary || '')}</td>
      </tr>`;
    }).join('');
    return `<div class="pd-table-wrap"><table class="pd-table">
      <thead><tr><th>圖</th><th>門店</th><th>營業日</th><th>金額</th><th>摘要</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
  }

  function periodTabHtml(period, settings, items) {
    const disabled = period ? '' : 'disabled';
    return `
      <div class="wk-page-body">
      <section class="rc-period-section">
        <h3>目前期間</h3>
        <div class="rc-period-bar">
          <span class="rc-period-label">${period ? escapeHtml(period.label) : '（無期間）'}</span>
          ${periodBadgeHtml(period)}
          ${period && period.end_date ? `<span class="rc-period-next">下次月結：${escapeHtml(period.end_date)}</span>` : ''}
        </div>
        <div class="ap-form">
          <input type="date" id="rc-enddate-input" ${disabled}>
          <button class="ap-btn secondary" id="rc-enddate-save" type="button" ${disabled}>調整結束日</button>
          <button class="ap-btn" id="rc-close-preview" type="button" ${disabled}>提前封月</button>
          <div class="ap-msg" id="rc-period-msg"></div>
        </div>
      </section>

      <section class="rc-period-section">
        <h3>上期未處理單</h3>
        ${unprocessedTableHtml(items)}
      </section>

      <section class="rc-period-section">
        <h3>月結設定（會計可編輯）</h3>
        <div class="ap-form">
          <label>月結日
            <input type="number" id="rc-set-closeday" min="1" max="28" value="${escapeHtml(String(settings.period_close_day ?? ''))}" style="width:70px">
          </label>
          <label>鎖定偏移(小時)
            <input type="number" id="rc-set-offset" min="0" max="168" value="${escapeHtml(String(settings.period_lock_offset_hours ?? ''))}" style="width:80px">
          </label>
          <button class="ap-btn" id="rc-set-save" type="button">儲存</button>
          <div class="ap-msg" id="rc-set-msg"></div>
        </div>
      </section>
      </div>`;
  }

  function wirePeriodTab(body, period) {
    body.querySelectorAll('.au-thumb').forEach((el) => {
      el.addEventListener('click', () => openImageLightbox(el.dataset.zoom));
    });

    const periodMsg = body.querySelector('#rc-period-msg');
    const enddateBtn = body.querySelector('#rc-enddate-save');
    if (enddateBtn && !enddateBtn.disabled) enddateBtn.addEventListener('click', async () => {
      periodMsg.style.color = ''; periodMsg.textContent = '';
      const v = body.querySelector('#rc-enddate-input').value;
      if (!v) { periodMsg.style.color = '#c62828'; periodMsg.textContent = '請選擇日期'; return; }
      try {
        const { status, data } = await periodsApi.patchEndDate(period.id, v);
        if (status === 200) {
          await refreshPeriod(period.id);
          await renderPeriod(body);
          const msg2 = body.querySelector('#rc-period-msg');
          if (msg2) { msg2.style.color = '#2e7d32'; msg2.textContent = '已更新結束日'; }
        } else {
          periodMsg.style.color = '#c62828'; periodMsg.textContent = errMsg(data && data.message);
        }
      } catch (e) { periodMsg.style.color = '#c62828'; periodMsg.textContent = '更新失敗，請重試'; }
    });

    const closeBtn = body.querySelector('#rc-close-preview');
    if (closeBtn && !closeBtn.disabled) closeBtn.addEventListener('click', async () => {
      periodMsg.style.color = ''; periodMsg.textContent = '';
      try {
        const { status, data } = await rcApi.closePreview(period.id);
        if (status !== 200) { periodMsg.style.color = '#c62828'; periodMsg.textContent = '讀取失敗，請重試'; return; }
        const n = data.unaudited_count || 0;
        const ok = await wkConfirm({
          title: '提前封月',
          desc: `這期還有 ${n} 筆沒打勾，封月後這些單不進帳，確定要封嗎？`,
          okLabel: '確定封月',
          danger: true,
        });
        if (!ok) return;
        const res = await rcApi.closePeriod(period.id);
        if (res.status === 200) {
          await refreshPeriod(period.id);
          await renderPeriod(body);
          const msg2 = body.querySelector('#rc-period-msg');
          if (msg2) { msg2.style.color = '#2e7d32'; msg2.textContent = '已封月'; }
        } else {
          periodMsg.style.color = '#c62828'; periodMsg.textContent = errMsg(res.data && res.data.message);
        }
      } catch (e) { periodMsg.style.color = '#c62828'; periodMsg.textContent = '操作失敗，請重試'; }
    });

    const setMsg = body.querySelector('#rc-set-msg');
    const setSaveBtn = body.querySelector('#rc-set-save');
    if (setSaveBtn) setSaveBtn.addEventListener('click', async () => {
      setMsg.style.color = ''; setMsg.textContent = '';
      const closeDay = Number(body.querySelector('#rc-set-closeday').value);
      const offset = Number(body.querySelector('#rc-set-offset').value);
      try {
        const { status, data } = await periodsApi.patchSettings({
          period_close_day: closeDay, period_lock_offset_hours: offset,
        });
        if (status === 200) {
          setMsg.style.color = '#2e7d32'; setMsg.textContent = '已儲存';
        } else {
          setMsg.style.color = '#c62828'; setMsg.textContent = errMsg(data && data.message);
        }
      } catch (e) { setMsg.style.color = '#c62828'; setMsg.textContent = '儲存失敗，請重試'; }
    });
  }

  async function renderPeriod(body) {
    body.innerHTML = '載入中…';
    const period = await ensurePeriod();
    let settings = { period_close_day: '', period_lock_offset_hours: '' };
    try {
      const { status, data } = await periodsApi.getSettings();
      if (status === 200 && data.status === 'ok') settings = data;
    } catch (e) { /* 靜默 */ }
    let items = [];
    try {
      const { status, data } = await rcApi.unprocessed();
      if (status === 200 && data.status === 'ok') items = data.items || [];
    } catch (e) { /* 靜默 */ }

    body.innerHTML = periodTabHtml(period, settings, items);
    wirePeriodTab(body, period);
  }

  // ---- 月報表分頁：月份下拉 + 交叉表（重用 month_report.js）----
  function reportTabHtml() {
    return `
      <div class="wk-toolbar">
        <div class="wk-toolbar-row">
          <label class="rc-period-label">月報表期間：
            <select id="rc-report-select" class="wk-select" style="margin-left:6px">${periodOptionsHtml(state.reportPeriodId, false)}</select>
          </label>
        </div>
      </div>
      <div class="wk-page-body">
        <div id="rc-report-body"></div>
      </div>`;
  }

  async function renderReport(body) {
    if (!state.periods.length) await loadPeriods();
    // 預設選最新一期（清單第一筆＝start_date 最新），讓下拉選中項與畫出來的報表一致
    if (state.reportPeriodId === '' && state.periods.length) {
      state.reportPeriodId = String(state.periods[0].id);
    }
    body.innerHTML = reportTabHtml();
    const reportDiv = body.querySelector('#rc-report-body');
    const draw = (pid) => renderMonthReport(reportDiv, pid ? { periodId: Number(pid) } : {});
    draw(state.reportPeriodId);
    body.querySelector('#rc-report-select').addEventListener('change', (e) => {
      state.reportPeriodId = e.target.value;
      draw(state.reportPeriodId);
    });
  }

  async function renderActiveTab() {
    const body = document.getElementById('rc-body');
    if (!body) return;
    body.innerHTML = '';
    if (state.tab === 'reconcile') await renderReconcile(body);
    else if (state.tab === 'period') await renderPeriod(body);
    else if (state.tab === 'report') await renderReport(body);
    else renderMyPassword(body);
  }

  function mount() {
    root().innerHTML = shellHtml();
    document.getElementById('rc-logout').addEventListener('click', async () => {
      try { await fetch('/auth/logout', { method: 'POST' }); } catch (e) { /* ignore */ }
      location.reload();
    });
    root().querySelectorAll('.wk-nav-item').forEach((btn) => {
      btn.addEventListener('click', () => {
        state.tab = btn.dataset.tab;
        root().querySelectorAll('.wk-nav-item').forEach((b) => b.removeAttribute('aria-current'));
        btn.setAttribute('aria-current', 'page');
        renderActiveTab();
      });
    });
    renderActiveTab();
  }

  mount();
}
