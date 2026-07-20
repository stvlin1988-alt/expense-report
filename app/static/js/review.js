import { escapeHtml } from './admin_util.js';
import { openImageLightbox } from './lightbox.js';
import { formatAmount, sumAmounts } from './expenses_util.js';
import { listSubmitted } from './expenses_api.js';

// 員工唯讀複查：本班已送出、主管尚未交/結班的單。只能看，不能改。
// 唯讀卡片 + sticky 合計 bar（原型 employee-mobile.html:281-296）。
export async function renderReviewPane(container) {
  container.innerHTML = `<h2 class="mb-pane-title">複查（本班已送出）</h2>
    <p class="mb-pane-sub">唯讀 · 台灣時間</p>
    <div class="mb-cardlist" id="mb-review-list"></div>
    <div class="mb-total-bar" id="mb-review-total" hidden></div>`;
  const { data } = await listSubmitted();
  const rows = (data && data.expenses) || [];
  const list = container.querySelector('#mb-review-list');
  rows.forEach((e) => {
    const card = document.createElement('div'); card.className = 'mb-card mb-ro-card';
    const thumb = e.thumb_url
      ? `<button type="button" class="mb-thumb au-thumb" data-zoom="${e.image_url || ''}"><img src="${e.thumb_url}" loading="lazy" alt="收據"><span class="mb-zoom-badge">🔍</span></button>`
      : '<span class="mb-thumb placeholder">—</span>';
    card.innerHTML = `<div class="mb-card-head"><span class="mb-thumb-wrap">${thumb}</span>
      <div class="mb-card-meta"><span class="mb-card-id">${escapeHtml(e.doc_no || '')}</span>
        <p class="mb-ro-summary">${escapeHtml(e.summary || '')}</p>
        <span><span class="mb-chip">${escapeHtml(e.category_name || '')}</span></span></div></div>
      <div class="mb-ro-line"><span class="k">備註</span><span class="v">${e.note ? escapeHtml(e.note) : '—'}</span></div>
      <div class="mb-ro-line"><span class="k">金額</span><span class="mb-ro-amt mb-amt">$${formatAmount(e.amount)}</span></div>`;
    const t = card.querySelector('.au-thumb');
    if (t && t.dataset.zoom) t.addEventListener('click', () => openImageLightbox(t.dataset.zoom));
    list.appendChild(card);
  });
  const total = container.querySelector('#mb-review-total');
  if (rows.length) { total.hidden = false;
    total.innerHTML = `<span class="lbl">共 ${rows.length} 筆</span><span class="sum mb-amt">總額 $${formatAmount(sumAmounts(rows))}</span>`; }
  else { list.innerHTML = '<div class="mb-empty-state" style="display:block">本班沒有已送出的單</div>'; }
}
