import { api } from './admin_api.js';
import { escapeHtml } from './admin_util.js';
import { categoryOptionsHtml, lightLabel, parseAmountInput } from './expenses_util.js';
import { formatMoney, formatDateTimeTW } from './audit_util.js';

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
      <button class="ap-tab" id="au-tab-summary" type="button">當日總表</button>
    </div>
    <div id="au-body"></div>`;
  const body = container.querySelector('#au-body');
  const showPending = () => renderPending(body, sid);
  container.querySelector('#au-tab-pending').addEventListener('click', showPending);
  container.querySelector('#au-tab-summary').addEventListener('click',
    () => renderSummary(body, sid));
  showPending();
}

async function renderSummary(body, sid, beforeId) {
  body.innerHTML = '載入中…';
  const [{ data: daysData }, { data }] = await Promise.all([
    api.auditDays(sid), api.auditSummary(sid, beforeId || undefined),
  ]);
  const days = (daysData && daysData.days) || [];
  const cur = String(beforeId || '');
  const dayOpts = ['<option value="">今日（當前）</option>'].concat(
    days.map((d) => `<option value="${d.handover_id}"${String(d.handover_id) === cur ? ' selected' : ''}>${formatDateTimeTW(d.closed_at)}</option>`)
  ).join('');
  const intervals = data.intervals || [];
  const open = data.open || { subtotal: 0, count: 0 };
  const intervalRows = intervals.map((it) => `
    <tr class="au-int" data-hid="${it.handover_id}">
      <td>第 ${it.seq} 班${it.type === 'day' ? '（結班）' : ''} ▸</td>
      <td>${formatDateTimeTW(it.closed_at)}</td>
      <td>${it.count} 筆</td><td>${formatMoney(it.subtotal)}</td>
    </tr>`).join('');
  const openRow = beforeId ? '' : `
    <tr class="au-int au-open-row" data-open="1">
      <td>當前未歸班 ▸</td><td>—</td><td>${open.count} 筆</td><td>${formatMoney(open.subtotal)}</td>
    </tr>`;
  body.innerHTML = `
    <div class="au-day-nav">稽核日：<select id="au-day-select">${dayOpts}</select></div>
    <table class="pd-table"><thead><tr><th>區間</th><th>交班時間</th><th>筆數</th><th>小計</th></tr></thead>
    <tbody>${intervalRows}${openRow}</tbody>
    <tfoot><tr><td colspan="3"><b>當日總額</b></td><td><b>${formatMoney(data.day_total)}</b></td></tr></tfoot>
    </table>`;
  body.querySelector('#au-day-select').addEventListener('change',
    (ev) => renderSummary(body, sid, ev.target.value));
  body.querySelectorAll('tr.au-int').forEach((tr) =>
    tr.addEventListener('click', () => toggleDetail(tr, sid)));
}

async function toggleDetail(tr, sid) {
  const next = tr.nextElementSibling;
  if (next && next.classList.contains('au-detail')) { next.remove(); return; }
  // 收合其他已展開的明細（一次只開一個）
  tr.parentElement.querySelectorAll('tr.au-detail').forEach((r) => r.remove());
  const detailTr = document.createElement('tr');
  detailTr.className = 'au-detail';
  detailTr.innerHTML = '<td colspan="4">載入中…</td>';
  tr.after(detailTr);
  const hid = tr.dataset.hid;
  const { data } = hid ? await api.auditHandoverItems(hid, sid) : await api.auditOpenItems(sid);
  const items = (data && data.items) || [];
  const cell = detailTr.querySelector('td');
  if (!items.length) { cell.textContent = '（無明細）'; return; }
  cell.innerHTML = `
    <table class="au-detail-table"><thead><tr>
      <th>建立</th><th>圖</th><th>摘要</th><th>分類</th><th>金額</th><th>燈</th><th>稽核者</th><th>稽核時間</th>
    </tr></thead><tbody>
    ${items.map((e) => `
      <tr>
        <td class="au-time">${formatDateTimeTW(e.created_at)}</td>
        <td>${e.thumb_url ? `<img src="${e.thumb_url}" width="40" class="au-thumb" data-zoom="${e.image_url || ''}">` : '—'}</td>
        <td>${escapeHtml(e.summary || '')}</td>
        <td>${escapeHtml(e.category_name || '')}</td>
        <td>${e.amount ?? ''}${e.is_modified_by_manager ? ' <span class="au-mod">主管改</span>' : ''}</td>
        <td>${lightLabel(e.light)}</td>
        <td>${escapeHtml(e.audited_by_name || '')}</td>
        <td class="au-time">${formatDateTimeTW(e.audited_at)}</td>
      </tr>`).join('')}
    </tbody></table>`;
  cell.querySelectorAll('.au-thumb').forEach((img) =>
    img.addEventListener('click', (ev) => { ev.stopPropagation(); openImageLightbox(img.dataset.zoom); }));
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
          <th>圖</th><th>建立</th><th>摘要</th><th>分類</th><th>金額</th><th>燈</th><th></th>
        </tr></thead><tbody>
        ${g.items.map((e) => rowHtml(e, tree)).join('')}
        </tbody></table>
      </div>`).join('');
    wireRows(body, sid);
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
    <td>${thumb}</td>
    <td class="au-time">${formatDateTimeTW(e.created_at)}</td>
    <td>${escapeHtml(e.summary || '')}</td>
    <td><select data-f="category">${categoryOptionsHtml(tree, e.category_id)}</select></td>
    <td><input value="${e.amount ?? ''}" inputmode="decimal" data-f="amount" style="width:80px"></td>
    <td>${lightLabel(e.light)}</td>
    <td><button data-act="check">打勾</button><div class="pd-row-err" data-f="err"></div></td>
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
        if (status === 200) { tr.remove(); refreshSubtotal(body, sid); } else err.textContent = '打勾失敗';
      } catch { err.textContent = '打勾失敗'; }
    });
  });
}

export function openImageLightbox(url) {
  if (!url) return;
  const ov = document.createElement('div');
  ov.className = 'au-lightbox';
  const img = document.createElement('img');
  img.src = url; img.alt = '原單';
  ov.appendChild(img);
  const close = () => { ov.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = (ev) => { if (ev.key === 'Escape') close(); };
  ov.addEventListener('click', close);
  document.addEventListener('keydown', onKey);
  document.body.appendChild(ov);
}
