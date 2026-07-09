import { api } from './admin_api.js';
import { escapeHtml } from './admin_util.js';
import { categoryOptionsHtml, lightLabel, parseAmountInput } from './expenses_util.js';
import { formatMoney, formatDateTimeTW, renderTrailRows } from './audit_util.js';
import { openImageLightbox } from './lightbox.js';

// storeId：super_admin 選定的店；manager 傳 null（後端用本店）
export async function renderAudit(container, identity, storeId) {
  const isSuper = identity.role === 'super_admin';
  if (isSuper && !storeId) {
    container.innerHTML = '<div class="ap-empty">請先於上方選擇一家店</div>';
    return;
  }
  const sid = isSuper ? storeId : undefined;
  container.innerHTML = `
    <div class="audit-sub">
      <button class="ap-tab active" id="au-tab-pending" type="button">待稽核</button>
      <button class="ap-tab" id="au-tab-summary" type="button">總表查詢</button>
    </div>
    <div id="au-body"></div>`;
  const body = container.querySelector('#au-body');
  const tabP = container.querySelector('#au-tab-pending');
  const tabS = container.querySelector('#au-tab-summary');
  const setActive = (el) => {
    [tabP, tabS].forEach((b) => b.classList.remove('active')); el.classList.add('active');
  };
  tabP.addEventListener('click', () => { setActive(tabP); renderPending(body, sid); });
  tabS.addEventListener('click', () => { setActive(tabS); renderSummary(body, sid); });
  setActive(tabP);
  renderPending(body, sid);
}

function shiftLabel(sh) {
  if (sh.handover_id === null) return '當前未歸班';
  const kind = sh.type === 'day' ? '結班' : '交班';
  return `第 ${sh.seq} 班（${kind} ${formatDateTimeTW(sh.closed_at)}）`;
}

function summaryRowHtml(e) {
  return `
    <tr data-eid="${e.id}">
      <td class="au-docno">${escapeHtml(e.doc_no || `#${e.id}`)}</td>
      <td class="au-time">${formatDateTimeTW(e.created_at)}</td>
      <td>${escapeHtml(e.created_by_name || '')}</td>
      <td>${e.thumb_url ? `<img src="${e.thumb_url}" width="40" class="au-thumb" data-zoom="${e.image_url || ''}">` : '—'}</td>
      <td>${escapeHtml(e.summary || '')}${e.is_no_receipt ? ' <span class="au-mod">無單據</span>' : ''}</td>
      <td>${escapeHtml(e.category_name || '')}</td>
      <td>${e.amount ?? ''}${e.is_modified_by_manager ? ' <span class="au-mod">主管改</span>' : ''}
        ${e.last_modified_at ? `<div class="au-lastmod">改：${escapeHtml(e.last_modified_by_name || '')}（${formatDateTimeTW(e.last_modified_at)}）</div>` : ''}</td>
      <td>${lightLabel(e.light)}</td>
      <td>${e.status === 'audited' ? '已稽核' : '待稽核'}</td>
      <td>${escapeHtml(e.audited_by_name || '')}</td>
      <td>${e.last_modified_at ? `<button class="au-trail-btn" data-trail="${e.id}" type="button">軌跡</button>` : ''}</td>
    </tr>`;
}

// 軌跡展開：委派綁定 scope 內的 [data-trail] 按鈕，點擊在該列下方插入一列
// 顯示 誰・時間・動作（含員工確認區改的那筆 + 主管簽核那筆）。總表/待稽核共用。
function wireTrails(scope, colspan) {
  scope.querySelectorAll('[data-trail]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const tr = btn.closest('tr');
      let box = tr.nextElementSibling;
      if (box && box.classList.contains('au-trail-tr')) { box.remove(); return; }
      box = document.createElement('tr');
      box.className = 'au-trail-tr';
      box.innerHTML = `<td colspan="${colspan}">載入中…</td>`;
      tr.after(box);
      try {
        const { data } = await api.expenseLogs(btn.dataset.trail);
        box.innerHTML = `<td colspan="${colspan}">${renderTrailRows(data.logs)}</td>`;
      } catch {
        box.innerHTML = `<td colspan="${colspan}">軌跡載入失敗</td>`;
      }
    });
  });
}

async function renderSummary(body, sid, dateStr) {
  body.innerHTML = '載入中…';
  // 預設今日（沿用後端算好的當前營業日；summary-dates[0]=今日）
  const { data: dd } = await api.auditSummaryDates(sid);
  const dates = (dd && dd.dates) || [];
  const today = dates[0] || '';
  const sel = dateStr || today;
  const { data } = sel ? await api.auditByDate(sid, sel) : { data: { shifts: [], total: 0, count: 0 } };
  const shifts = data.shifts || [];
  const shiftBlocks = shifts.map((sh) => `
    <div class="au-group">
      <div class="au-group-head">${shiftLabel(sh)}　小計 ${formatMoney(sh.subtotal)}（${sh.count} 筆）</div>
      <div class="pd-table-wrap">
      <table class="pd-table"><thead><tr>
        <th>單號</th><th>建立</th><th>建立者</th><th>圖</th><th>摘要</th><th>分類</th><th>金額</th><th>燈</th><th>狀態</th><th>稽核者</th><th>軌跡</th>
      </tr></thead><tbody>${sh.items.map(summaryRowHtml).join('')}</tbody></table>
      </div>
    </div>`).join('');
  body.innerHTML = `
    <div class="au-day-nav">日期：<input type="date" id="au-day-date" value="${sel}"${today ? ` max="${today}"` : ''}></div>
    ${shiftBlocks || '<div class="ap-empty">當天沒有單據</div>'}
    <div class="au-daytotal">當日總額 <b>${formatMoney(data.total)}</b>（${data.count} 筆）</div>`;
  const dinp = body.querySelector('#au-day-date');
  if (dinp) dinp.addEventListener('change', (ev) => {
    if (ev.target.value) renderSummary(body, sid, ev.target.value);
  });
  body.querySelectorAll('.au-thumb').forEach((img) =>
    img.addEventListener('click', () => openImageLightbox(img.dataset.zoom)));
  wireTrails(body, 11);
}

async function renderPending(body, sid) {
  body.innerHTML = '載入中…';
  const { data } = await api.auditPending(sid);
  // 分類清單（供下拉）——沿用員工端 /expenses/categories
  const catResp = await fetch('/expenses/categories').then((r) => r.json()).catch(() => ({}));
  const tree = (catResp && catResp.categories) || [];
  const groups = (data && data.groups) || [];
  if (!groups.length) {
    body.innerHTML = '<div class="ap-empty">沒有待稽核單據</div>';
  } else {
    body.innerHTML = groups.map((g) => `
      <div class="au-group">
        <div class="au-group-head">${g.business_date}　日小計 ${formatMoney(g.subtotal)}</div>
        <table class="pd-table"><thead><tr>
          <th>單號</th><th>圖</th><th>建立</th><th>建立者</th><th>摘要</th><th>分類</th><th>金額</th><th>燈</th><th></th>
        </tr></thead><tbody>
        ${g.items.map((e) => rowHtml(e, tree)).join('')}
        </tbody></table>
      </div>`).join('');
    wireRows(body, sid);
    wireTrails(body, 9);
  }
  // 交班/結班/取消：交班狀態與待稽核佇列無關，即使清空也需常駐可操作
  body.appendChild(actionBar(sid, body));
}

// 讀 auditSummary 的 open bucket（已打勾、尚未歸班）寫入 action bar 的即時小計，
// 不重繪整個待稽核列表 → 不會蓋掉其他列正在編輯中的金額/分類。
async function refreshSubtotal(body, sid) {
  const el = body.querySelector('#au-subtotal');
  if (!el) return;
  const { data } = await api.auditSummary(sid);
  const open = (data && data.open) || { subtotal: 0, count: 0 };
  el.textContent = `當前班即時小計 ${formatMoney(open.subtotal)}（${open.count} 筆）`;
}

function actionBar(sid, body) {
  const bar = document.createElement('div');
  bar.className = 'au-actionbar';
  bar.innerHTML = `
    <button class="modal-btn" id="au-shift" type="button">交班</button>
    <button class="modal-btn" id="au-day" type="button">結班</button>
    <button class="modal-btn secondary" id="au-undo" type="button">取消上一次</button>
    <span class="au-subtotal" id="au-subtotal"></span>
    <span class="pd-row-err" id="au-bar-err"></span>`;
  const barErr = bar.querySelector('#au-bar-err');
  const doClose = async (type) => {
    barErr.textContent = '';
    const { status, data } = await api.auditHandover(type, sid);
    barErr.textContent = status === 200
      ? `已${type === 'day' ? '結班' : '交班'}（${data.count} 筆）` : '沒有可歸班的單據';
    if (status === 200) refreshSubtotal(body, sid);
  };
  bar.querySelector('#au-shift').addEventListener('click', () => doClose('shift'));
  bar.querySelector('#au-day').addEventListener('click', () => doClose('day'));
  bar.querySelector('#au-undo').addEventListener('click', async () => {
    barErr.textContent = '';
    const { status, data } = await api.auditUndo(sid);
    barErr.textContent = status === 200 ? `已取消，退回 ${data.reopened} 筆` : '沒有可取消的交班';
    if (status === 200) refreshSubtotal(body, sid);
  });
  // action bar 一建立就顯示目前的即時小計（body 稍後由呼叫端 append，
  // fetch 屬非同步、resolve 時 bar 已在 DOM 內）
  refreshSubtotal(body, sid);
  return bar;
}

function rowHtml(e, tree) {
  const thumb = e.thumb_url
    ? `<img src="${e.thumb_url}" loading="lazy" width="48" class="au-thumb" data-zoom="${e.image_url || ''}">`
    : '—';
  return `<tr data-id="${e.id}">
    <td class="au-docno">${escapeHtml(e.doc_no || `#${e.id}`)}</td>
    <td>${thumb}</td>
    <td class="au-time">${formatDateTimeTW(e.created_at)}</td>
    <td>${escapeHtml(e.created_by_name || '')}</td>
    <td>${escapeHtml(e.summary || '')}</td>
    <td><select data-f="category">${categoryOptionsHtml(tree, e.category_id)}</select></td>
    <td><input value="${e.amount ?? ''}" inputmode="decimal" data-f="amount" style="width:80px">
      ${e.last_modified_at ? `<div class="au-lastmod">改：${escapeHtml(e.last_modified_by_name || '')}（${formatDateTimeTW(e.last_modified_at)}）</div>` : ''}</td>
    <td>${lightLabel(e.light)}</td>
    <td><button data-act="check">打勾</button>${e.last_modified_at ? `<button class="au-trail-btn" data-trail="${e.id}" type="button">軌跡</button>` : ''}<div class="pd-row-err" data-f="err"></div></td>
  </tr>`;
}

function wireRows(body, sid) {
  body.querySelectorAll('tr[data-id]').forEach((tr) => {
    const id = Number(tr.dataset.id);
    const err = tr.querySelector('[data-f="err"]');
    const cat = tr.querySelector('[data-f="category"]');
    const thumbEl = tr.querySelector('.au-thumb');
    if (thumbEl) thumbEl.addEventListener('click', () => openImageLightbox(thumbEl.dataset.zoom));
    cat.addEventListener('change', async () => {
      err.textContent = '';
      const categoryId = cat.value === '' ? null : Number(cat.value);
      try {
        const { status } = await api.auditEdit(id, { category_id: categoryId }, sid);
        if (status !== 200) err.textContent = '分類儲存失敗';
      } catch { err.textContent = '分類儲存失敗'; }
    });
    tr.querySelector('[data-act="check"]').addEventListener('click', async () => {
      err.textContent = '';
      const parsed = parseAmountInput(tr.querySelector('[data-f="amount"]').value);
      if (!parsed.valid) { err.textContent = '金額格式不正確'; return; }
      const categoryId = cat.value === '' ? null : Number(cat.value);
      try {
        const editRes = await api.auditEdit(id, { amount: parsed.value, category_id: categoryId }, sid);
        if (editRes.status !== 200) { err.textContent = '金額/分類儲存失敗'; return; }
        const { status } = await api.auditCheck(id, sid);
        if (status === 200) {
          const trail = tr.nextElementSibling;
          if (trail && trail.classList.contains('au-trail-tr')) trail.remove();
          tr.remove();
          refreshSubtotal(body, sid);
        } else err.textContent = '打勾失敗';
      } catch { err.textContent = '打勾失敗'; }
    });
  });
}
