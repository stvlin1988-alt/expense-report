import { escapeHtml } from './admin_util.js';
import { lightLabel, parseAmountInput, categoryOptionsHtml } from './expenses_util.js';
import { formatDateTimeTW, renderTrailRows } from './audit_util.js';
import { Camera } from './camera.js';
import { openImageLightbox } from './lightbox.js';
import {
  listPending, patchExpense, submitExpense, discardExpense, listCategories, noReceipt, reocrExpense, getExpenseLogs,
} from './expenses_api.js';

const root = () => document.getElementById('modal-root');

export async function showPendingView(onBack) {
  root().innerHTML = `
    <div class="modal-backdrop"><div class="modal-box wide">
      <h2>確認區</h2>
      <button class="modal-btn" id="pd-refresh" type="button">↻ 重整</button>
      <button class="modal-btn" id="pd-noreceipt" type="button">＋無單據建帳</button>
      <div id="pd-noreceipt-form"></div>
      <div id="pd-msg" class="modal-msg"></div>
      <div class="pd-table-wrap">
        <table id="pd-table"><thead><tr>
          <th>圖</th><th>建立</th><th>建立者</th><th>摘要</th><th>分類</th><th>金額</th><th>燈</th><th></th>
        </tr></thead><tbody></tbody></table>
      </div>
      <button class="modal-btn secondary" id="pd-back" type="button">返回</button>
    </div></div>`;
  document.getElementById('pd-back').addEventListener('click', onBack);
  document.getElementById('pd-refresh').addEventListener('click', () => showPendingView(onBack));

  const [{ data }, { data: cat }] = await Promise.all([listPending(), listCategories()]);
  const tree = cat.categories || [];

  document.getElementById('pd-noreceipt').addEventListener('click', () => {
    showNoReceiptForm(tree, onBack);
  });

  const tbody = document.querySelector('#pd-table tbody');
  (data.expenses || []).forEach((e) => {
    const tr = document.createElement('tr');
    const thumb = e.thumb_url
      ? `<img src="${e.thumb_url}" loading="lazy" width="48" class="au-thumb" data-zoom="${e.image_url || ''}">`
      : (e.status === 'pending_ocr' ? '🕓' : '—');
    tr.innerHTML = `
      <td>${thumb}</td>
      <td class="au-time">${formatDateTimeTW(e.created_at)}</td>
      <td>${escapeHtml(e.created_by_name || '')}</td>
      <td>${e.status === 'pending_ocr'
        ? '<span class="pd-ocring">🕓 辨識中…（稍後按重整）</span>'
        : `<input value="${escapeHtml(e.summary || '')}" data-f="summary">`}</td>
      <td><select data-f="category"></select></td>
      <td><input value="${e.amount ?? ''}" inputmode="decimal" data-f="amount" style="width:80px"></td>
      <td>${lightLabel(e.light)}</td>
      <td>
        ${e.status === 'pending_ocr' ? '' : '<button data-act="submit">送出</button>'}<button data-act="del">丟棄</button>
        ${e.ocr_failed ? '<button data-act="reocr">重新辨識</button>' : ''}
        <button data-act="trail" type="button">軌跡</button>
        ${e.last_modified_at
          ? `<div class="pd-lastmod">最後修改：${escapeHtml(e.last_modified_by_name || '')}（${formatDateTimeTW(e.last_modified_at)}）</div>`
          : ''}
        <div class="pd-trail" data-f="trail" hidden></div>
        <div class="pd-row-err" data-f="err"></div>
        ${e.ocr_failed ? '<div class="pd-ocr-failed">⚠ OCR 失敗，請手動確認金額/分類</div>' : ''}
      </td>`;
    const rowErr = tr.querySelector('[data-f="err"]');
    const setErr = (t) => { rowErr.textContent = t || ''; };
    const thumbEl = tr.querySelector('.au-thumb');
    if (thumbEl && thumbEl.dataset.zoom) {
      thumbEl.addEventListener('click', () => openImageLightbox(thumbEl.dataset.zoom));
    }
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
    const submitBtn = tr.querySelector('[data-act="submit"]');
    if (submitBtn) {
      submitBtn.addEventListener('click', async () => {
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
    }
    tr.querySelector('[data-act="del"]').addEventListener('click', async () => {
      setErr('');
      const { status } = await discardExpense(e.id);
      if (status === 200) tr.remove();
      else setErr('丟棄失敗，請稍後再試');
    });
    const reBtn = tr.querySelector('[data-act="reocr"]');
    if (reBtn) {
      reBtn.addEventListener('click', async () => {
        setErr('');
        const { status } = await reocrExpense(e.id);
        if (status === 202 || status === 200) {
          setErr('已送出重新辨識，稍後重整確認區查看');
          reBtn.disabled = true;
        } else {
          setErr('重新辨識失敗，請稍後再試');
        }
      });
    }
    const trailBox = tr.querySelector('[data-f="trail"]');
    tr.querySelector('[data-act="trail"]').addEventListener('click', async () => {
      if (!trailBox.hidden) { trailBox.hidden = true; return; }
      trailBox.hidden = false;
      trailBox.innerHTML = '載入中…';
      try {
        const { data } = await getExpenseLogs(e.id);
        trailBox.innerHTML = renderTrailRows(data.logs);
      } catch {
        trailBox.innerHTML = '<div class="au-trail-empty">軌跡載入失敗</div>';
      }
    });
    tbody.appendChild(tr);
  });
  if (!(data.expenses || []).length) {
    document.getElementById('pd-msg').textContent = '確認區沒有待確認單據';
  }
}

function showNoReceiptForm(tree, onBack) {
  const container = document.getElementById('pd-noreceipt-form');
  container.innerHTML = `
    <div class="pd-noreceipt-box">
      <input placeholder="摘要" id="nr-summary">
      <input placeholder="金額" inputmode="decimal" id="nr-amount">
      <select id="nr-category"></select>
      <input placeholder="原因（選填）" id="nr-reason">
      <div class="nr-photo">
        <button class="modal-btn secondary" id="nr-photo-btn" type="button">📷 拍照（選填）</button>
        <div id="nr-cam" class="nr-cam" hidden>
          <video id="nr-video" playsinline></video>
          <canvas id="nr-canvas" hidden></canvas>
          <button class="modal-btn" id="nr-shoot" type="button">拍下</button>
        </div>
        <div id="nr-preview" class="nr-preview"></div>
      </div>
      <button class="modal-btn" id="nr-submit" type="button">送出</button>
      <button class="modal-btn secondary" id="nr-cancel" type="button">取消</button>
      <div class="pd-row-err" id="nr-err"></div>
    </div>`;
  document.getElementById('nr-category').innerHTML = categoryOptionsHtml(tree, null);
  const err = document.getElementById('nr-err');

  // 可選附一張佐證照（沿用 Camera，記憶體不落地）
  let photo = null;
  const cam = new Camera(document.getElementById('nr-video'), document.getElementById('nr-canvas'));
  const camBox = document.getElementById('nr-cam');
  const preview = document.getElementById('nr-preview');
  const stopCam = () => { try { cam.stop(); } catch { /* noop */ } camBox.hidden = true; };
  document.getElementById('nr-photo-btn').addEventListener('click', async () => {
    err.textContent = '';
    camBox.hidden = false;
    try { await cam.start(); } catch { err.textContent = '無法開啟相機'; camBox.hidden = true; }
  });
  document.getElementById('nr-shoot').addEventListener('click', () => {
    photo = cam.capture();
    stopCam();
    preview.innerHTML = `<img src="${photo}" width="80" alt="佐證照">
      <button class="modal-btn secondary" id="nr-photo-clear" type="button">移除</button>`;
    document.getElementById('nr-photo-clear').addEventListener('click', () => {
      photo = null; preview.innerHTML = '';
    });
  });

  document.getElementById('nr-cancel').addEventListener('click', () => {
    stopCam(); container.innerHTML = '';
  });
  document.getElementById('nr-submit').addEventListener('click', async () => {
    err.textContent = '';
    const summary = document.getElementById('nr-summary').value;
    const parsed = parseAmountInput(document.getElementById('nr-amount').value);
    if (!parsed.valid) { err.textContent = '金額格式不正確，請重新輸入'; return; }
    const reason = document.getElementById('nr-reason').value.trim();
    const catSelect = document.getElementById('nr-category');
    const categoryId = catSelect.value === '' ? null : Number(catSelect.value);
    const payload = { summary, amount: parsed.value, category_id: categoryId, reason };
    if (photo) payload.image = photo;
    const { status } = await noReceipt(payload);
    if (status === 200) {
      stopCam();
      showPendingView(onBack);
    } else {
      err.textContent = '建立失敗，請稍後再試';
    }
  });
}
