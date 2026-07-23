// 經理手機殼（UI 重塑 2026-07）：抬頭（跨店選店）+ 可橫捲主分頁 + 7 pane。
// 取代經理在觸控裝置上原本走的桌面側邊欄工作台（admin.js showAdminPanel）；桌機仍走 admin.js。
// 混合：店別/月結殼/我的密碼原生；稽核唯讀/帳號/裝置/操作記錄重用經理電腦版 render 包 .mb-admin-embed；
// 月報表交叉表重用 renderMonthReport（Task 2）。
import { escapeHtml, isValidPin } from './admin_util.js';
import { api } from './admin_api.js';
import { mbToast, stopPaneCamera, postJSON } from './mb_util.js';
import { renderAudit } from './admin_audit.js';
import { renderAccounts } from './admin_accounts.js';
import { renderDevices } from './admin_devices.js';
import { renderLogs } from './admin_logs.js';

const root = () => document.getElementById('modal-root');
// 分頁順序對齊原型（稽核 首、月結 預設選中）
const TABS = ['audit', 'month', 'stores', 'accounts', 'devices', 'logs', 'mypw'];
const LABELS = { audit: '稽核', month: '月結', stores: '店別', accounts: '帳號', devices: '裝置', logs: '操作記錄', mypw: '我的密碼' };

export function showSuperApp(identity) {
  const saved = Number(localStorage.getItem('admin_store_id'));
  const state = { tab: 'month', storeId: Number.isFinite(saved) && saved > 0 ? saved : null, stores: [] };

  const paneHtml = TABS.map((t) =>
    `<section class="mb-pane${t === state.tab ? ' active' : ''}" id="mb-pane-${t}" aria-label="${LABELS[t]}"></section>`).join('');
  const tabBtns = TABS.map((t) =>
    `<button class="mb-toptab${t === state.tab ? ' active' : ''}" data-tab="${t}" type="button">${LABELS[t]}</button>`).join('');

  root().innerHTML = `
    <div class="mb-app" id="mb-app">
      <header class="mb-appbar">
        <div class="mb-who" id="mb-who">
          <span><span class="mb-name">${escapeHtml(identity.name)}</span><span class="mb-sub">經理・跨店</span></span>
        </div>
        <div class="mb-appbar-actions">
          <select class="mb-store-sel" id="ap-store" aria-label="選擇門市（同時決定稽核與月報表）"></select>
          <button class="mb-icon-btn" id="mb-mypw" title="我的密碼" aria-label="我的密碼">🔑</button>
          <button class="mb-icon-btn" id="mb-logout" title="登出" aria-label="登出">⎋</button>
        </div>
      </header>
      <nav class="mb-toptabs" role="tablist" aria-label="主功能">${tabBtns}</nav>
      <main class="mb-content">${paneHtml}</main>
      <div class="mb-toast" id="mb-toast" role="status" aria-live="polite"></div>
    </div>`;

  const panes = {};
  TABS.forEach((t) => { panes[t] = document.getElementById('mb-pane-' + t); });
  const storeSel = document.getElementById('ap-store');

  const reload = () => renderPane(state.tab);
  const refreshStores = async () => {
    try { const { data } = await api.getStores(); state.stores = (data && data.stores) || []; }
    catch { state.stores = []; }
    // 抬頭選店：全部門市 + 各可見店 code（保留當前選取）
    const opts = [`<option value=""${state.storeId == null ? ' selected' : ''}>全部門市</option>`]
      .concat(state.stores.filter((s) => s.viewable !== false).map((s) =>
        `<option value="${s.id}"${s.id === state.storeId ? ' selected' : ''}>${escapeHtml(s.code)}</option>`));
    storeSel.innerHTML = opts.join('');
  };
  const ctx = () => ({ identity, storeId: state.storeId, stores: state.stores, api, reload, refreshStores });

  function renderPane(name) {
    const el = panes[name];
    if (name === 'audit') {
      el.innerHTML = '<div class="mb-admin-embed"></div>';
      renderAudit(el.querySelector('.mb-admin-embed'), identity, state.storeId, state.stores);
    } else if (name === 'month') {
      renderMonthPane(el);                         // Task 1 佔位；Task 2 真作
    } else if (name === 'stores') {
      renderStoresPaneWrap(el);                    // Task 1 佔位；Task 3 真作
    } else if (name === 'accounts') {
      el.innerHTML = '<div class="mb-pane-title" style="padding:12px 14px 0">帳號</div><div class="mb-admin-embed"></div>';
      renderAccounts(el.querySelector('.mb-admin-embed'), ctx());
    } else if (name === 'devices') {
      el.innerHTML = '<div class="mb-pane-title" style="padding:12px 14px 0">裝置</div><div class="mb-admin-embed"></div>';
      renderDevices(el.querySelector('.mb-admin-embed'), ctx());
    } else if (name === 'logs') {
      el.innerHTML = '<div class="mb-pane-title" style="padding:12px 14px 0">操作記錄</div><div class="mb-admin-embed"></div>';
      renderLogs(el.querySelector('.mb-admin-embed'), identity, state.storeId);
    } else if (name === 'mypw') {
      renderMyPasswordPane(el);
    }
  }

  function showTab(name) {
    if (!panes[name] || name === state.tab) return;
    stopPaneCamera(panes[state.tab]);
    state.tab = name;
    document.querySelectorAll('.mb-toptab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
    Object.entries(panes).forEach(([k, el]) => el.classList.toggle('active', k === name));
    document.querySelector('.mb-content').scrollTop = 0;
    renderPane(name);
  }

  document.querySelectorAll('.mb-toptab').forEach((t) => t.addEventListener('click', () => showTab(t.dataset.tab)));
  document.getElementById('mb-mypw').addEventListener('click', () => showTab('mypw'));
  document.getElementById('mb-logout').addEventListener('click', async () => {
    stopPaneCamera(panes[state.tab]);
    await postJSON('/auth/logout');
    location.reload();
  });

  // 抬頭選店（跨店）：更新 storeId + localStorage，重繪當前 pane（稽核/月結吃它）。
  // renderAudit 唯讀分支的 pickStore() 也是對 #ap-store dispatch change → 走這裡。
  storeSel.addEventListener('change', () => {
    state.storeId = storeSel.value ? parseInt(storeSel.value, 10) : null;
    if (state.storeId != null) localStorage.setItem('admin_store_id', String(state.storeId));
    else localStorage.removeItem('admin_store_id');
    renderPane(state.tab);
  });

  // 我的密碼 pane（自寫，沿用主管手機同流程：4 位數字 PIN，api.changeMyPassword）
  function renderMyPasswordPane(el) {
    el.innerHTML = `
      <div class="mb-ph-card"><h3>變更我的密碼</h3>
        <div class="mb-form-field"><label for="mb-pw-old">舊密碼</label><input type="password" id="mb-pw-old" inputmode="numeric" maxlength="4" autocomplete="current-password"></div>
        <div class="mb-form-field"><label for="mb-pw-new">新密碼</label><input type="password" id="mb-pw-new" inputmode="numeric" maxlength="4" autocomplete="new-password"></div>
        <div class="mb-form-field"><label for="mb-pw-new2">確認新密碼</label><input type="password" id="mb-pw-new2" inputmode="numeric" maxlength="4" autocomplete="new-password"></div>
        <button class="mb-pw-btn" id="mb-pw-submit" type="button">更新密碼</button>
        <div class="mb-au-err" id="mb-pw-err"></div></div>`;
    const oldEl = el.querySelector('#mb-pw-old');
    const newEl = el.querySelector('#mb-pw-new');
    const new2El = el.querySelector('#mb-pw-new2');
    [oldEl, newEl, new2El].forEach((inp) => inp.addEventListener('input', () => {
      inp.value = inp.value.replace(/\D/g, '').slice(0, 4);
    }));
    el.querySelector('#mb-pw-submit').addEventListener('click', async () => {
      const oldp = oldEl.value, np = newEl.value, np2 = new2El.value;
      const err = el.querySelector('#mb-pw-err');
      err.textContent = '';
      if (!isValidPin(np)) { err.textContent = '新密碼需為 4 位數字'; return; }
      if (np !== np2) { err.textContent = '兩次新密碼不一致'; return; }
      try {
        const { status } = await api.changeMyPassword(oldp, np);
        if (status === 200) { mbToast('密碼已更新'); oldEl.value = ''; newEl.value = ''; new2El.value = ''; }
        else err.textContent = '更新失敗（舊密碼可能不正確）';
      } catch { err.textContent = '更新失敗，請重試'; }
    });
  }

  // Task 1 佔位：月結／店別（Task 2/3 換真作）
  function renderMonthPane(el) {
    el.innerHTML = '<div class="mb-ph-card"><h3>月結（待實作）</h3></div>';
  }
  function renderStoresPaneWrap(el) {
    el.innerHTML = '<div class="mb-ph-card"><h3>店別管理（待實作）</h3></div>';
  }

  refreshStores().then(() => { renderPane(state.tab); });   // 進站預設月結
}
