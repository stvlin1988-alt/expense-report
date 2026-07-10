import { escapeHtml } from './admin_util.js';
import { openImageLightbox } from './lightbox.js';
import { listSubmitted } from './expenses_api.js';

const root = () => document.getElementById('modal-root');

// 員工唯讀複查：本班已送出、主管尚未交/結班的單。只能看，不能改。
export async function showReviewView(onBack) {
  root().innerHTML = `
    <div class="modal-backdrop"><div class="modal-box wide">
      <h2>複查（本班已送出）</h2>
      <button class="modal-btn" id="rv-refresh" type="button">↻ 重整</button>
      <div id="rv-msg" class="modal-msg"></div>
      <div class="pd-table-wrap">
        <table id="rv-table"><thead><tr>
          <th>單號</th><th>圖</th><th>摘要</th><th>分類</th><th>金額</th>
        </tr></thead><tbody></tbody></table>
      </div>
      <button class="modal-btn secondary" id="rv-back" type="button">返回</button>
    </div></div>`;
  document.getElementById('rv-back').addEventListener('click', onBack);
  document.getElementById('rv-refresh').addEventListener('click', () => showReviewView(onBack));

  const { data } = await listSubmitted();
  const rows = (data && data.expenses) || [];
  const tbody = document.querySelector('#rv-table tbody');
  rows.forEach((e) => {
    const tr = document.createElement('tr');
    const thumb = e.thumb_url
      ? `<img src="${e.thumb_url}" loading="lazy" width="48" class="au-thumb" data-zoom="${e.image_url || ''}">`
      : '—';
    tr.innerHTML = `
      <td>${escapeHtml(e.doc_no || '')}</td>
      <td>${thumb}</td>
      <td>${escapeHtml(e.summary || '')}</td>
      <td>${escapeHtml(e.category_name || '')}</td>
      <td>${e.amount ?? ''}</td>`;
    const thumbEl = tr.querySelector('.au-thumb');
    if (thumbEl && thumbEl.dataset.zoom) {
      thumbEl.addEventListener('click', () => openImageLightbox(thumbEl.dataset.zoom));
    }
    tbody.appendChild(tr);
  });
  if (!rows.length) {
    document.getElementById('rv-msg').textContent = '本班沒有已送出的單';
  }
}
