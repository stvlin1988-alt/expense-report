import { api } from './admin_api.js';
import { isValidPin, escapeHtml } from './admin_util.js';
import { renderAccounts } from './admin_accounts.js';
import { renderDevices } from './admin_devices.js';

const root = () => document.getElementById('modal-root');

export async function showAdminPanel(identity) {
  const isSuper = identity.role === 'super_admin';
  const state = { tab: 'accounts', storeId: null, stores: [] };

  // 先抓店清單（供調店切換 + 分頁下拉）
  try {
    const { status, data } = await api.getStores();
    if (status === 200 && data.status === 'ok') state.stores = data.stores;
  } catch (e) { /* 靜默：分頁自行處理空清單 */ }

  const tabs = [
    { key: 'accounts', label: '帳號' },
    { key: 'devices', label: '裝置' },
    ...(isSuper ? [{ key: 'stores', label: '店別' }] : []),
    { key: 'mypw', label: '我的密碼' },
  ];

  function shellHtml() {
    const storeOpts = isSuper
      ? `<select id="ap-store" class="ap-select">
           <option value="">全部店</option>
           ${state.stores.map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join('')}
         </select>`
      : '';
    const tabBtns = tabs.map((t) =>
      `<button class="ap-tab${t.key === state.tab ? ' active' : ''}" data-tab="${t.key}" type="button">${t.label}</button>`
    ).join('');
    return `
      <div class="admin-panel">
        <header class="ap-head">
          <span class="ap-title">管理後台</span>
          <span class="ap-who">${escapeHtml(identity.name)}</span>
          ${storeOpts}
          <button class="ap-btn ap-logout" id="ap-logout" type="button">登出</button>
        </header>
        <nav class="ap-tabs">${tabBtns}</nav>
        <section class="ap-body" id="ap-body"></section>
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
      sel.innerHTML = `<option value="">全部店</option>` +
        state.stores.map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join('');
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
    const rows = state.stores.map((s) =>
      `<tr><td>${escapeHtml(s.name)}</td><td>${escapeHtml(s.code)}</td></tr>`).join('');
    container.innerHTML = `
      <table class="ap-table">
        <thead><tr><th>店名</th><th>代碼</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="2">尚無店別</td></tr>'}</tbody>
      </table>
      <div class="ap-form">
        <input type="text" id="st-name" placeholder="店名" autocomplete="off">
        <input type="text" id="st-code" placeholder="代碼" autocomplete="off">
        <button class="ap-btn" id="st-add" type="button">新增店</button>
        <div class="ap-msg" id="st-msg"></div>
      </div>`;
    const msg = container.querySelector('#st-msg');
    container.querySelector('#st-add').addEventListener('click', async () => {
      msg.textContent = '';
      const name = container.querySelector('#st-name').value.trim();
      const code = container.querySelector('#st-code').value.trim();
      if (!name || !code) { msg.textContent = '請填店名與代碼'; return; }
      try {
        const { status, data } = await api.createStore(name, code);
        if (status === 200 && data.status === 'ok') {
          await refreshStores();
          renderActiveTab();
        } else if (status === 409) {
          msg.style.color = '#c62828'; msg.textContent = '店名或代碼已存在';
        } else {
          msg.style.color = '#c62828'; msg.textContent = '新增失敗';
        }
      } catch (e) {
        msg.style.color = '#c62828'; msg.textContent = '新增失敗，請重試';
      }
    });
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
    else if (state.tab === 'stores') renderStores(body);
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
      renderActiveTab();
    });
    root().querySelectorAll('.ap-tab').forEach((btn) => {
      btn.addEventListener('click', () => {
        state.tab = btn.dataset.tab;
        root().querySelectorAll('.ap-tab').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        renderActiveTab();
      });
    });
    renderActiveTab();
  }

  mount();
}
