// 主管稽核 pane（UI 重塑 2026-07）：待稽核卡片 + action bar 交班/結班/取消 + 即時小計。
// 沿用桌面 admin_audit.js 同一資料流（admin_api.js audit 端點）與 data-f/data-act 契約，
// 只把 <tr> 換成 .mb-au-card。總表查詢（Task 3）另補 renderSummary。
import { api } from './admin_api.js';
import { escapeHtml } from './admin_util.js';
import { categoryOptionsHtml, lightLabel, parseAmountInput } from './expenses_util.js';
import { formatMoney, formatDateTimeTW, renderTrailRows } from './audit_util.js';
import { openImageLightbox } from './lightbox.js';

const SID = undefined; // 主管鎖本店，後端用本店

export async function renderAuditPane(container, { onSubtotalChange } = {}) {
  container.innerHTML = `
    <div class="mb-subtabs" role="tablist" aria-label="稽核子功能">
      <button class="mb-subtab active" data-sub="pending" type="button">待稽核</button>
      <button class="mb-subtab" data-sub="summary" type="button">總表查詢</button>
    </div>
    <div id="mb-au-body"></div>`;
  const body = container.querySelector('#mb-au-body');
  const subs = container.querySelectorAll('.mb-subtab');
  const setSub = (name) => {
    subs.forEach((b) => b.classList.toggle('active', b.dataset.sub === name));
    if (name === 'pending') renderPending(body, onSubtotalChange);
    else renderSummary(body);                    // Task 3 提供
  };
  subs.forEach((b) => b.addEventListener('click', () => setSub(b.dataset.sub)));
  setSub('pending');
}

// 總表查詢：Task 3 佔位，避免子分頁切過去時整頁掛掉。
function renderSummary(body) {
  body.innerHTML = '<div class="mb-ph-card"><h3>總表查詢（Task 3）</h3></div>';
}

async function overdueHtml() {
  try {
    const { status, data } = await api.auditOverdue(SID);
    if (status === 200 && data && data.count > 0) {
      return `<div class="mb-overdue"><span>有 ${data.count} 筆 ${escapeHtml(data.oldest_business_date || '')} 以前的單還沒打勾，請優先處理。</span></div>`;
    }
  } catch { /* 逾期提醒非關鍵路徑，靜默略過 */ }
  return '';
}

async function renderPending(body, onSubtotalChange) {
  body.innerHTML = '<div class="mb-empty-state" style="display:block">載入中…</div>';
  const [{ data }, banner] = await Promise.all([api.auditPending(SID), overdueHtml()]);
  const catResp = await fetch('/expenses/categories').then((r) => r.json()).catch(() => ({}));
  const tree = (catResp && catResp.categories) || [];
  const groups = (data && data.groups) || [];
  if (!groups.length) {
    body.innerHTML = banner + '<div class="mb-empty-state" style="display:block">沒有待稽核單據</div>';
    if (onSubtotalChange) refreshSubtotal(onSubtotalChange);
    return;
  }
  body.innerHTML = banner + groups.map((g) => `
    <div class="mb-day-head"><span class="d">${escapeHtml(g.business_date)}</span>
      <span class="sum">日小計 <b class="num">${formatMoney(g.subtotal)}</b></span></div>
    <div class="mb-cardlist">${g.items.map((e) => cardHtml(e, tree)).join('')}</div>`).join('');
  wireCards(body, onSubtotalChange);
  if (onSubtotalChange) refreshSubtotal(onSubtotalChange);
}

function cardHtml(e, tree) {
  const thumb = e.thumb_url
    ? `<img src="${e.thumb_url}" loading="lazy" class="mb-au-thumb au-thumb" data-zoom="${e.image_url || ''}" alt="收據">`
    : '<span class="mb-au-thumb none">—</span>';
  const reject = e.is_rejected
    ? `<div class="mb-au-flag"><span>會計退回：${escapeHtml(e.reject_reason || '')}</span></div>` : '';
  const mgrEdit = e.is_modified_by_manager ? ' <span class="chip chip-warn">主管改</span>' : '';
  return `<article class="mb-au-card" data-id="${e.id}">
    <div class="mb-au-top">
      ${thumb}
      <div class="mb-au-meta"><div class="mb-au-docno">${escapeHtml(e.doc_no || `#${e.id}`)}</div>
        <div class="mb-au-byline">${escapeHtml(e.created_by_name || '')} · ${formatDateTimeTW(e.created_at)}</div></div>
    </div>
    ${reject}
    <div class="mb-au-summary">${escapeHtml(e.summary || '')}${e.is_no_receipt ? ' <span class="au-mod">無單據</span>' : ''}</div>
    <div class="mb-au-fields">
      <div class="mb-au-field"><label>分類</label><select data-f="category">${categoryOptionsHtml(tree, e.category_id)}</select></div>
      <div class="mb-au-field"><label>金額${mgrEdit}</label><input class="amt num" inputmode="decimal" data-f="amount" value="${e.amount ?? ''}"></div>
      <div class="mb-au-field full"><label>備註</label><input data-f="note" maxlength="200" placeholder="備註（可留空）" value="${escapeHtml(e.note || '')}"></div>
    </div>
    <div class="mb-au-light">${lightLabel(e.light)}</div>
    ${e.has_audit_log ? '<button class="mb-au-hist-toggle" data-act="hist" type="button">▶ 歷程</button><div class="mb-au-hist" hidden></div>' : ''}
    <button class="mb-au-check" data-act="check" type="button">✓ 打勾</button>
    <div class="mb-au-err" data-f="err"></div>
  </article>`;
}

function wireCards(body, onSubtotalChange) {
  body.querySelectorAll('.mb-au-card').forEach((card) => {
    const id = Number(card.dataset.id);
    const err = card.querySelector('[data-f="err"]');
    const cat = card.querySelector('[data-f="category"]');
    const note = card.querySelector('[data-f="note"]');
    const thumbEl = card.querySelector('.au-thumb');
    if (thumbEl) thumbEl.addEventListener('click', () => openImageLightbox(thumbEl.dataset.zoom));
    cat.addEventListener('change', async () => {
      err.textContent = '';
      const categoryId = cat.value === '' ? null : Number(cat.value);
      try { const { status } = await api.auditEdit(id, { category_id: categoryId }, SID);
        if (status !== 200) err.textContent = '分類儲存失敗'; } catch { err.textContent = '分類儲存失敗'; }
    });
    note.addEventListener('change', async () => {
      err.textContent = '';
      try { const { status } = await api.auditEdit(id, { note: note.value }, SID);
        if (status !== 200) err.textContent = '備註儲存失敗'; } catch { err.textContent = '備註儲存失敗'; }
    });
    const histBtn = card.querySelector('[data-act="hist"]');
    if (histBtn) histBtn.addEventListener('click', async () => {
      const box = card.querySelector('.mb-au-hist');
      if (!box.hidden) { box.hidden = true; return; }
      box.hidden = false; box.textContent = '載入中…';
      try { const { data } = await api.expenseLogs(id);
        box.innerHTML = renderTrailRows(data.logs);
      } catch { box.textContent = '歷程載入失敗'; }
    });
    card.querySelector('[data-act="check"]').addEventListener('click', async () => {
      err.textContent = '';
      const parsed = parseAmountInput(card.querySelector('[data-f="amount"]').value);
      if (!parsed.valid) { err.textContent = '金額格式不正確'; return; }
      const categoryId = cat.value === '' ? null : Number(cat.value);
      try {
        const editRes = await api.auditEdit(id, { amount: parsed.value, category_id: categoryId, note: note.value }, SID);
        if (editRes.status !== 200) { err.textContent = '金額/分類/備註儲存失敗'; return; }
        const { status } = await api.auditCheck(id, SID);
        if (status === 200) { card.remove(); if (onSubtotalChange) refreshSubtotal(onSubtotalChange); }
        else err.textContent = '打勾失敗';
      } catch { err.textContent = '打勾失敗'; }
    });
  });
}

async function refreshSubtotal(onSubtotalChange) {
  try {
    const { data } = await api.auditSummary(SID);
    const open = (data && data.open) || { subtotal: 0, count: 0 };
    onSubtotalChange({ subtotalText: formatMoney(open.subtotal), count: open.count });
  } catch { /* 小計非關鍵，失敗不擋 */ }
}

export function wireActionBar(barEl, { onSubtotalChange } = {}) {
  const err = barEl.querySelector('#mb-ab-err');
  const doClose = async (type) => {
    err.textContent = '';
    const { status, data } = await api.auditHandover(type, SID);
    err.textContent = status === 200 ? `已${type === 'day' ? '結班' : '交班'}（${data.count} 筆）` : '沒有可歸班的單據';
    if (status === 200 && onSubtotalChange) refreshSubtotal(onSubtotalChange);
  };
  barEl.querySelector('#mb-ab-shift').addEventListener('click', () => doClose('shift'));
  barEl.querySelector('#mb-ab-day').addEventListener('click', () => doClose('day'));
  barEl.querySelector('#mb-ab-undo').addEventListener('click', async () => {
    err.textContent = '';
    const { status, data } = await api.auditUndo(SID);
    err.textContent = status === 200 ? `已取消，退回 ${data.reopened} 筆` : '沒有可取消的交班';
    if (status === 200 && onSubtotalChange) refreshSubtotal(onSubtotalChange);
  });
  if (onSubtotalChange) refreshSubtotal(onSubtotalChange);
}
