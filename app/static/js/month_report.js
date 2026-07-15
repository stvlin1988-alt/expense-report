import { reportsApi } from './reports_api.js';
import { escapeHtml } from './admin_util.js';

/**
 * 純函式：把一個 cell（{reconciled, pending}）依 period 狀態格式化成顯示文字。
 * closed：pending 恆為 0，只顯示單一數字。open/closing：顯示「已核銷 / 待核銷」。
 * negative：reconciled 或（open/closing 時的）pending 任一為負，供呼叫端套紅字 class。
 */
export function formatCell(cell, periodStatus) {
  const r = Number((cell && cell.reconciled) || 0);
  const p = Number((cell && cell.pending) || 0);
  const fmt = (n) => n.toLocaleString('en-US', { maximumFractionDigits: 2 });
  if (periodStatus === 'closed') {
    return { text: fmt(r), negative: r < 0 };
  }
  return { text: `${fmt(r)} / ${fmt(p)}`, negative: r < 0 || p < 0 };
}

function cellHtml(cell, periodStatus) {
  const { text, negative } = formatCell(cell, periodStatus);
  return `<span class="rc-amt${negative ? ' rc-neg' : ''}">${escapeHtml(text)}</span>`;
}

function perStoreCells(row, stores, periodStatus) {
  return stores.map((s) => {
    const cell = (row.per_store && row.per_store[s.id]) || { reconciled: 0, pending: 0 };
    return `<td>${cellHtml(cell, periodStatus)}</td>`;
  }).join('');
}

// 大類列：可展開鈕（有 children 才顯示）＋科目名稱＋各店金額＋大類總計。
function majorRowHtml(row, idx, stores, periodStatus) {
  const hasChildren = !!(row.children && row.children.length);
  const toggle = hasChildren
    ? `<button type="button" class="mr-toggle" data-idx="${idx}" aria-expanded="false">▶</button> `
    : '';
  return `<tr class="mr-major-row" data-idx="${idx}">
    <td>${toggle}${escapeHtml(row.major_name)}</td>
    ${perStoreCells(row, stores, periodStatus)}
    <td>${cellHtml(row.total, periodStatus)}</td>
  </tr>`;
}

// 細類列：預設 hidden，點大類的展開鈕才顯示。
function childRowHtml(child, parentIdx, stores, periodStatus) {
  return `<tr class="mr-child-row" data-parent-idx="${parentIdx}" hidden>
    <td class="mr-child-name">${escapeHtml(child.major_name)}</td>
    ${perStoreCells(child, stores, periodStatus)}
    <td>${cellHtml(child.total, periodStatus)}</td>
  </tr>`;
}

function footerRowHtml(data, stores, periodStatus) {
  const storeCells = stores.map((s) => {
    const cell = (data.store_totals && data.store_totals[s.id]) || { reconciled: 0, pending: 0 };
    return `<td>${cellHtml(cell, periodStatus)}</td>`;
  }).join('');
  return `<tr class="mr-total-row">
    <td>總計</td>
    ${storeCells}
    <td>${cellHtml(data.grand_total, periodStatus)}</td>
  </tr>`;
}

function tableHtml(data) {
  const stores = data.stores || [];
  const rows = data.rows || [];
  const periodStatus = data.period && data.period.status;
  const headCells = stores.map((s) => `<th>${escapeHtml(s.name)}</th>`).join('');
  const bodyRows = rows.map((row, idx) => {
    const childRows = (row.children || [])
      .map((child) => childRowHtml(child, idx, stores, periodStatus)).join('');
    return majorRowHtml(row, idx, stores, periodStatus) + childRows;
  }).join('');
  return `
    <div class="pd-table-wrap">
      <table class="pd-table mr-table">
        <thead><tr><th>科目</th>${headCells}<th>總計</th></tr></thead>
        <tbody>${bodyRows}${footerRowHtml(data, stores, periodStatus)}</tbody>
      </table>
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

/** 抓 /reports/monthly 資料並畫月報表交叉表到 container。periodId 可省略（取當期）。 */
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
  container.innerHTML = tableHtml(data);
  wireToggles(container);
}
