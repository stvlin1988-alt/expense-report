import { api } from './admin_api.js';
import { escapeHtml } from './admin_util.js';
import { categoryOptionsHtml, lightLabel, parseAmountInput } from './expenses_util.js';
import { formatMoney, formatDateTimeTW, renderTrailRows, status_label } from './audit_util.js';
import { openImageLightbox } from './lightbox.js';

// storeId：super_admin 選定的店；manager 傳 null（後端用本店）
// stores：全店清單（{id, code, viewable, active}），供經理唯讀 render 的「選店/空狀態快速鍵」用。
export async function renderAudit(container, identity, storeId, stores) {
  const isSuper = identity.role === 'super_admin';
  if (isSuper) return renderAuditReadonly(container, storeId, stores);
  // 主管：沿用現行可操作流程（待稽核／總表兩個 sub-tab），外觀 wk 化、行為不變。
  const sid = undefined;
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

// ===== 經理（super_admin）唯讀 render =====
// 全部門市（storeId 為 null）→ 空狀態卡＋各可見店快速鍵；選定店 → 依班別分組唯讀表
// （縮圖／摘要／單號·建立者·時間、店別、分類、金額、燈號＋徽章）。無編輯/打勾/交班。
// 選店/返回全部門市透過全域 #ap-store（isSuper 才存在）dispatch change，讓 admin.js 更新 state 並重繪。
function pickStore(id) {
  const sel = document.getElementById('ap-store');
  if (!sel) return;
  sel.value = id == null ? '' : String(id);
  sel.dispatchEvent(new Event('change'));
}

function readonlyRowHtml(e, storeCode) {
  const thumb = e.thumb_url
    ? `<img src="${e.thumb_url}" loading="lazy" class="wk-rcp-thumb au-thumb" data-zoom="${e.image_url || ''}" alt="收據">`
    : '<span class="wk-rcp-none">—</span>';
  const checked = e.status !== 'submitted';
  const lamp = checked
    ? '<span class="wk-lamp"><span class="wk-dot wk-dot-g"></span>已稽核</span>'
    : '<span class="wk-lamp"><span class="wk-dot wk-dot-y"></span>待稽核</span>';
  const badgeCls = {
    submitted: 'wk-badge-pending', audited: 'wk-badge-neutral',
    reconciled: 'wk-badge-open', rejected: 'wk-badge-bad',
  }[e.status] || 'wk-badge-neutral';
  const badge = `<span class="wk-badge ${badgeCls}">${escapeHtml(status_label(e.status))}</span>`;
  const amt = Number(e.amount);
  const neg = Number.isFinite(amt) && amt < 0;
  return `<tr>
    <td><div class="wk-doc-cell wk-audit-doc">${thumb}
      <div class="wk-doc-meta"><span class="wk-doc-summary">${escapeHtml(e.summary || '')}${e.is_no_receipt ? ' <span class="au-mod">無單據</span>' : ''}</span>
        <span class="wk-doc-sub">${escapeHtml(e.doc_no || `#${e.id}`)} · ${escapeHtml(e.created_by_name || '')} · ${formatDateTimeTW(e.created_at)}</span>
        ${e.note ? `<span class="wk-doc-note">備註：${escapeHtml(e.note)}</span>` : ''}
      </div></div></td>
    <td><span class="wk-store-tag">${escapeHtml(storeCode)}</span></td>
    <td><span class="wk-chip">${escapeHtml(e.category_name || '未分類')}</span></td>
    <td class="num${neg ? ' neg' : ''}">${formatMoney(e.amount)}</td>
    <td><div class="wk-lamp-cell">${lamp}${badge}</div></td>
  </tr>`;
}

async function renderAuditReadonly(container, storeId, stores) {
  const viewableStores = (stores || []).filter((s) => s.viewable !== false);
  const scopeLabel = storeId == null
    ? '全部門市'
    : escapeHtml((viewableStores.find((s) => s.id === storeId) || {}).code || '');
  const toolbar = `
    <div class="wk-toolbar"><div class="wk-toolbar-row">
      <span class="wk-toolbar-title">交接班稽核</span>
      <span class="wk-badge wk-badge-locked">唯讀</span>
      <span class="wk-filter-label">打勾稽核由各店主管於交接班執行，經理僅檢視結果</span>
      <span class="wk-spacer"></span>
      <span class="wk-badge wk-badge-scope">${scopeLabel}</span>
    </div></div>`;

  if (storeId == null) {
    const btns = viewableStores.map((s) =>
      `<button class="wk-btn wk-btn-secondary" data-pick="${s.id}" type="button">${escapeHtml(s.code)}</button>`).join('');
    container.innerHTML = `${toolbar}
      <div class="wk-page-body"><div class="wk-empty-tip">
        請先在左側「<b>門市範圍</b>」選擇一家店<br>
        <span style="font-size:12px;color:var(--wk-faint)">選店同時決定稽核與月報表看哪家</span>
        <div class="wk-empty-stores">${btns}</div>
      </div></div>`;
    container.querySelectorAll('[data-pick]').forEach((b) =>
      b.addEventListener('click', () => pickStore(Number(b.dataset.pick))));
    return;
  }

  container.innerHTML = `${toolbar}<div class="wk-page-body"><div class="wk-empty">載入中…</div></div>`;
  const storeCode = scopeLabel;
  const { data: dd } = await api.auditSummaryDates(storeId);
  const dates = (dd && dd.dates) || [];
  const today = dates[0] || '';
  const { data } = today ? await api.auditByDate(storeId, today) : { data: { shifts: [] } };
  const shifts = data.shifts || [];
  const rows = shifts.map((sh) => `
    <tr class="wk-day-head"><td colspan="5">${escapeHtml(shiftLabel(sh))}　小計 ${formatMoney(sh.subtotal)}（${sh.count} 筆）</td></tr>
    ${sh.items.map((e) => readonlyRowHtml(e, storeCode)).join('')}`).join('');

  const pageBody = container.querySelector('.wk-page-body');
  pageBody.innerHTML = `
    <div class="wk-audit-back-bar">
      <button class="wk-btn wk-btn-secondary" id="au-ro-back" type="button">‹ 返回全部門市</button>
      <span class="wk-filter-label">目前檢視　<span class="wk-store-tag">${escapeHtml(storeCode)}</span></span>
    </div>
    <div class="wk-card"><div class="table-wrap">
      <table class="wk-audit-table"><thead><tr>
        <th>單據</th><th>店別</th><th>分類</th><th class="num-h">金額</th><th>稽核狀態</th>
      </tr></thead><tbody>${rows || '<tr><td colspan="5" class="wk-empty">目前沒有單據</td></tr>'}</tbody></table>
    </div></div>`;
  pageBody.querySelector('#au-ro-back').addEventListener('click', () => pickStore(null));
  pageBody.querySelectorAll('.au-thumb').forEach((img) =>
    img.addEventListener('click', () => openImageLightbox(img.dataset.zoom)));
}

function shiftLabel(sh) {
  if (sh.handover_id === null) return '當前未歸班';
  const kind = sh.type === 'day' ? '結班' : '交班';
  return `第 ${sh.seq} 班（${kind} ${formatDateTimeTW(sh.closed_at)}）`;
}

// 「改：誰（時間）」小標，只掛在實際被改的欄位（金額/分類）下方。
// 舊資料無 last_modified_fields → 退回掛在金額欄（沿用舊行為）。
function lastModTag(e, field) {
  if (!e.last_modified_at) return '';
  const fields = e.last_modified_fields ? e.last_modified_fields.split(',') : null;
  const show = fields ? fields.includes(field) : (field === 'amount');
  if (!show) return '';
  return `<div class="au-lastmod">改：${escapeHtml(e.last_modified_by_name || '')}（${formatDateTimeTW(e.last_modified_at)}）</div>`;
}

function summaryRowHtml(e) {
  return `
    <tr data-eid="${e.id}">
      <td class="au-docno">${escapeHtml(e.doc_no || `#${e.id}`)}</td>
      <td class="au-time">${formatDateTimeTW(e.created_at)}</td>
      <td>${escapeHtml(e.created_by_name || '')}</td>
      <td>${e.thumb_url ? `<img src="${e.thumb_url}" width="40" class="au-thumb" data-zoom="${e.image_url || ''}">` : '—'}</td>
      <td>${escapeHtml(e.summary || '')}${e.is_no_receipt ? ' <span class="au-mod">無單據</span>' : ''}</td>
      <td>${escapeHtml(e.category_name || '')}${lastModTag(e, 'category')}</td>
      <td>${e.amount ?? ''}${e.is_modified_by_manager ? ' <span class="au-mod">主管改</span>' : ''}${lastModTag(e, 'amount')}</td>
      <td>${e.note ? escapeHtml(e.note) : ''}</td>
      <td>${lightLabel(e.light)}</td>
      <td>${escapeHtml(status_label(e.status))}</td>
      <td>${escapeHtml(e.audited_by_name || '—')}</td>
      <td>${e.has_audit_log ? `<button class="au-trail-btn" data-trail="${e.id}" type="button">歷程</button>` : ''}</td>
    </tr>`;
}

// 歷程展開：委派綁定 scope 內的 [data-trail] 按鈕，點擊在該列下方插入一列
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
        box.innerHTML = `<td colspan="${colspan}">歷程載入失敗</td>`;
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
    <div class="wk-card au-group">
      <div class="wk-card-head au-group-head">${shiftLabel(sh)}　小計 ${formatMoney(sh.subtotal)}（${sh.count} 筆）</div>
      <div class="table-wrap">
      <table class="wk-audit-table"><thead><tr>
        <th>單號</th><th>建立</th><th>建立者</th><th>圖</th><th>摘要</th><th>分類</th><th>金額</th><th>備註</th><th>燈</th><th>狀態</th><th>稽核者</th><th>歷程</th>
      </tr></thead><tbody>${sh.items.map(summaryRowHtml).join('')}</tbody></table>
      </div>
    </div>`).join('');
  body.innerHTML = `
    <div class="au-day-nav">日期：<input type="date" id="au-day-date" value="${sel}"${today ? ` max="${today}"` : ''}></div>
    ${shiftBlocks || '<div class="wk-empty">當天沒有單據</div>'}
    <div class="au-daytotal">當日總額 <b>${formatMoney(data.total)}</b>（${data.count} 筆）</div>`;
  const dinp = body.querySelector('#au-day-date');
  if (dinp) dinp.addEventListener('change', (ev) => {
    if (ev.target.value) renderSummary(body, sid, ev.target.value);
  });
  body.querySelectorAll('.au-thumb').forEach((img) =>
    img.addEventListener('click', () => openImageLightbox(img.dataset.zoom)));
  wireTrails(body, 12);
}

// 逾期橫幅：清單載入時同時打 /audit/overdue，count>0 就在清單上方插一條提醒。
// 失敗（網路/權限）就當沒有逾期，不擋主流程。
async function overdueBannerHtml(sid) {
  try {
    const { status, data } = await api.auditOverdue(sid);
    if (status === 200 && data && data.count > 0) {
      return `<div class="ap-overdue">有 ${data.count} 筆 `
        + `${escapeHtml(data.oldest_business_date || '')} 以前的單還沒打勾</div>`;
    }
  } catch { /* 逾期提醒非關鍵路徑，靜默略過 */ }
  return '';
}

async function renderPending(body, sid) {
  body.innerHTML = '載入中…';
  const [{ data }, banner] = await Promise.all([api.auditPending(sid), overdueBannerHtml(sid)]);
  // 分類清單（供下拉）——沿用員工端 /expenses/categories
  const catResp = await fetch('/expenses/categories').then((r) => r.json()).catch(() => ({}));
  const tree = (catResp && catResp.categories) || [];
  const groups = (data && data.groups) || [];
  if (!groups.length) {
    body.innerHTML = `${banner}<div class="wk-empty">沒有待稽核單據</div>`;
  } else {
    body.innerHTML = banner + groups.map((g) => `
      <div class="wk-card au-group">
        <div class="wk-card-head au-group-head">${g.business_date}　日小計 ${formatMoney(g.subtotal)}</div>
        <div class="table-wrap">
        <table class="wk-audit-table"><thead><tr>
          <th>單號</th><th>圖</th><th>建立</th><th>建立者</th><th>摘要</th><th>分類</th><th>金額</th><th>備註</th><th>燈</th><th></th>
        </tr></thead><tbody>
        ${g.items.map((e) => rowHtml(e, tree)).join('')}
        </tbody></table>
        </div>
      </div>`).join('');
    wireRows(body, sid);
    wireTrails(body, 10);
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
    <button class="wk-btn wk-btn-primary" id="au-shift" type="button">交班</button>
    <button class="wk-btn wk-btn-primary" id="au-day" type="button">結班</button>
    <button class="wk-btn wk-btn-secondary" id="au-undo" type="button">取消上一次</button>
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
  return `<tr data-id="${e.id}"${e.is_rejected ? ' class="ap-row-rejected"' : ''}>
    <td class="au-docno">${escapeHtml(e.doc_no || `#${e.id}`)}</td>
    <td>${thumb}</td>
    <td class="au-time">${formatDateTimeTW(e.created_at)}</td>
    <td>${escapeHtml(e.created_by_name || '')}</td>
    <td>${escapeHtml(e.summary || '')}</td>
    <td><select data-f="category">${categoryOptionsHtml(tree, e.category_id)}</select>${lastModTag(e, 'category')}</td>
    <td><input value="${e.amount ?? ''}" inputmode="decimal" data-f="amount" class="wk-input"></td>
    <td><input value="${escapeHtml(e.note || '')}" maxlength="200" placeholder="備註（可留空）" data-f="note" class="wk-input"></td>
    <td>${lightLabel(e.light)}</td>
    <td>
      ${e.is_rejected ? `<div class="ap-reject-reason">會計退回：${escapeHtml(e.reject_reason || '')}</div>` : ''}
      <button class="wk-btn wk-btn-sm wk-btn-primary" data-act="check" type="button">打勾</button>${e.has_audit_log ? `<button class="au-trail-btn" data-trail="${e.id}" type="button">歷程</button>` : ''}<div class="pd-row-err" data-f="err"></div>
    </td>
  </tr>`;
}

function wireRows(body, sid) {
  body.querySelectorAll('tr[data-id]').forEach((tr) => {
    const id = Number(tr.dataset.id);
    const err = tr.querySelector('[data-f="err"]');
    const cat = tr.querySelector('[data-f="category"]');
    const note = tr.querySelector('[data-f="note"]');
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
    note.addEventListener('change', async () => {
      err.textContent = '';
      try {
        const { status } = await api.auditEdit(id, { note: note.value }, sid);
        if (status !== 200) err.textContent = '備註儲存失敗';
      } catch { err.textContent = '備註儲存失敗'; }
    });
    tr.querySelector('[data-act="check"]').addEventListener('click', async () => {
      err.textContent = '';
      const parsed = parseAmountInput(tr.querySelector('[data-f="amount"]').value);
      if (!parsed.valid) { err.textContent = '金額格式不正確'; return; }
      const categoryId = cat.value === '' ? null : Number(cat.value);
      try {
        const editRes = await api.auditEdit(
          id, { amount: parsed.value, category_id: categoryId, note: note.value }, sid,
        );
        if (editRes.status !== 200) { err.textContent = '金額/分類/備註儲存失敗'; return; }
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
