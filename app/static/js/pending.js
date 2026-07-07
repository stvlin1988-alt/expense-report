import { escapeHtml } from './admin_util.js';
import { lightLabel, parseAmountInput } from './expenses_util.js';
import { listPending, patchExpense, submitExpense, discardExpense } from './expenses_api.js';

const root = () => document.getElementById('modal-root');

export async function showPendingView(onBack) {
  root().innerHTML = `
    <div class="modal-backdrop"><div class="modal-box wide">
      <h2>暫存區</h2>
      <div id="pd-msg" class="modal-msg"></div>
      <div class="pd-table-wrap">
        <table id="pd-table"><thead><tr>
          <th>圖</th><th>摘要</th><th>金額</th><th>燈</th><th></th>
        </tr></thead><tbody></tbody></table>
      </div>
      <button class="modal-btn secondary" id="pd-back" type="button">返回</button>
    </div></div>`;
  document.getElementById('pd-back').addEventListener('click', onBack);

  const { data } = await listPending();
  const tbody = document.querySelector('#pd-table tbody');
  (data.expenses || []).forEach((e) => {
    const tr = document.createElement('tr');
    const thumb = e.thumb_url
      ? `<img src="${e.thumb_url}" loading="lazy" width="48">`
      : (e.status === 'pending_ocr' ? '🕓' : '—');
    tr.innerHTML = `
      <td>${thumb}</td>
      <td><input value="${escapeHtml(e.summary || '')}" data-f="summary"></td>
      <td><input value="${e.amount ?? ''}" inputmode="decimal" data-f="amount" style="width:80px"></td>
      <td>${lightLabel(e.light)}</td>
      <td>
        <button data-act="submit">送出</button><button data-act="del">丟棄</button>
        <div class="pd-row-err" data-f="err"></div>
      </td>`;
    const rowErr = tr.querySelector('[data-f="err"]');
    const setErr = (t) => { rowErr.textContent = t || ''; };
    tr.querySelector('[data-act="submit"]').addEventListener('click', async () => {
      setErr('');
      const summary = tr.querySelector('[data-f="summary"]').value;
      const parsed = parseAmountInput(tr.querySelector('[data-f="amount"]').value);
      if (!parsed.valid) { setErr('金額格式不正確，請重新輸入'); return; }
      await patchExpense(e.id, { summary, amount: parsed.value });
      const { status } = await submitExpense(e.id);
      if (status === 200) tr.remove();
      else setErr('送出失敗，請稍後再試');
    });
    tr.querySelector('[data-act="del"]').addEventListener('click', async () => {
      setErr('');
      const { status } = await discardExpense(e.id);
      if (status === 200) tr.remove();
      else setErr('丟棄失敗，請稍後再試');
    });
    tbody.appendChild(tr);
  });
  if (!(data.expenses || []).length) {
    document.getElementById('pd-msg').textContent = '暫存區沒有待確認單據';
  }
}
