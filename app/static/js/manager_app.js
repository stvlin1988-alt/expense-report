// 主管手機殼（UI 重塑 2026-07）：抬頭 + 可橫捲主分頁 + 5 pane + 常駐 action bar（僅稽核）。
// 取代主管原本與經理共用的桌面側邊欄工作台（admin.js showAdminPanel）。經理仍走 admin.js。
import { escapeHtml } from './admin_util.js';
import { api } from './admin_api.js';
import { mbToast, stopPaneCamera, postJSON } from './mb_util.js';
import { renderAuditPane, wireActionBar } from './manager_audit_mobile.js'; // Task 2/3 提供
import { renderLogs } from './admin_logs.js';       // Task 4 接
import { renderAccounts } from './admin_accounts.js'; // Task 4 接
import { renderDevices } from './admin_devices.js';   // Task 4 接

const root = () => document.getElementById('modal-root');
const TABS = ['audit', 'logs', 'accounts', 'devices', 'mypw'];
const LABELS = { audit: '稽核', logs: '操作記錄', accounts: '帳號', devices: '裝置', mypw: '我的密碼' };

export function showManagerApp(identity) {
  const state = { tab: 'audit', stores: [] };

  const paneHtml = TABS.map((t) =>
    `<section class="mb-pane${t === 'audit' ? ' active' : ''}" id="mb-pane-${t}" aria-label="${LABELS[t]}"></section>`).join('');
  const tabBtns = TABS.map((t) =>
    `<button class="mb-toptab${t === 'audit' ? ' active' : ''}" data-tab="${t}" type="button">${LABELS[t]}</button>`).join('');

  root().innerHTML = `
    <div class="mb-app" id="mb-app">
      <header class="mb-appbar">
        <div class="mb-who" id="mb-who">
          <span><span class="mb-name">${escapeHtml(identity.name)}</span><span class="mb-sub">主管</span></span>
        </div>
        <div class="mb-appbar-actions">
          <button class="mb-icon-btn" id="mb-mypw" title="我的密碼" aria-label="我的密碼">🔑</button>
          <button class="mb-icon-btn" id="mb-logout" title="登出" aria-label="登出">⎋</button>
        </div>
      </header>
      <nav class="mb-toptabs" role="tablist" aria-label="主功能">${tabBtns}</nav>
      <main class="mb-content">${paneHtml}</main>
      <div class="mb-actionbar" id="mb-actionbar" hidden></div>
      <div class="mb-toast" id="mb-toast" role="status" aria-live="polite"></div>
    </div>`;

  const panes = {};
  TABS.forEach((t) => { panes[t] = document.getElementById('mb-pane-' + t); });
  const actionbar = document.getElementById('mb-actionbar');

  const reload = () => renderPane(state.tab);
  const refreshStores = async () => {
    try { const { data } = await api.getStores(); state.stores = (data && data.stores) || []; }
    catch { state.stores = []; }
    // 抬頭店徽：由 identity.store_id 查本店 code（查不到就不顯示，不造假）
    const mine = state.stores.find((s) => s.id === identity.store_id);
    const who = document.getElementById('mb-who');
    const badge = mine && mine.code
      ? `<span class="mb-store-badge">${escapeHtml(mine.code)}</span>` : '';
    who.innerHTML = `${badge}<span><span class="mb-name">${escapeHtml(identity.name)}</span><span class="mb-sub">主管</span></span>`;
  };
  const ctx = () => ({ identity, storeId: null, stores: state.stores, api, reload, refreshStores });

  function renderPane(name) {
    const el = panes[name];
    if (name === 'audit') {
      renderAuditPane(el, { onSubtotalChange: paintSubtotal });
    } else if (name === 'logs') {
      renderLogs(el, identity, null);              // Task 4：主管本店，storeId=null
    } else if (name === 'accounts') {
      renderAccounts(el, ctx());                   // Task 4
    } else if (name === 'devices') {
      renderDevices(el, ctx());                    // Task 4
    } else if (name === 'mypw') {
      renderMyPasswordPane(el);                    // Task 5
    }
  }

  function showTab(name) {
    if (!panes[name] || name === state.tab) return;
    stopPaneCamera(panes[state.tab]);
    state.tab = name;
    document.querySelectorAll('.mb-toptab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
    Object.entries(panes).forEach(([k, el]) => el.classList.toggle('active', k === name));
    actionbar.hidden = (name !== 'audit');         // action bar 僅稽核顯示
    document.querySelector('.mb-content').scrollTop = 0;
    renderPane(name);
  }
  function paintSubtotal(open) {
    const b = actionbar.querySelector('#mb-ab-total');
    const c = actionbar.querySelector('#mb-ab-count');
    if (b) b.textContent = open ? open.subtotalText : '$0';
    if (c) c.textContent = open ? String(open.count) : '0';
  }

  document.querySelectorAll('.mb-toptab').forEach((t) => t.addEventListener('click', () => showTab(t.dataset.tab)));
  document.getElementById('mb-mypw').addEventListener('click', () => showTab('mypw'));
  document.getElementById('mb-logout').addEventListener('click', async () => {
    stopPaneCamera(panes[state.tab]);
    await postJSON('/auth/logout');
    location.reload();
  });

  // 建立 action bar 內容（Task 2 wireActionBar 接手交班/結班/取消 + 小計）
  actionbar.innerHTML = `
    <div class="mb-ab-sub"><span>當前班即時小計</span>
      <span><b id="mb-ab-total" class="num">$0</b>（<span id="mb-ab-count" class="num">0</span> 筆）</span></div>
    <div class="mb-ab-btns">
      <button class="mb-ab-btn mb-ab-primary" id="mb-ab-shift" type="button">交班</button>
      <button class="mb-ab-btn mb-ab-primary" id="mb-ab-day" type="button">結班</button>
      <button class="mb-ab-btn mb-ab-secondary" id="mb-ab-undo" type="button">取消上一次</button>
    </div>
    <span class="mb-ab-err" id="mb-ab-err"></span>`;

  // 我的密碼 pane（Task 5 實作；Task 1 先放佔位避免 undefined）
  function renderMyPasswordPane(el) {
    el.innerHTML = '<div class="mb-ph-card"><h3>我的密碼</h3></div>';
  }

  refreshStores().then(() => {
    renderPane('audit');           // 進站預設稽核
    actionbar.hidden = (state.tab !== 'audit');
    wireActionBar(actionbar, { onSubtotalChange: paintSubtotal }); // Task 2 提供；Task 1 若尚未有可先 no-op
  });
}
