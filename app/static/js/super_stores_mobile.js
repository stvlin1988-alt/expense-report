// 經理手機・店別管理原生卡片（UI 重塑 2026-07）。重用桌面同 API：
// setStoreViewable（檢視顯示）/ setStoreActive（對外連結 kill-switch，關閉走確認）/ createStore（新增）。
// 不接刪店（spec §6 定案：高風險，UI 不出現）。
import { escapeHtml } from './admin_util.js';
import { api } from './admin_api.js';
import { mbToast } from './mb_util.js';

export async function renderStoresPane(container, { onChanged } = {}) {
  container.innerHTML = `
    <div class="mb-pane-title" style="padding:12px 14px 0">店別管理</div>
    <div class="mb-store-hint">「顯示於選單／月報表」打勾＝這家店會出現在選店選單與月報表（取消只是隱藏，不影響營運）。「對外連結」是 kill-switch，關閉會停止該店對外收單。</div>
    <div id="mb-store-list"><div class="mb-empty-state" style="display:block">載入中…</div></div>
    <div class="mb-store-add">
      <h3>新增店</h3>
      <input id="mb-new-store" maxlength="2" placeholder="店別英文代號（≤2 字母，如 TN）" autocomplete="off" aria-label="店別英文代號">
      <button class="mb-pw-btn" id="mb-store-add-btn" type="button">新增</button>
      <div class="mb-au-err" id="mb-store-err"></div>
    </div>`;
  const list = container.querySelector('#mb-store-list');

  const draw = async () => {
    let stores = [];
    try { const { data } = await api.getStores(); stores = (data && data.stores) || []; }
    catch { list.innerHTML = '<div class="mb-empty-state" style="display:block">載入失敗</div>'; return; }
    list.innerHTML = stores.map((s) => {
      const view = s.viewable !== false, conn = s.active !== false;
      return `<article class="mb-store-card" data-id="${s.id}">
        <div class="mb-store-top"><span class="mb-store-code">${escapeHtml(s.code)}</span>
          <span class="mb-store-conn ${conn ? 'on' : 'off'}">${conn ? '對外收單中' : '已停止對外'}</span></div>
        <label class="mb-store-toggle"><input type="checkbox" class="st-view"${view ? ' checked' : ''}>
          <span>顯示於選單／月報表${view ? '' : '（已隱藏，不影響營運）'}</span></label>
        <button class="mb-store-kill${conn ? '' : ' is-off'}" data-act="conn" type="button">${conn ? '停止對外連結（kill-switch）' : '恢復對外連結'}</button>
      </article>`;
    }).join('') || '<div class="mb-empty-state" style="display:block">尚無店別</div>';

    list.querySelectorAll('.mb-store-card').forEach((card) => {
      const id = Number(card.dataset.id);
      const s = stores.find((x) => x.id === id) || {};
      card.querySelector('.st-view').addEventListener('change', async (ev) => {
        const next = ev.target.checked;
        try {
          const { status } = await api.setStoreViewable(id, next);
          if (status === 200) { mbToast(`${s.code} ${next ? '已顯示於選單／月報表' : '已自選單／月報表隱藏'}`); if (onChanged) onChanged(); draw(); }
          else { ev.target.checked = !next; mbToast('切換失敗'); }
        } catch { ev.target.checked = !next; mbToast('切換失敗'); }
      });
      card.querySelector('[data-act="conn"]').addEventListener('click', async () => {
        const on = s.active !== false;
        const next = !on;                        // on→關；off→開
        if (!next && !window.confirm(`確定停止店別 ${s.code} 的對外連結？該店將無法對外收單。`)) return;
        try {
          const { status } = await api.setStoreActive(id, next);
          if (status === 200) { mbToast(`${s.code} ${next ? '已恢復對外連結' : '已停止對外連結'}`); draw(); }
          else mbToast('切換失敗');
        } catch { mbToast('切換失敗'); }
      });
    });
  };

  container.querySelector('#mb-store-add-btn').addEventListener('click', async () => {
    const inp = container.querySelector('#mb-new-store');
    const err = container.querySelector('#mb-store-err');
    err.textContent = '';
    const raw = (inp.value || '').trim().toUpperCase();
    if (!/^[A-Z]{1,2}$/.test(raw)) { err.textContent = '請輸入 1–2 個英文字母'; return; }
    try {
      const { status, data } = await api.createStore(raw, raw);
      if (status === 200 || status === 201) { mbToast(`已新增店別 ${raw}`); inp.value = ''; if (onChanged) onChanged(); draw(); }
      else err.textContent = (data && data.error) || '新增失敗（代號可能重複）';
    } catch { err.textContent = '新增失敗，請重試'; }
  });

  draw();
}
