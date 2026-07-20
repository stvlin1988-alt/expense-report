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

// extraClass：目前用來標「總計」欄（.wk-xt-tot，見 app.css），其餘 cell 不帶。
function cellHtml(cell, extraClass = '') {
  const { text, negative } = formatCell(cell);
  const cls = `num${negative ? ' neg' : ''}${extraClass ? ` ${extraClass}` : ''}`;
  return `<td class="${cls}">${escapeHtml(text)}</td>`;
}

// 全部門市模式：每家店一欄。回傳該列所有門市欄的 <td>。
function perStoreTds(obj, stores) {
  return stores.map((s) => cellHtml((obj.per_store && obj.per_store[s.id]) || null)).join('');
}

// 大類列：可展開鈕（有 children 才顯示，原型三角形 .wk-tri，靠 aria-expanded 轉向）＋科目名稱＋金額欄。
function majorRowHtml(row, idx, stores, storeId) {
  const hasChildren = !!(row.children && row.children.length);
  const nameCell = hasChildren
    ? `<button type="button" class="wk-cat-toggle" data-idx="${idx}" aria-expanded="false"><span class="wk-tri"></span>${escapeHtml(row.major_name)}</button>`
    : `<span class="wk-cat-plain">${escapeHtml(row.major_name)}</span>`;
  const amountTds = storeId
    ? cellHtml(pickCell(row, storeId))
    : perStoreTds(row, stores) + cellHtml(row.total, 'wk-xt-tot');
  return `<tr class="mr-major-row" data-idx="${idx}">
    <td>${nameCell}</td>${amountTds}
  </tr>`;
}

// 細類列：預設 hidden，點大類的展開鈕才顯示。
function childRowHtml(child, parentIdx, stores, storeId) {
  const amountTds = storeId
    ? cellHtml(pickCell(child, storeId))
    : perStoreTds(child, stores) + cellHtml(child.total, 'wk-xt-tot');
  return `<tr class="mr-child-row" data-parent-idx="${parentIdx}" hidden>
    <td class="mr-child-name">${escapeHtml(child.major_name)}</td>${amountTds}
  </tr>`;
}

function footerRowHtml(data, stores, storeId) {
  const amountTds = storeId
    ? cellHtml((data.store_totals && data.store_totals[storeId]) || null, 'wk-xt-tot')
    : stores.map((s) => cellHtml((data.store_totals && data.store_totals[s.id]) || null)).join('')
      + cellHtml(data.grand_total, 'wk-xt-tot');
  return `<tr class="mr-total-row"><td>總計</td>${amountTds}</tr>`;
}

function tableHtml(data, storeId) {
  const stores = data.stores || [];
  const rows = data.rows || [];
  // 表頭：全部門市＝每店一欄＋總計；單店＝金額一欄。
  // 店別欄顯示英文代號：data.stores[].name 後端回傳的其實就是 Store.code
  // （app/reports/routes.py: {"id": s.id, "name": s.code}）——這裡優先取 .code
  // （若未來 API 補上獨立 code 欄位），退回既有 .name，絕不顯示中文店名。
  const headCells = storeId
    ? '<th>金額</th>'
    : stores.map((s) => `<th>${escapeHtml(s.code || s.name)}</th>`).join('') + '<th class="wk-xt-tot">總計</th>';
  const bodyRows = rows.map((row, idx) => {
    const childRows = (row.children || [])
      .map((child) => childRowHtml(child, idx, stores, storeId)).join('');
    return majorRowHtml(row, idx, stores, storeId) + childRows;
  }).join('');
  return `
    <div class="table-wrap">
      <table class="wk-xt${storeId ? ' wk-xt-one' : ''}">
        <thead><tr><th>科目</th>${headCells}</tr></thead>
        <tbody>${bodyRows}${footerRowHtml(data, stores, storeId)}</tbody>
      </table>
    </div>`;
}

function headerHtml(data, storeId, showPicker) {
  const stores = data.stores || [];
  const label = (data.period && data.period.label) || '';
  const periodSpan = `<span class="mr-period">期間 ${escapeHtml(label)}</span>`;
  if (!showPicker) {
    // 門市由外層（經理後台標頭店別選單）控制，這裡不再重複下拉。
    return `<div class="mr-head">${periodSpan}</div>`;
  }
  const opts = [`<option value=""${storeId === '' ? ' selected' : ''}>全部門市</option>`]
    .concat(stores.map((s) =>
      `<option value="${s.id}"${String(s.id) === String(storeId) ? ' selected' : ''}>${escapeHtml(s.name)}</option>`));
  return `<div class="mr-head">
      ${periodSpan}
      <label class="mr-store-pick">門市：
        <select class="mr-store-select ap-select">${opts.join('')}</select>
      </label>
    </div>`;
}

function wireToggles(container) {
  container.querySelectorAll('.wk-cat-toggle').forEach((btn) => {
    btn.addEventListener('click', () => {
      const idx = btn.dataset.idx;
      const expanded = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', String(!expanded));
      // 旋轉靠 CSS：.wk-cat-toggle[aria-expanded="true"] .wk-tri
      container.querySelectorAll(`.mr-child-row[data-parent-idx="${idx}"]`).forEach((tr) => {
        tr.hidden = expanded;
      });
    });
  });
}

/**
 * 抓 /reports/monthly 資料並畫月報表到 container。
 * opts.periodId：可省略（取當期）。
 * opts.storeId：預選門市（空字串＝全部門市）。
 * opts.lockStore：true 時門市由外層控制（不畫自己的下拉，用 opts.storeId 固定）——
 *   給經理後台用（標頭店別選單同時管稽核與月結）；會計端不帶此旗標，走自己的下拉。
 * 「全部門市」＝各店一欄＋總計；選單店＝收成「科目→金額」一欄。切換門市 client 端重繪。
 */
export async function renderMonthReport(container, { periodId, storeId = '', lockStore = false } = {}) {
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
  if (lockStore) {
    // 門市由外層固定，不畫下拉、不需重繪
    container.innerHTML = headerHtml(data, storeId, false) + tableHtml(data, storeId);
    wireToggles(container);
    return;
  }
  let sel = storeId || '';
  const render = () => {
    container.innerHTML = headerHtml(data, sel, true) + tableHtml(data, sel);
    const s = container.querySelector('.mr-store-select');
    if (s) s.addEventListener('change', () => { sel = s.value; render(); });
    wireToggles(container);
  };
  render();
}
