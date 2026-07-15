import { reportsApi } from './reports_api.js';
import { escapeHtml } from './admin_util.js';

/**
 * 純函式：把一個 cell（{reconciled, pending}）格式化成「單一總額」顯示文字。
 * 月報表看的是該期整體已確認金額（已核銷＋待核銷合計），不拆「已核銷／待核銷」。
 * negative：合計為負時供呼叫端套紅字 class。
 */
export function formatCell(cell) {
  const total = Number((cell && cell.reconciled) || 0) + Number((cell && cell.pending) || 0);
  return { text: total.toLocaleString('en-US', { maximumFractionDigits: 2 }), negative: total < 0 };
}

/**
 * 依選取的門市取某列的金額 cell。
 * storeId 為空字串＝「全部門市」→ 用該列的 .total（各店合計）；
 * 否則取該列 per_store[storeId]（該店在這列的金額）。查無則回 0。
 */
export function pickCell(obj, storeId) {
  if (!storeId) return (obj && obj.total) || { reconciled: 0, pending: 0 };
  return (obj && obj.per_store && obj.per_store[storeId]) || { reconciled: 0, pending: 0 };
}

function cellHtml(cell) {
  const { text, negative } = formatCell(cell);
  return `<td><span class="rc-amt${negative ? ' rc-neg' : ''}">${escapeHtml(text)}</span></td>`;
}

// 全部門市模式：每家店一欄。回傳該列所有門市欄的 <td>。
function perStoreTds(obj, stores) {
  return stores.map((s) => cellHtml((obj.per_store && obj.per_store[s.id]) || null)).join('');
}

// 大類列：可展開鈕（有 children 才顯示）＋科目名稱＋金額欄。
function majorRowHtml(row, idx, stores, storeId) {
  const hasChildren = !!(row.children && row.children.length);
  const toggle = hasChildren
    ? `<button type="button" class="mr-toggle" data-idx="${idx}" aria-expanded="false">▶</button> `
    : '';
  const amountTds = storeId
    ? cellHtml(pickCell(row, storeId))
    : perStoreTds(row, stores) + cellHtml(row.total);
  return `<tr class="mr-major-row" data-idx="${idx}">
    <td>${toggle}${escapeHtml(row.major_name)}</td>${amountTds}
  </tr>`;
}

// 細類列：預設 hidden，點大類的展開鈕才顯示。
function childRowHtml(child, parentIdx, stores, storeId) {
  const amountTds = storeId
    ? cellHtml(pickCell(child, storeId))
    : perStoreTds(child, stores) + cellHtml(child.total);
  return `<tr class="mr-child-row" data-parent-idx="${parentIdx}" hidden>
    <td class="mr-child-name">${escapeHtml(child.major_name)}</td>${amountTds}
  </tr>`;
}

function footerRowHtml(data, stores, storeId) {
  const amountTds = storeId
    ? cellHtml((data.store_totals && data.store_totals[storeId]) || null)
    : stores.map((s) => cellHtml((data.store_totals && data.store_totals[s.id]) || null)).join('')
      + cellHtml(data.grand_total);
  return `<tr class="mr-total-row"><td>總計</td>${amountTds}</tr>`;
}

function tableHtml(data, storeId) {
  const stores = data.stores || [];
  const rows = data.rows || [];
  // 表頭：全部門市＝每店一欄＋總計；單店＝金額一欄。
  const headCells = storeId
    ? '<th>金額</th>'
    : stores.map((s) => `<th>${escapeHtml(s.name)}</th>`).join('') + '<th>總計</th>';
  const bodyRows = rows.map((row, idx) => {
    const childRows = (row.children || [])
      .map((child) => childRowHtml(child, idx, stores, storeId)).join('');
    return majorRowHtml(row, idx, stores, storeId) + childRows;
  }).join('');
  return `
    <div class="pd-table-wrap">
      <table class="pd-table mr-table${storeId ? ' mr-single' : ''}">
        <thead><tr><th>科目</th>${headCells}</tr></thead>
        <tbody>${bodyRows}${footerRowHtml(data, stores, storeId)}</tbody>
      </table>
    </div>`;
}

function headerHtml(data, storeId) {
  const stores = data.stores || [];
  const label = (data.period && data.period.label) || '';
  const opts = [`<option value=""${storeId === '' ? ' selected' : ''}>全部門市</option>`]
    .concat(stores.map((s) =>
      `<option value="${s.id}"${String(s.id) === String(storeId) ? ' selected' : ''}>${escapeHtml(s.name)}</option>`));
  return `<div class="mr-head">
      <span class="mr-period">期間 ${escapeHtml(label)}</span>
      <label class="mr-store-pick">門市：
        <select class="mr-store-select ap-select">${opts.join('')}</select>
      </label>
    </div>`;
}

function wireToggles(container) {
  container.querySelectorAll('.mr-toggle').forEach((btn) => {
    btn.addEventListener('click', () => {
      const idx = btn.dataset.idx;
      const expanded = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', String(!expanded));
      btn.textContent = expanded ? '▶' : '▼';
      container.querySelectorAll(`.mr-child-row[data-parent-idx="${idx}"]`).forEach((tr) => {
        tr.hidden = expanded;
      });
    });
  });
}

/**
 * 抓 /reports/monthly 資料並畫月報表到 container。periodId 可省略（取當期）。
 * UI：上方門市下拉。「全部門市」＝各店一欄＋總計；選單店＝收成「科目→金額」一欄。
 * 切換門市走 client 端重繪，不重新抓資料。
 */
export async function renderMonthReport(container, { periodId } = {}) {
  container.innerHTML = '<div class="ap-empty">載入中…</div>';
  let status, data;
  try {
    ({ status, data } = await reportsApi.monthly(periodId));
  } catch (e) {
    container.innerHTML = '<div class="ap-empty">載入失敗，請重試</div>';
    return;
  }
  if (status !== 200 || !data || data.status !== 'ok') {
    container.innerHTML = '<div class="ap-empty">載入失敗，請重試</div>';
    return;
  }
  let storeId = '';   // 預設「全部門市」（各店攤開）
  const render = () => {
    container.innerHTML = headerHtml(data, storeId) + tableHtml(data, storeId);
    const sel = container.querySelector('.mr-store-select');
    if (sel) sel.addEventListener('change', () => { storeId = sel.value; render(); });
    wireToggles(container);
  };
  render();
}
