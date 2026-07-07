import { escapeHtml } from './admin_util.js';
import { lightLabel, parseAmountInput, categoryOptionsHtml } from './expenses_util.js';
import {
  listPending, patchExpense, submitExpense, discardExpense, listCategories, noReceipt,
} from './expenses_api.js';

const root = () => document.getElementById('modal-root');

export async function showPendingView(onBack) {
  root().innerHTML = `
    <div class="modal-backdrop"><div class="modal-box wide">
      <h2>暫存區</h2>
      <button class="modal-btn" id="pd-noreceipt" type="button">＋無單據建帳</button>
      <div id="pd-msg" class="modal-msg"></div>
      <div class="pd-table-wrap">
        <table id="pd-table"><thead><tr>
          <th>圖</th><th>摘要</th><th>分類</th><th>金額</th><th>燈</th><th></th>
        </tr></thead><tbody></tbody></table>
      </div>
      <div id="pd-noreceipt-form"></div>
      <button class="modal-btn secondary" id="pd-back" type="button">返回</button>
    </div></div>`;
  document.getElementById('pd-back').addEventListener('click', onBack);

  const [{ data }, { data: cat }] = await Promise.all([listPending(), listCategories()]);
  const tree = cat.categories || [];

  document.getElementById('pd-noreceipt').addEventListener('click', () => {
    showNoReceiptForm(tree, onBack);
  });

  const tbody = document.querySelector('#pd-table tbody');
  (data.expenses || []).forEach((e) => {
    const tr = document.createElement('tr');
    const thumb = e.thumb_url
      ? `<img src="${e.thumb_url}" loading="lazy" width="48">`
      : (e.status === 'pending_ocr' ? '🕓' : '—');
    tr.innerHTML = `
      <td>${thumb}</td>
      <td><input value="${escapeHtml(e.summary || '')}" data-f="summary"></td>
      <td><select data-f="category"></select></td>
      <td><input value="${e.amount ?? ''}" inputmode="decimal" data-f="amount" style="width:80px"></td>
      <td>${lightLabel(e.light)}</td>
      <td>
        <button data-act="submit">送出</button><button data-act="del">丟棄</button>
        <div class="pd-row-err" data-f="err"></div>
      </td>`;
    const rowErr = tr.querySelector('[data-f="err"]');
    const setErr = (t) => { rowErr.textContent = t || ''; };
    const catSelect = tr.querySelector('[data-f="category"]');
    catSelect.innerHTML = categoryOptionsHtml(tree, e.category_id);
    catSelect.addEventListener('change', async () => {
      setErr('');
      const categoryId = catSelect.value === '' ? null : Number(catSelect.value);
      // 即時修正、不阻塞送出；失敗要出聲，否則使用者以為已存
      try {
        const { status } = await patchExpense(e.id, { category_id: categoryId });
        if (status !== 200) setErr('分類儲存失敗，送出前會再試一次');
      } catch {
        setErr('分類儲存失敗，送出前會再試一次');
      }
    });
    tr.querySelector('[data-act="submit"]').addEventListener('click', async () => {
      setErr('');
      const summary = tr.querySelector('[data-f="summary"]').value;
      const parsed = parseAmountInput(tr.querySelector('[data-f="amount"]').value);
      if (!parsed.valid) { setErr('金額格式不正確，請重新輸入'); return; }
      const categoryId = catSelect.value === '' ? null : Number(catSelect.value);
      await patchExpense(e.id, { summary, amount: parsed.value, category_id: categoryId });
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

function showNoReceiptForm(tree, onBack) {
  const container = document.getElementById('pd-noreceipt-form');
  container.innerHTML = `
    <div class="pd-noreceipt-box">
      <input placeholder="摘要" id="nr-summary">
      <input placeholder="金額" inputmode="decimal" id="nr-amount">
      <select id="nr-category"></select>
      <input placeholder="原因（必填）" id="nr-reason">
      <button class="modal-btn" id="nr-submit" type="button">送出</button>
      <button class="modal-btn secondary" id="nr-cancel" type="button">取消</button>
      <div class="pd-row-err" id="nr-err"></div>
    </div>`;
  document.getElementById('nr-category').innerHTML = categoryOptionsHtml(tree, null);
  const err = document.getElementById('nr-err');
  document.getElementById('nr-cancel').addEventListener('click', () => { container.innerHTML = ''; });
  document.getElementById('nr-submit').addEventListener('click', async () => {
    err.textContent = '';
    const summary = document.getElementById('nr-summary').value;
    const parsed = parseAmountInput(document.getElementById('nr-amount').value);
    if (!parsed.valid) { err.textContent = '金額格式不正確，請重新輸入'; return; }
    const reason = document.getElementById('nr-reason').value.trim();
    if (!reason) { err.textContent = '請填寫原因'; return; }
    const catSelect = document.getElementById('nr-category');
    const categoryId = catSelect.value === '' ? null : Number(catSelect.value);
    const { status } = await noReceipt({
      summary, amount: parsed.value, category_id: categoryId, reason,
    });
    if (status === 200) {
      showPendingView(onBack);
    } else {
      err.textContent = '建立失敗，請稍後再試';
    }
  });
}
