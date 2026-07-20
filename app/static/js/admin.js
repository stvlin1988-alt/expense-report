import { api } from './admin_api.js';
import { isValidPin, escapeHtml } from './admin_util.js';
import { renderAccounts } from './admin_accounts.js';
import { renderDevices } from './admin_devices.js';
import { renderAudit } from './admin_audit.js';
import { renderLogs } from './admin_logs.js';
import { renderMonthReport } from './month_report.js';
import { periodsApi } from './periods_api.js';

const root = () => document.getElementById('modal-root');

export async function showAdminPanel(identity) {
  const isSuper = identity.role === 'super_admin';
  const state = { tab: isSuper ? 'report' : 'audit', storeId: null, stores: [] };

  // 先抓店清單（供調店切換 + 分頁下拉）
  try {
    const { status, data } = await api.getStores();
    if (status === 200 && data.status === 'ok') state.stores = data.stores;
  } catch (e) { /* 靜默：分頁自行處理空清單 */ }

  // super_admin 稽核/查詢一律看單一店（不做跨店彙整）：預設上次選的店，否則第一家。
  if (isSuper) {
    const saved = parseInt(localStorage.getItem('admin_store_id'), 10);
    const validSaved = state.stores.find((s) => s.id === saved);
    state.storeId = validSaved ? saved : (state.stores[0] ? state.stores[0].id : null);
  }

  const tabs = [
    ...(isSuper ? [{ key: 'report', label: '月報表' }] : []),
    { key: 'audit', label: '稽核' },
    ...(isSuper ? [{ key: 'stores', label: '店別管理' }] : []),
    ...(isSuper ? [{ key: 'closing', label: '月結設定', ro: true }] : []),
    { key: 'accounts', label: '帳號' },
    { key: 'devices', label: '裝置' },
    { key: 'logs', label: '操作記錄' },
    { key: 'mypw', label: '我的密碼' },
  ];

  function shellHtml() {
    const scope = isSuper ? `
      <div class="wk-store-scope">
        <label class="wk-store-scope-label" for="ap-store">門市範圍（稽核＋月報表）</label>
        <select class="wk-store-scope-sel" id="ap-store" aria-label="選擇門市，同時決定稽核與月報表範圍">
          <option value=""${state.storeId == null ? ' selected' : ''}>全部門市</option>
          ${state.stores.filter((s) => s.viewable !== false).map((s) => `<option value="${s.id}"${s.id === state.storeId ? ' selected' : ''}>${escapeHtml(s.code)}</option>`).join('')}
        </select>
      </div>` : '';
    const navBtns = tabs.map((t) =>
      `<button class="wk-nav-item" data-tab="${t.key}"${t.key === state.tab ? ' aria-current="page"' : ''} type="button">${escapeHtml(t.label)}${t.ro ? '<span class="wk-nav-ro">🔒</span>' : ''}</button>`
    ).join('');
    const roleLabel = isSuper ? '經理・跨店管理' : '主管';
    return `
      <div class="wk-app">
        <aside class="wk-sidebar">
          <div class="wk-brand"><div class="wk-brand-name">雜支管理</div><div class="wk-brand-sub">${isSuper ? '經理工作台' : '主管工作台'}</div></div>
          ${scope}
          <nav class="wk-nav" aria-label="主導覽">${navBtns}</nav>
          <div class="wk-side-foot">
            <div class="wk-side-user"><span class="wk-avatar">${escapeHtml(identity.name.slice(0, 1))}</span>
              <div><div class="wk-side-user-name">${escapeHtml(identity.name)}</div><div class="wk-side-user-role">${roleLabel}</div></div></div>
            <button class="wk-btn wk-btn-secondary" id="ap-logout" type="button">登出</button>
          </div>
        </aside>
        <main class="wk-main"><div id="ap-body"></div></main>
      </div>`;
  }

  function ctx() {
    return {
      identity,
      storeId: state.storeId,
      stores: state.stores,
      api,
      reload: renderActiveTab,
      refreshStores: refreshStores,
    };
  }

  async function refreshStores() {
    try {
      const { status, data } = await api.getStores();
      if (status === 200 && data.status === 'ok') state.stores = data.stores;
    } catch (e) { /* 靜默 */ }
    // 重畫店別下拉（保留當前選擇）
    const sel = document.getElementById('ap-store');
    if (sel) {
      const cur = sel.value;
      sel.innerHTML = `<option value="">全部門市</option>` +
        state.stores.filter((s) => s.viewable !== false).map((s) => `<option value="${s.id}">${escapeHtml(s.code)}</option>`).join('');
      sel.value = cur;
    }
  }

  function renderMyPassword(container) {
    container.innerHTML = `
      <div class="ap-form">
        <input type="password" id="mp-old" placeholder="舊密碼" inputmode="numeric" maxlength="4" autocomplete="off">
        <input type="password" id="mp-new" placeholder="新密碼(4位)" inputmode="numeric" maxlength="4" autocomplete="off">
        <button class="ap-btn" id="mp-submit" type="button">變更密碼</button>
        <div class="ap-msg" id="mp-msg"></div>
      </div>`;
    const old = container.querySelector('#mp-old');
    const neu = container.querySelector('#mp-new');
    const msg = container.querySelector('#mp-msg');
    [old, neu].forEach((el) => el.addEventListener('input', () => {
      el.value = el.value.replace(/\D/g, '').slice(0, 4);
    }));
    container.querySelector('#mp-submit').addEventListener('click', async () => {
      msg.textContent = '';
      if (!isValidPin(neu.value)) { msg.textContent = '新密碼需為 4 位數字'; return; }
      try {
        const { status, data } = await api.changeMyPassword(old.value, neu.value);
        if (status === 200 && data.status === 'ok') {
          msg.style.color = '#2e7d32'; msg.textContent = '已變更';
          old.value = ''; neu.value = '';
        } else if (data.message === 'wrong old password' || status === 400) {
          msg.style.color = '#c62828'; msg.textContent = '舊密碼錯誤或格式不符';
        } else {
          msg.style.color = '#c62828'; msg.textContent = '變更失敗';
        }
      } catch (e) {
        msg.style.color = '#c62828'; msg.textContent = '變更失敗，請重試';
      }
    });
  }

  function renderStores(container) {
    // 僅 super_admin 進得來（tab 不對其他角色顯示）
    const rows = state.stores.map((s) => {
      const view = s.viewable !== false;
      const conn = s.active !== false;
      return `<tr><td>${escapeHtml(s.code)}</td>
           <td><label class="st-onoff"><input type="checkbox" class="st-viewable" data-id="${s.id}"${view ? ' checked' : ''}> 顯示</label></td>
           <td>${conn ? '連線中' : '<span class="rc-neg">已關閉</span>'}
               <button class="ap-btn" data-conn="${s.id}" data-active="${conn ? '1' : '0'}" type="button">${conn ? '關閉對外連結' : '開啟對外連結'}</button></td>
           <td class="ap-rowbtns"><button class="ap-btn danger" data-del="${s.id}" type="button">刪除</button></td></tr>`;
    }).join('');
    container.innerHTML = `
      <div class="ap-table-wrap">
        <table class="ap-table">
          <thead><tr><th>店別</th><th>檢視</th><th>對外連結</th><th>操作</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="4">尚無店別</td></tr>'}</tbody>
        </table>
      </div>
      <p class="ap-hint">「檢視」打勾＝這家店會出現在選店選單／月報表等檢視裡（取消只是隱藏，不影響營運）。<br>
      「對外連結」關閉＝該店所有人員／主管立即被擋在計算機外、進不去（真正停用該店）。兩者互不影響，僅經理可改。</p>
      <div class="ap-form">
        <input type="text" id="st-code" placeholder="店別（英文）" autocomplete="off">
        <button class="ap-btn" id="st-add" type="button">新增店</button>
        <div class="ap-msg" id="st-msg"></div>
      </div>`;
    const msg = container.querySelector('#st-msg');
    container.querySelectorAll('button[data-del]').forEach((b) => {
      b.addEventListener('click', async () => {
        const id = parseInt(b.dataset.del, 10);
        if (!confirm('確定刪除此店別？（店內有帳號或裝置則無法刪除）')) return;
        try {
          const { status, data } = await api.deleteStore(id);
          if (status === 200 && data.status === 'ok') { await refreshStores(); renderActiveTab(); }
          else if (status === 409) { msg.style.color = '#c62828'; msg.textContent = '店別有帳號或裝置，無法刪除'; }
          else { msg.style.color = '#c62828'; msg.textContent = '刪除失敗'; }
        } catch (e) { msg.style.color = '#c62828'; msg.textContent = '刪除失敗，請重試'; }
      });
    });
    // 檢視顯示：打勾方框（顯示/隱藏於檢視，不影響營運）
    container.querySelectorAll('input.st-viewable').forEach((cb) => {
      cb.addEventListener('change', async () => {
        msg.textContent = '';
        const id = parseInt(cb.dataset.id, 10);
        const next = cb.checked;
        try {
          const { status, data } = await api.setStoreViewable(id, next);
          if (!(status === 200 && data.status === 'ok')) {
            cb.checked = !next;
            msg.style.color = '#c62828'; msg.textContent = '切換失敗';
          } else { await refreshStores(); }
        } catch (e) {
          cb.checked = !next;
          msg.style.color = '#c62828'; msg.textContent = '切換失敗，請重試';
        }
      });
    });
    // 對外連結：停用/啟用按鈕（真正關掉該店＝把人員擋在計算機外）
    container.querySelectorAll('button[data-conn]').forEach((b) => {
      b.addEventListener('click', async () => {
        msg.textContent = '';
        const id = parseInt(b.dataset.conn, 10);
        const next = b.dataset.active !== '1';   // 目前連線→關閉(false)；目前關閉→開啟(true)
        if (!next && !confirm('關閉對外連結後，這家店所有人員／主管會立即被擋在計算機外、無法進入。確定？')) return;
        try {
          const { status, data } = await api.setStoreActive(id, next);
          if (status === 200 && data.status === 'ok') { await refreshStores(); renderActiveTab(); }
          else { msg.style.color = '#c62828'; msg.textContent = '切換失敗'; }
        } catch (e) { msg.style.color = '#c62828'; msg.textContent = '切換失敗，請重試'; }
      });
    });
    container.querySelector('#st-add').addEventListener('click', async () => {
      msg.textContent = '';
      const code = container.querySelector('#st-code').value.trim();
      if (!code) { msg.textContent = '請填店別'; return; }
      try {
        // 店別以英文代碼為唯一識別；name 帶同 code（後端 name 缺省亦等於 code）
        const { status, data } = await api.createStore(code, code);
        if (status === 200 && data.status === 'ok') {
          await refreshStores();
          renderActiveTab();
        } else if (status === 409) {
          msg.style.color = '#c62828'; msg.textContent = '店別已存在';
        } else {
          msg.style.color = '#c62828'; msg.textContent = '新增失敗';
        }
      } catch (e) {
        msg.style.color = '#c62828'; msg.textContent = '新增失敗，請重試';
      }
    });
  }

  // 月報表（super_admin only）：跟隨側欄的門市範圍選單（同一個選店同時管稽核與月結），
  // 並在工具列鏡像同一個選店（兩處操作即時互相同步，改哪一個都一樣）。
  // 選特定店→只看該店；選「全部門市」(storeId null)→各店攤開。
  function renderReport(container) {
    const scopeOpts = `<option value=""${state.storeId == null ? ' selected' : ''}>全部門市</option>` +
      state.stores.filter((s) => s.viewable !== false).map((s) => `<option value="${s.id}"${s.id === state.storeId ? ' selected' : ''}>${escapeHtml(s.code)}</option>`).join('');
    const label = state.storeId == null ? '全部門市' : `門市 ${escapeHtml((state.stores.find((s) => s.id === state.storeId) || {}).code || '')}`;
    container.innerHTML = `
      <div class="wk-toolbar"><div class="wk-toolbar-row">
        <span class="wk-toolbar-title">月報表</span>
        <span class="wk-spacer"></span>
        <label class="wk-filter-label">範圍</label>
        <select class="wk-select" id="report-scope-sel">${scopeOpts}</select>
      </div></div>
      <div class="wk-page-body"><div class="wk-card">
        <div class="wk-card-head"><span class="wk-card-title">店 × 科目 交叉表</span>
          <span class="wk-badge wk-badge-scope" id="report-scope-badge">${label}</span></div>
        <div class="table-wrap" id="report-wrap"></div>
        <div class="wk-report-note">金額單位：新台幣。僅計入「已核銷」單據；退回與挪期不列入。負數以紅字顯示。</div>
      </div></div>`;
    const draw = () => renderMonthReport(container.querySelector('#report-wrap'),
      { storeId: state.storeId != null ? String(state.storeId) : '', lockStore: true });
    draw();
    container.querySelector('#report-scope-sel').addEventListener('change', (e) => {
      state.storeId = e.target.value ? parseInt(e.target.value, 10) : null;
      if (state.storeId != null) localStorage.setItem('admin_store_id', String(state.storeId));
      else localStorage.removeItem('admin_store_id');
      const side = document.getElementById('ap-store'); if (side) side.value = e.target.value;
      renderReport(container);
    });
  }

  // 月結設定（super_admin only）：唯讀顯示月結日/鎖定偏移（不提供編輯，後端 PATCH 對經理亦 403）。
  // 此 task 只搬程式、維持舊樣式，wk 化留 Task 3。
  async function renderClosing(container) {
    container.innerHTML = `<div class="ap-form" id="mo-settings"><div class="ap-empty">載入中…</div></div>`;
    const settingsBox = container.querySelector('#mo-settings');
    try {
      const { status, data } = await periodsApi.getSettings();
      if (status === 200 && data.status === 'ok') {
        settingsBox.innerHTML = `
          <div>月結日：${escapeHtml(String(data.period_close_day))} 號</div>
          <div>鎖定偏移：${escapeHtml(String(data.period_lock_offset_hours))} 小時（換期日後 ${escapeHtml(String(data.period_lock_offset_hours))} 小時鎖定）</div>`;
      } else {
        settingsBox.innerHTML = '<div class="ap-empty">載入失敗，請重試</div>';
      }
    } catch (e) {
      settingsBox.innerHTML = '<div class="ap-empty">載入失敗，請重試</div>';
    }
  }

  function renderActiveTab() {
    const body = document.getElementById('ap-body');
    if (!body) return;
    const liveVid = body.querySelector('video');
    if (liveVid && liveVid.srcObject) {
      liveVid.srcObject.getTracks().forEach((t) => t.stop());
      liveVid.srcObject = null;
    }
    body.innerHTML = '';
    if (state.tab === 'accounts') renderAccounts(body, ctx());
    else if (state.tab === 'devices') renderDevices(body, ctx());
    else if (state.tab === 'audit') renderAudit(body, identity, state.storeId);
    else if (state.tab === 'logs') renderLogs(body, identity, state.storeId);
    else if (state.tab === 'stores') renderStores(body);
    else if (state.tab === 'report') renderReport(body);
    else if (state.tab === 'closing') renderClosing(body);
    else if (state.tab === 'mypw') renderMyPassword(body);
  }

  function mount() {
    root().innerHTML = shellHtml();
    document.getElementById('ap-logout').addEventListener('click', async () => {
      try { await fetch('/auth/logout', { method: 'POST' }); } catch (e) { /* ignore */ }
      location.reload();
    });
    const sel = document.getElementById('ap-store');
    if (sel) sel.addEventListener('change', () => {
      state.storeId = sel.value ? parseInt(sel.value, 10) : null;
      if (state.storeId != null) localStorage.setItem('admin_store_id', String(state.storeId));
      else localStorage.removeItem('admin_store_id');
      renderActiveTab();
    });
    root().querySelectorAll('.wk-nav-item').forEach((btn) => {
      btn.addEventListener('click', () => {
        state.tab = btn.dataset.tab;
        root().querySelectorAll('.wk-nav-item').forEach((b) => b.removeAttribute('aria-current'));
        btn.setAttribute('aria-current', 'page');
        window.scrollTo(0, 0);
        renderActiveTab();
      });
    });
    renderActiveTab();
  }

  mount();
}
