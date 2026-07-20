import { escapeHtml } from './admin_util.js';
import {
  lightLabel, parseAmountInput, categoryOptionsHtml,
} from './expenses_util.js';
import { formatDateTimeTW } from './audit_util.js';
import { Camera } from './camera.js';
import { openImageLightbox } from './lightbox.js';
import { mbToast } from './employee_app.js';
import {
  listPending, patchExpense, submitExpense, discardExpense, listCategories, noReceipt, reocrExpense,
} from './expenses_api.js';

// 確認區 pane（單欄卡片）：取代 showAppView 的表格版 showPendingView。
// 沿用全部後端 API 與 data-f/data-act 契約，只換外層結構。
export async function renderConfirmPane(container, { onCountChange } = {}) {
  container.innerHTML = `
    <h2 class="mb-pane-title">確認區</h2><p class="mb-pane-sub">辨識完成後請逐筆核對再送出</p>
    <div class="mb-toolbar">
      <button class="mb-btn" id="mb-noreceipt" type="button">＋ 無單據建帳</button>
      <button class="mb-btn refresh" id="mb-confirm-refresh" title="重整" aria-label="重整" type="button">↻</button>
    </div>
    <div id="mb-noreceipt-form"></div>
    <div class="mb-cardlist" id="mb-confirm-list"></div>
    <div class="mb-empty-state" id="mb-confirm-empty" style="display:none">確認區沒有待確認單據</div>`;
  container.querySelector('#mb-confirm-refresh').addEventListener('click', () => renderConfirmPane(container, { onCountChange }));

  const [{ data }, { data: cat }] = await Promise.all([listPending(), listCategories()]);
  const tree = cat.categories || [];

  container.querySelector('#mb-noreceipt').addEventListener('click', () => {
    showNoReceiptForm(container, tree, () => renderConfirmPane(container, { onCountChange }));
  });

  const list = container.querySelector('#mb-confirm-list');
  const items = data.expenses || [];
  const report = () => { if (onCountChange) onCountChange(list.querySelectorAll('.mb-card:not(.sent)').length); };
  items.forEach((e) => list.appendChild(cardFor(e, tree, report)));
  container.querySelector('#mb-confirm-empty').style.display = items.length ? 'none' : 'block';
  report();
}

// OCR 信心度燈號（後端 traffic_light：green/yellow/red）→ 縮圖右上角圓點顏色。
function dotClassFor(light) {
  return { green: 'ok', yellow: 'warn', red: 'bad' }[light] || 'ok';
}

function thumbWrapHtml(e, dotCls, dotTitle, pulse) {
  const dot = dotCls
    ? `<span class="mb-dot mb-dot-${dotCls}${pulse ? ' pulse' : ''}"${dotTitle ? ` title="${escapeHtml(dotTitle)}"` : ''}></span>`
    : '';
  if (e.thumb_url) {
    return `<span class="mb-thumb-wrap">
      <img src="${e.thumb_url}" loading="lazy" alt="收據縮圖" class="mb-thumb au-thumb" data-zoom="${escapeHtml(e.image_url || e.thumb_url)}">
      <span class="mb-zoom-badge" aria-hidden="true">🔍</span>
      ${dot}
    </span>`;
  }
  return `<span class="mb-thumb-wrap">
    <span class="mb-thumb placeholder" aria-hidden="true">${e.status === 'pending_ocr' ? '🕓' : '—'}</span>
    ${dot}
  </span>`;
}

// 建一張確認卡：pending_ocr 骨架卡／正常可編輯卡／ocr_failed 卡。
// change/submit/del/reocr 邏輯沿用原 showPendingView（table 版）45-127 行的做法。
function cardFor(e, tree, report) {
  const card = document.createElement('div');
  card.className = 'mb-card';
  card.dataset.id = String(e.id);

  if (e.status === 'pending_ocr') {
    card.innerHTML = `
      <div class="mb-card-head">
        ${thumbWrapHtml(e, 'warn', '辨識中', true)}
        <div class="mb-card-meta">
          <span class="mb-card-time">${escapeHtml(formatDateTimeTW(e.created_at))}</span>
        </div>
      </div>
      <div class="mb-status-strip pending">🕓 辨識中…（稍後按重整）</div>
      <div class="mb-skeleton"><i></i><i></i></div>`;
    wireThumbZoom(card);
    return card;
  }

  const ocrFailed = !!e.ocr_failed;
  const dotCls = dotClassFor(e.light);
  card.innerHTML = `
    <div class="mb-card-head">
      ${thumbWrapHtml(e, dotCls, lightLabel(e.light))}
      <div class="mb-card-meta">
        <span class="mb-card-time">${escapeHtml(formatDateTimeTW(e.created_at))}</span>
      </div>
    </div>
    <div class="mb-field">
      <input value="${escapeHtml(e.summary || '')}" data-f="summary" placeholder="摘要">
    </div>
    <div class="mb-field-row">
      <div class="mb-field"><select data-f="category"></select></div>
      <div class="mb-field mb-f-amt"><input value="${e.amount ?? ''}" inputmode="decimal" data-f="amount"></div>
    </div>
    <div class="mb-field">
      <input value="${escapeHtml(e.note || '')}" maxlength="200" placeholder="備註（可留空）" data-f="note">
    </div>
    ${ocrFailed ? '<div class="mb-status-strip fail">⚠ OCR 失敗，請手動確認金額/分類</div>' : ''}
    <div class="mb-card-actions">
      <button class="mb-btn mb-btn-primary" data-act="submit" type="button">送出</button>
      ${ocrFailed ? '<button class="mb-btn mb-btn-ghost" data-act="reocr" type="button">重新辨識</button>' : ''}
      <button class="mb-btn mb-btn-danger" data-act="del" type="button">丟棄</button>
    </div>
    <div class="pd-row-err" data-f="err"></div>`;

  wireThumbZoom(card);

  const errEl = card.querySelector('[data-f="err"]');
  const setErr = (t) => { errEl.textContent = t || ''; };

  const catSelect = card.querySelector('[data-f="category"]');
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

  const noteInput = card.querySelector('[data-f="note"]');
  noteInput.addEventListener('change', async () => {
    setErr('');
    try {
      const { status } = await patchExpense(e.id, { note: noteInput.value });
      if (status !== 200) setErr('備註儲存失敗，送出前會再試一次');
    } catch {
      setErr('備註儲存失敗，送出前會再試一次');
    }
  });

  card.querySelector('[data-act="submit"]').addEventListener('click', async () => {
    setErr('');
    const summary = card.querySelector('[data-f="summary"]').value;
    const parsed = parseAmountInput(card.querySelector('[data-f="amount"]').value);
    if (!parsed.valid) { setErr('金額格式不正確，請重新輸入'); return; }
    const categoryId = catSelect.value === '' ? null : Number(catSelect.value);
    const patch = {
      summary, amount: parsed.value, category_id: categoryId, note: noteInput.value,
    };
    await patchExpense(e.id, patch);
    const { status } = await submitExpense(e.id);
    if (status === 200) {
      card.remove();
      mbToast('已送出');
      report();
    } else {
      setErr('送出失敗，請稍後再試');
    }
  });

  card.querySelector('[data-act="del"]').addEventListener('click', async () => {
    setErr('');
    const { status } = await discardExpense(e.id);
    if (status === 200) {
      card.remove();
      report();
    } else {
      setErr('丟棄失敗，請稍後再試');
    }
  });

  const reBtn = card.querySelector('[data-act="reocr"]');
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

  return card;
}

function wireThumbZoom(card) {
  const thumbEl = card.querySelector('.au-thumb');
  if (thumbEl && thumbEl.dataset.zoom) {
    thumbEl.addEventListener('click', () => openImageLightbox(thumbEl.dataset.zoom));
  }
}

// 無單據建帳表單（Task 4 會正式卡片化，本 task 先接上鈕、沿用既有表單邏輯）。
function showNoReceiptForm(container, tree, onDone) {
  const formEl = container.querySelector('#mb-noreceipt-form');
  formEl.innerHTML = `
    <div class="mb-card" id="mb-nr-box">
      <div class="mb-field"><input placeholder="摘要" id="nr-summary"></div>
      <div class="mb-field-row">
        <div class="mb-field"><select id="nr-category"></select></div>
        <div class="mb-field mb-f-amt"><input placeholder="金額" inputmode="decimal" id="nr-amount"></div>
      </div>
      <div class="mb-field"><input placeholder="原因（選填）" id="nr-reason"></div>
      <div class="nr-photo">
        <button class="mb-btn mb-btn-ghost mb-btn-sm" id="nr-photo-btn" type="button">📷 拍照（選填）</button>
        <div id="nr-cam" class="nr-cam" hidden>
          <video id="nr-video" playsinline></video>
          <canvas id="nr-canvas" hidden></canvas>
          <button class="mb-btn mb-btn-sm" id="nr-shoot" type="button">拍下</button>
        </div>
        <div id="nr-preview" class="nr-preview"></div>
      </div>
      <div class="mb-card-actions">
        <button class="mb-btn mb-btn-primary" id="nr-submit" type="button">送出</button>
        <button class="mb-btn mb-btn-ghost" id="nr-cancel" type="button">取消</button>
      </div>
      <div class="pd-row-err" id="nr-err"></div>
    </div>`;
  formEl.querySelector('#nr-category').innerHTML = categoryOptionsHtml(tree, null);
  const err = formEl.querySelector('#nr-err');

  // 可選附一張佐證照（沿用 Camera，記憶體不落地）
  let photo = null;
  const cam = new Camera(formEl.querySelector('#nr-video'), formEl.querySelector('#nr-canvas'));
  const camBox = formEl.querySelector('#nr-cam');
  const preview = formEl.querySelector('#nr-preview');
  const stopCam = () => { try { cam.stop(); } catch { /* noop */ } camBox.hidden = true; };
  formEl.querySelector('#nr-photo-btn').addEventListener('click', async () => {
    err.textContent = '';
    camBox.hidden = false;
    try { await cam.start(); } catch { err.textContent = '無法開啟相機'; camBox.hidden = true; }
  });
  formEl.querySelector('#nr-shoot').addEventListener('click', () => {
    photo = cam.capture();
    stopCam();
    preview.innerHTML = `<img src="${photo}" width="80" alt="佐證照">
      <button class="mb-btn mb-btn-ghost mb-btn-sm" id="nr-photo-clear" type="button">移除</button>`;
    preview.querySelector('#nr-photo-clear').addEventListener('click', () => {
      photo = null; preview.innerHTML = '';
    });
  });

  formEl.querySelector('#nr-cancel').addEventListener('click', () => {
    stopCam(); formEl.innerHTML = '';
  });
  formEl.querySelector('#nr-submit').addEventListener('click', async () => {
    err.textContent = '';
    const summary = formEl.querySelector('#nr-summary').value;
    const parsed = parseAmountInput(formEl.querySelector('#nr-amount').value);
    if (!parsed.valid) { err.textContent = '金額格式不正確，請重新輸入'; return; }
    const reason = formEl.querySelector('#nr-reason').value.trim();
    const catSelect = formEl.querySelector('#nr-category');
    const categoryId = catSelect.value === '' ? null : Number(catSelect.value);
    const payload = {
      summary, amount: parsed.value, category_id: categoryId, reason,
    };
    if (photo) payload.image = photo;
    const { status } = await noReceipt(payload);
    if (status === 200) {
      stopCam();
      onDone();
    } else {
      err.textContent = '建立失敗，請稍後再試';
    }
  });
}
