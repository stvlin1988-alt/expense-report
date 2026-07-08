import { api } from './admin_api.js';
import { escapeHtml } from './admin_util.js';
import { categoryOptionsHtml, lightLabel, parseAmountInput } from './expenses_util.js';
import { formatMoney } from './audit_util.js';

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

async function renderSummary(body, sid) {
  body.innerHTML = '載入中…';
  const { data } = await api.auditSummary(sid);
  const rows = (data.intervals || []).map((it) =>
    `<tr><td>第 ${it.seq} 班${it.type === 'day' ? '（結班）' : ''}</td>
         <td>${new Date(it.closed_at).toLocaleString('zh-TW', { timeZone: 'Asia/Taipei' })}</td>
         <td>${it.count} 筆</td><td>${formatMoney(it.subtotal)}</td></tr>`).join('');
  const open = data.open || { subtotal: 0, count: 0 };
  body.innerHTML = `
    <table class="pd-table"><thead><tr><th>區間</th><th>交班時間</th><th>筆數</th><th>小計</th></tr></thead>
    <tbody>
      ${rows}
      <tr class="au-open"><td>當前未歸班</td><td>—</td><td>${open.count} 筆</td><td>${formatMoney(open.subtotal)}</td></tr>
    </tbody>
    <tfoot><tr><td colspan="3"><b>當日總額</b></td><td><b>${formatMoney(data.day_total)}</b></td></tr></tfoot>
    </table>`;
}

async function renderPending(body, sid) {
  body.innerHTML = '載入中…';
  const { data } = await api.auditPending(sid);
  // 分類清單（供下拉）——沿用員工端 /expenses/categories
  const catResp = await fetch('/expenses/categories').then((r) => r.json()).catch(() => ({}));
  const tree = (catResp && catResp.categories) || [];
  const groups = (data && data.groups) || [];
  if (!groups.length) { body.innerHTML = '<div class="ap-empty">沒有待稽核單據</div>'; return; }
  body.innerHTML = groups.map((g) => `
    <div class="au-group">
      <div class="au-group-head">${g.business_date}　日小計 ${formatMoney(g.subtotal)}</div>
      <table class="pd-table"><thead><tr>
        <th>圖</th><th>摘要</th><th>分類</th><th>金額</th><th>燈</th><th></th>
      </tr></thead><tbody>
      ${g.items.map((e) => rowHtml(e, tree)).join('')}
      </tbody></table>
    </div>`).join('');
  wireRows(body, sid);
  const bar = document.createElement('div');
  bar.className = 'au-actionbar';
  bar.innerHTML = `
    <button class="modal-btn" id="au-shift" type="button">交班</button>
    <button class="modal-btn" id="au-day" type="button">結班</button>
    <button class="modal-btn secondary" id="au-undo" type="button">取消上一次</button>
    <span class="pd-row-err" id="au-bar-err"></span>`;
  body.appendChild(bar);
  const barErr = bar.querySelector('#au-bar-err');
  const doClose = async (type) => {
    barErr.textContent = '';
    const { status, data } = await api.auditHandover(type, sid);
    barErr.textContent = status === 200
      ? `已${type === 'day' ? '結班' : '交班'}（${data.count} 筆）` : '沒有可歸班的單據';
  };
  bar.querySelector('#au-shift').addEventListener('click', () => doClose('shift'));
  bar.querySelector('#au-day').addEventListener('click', () => doClose('day'));
  bar.querySelector('#au-undo').addEventListener('click', async () => {
    barErr.textContent = '';
    const { status, data } = await api.auditUndo(sid);
    barErr.textContent = status === 200 ? `已取消，退回 ${data.reopened} 筆` : '沒有可取消的交班';
  });
}

function rowHtml(e, tree) {
  const thumb = e.thumb_url ? `<img src="${e.thumb_url}" loading="lazy" width="48">` : '—';
  return `<tr data-id="${e.id}">
    <td>${thumb}</td>
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
        if (status === 200) tr.remove(); else err.textContent = '打勾失敗';
      } catch { err.textContent = '打勾失敗'; }
    });
  });
}
