# 經理手機 App UI 重塑 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把經理（super_admin）在**觸控裝置（手機/平板）**上，從現行「一律進桌面側邊欄工作台（`showAdminPanel`，`admin.js`）」重塑成原型 `super-mobile.html` 的「常駐手機殼（抬頭跨店選店 ＋ 可橫捲主分頁 ＋ 內容 pane）」；桌機仍走 `showAdminPanel`。

**Architecture:** 純前端／CSS／DOM 重塑，**不動後端、不改 API、不改任務流、不碰計算機幌子、角色守門全沿用現況**。新增 `super_app.js`（`showSuperApp`），沿用員工/主管已建的 `.mb-*` 手機設計層與 `mb_util.js` 共用工具。**混合策略**：店別管理、我的密碼寫原生 `.mb-*`；月結設定唯讀卡原生 + 月報表交叉表**重用 `renderMonthReport`**（`.wk-xt` 已 sticky 科目首欄＋橫捲）；稽核唯讀／帳號／裝置／操作記錄**重用經理電腦版已建好的 render**（`renderAudit` isSuper 分支／`renderAccounts`／`renderDevices`／`renderLogs`），套 `.mb-admin-embed`。**登入依 `pointer:coarse` 判一次**路由。視覺 SoT = `docs/superpowers/ui-prototypes/super-mobile.html`；spec = `docs/superpowers/specs/2026-07-23-ui-redesign-super-mobile-design.md`。

**Tech Stack:** Vanilla ES module（無框架）、單一 `app/static/css/app.css`、Flask 模板、PWA service worker（`sw.js` 快取靜態清單）。

## 前端驗證策略（本 plan 對 TDD 的 adaptation）

沿用員工/主管手機 plan 同一套（DOM／CSS 重塑非後端邏輯，故驗證分軌）：
- **純函式** → 本 plan **不動任何純函式**（`month_report.js` 的 `formatCell`/`pickCell`、`isValidPin`、`formatMoney` 維持行為）；每 task 結尾**重跑既有 node 測全綠（71 passed 基準）**。
- **後端未動** → 每 task 結尾跑 `python3 -m pytest -q` 確認 **567 passed** 沒被誤傷（本 plan 不改後端，僅防呆）。
- **DOM／CSS 重塑** → 本機開 server + dev 登入經理，**對照原型逐項目視檢**。

**本機啟動（harness `run_in_background: true`，勿用 shell `&`／nohup）：**
```
cd ~/project/report; set -a; . ./.env 2>/dev/null; set +a; export E2E_LOGIN_BYPASS=1 FLASK_APP=wsgi.py SECRET_KEY=${SECRET_KEY:-dev}; .venv/bin/python -m flask db upgrade; .venv/bin/python -m flask run --port 5001 --no-reload
```
- **經理面板入口**：`http://127.0.0.1:5001/dev/login-super`（dev 捷徑，繞過計算機+裝置閘，建/登入測試經理）。
- ⚠️ **路由靠 `pointer:coarse`**：桌機瀏覽器直開 `/dev/login-super` 會走 `showAdminPanel`（桌面工作台）。要看手機殼，先開 **Chrome DevTools → Toggle device toolbar（裝置模擬，會讓 `matchMedia('(pointer:coarse)')` 為 true）** 再登入；或用真手機。
- 對照原型：本機直接開檔 `docs/superpowers/ui-prototypes/super-mobile.html`。
- ⚠️ dev.db 資料可能很少；驗證稽核/月報表多店時，先於店別管理新增 TP/TC/KH 幾家，或用員工流建幾筆單。
- 改前端後：瀏覽器**硬重整**（避 sw 快取）；每個 task 最後 bump `sw.js` CACHE_NAME（現 `calc-v76` → 本 plan 依序 `calc-v77`…`calc-v79`）並**補新檔進 STATIC_URLS**。

---

## Global Constraints

以下每個 task 都隱含適用（值逐字取自 spec `docs/superpowers/specs/2026-07-23-ui-redesign-super-mobile-design.md` 與原型 `super-mobile.html`）：

- **不碰計算機幌子**（`calculator.js`/`secret.js`），不改後端/API/任務流；**角色守門全沿用現況**（月報表 reports/monthly＝accountant+super_admin；月結 periods GET＝accountant+super_admin，PATCH 僅 accountant；店別 CRUD＝super_admin；稽核＝manager+super_admin；帳號/裝置/操作記錄＝manager+super_admin；改密碼＝本人）。
- **經理可跨店**：抬頭選店 `state.storeId`（`null`＝全部門市），同時決定「稽核」與「月報表」看哪家。與主管（鎖本店 `sid=undefined`）路徑不同，勿混用。
- **抬頭選店 `id="ap-store"`**：`renderAudit` isSuper 唯讀分支的 `pickStore()`（admin_audit.js:36）用 `document.getElementById('ap-store')` 設值＋dispatch change；手機殼抬頭選店沿用此 id，唯讀稽核的選店快速鍵/返回鈕即零修改可用。
- **設計 token 沿用既有 `--wk-*`／`--mb-*`**（app.css 已定義 light/dark 三段 + 員工/主管手機段落）；本 plan **不重定義 token**，經理專屬 `.mb-*` 元件一律引用既有變數。
- **店別英文代號**（`s.code`，≤2 字母），**絕不露中文店名**。
- **時間台灣時間**（`formatDateTimeTW`）；營業日 08:00 分界；**不照搬原型假班別/假日期/假金額**，只顯示後端實際回傳欄位。
- **負數金額紅字**（`.num.neg`，U+2212 由 `formatMoney` 產出），金額 `tabular-nums`。
- **卡片列表單欄滿版**；**可橫捲主分頁不可藏任何分頁**。
- **收據縮圖真 `<img> thumb_url`**，點開走既有 `openImageLightbox`。
- **不接刪店**（spec §6 定案：高風險，UI 不出現）。
- **每次改 css/js → bump `sw.js` CACHE_NAME + 補新檔進 `STATIC_URLS`**（現 `calc-v76`；`mb_util.js`/`admin_api.js`/`admin_audit.js`/`admin_accounts.js`/`admin_devices.js`/`admin_logs.js`/`periods_api.js` 已在清單，主管手機 plan 補齊；本 plan 需補 `super_app.js`/`month_report.js`/`reports_api.js`/`super_stores_mobile.js`）。

---

## File Structure

| 檔案 | 動作 | 責任 |
|---|---|---|
| `app/static/js/super_app.js` | **Create** | 經理手機殼 `showSuperApp(identity)`：抬頭（姓名·跨店/選店 `#ap-store`/我的密碼/登出）＋可橫捲主分頁（稽核/月結/店別/帳號/裝置/操作記錄/我的密碼）＋內容 pane＋toast。稽核唯讀/帳號/裝置/操作記錄重用現有 render 包 `.mb-admin-embed`；月結 pane（原生月結卡＋重用 `renderMonthReport`）與我的密碼 pane 自寫；店別 pane 委給 `super_stores_mobile.js`。組 `ctx()` 供帳號/裝置重用。 |
| `app/static/js/super_stores_mobile.js` | **Create**（Task 3） | 經理店別管理原生卡：`renderStoresPane(container, { onChanged })`——顯示 toggle（`api.setStoreViewable`）＋對外連結 kill-switch（`api.setStoreActive`，關閉走確認）＋新增店（`api.createStore`）。不接刪店。 |
| `app/static/js/auth.js` | Modify（路由，:126） | `super_admin` 分派：`pointer:coarse` → `showSuperApp(identity)`；否則維持 `showAdminPanel`。頂部補 import。 |
| `app/static/js/main.js` | Modify（路由，:169） | 暗號 re-entry 分派：同 auth.js 拆分。頂部補 import。 |
| `app/static/css/app.css` | Modify（append「手機設計層－經理」段落） | 新增 `.mb-store-sel`（抬頭選店）、`.mb-month-head`/`.mb-closing-card`/`.mb-ro-head`/`.mb-ro-lock`/`.mb-kv`/`.mb-month-scope`/`.mb-badge*`（月結）、`.mb-store-hint`/`.mb-store-card`/`.mb-store-top`/`.mb-store-code`/`.mb-store-conn`/`.mb-store-toggle`/`.mb-store-kill`/`.mb-store-add`（店別）。沿用既有 `.mb-app`/`.mb-appbar`/`.mb-toptabs`/`.mb-admin-embed`/`.mb-ph-card`/`.mb-pane-title`/`.mb-form-field`/`.mb-pw-btn`/`.mb-au-err`/`.mb-empty-state`。舊段落不動。 |
| `app/static/sw.js` | Modify（每 task） | bump CACHE_NAME；補 `super_app.js`(T1)/`month_report.js`+`reports_api.js`(T2)/`super_stores_mobile.js`(T3) 進 STATIC_URLS。 |

**Task 邊界原則**：Task 1 打底（殼＋路由＋選店＋所有重用 pane＋我的密碼＋月結/店別佔位），Task 2/3 填兩個原生 pane。每個 task 是「一個可對照原型獨立目視驗收的交付」。

---

## Task 1: 手機殼 + 路由 + 選店抬頭 + 重用 pane（稽核唯讀/帳號/裝置/操作記錄）+ 我的密碼 + 月結/店別佔位

新建 `super_app.js` 常駐手機殼，登入依 `pointer:coarse` 路由經理進來，抬頭選店（`#ap-store`）跨店驅動稽核，重用四個現有 render，我的密碼自寫，月結/店別先放佔位（Task 2/3 填）。此 task 後殼可登入、可切所有分頁、選店驅動稽核唯讀、重用面板全可用。

**Files:**
- Create: `app/static/js/super_app.js`
- Modify: `app/static/js/auth.js`（頂部 import + `submit()` 分派 :126）、`app/static/js/main.js`（頂部 import + re-entry 分派 :169）
- Modify: `app/static/css/app.css`（append「手機設計層－經理」段落起頭：`.mb-store-sel`）
- Modify: `app/static/sw.js`（CACHE_NAME → `calc-v77`；STATIC_URLS 補 `super_app.js`）

**Interfaces:**
- Consumes: `escapeHtml`/`isValidPin`(admin_util.js)、`api`(admin_api.js：`getStores`/`changeMyPassword`)、`mbToast`/`stopPaneCamera`/`postJSON`(mb_util.js)、`renderAudit(container, identity, storeId, stores)`(admin_audit.js，isSuper→唯讀)、`renderAccounts(container, ctx)`(admin_accounts.js)、`renderDevices(container, ctx)`(admin_devices.js)、`renderLogs(container, identity, storeId)`(admin_logs.js)、既有 `.mb-*` CSS。
- Produces:
  - `super_app.js`：`export function showSuperApp(identity)`。殼 DOM 契約供 Task 2/3 —— pane 容器 id `#mb-pane-{audit,month,stores,accounts,devices,logs,mypw}`；主分頁 `.mb-toptab[data-tab]`；抬頭選店 `#ap-store`；閉包內函式 `renderMonthPane(el)`（Task 2 換真作）、`renderStoresPaneWrap(el)`（Task 3 換真作）、`ctx()`→`{identity, storeId, stores, api, reload, refreshStores}`。

- [ ] **Step 1: 寫 `super_app.js` 殼（含重用 pane、我的密碼、月結/店別佔位）**

新建 `app/static/js/super_app.js`：
```js
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
```
> ⚠️ Task 1 super_app.js **不 import** `month_report.js`/`periods_api.js`/`super_stores_mobile.js`（Task 2/3 才建/接）——否則 module 載入即失敗。月結/店別佔位用閉包內函式，Task 2/3 只改函式體＋補 import。

- [ ] **Step 2: 抬頭選店 CSS 進 app.css**

`app.css` 末尾 append，用註解分區：
```css
/* ============================================================
   手機設計層－經理（UI 重塑 2026-07；super_admin 手機/平板）
   沿用員工/主管手機段落的 .mb-app/.mb-appbar/.mb-toptabs/.mb-admin-embed/.mb-ph-card 基底。
   本段新增經理專屬：抬頭跨店選店 / 月結唯讀卡 / 店別管理卡。
   視覺 SoT: docs/superpowers/ui-prototypes/super-mobile.html
   ============================================================ */
/* 抬頭跨店選店（原型 .store-sel；置於 .mb-appbar-actions） */
.mb-store-sel{ max-width:104px; min-height:36px; padding:0 26px 0 10px; font-size:14px; font-weight:600;
  color:var(--wk-ink); background:var(--wk-surface-2); border:1px solid var(--wk-line);
  border-radius:var(--wk-radius-sm); appearance:none; -webkit-appearance:none;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'><path d='M2 4l4 4 4-4' stroke='%23888' stroke-width='1.5' fill='none' stroke-linecap='round' stroke-linejoin='round'/></svg>");
  background-repeat:no-repeat; background-position:right 8px center; }
.mb-store-sel:focus{ outline:none; box-shadow:0 0 0 3px var(--wk-accent-soft); border-color:var(--wk-accent); }
```

- [ ] **Step 3: 路由經理進新殼（auth.js / main.js，依 pointer:coarse）**

`auth.js`：頂部加 `import { showSuperApp } from './super_app.js';`。`submit()` 內 role 分派（現 auth.js:126 `super_admin` → `showAdminPanel(identity)`）改成：
```js
else if (data.role === 'super_admin') {
  if (window.matchMedia('(pointer: coarse)').matches) showSuperApp(identity);
  else showAdminPanel(identity);
}
```
`main.js`：頂部加 `import { showSuperApp } from './super_app.js';`。re-entry 分派（現 main.js:169 `super_admin` → `showAdminPanel(cfg.identity)`）改成：
```js
} else if (cfg.identity.role === 'super_admin') {
  if (window.matchMedia('(pointer: coarse)').matches) showSuperApp(cfg.identity);
  else showAdminPanel(cfg.identity);
}
```
> `showAdminPanel` import **保留**（桌機經理續用）。主管走 `showManagerApp` 不受影響。

- [ ] **Step 4: 本機驗證殼**

開 server。**DevTools 開裝置模擬（pointer:coarse）**後硬重整 `/dev/login-super`。對照原型 `super-mobile.html`：
- 滿版手機殼、抬頭（姓名＋「經理・跨店」＋選店下拉＋🔑＋⎋登出）。
- 主分頁列可橫捲：稽核/月結/店別/帳號/裝置/操作記錄/我的密碼，點擊切換、active 底線在 accent；**進站預設停在「月結」**（顯示佔位卡）。
- **稽核分頁**：選「全部門市」→ 空狀態卡＋各可見店快速鍵；點某店快速鍵 → 抬頭選店同步切該店 + 顯示該店唯讀稽核表（依班別分組、燈號/徽章、無操作鈕）；「‹ 返回全部門市」回空狀態。抬頭選店改店也即時重繪稽核。
- 帳號/裝置/操作記錄分頁：重用內容顯示（桌面 `.wk-*` 樣式收在 `.mb-admin-embed` 內，可捲），能力保留。
- 我的密碼：改密碼成功 toast、防呆（4 位數字/一致）。登出可用。
- 月結/店別顯示佔位卡。
- **桌機回歸**：關掉裝置模擬（pointer:fine）重登 `/dev/login-super`，確認走**桌面側邊欄工作台**（`showAdminPanel`）完全照舊。
- 無 console error；`node --test tests/js/*.mjs`（71 passed）；`python3 -m pytest -q`（567，後端未動）。
> 主管/員工回歸：`/dev/login-manager`（裝置模擬）走 `showManagerApp` 照舊、`/dev/login-test` 員工照舊——本 task 只改 super_admin 分支。

- [ ] **Step 5: bump sw(`calc-v77`) + commit**
```bash
# sw.js: const CACHE_NAME = 'calc-v77';　STATIC_URLS 補一行 '/static/js/super_app.js',
git add app/static/js/super_app.js app/static/js/auth.js app/static/js/main.js \
  app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 經理手機殼 + pointer 路由 + 選店抬頭 + 重用 pane + 我的密碼"
```

---

## Task 2: 月結 pane（原生月結設定唯讀卡 + 重用 `renderMonthReport` 交叉表）

把 Task 1 的 `renderMonthPane` 佔位換成真作：原生「月結設定唯讀卡」（🔒，資料同 `admin.js:renderClosing` 的 periods）＋範圍標籤＋`renderMonthReport`（門市由抬頭選店 `state.storeId` 鎖定）。

**Files:**
- Modify: `app/static/js/super_app.js`（頂部補 import；`renderMonthPane` 真作）
- Modify: `app/static/css/app.css`（手機段落 append 月結卡 `.mb-month-*`/`.mb-closing-card`/`.mb-ro-*`/`.mb-kv`/`.mb-badge*`）
- Modify: `app/static/sw.js`（`calc-v78`；STATIC_URLS 補 `month_report.js`、`reports_api.js`）

**Interfaces:**
- Consumes: `renderMonthReport(container, { storeId, lockStore })`(month_report.js)、`periodsApi.getSettings()`/`periodsApi.list()`(periods_api.js)、Task 1 殼閉包 `state`/`escapeHtml`、既有 `.mb-admin-embed`。
- Produces: `renderMonthPane(el)` 真作（殼閉包內，覆寫 Task 1 佔位）。

- [ ] **Step 1: 月結卡 CSS（照原型 .ro-card / .kv / .badge）**

`app.css` 手機段落 append，值照原型 `super-mobile.html` `.ro-card`/`.ro-head`/`.ro-lock`/`.kv`/`.badge`（加 `mb-` 前綴、`var(--x)`→`var(--wk-x)`）：
```css
.mb-month-head{ display:flex; align-items:baseline; gap:8px; padding:2px 4px 10px; }
.mb-month-head h2{ margin:0; font-size:17px; }
.mb-badge{ font-size:11.5px; font-weight:700; padding:2px 8px; border-radius:999px;
  background:var(--wk-surface-2); color:var(--wk-muted); }
.mb-badge-open{ background:var(--wk-warn-soft); color:var(--wk-warn-ink); }
.mb-closing-card{ background:var(--wk-surface); border:1px solid var(--wk-line); border-radius:var(--wk-radius);
  box-shadow:var(--mb-shadow,0 1px 2px rgba(28,39,51,.08)); padding:13px 14px; margin-bottom:14px; }
.mb-ro-head{ display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }
.mb-ro-head h3{ margin:0; font-size:14.5px; }
.mb-ro-lock{ font-size:12px; font-weight:600; color:var(--wk-muted); }
.mb-kv{ display:flex; justify-content:space-between; padding:6px 0; border-top:1px solid var(--wk-line-soft); font-size:13.5px; }
.mb-kv .k{ color:var(--wk-muted); } .mb-kv .v{ color:var(--wk-ink); font-weight:600; font-variant-numeric:tabular-nums; }
.mb-month-scope{ font-size:12.5px; color:var(--wk-faint); font-weight:600; padding:0 2px 8px; }
```

- [ ] **Step 2: `renderMonthPane` 真作 + import**

`super_app.js` 頂部 import 區補：
```js
import { renderMonthReport } from './month_report.js';
import { periodsApi } from './periods_api.js';
```
把 Task 1 的佔位 `renderMonthPane` 換成（仍在 `showSuperApp` 閉包內，可讀 `state`）：
```js
async function renderMonthPane(el) {
  el.innerHTML = `
    <div class="mb-month-head" id="mb-month-head"><h2>本期</h2></div>
    <div class="mb-closing-card" id="mb-closing"><div class="mb-empty-state" style="display:block">載入中…</div></div>
    <div class="mb-month-scope" id="mb-month-scope"></div>
    <div class="mb-admin-embed" id="mb-report-wrap"></div>`;
  // 月結設定唯讀卡（資料同 admin.js renderClosing：getSettings + list[0]=當期）
  try {
    const [{ status: s1, data: st }, { status: s2, data: pl }] =
      await Promise.all([periodsApi.getSettings(), periodsApi.list()]);
    const head = el.querySelector('#mb-month-head');
    const box = el.querySelector('#mb-closing');
    if (s1 === 200 && st.status === 'ok' && s2 === 200 && pl.status === 'ok') {
      const cur = (pl.periods || [])[0] || null;
      const stLabel = { open: '進行中', closing: '寬限期', closed: '已封月' }[cur && cur.status] || (cur ? cur.status : '');
      head.innerHTML = `<h2>${cur ? escapeHtml(cur.label) : '本期'}</h2>${cur ? `<span class="mb-badge mb-badge-open">${escapeHtml(stLabel)}</span>` : ''}`;
      box.innerHTML = `
        <div class="mb-ro-head"><h3>月結設定</h3><span class="mb-ro-lock">🔒 唯讀（僅會計可改）</span></div>
        <div class="mb-kv"><span class="k">月結日</span><span class="v">每月 ${escapeHtml(String(st.period_close_day))} 日</span></div>
        <div class="mb-kv"><span class="k">鎖定偏移</span><span class="v">封月後 ${escapeHtml(String(st.period_lock_offset_hours))} 小時</span></div>
        <div class="mb-kv"><span class="k">營業日分界</span><span class="v">08:00（台灣時間）</span></div>`;
    } else {
      box.innerHTML = '<div class="mb-empty-state" style="display:block">月結設定載入失敗</div>';
    }
  } catch { el.querySelector('#mb-closing').innerHTML = '<div class="mb-empty-state" style="display:block">月結設定載入失敗</div>'; }
  // 範圍標籤 + 月報表交叉表（重用 renderMonthReport，門市由抬頭選店鎖定）
  const scope = el.querySelector('#mb-month-scope');
  scope.textContent = state.storeId == null
    ? '月報表：全部門市（左右滑動看各店欄位）'
    : `月報表：門市 ${(state.stores.find((s) => s.id === state.storeId) || {}).code || ''}`;
  renderMonthReport(el.querySelector('#mb-report-wrap'),
    { storeId: state.storeId != null ? String(state.storeId) : '', lockStore: true });
}
```
> `renderMonthReport` 產 `.table-wrap > table.wk-xt`（科目 sticky 首欄，已在 app.css 定義）；套 `.mb-admin-embed` 讓它在手機殼內可橫捲。抬頭選店改變 → 殼的 change handler 呼叫 `renderPane('month')` → 重繪整個月結 pane（含交叉表切全部/單店）。

- [ ] **Step 3: 驗證（對照原型 5.4 月結）**

`/dev/login-super`（裝置模擬）→ 月結：期別標頭（後端當期 label＋狀態徽章）、月結設定唯讀卡（🔒＋月結日/鎖定偏移/營業日分界，數字對得上桌面工作台月結分頁）、範圍標籤。抬頭選「全部門市」→ 交叉表（科目 sticky 首欄、各店欄＋總計、可橫捲、大類可展開子分類、負數紅字）；選單店 → 收成兩欄（科目｜金額）。切店即時重繪。`node --test`（71）+ `pytest -q`（567）全綠。

- [ ] **Step 4: bump sw(`calc-v78`) + commit**
```bash
# sw.js: calc-v78；STATIC_URLS 補 '/static/js/month_report.js', '/static/js/reports_api.js',
git add app/static/js/super_app.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 經理手機 月結 pane（月結設定唯讀卡 + 重用月報表交叉表）"
```

---

## Task 3: 店別管理 pane（原生卡：顯示 toggle + 對外連結 kill-switch + 新增店）+ 整合收尾

新建 `super_stores_mobile.js` 原生店別卡，接進殼，補齊 sw STATIC_URLS，整合回歸。

**Files:**
- Create: `app/static/js/super_stores_mobile.js`
- Modify: `app/static/js/super_app.js`（頂部補 import；`renderStoresPaneWrap` 真作）
- Modify: `app/static/css/app.css`（手機段落 append 店別卡 `.mb-store-*`）
- Modify: `app/static/sw.js`（`calc-v79`；STATIC_URLS 補 `super_stores_mobile.js`）

**Interfaces:**
- Consumes: `escapeHtml`(admin_util.js)、`api`(admin_api.js：`getStores`/`setStoreViewable`/`setStoreActive`/`createStore`)、`mbToast`(mb_util.js)、既有 `.mb-pane-title`/`.mb-pw-btn`/`.mb-au-err`/`.mb-empty-state`。
- Produces: `export async function renderStoresPane(container, { onChanged })`——`onChanged` 於顯示切換/新增店後呼叫（殼傳 `refreshStores` 刷新抬頭選店）。

- [ ] **Step 1: 店別卡 CSS（照原型 .store-card 家族）**

`app.css` 手機段落 append，值照原型 `super-mobile.html` `.store-card`/`.sc-top`/`.sc-code`/`.sc-conn`/`.sc-toggle`/`.sc-kill`/`.add-box`（加 `mb-` 前綴、`var(--x)`→`var(--wk-x)`）：
```css
.mb-store-hint{ font-size:12.5px; line-height:1.6; color:var(--wk-muted); background:var(--wk-surface-2);
  border:1px solid var(--wk-line); border-radius:var(--wk-radius); padding:10px 12px; margin:0 0 14px; }
.mb-store-card{ background:var(--wk-surface); border:1px solid var(--wk-line); border-radius:var(--wk-radius);
  box-shadow:var(--mb-shadow,0 1px 2px rgba(28,39,51,.08)); padding:13px 14px; margin-bottom:12px;
  display:flex; flex-direction:column; gap:11px; }
.mb-store-top{ display:flex; align-items:center; gap:10px; }
.mb-store-code{ font-weight:800; font-size:16px; letter-spacing:.5px; }
.mb-store-conn{ margin-left:auto; font-size:11.5px; font-weight:700; padding:2px 9px; border-radius:999px; }
.mb-store-conn.on{ background:var(--wk-ok-soft); color:var(--wk-ok-ink); }
.mb-store-conn.off{ background:var(--wk-bad-soft); color:var(--wk-bad-ink); }
.mb-store-toggle{ display:flex; gap:9px; align-items:flex-start; font-size:13.5px; color:var(--wk-ink); }
.mb-store-toggle input{ width:20px; height:20px; margin-top:1px; flex:none; accent-color:var(--wk-accent); }
.mb-store-kill{ min-height:44px; border-radius:var(--wk-radius-sm); border:1px solid color-mix(in srgb, var(--wk-bad) 32%, transparent);
  background:var(--wk-bad-soft); color:var(--wk-bad-ink); font-weight:700; font-size:13.5px; }
.mb-store-kill.is-off{ border-color:color-mix(in srgb, var(--wk-ok) 32%, transparent);
  background:var(--wk-ok-soft); color:var(--wk-ok-ink); }
.mb-store-add{ background:var(--wk-surface); border:1px dashed var(--wk-line); border-radius:var(--wk-radius);
  padding:13px 14px; margin-top:4px; }
.mb-store-add h3{ margin:0 0 10px; font-size:14px; }
.mb-store-add input{ width:100%; min-height:44px; border:1px solid var(--wk-line); border-radius:var(--wk-radius-sm);
  background:var(--wk-surface-2); padding:0 12px; font-size:15px; color:var(--wk-ink); margin-bottom:10px;
  text-transform:uppercase; }
```

- [ ] **Step 2: 寫 `super_stores_mobile.js`**

新建 `app/static/js/super_stores_mobile.js`：
```js
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
```
> kill-switch **關閉走 `window.confirm`**（對齊 spec §4「關閉走確認」；桌面用 `wkConfirm` modal，手機用原生 confirm 即可，避免多拉一個 modal 相依）。顯示 toggle 失敗時把 checkbox 打回原狀。`createStore(raw, raw)` 與桌面 `renderStores` 一致（name=code=代號）。

- [ ] **Step 3: 接進殼 + 補 STATIC_URLS**

`super_app.js` 頂部 import 區補：
```js
import { renderStoresPane } from './super_stores_mobile.js';
```
把 Task 1 的佔位 `renderStoresPaneWrap` 換成：
```js
function renderStoresPaneWrap(el) {
  renderStoresPane(el, { onChanged: refreshStores });   // 顯示切換/新增店後刷新抬頭選店
}
```
> `onChanged: refreshStores`——顯示 toggle 或新增店會影響抬頭選店選單（可見店清單），刷新它。

- [ ] **Step 4: 驗證（對照原型 5.4 店別）**

`/dev/login-super`（裝置模擬）→ 店別：說明卡 + 各店卡片（店 code、對外狀態徽章、顯示 toggle、kill-switch 鈕）。
- 勾/取消「顯示於選單／月報表」→ toast + 抬頭選店選單即時增減該店（取消後該店從選店消失）。
- 點「停止對外連結」→ **confirm** 後徽章轉「已停止對外」、鈕變「恢復對外連結」（綠）；再點恢復。
- 新增店：輸入 1–2 字母 → toast + 出現新卡 + 抬頭選店多一項；非法輸入顯示錯誤。
- **無刪店按鈕**。`node --test`（71）+ `pytest -q`（567）全綠。

- [ ] **Step 5: 整合回歸（對照原型 + spec §5.4）**

`/dev/login-super`（裝置模擬）走完：稽核唯讀（選店/空狀態/唯讀表/返回）→ 月結（月結卡/交叉表全部+單店/切店）→ 店別（toggle/kill-switch/新增）→ 帳號/裝置/操作記錄（重用可用）→ 我的密碼（改密碼防呆+toast）。全程對照原型視覺、深/淺主題、無 console error、時間台灣時間、店別英文代號、負數紅字、單欄滿版、主分頁橫捲不藏。
- **桌機回歸**：pointer:fine 開 `/dev/login-super` 仍走 `showAdminPanel` 桌面工作台照舊。
- **主管/員工回歸**：`/dev/login-manager`（模擬）走 `showManagerApp`、`/dev/login-test` 員工照舊。

- [ ] **Step 6: bump sw(`calc-v79`) + commit**
```bash
# sw.js: calc-v79；STATIC_URLS 補 '/static/js/super_stores_mobile.js',
git add app/static/js/super_stores_mobile.js app/static/js/super_app.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 經理手機 店別管理原生卡（顯示/kill-switch/新增）+ 整合收尾"
```

---

## Self-Review（對照 spec §5.4 + 原型）

**Spec coverage**：登入依 pointer:coarse 路由（Task1 §2.1）✔ / 抬頭跨店選店同時驅動稽核+月報表（Task1，`#ap-store`）✔ / 主分頁 稽核·月結·店別·帳號·裝置·操作記錄·我的密碼（Task1 殼）✔ / 稽核唯讀重用（Task1，renderAudit isSuper）✔ / 月結設定唯讀卡🔒 + 月報表交叉表重用（Task2）✔ / 店別管理：顯示 toggle + kill-switch + 新增、不接刪店（Task3）✔ / 帳號·裝置·操作記錄重用（Task1）✔ / 我的密碼自寫（Task1）✔ / 深淺主題 token 沿用（各 task 引 `--wk-*`）✔ / 店別英文代號·時間台灣·負數紅字·單欄滿版·主分頁橫捲（Global Constraints）✔ / 桌面工作台不動（Task1 保留 showAdminPanel）✔ / bump sw + 補預快取（每 task）✔。

**Placeholder scan**：無 TBD/TODO；每 code 步驟有完整程式碼；佔位（Task1 renderMonthPane/renderStoresPaneWrap）明標 Task2/3 換真作且給了真作全碼。**外部相依/待確認**（實作時對齊，非 placeholder）：(a) periods 欄位 `period_close_day`/`period_lock_offset_hours`/`periods[0].{label,status}`——逐字取自 `admin.js:renderClosing`（現行桌面就這樣讀）；(b) `createStore` 成功碼——桌面 `renderStores` 判 status 200/201，本 plan 同；(c) dev 經理若無店，先於店別管理新增（Task3 Step4 已註）。

**Type consistency**：`showSuperApp(identity)` / `renderMonthPane(el)` / `renderStoresPaneWrap(el)` / `renderStoresPane(container,{onChanged})` / `ctx()`→`{identity,storeId,stores,api,reload,refreshStores}` 跨 Task 一致；沿用既有 `renderAudit(container,identity,storeId,stores)`／`renderAccounts/Devices(container,ctx)`／`renderLogs(container,identity,storeId)`／`renderMonthReport(container,{storeId,lockStore})`／`periodsApi.getSettings()`/`list()`／`api.setStoreViewable/setStoreActive/createStore/changeMyPassword` 全不改。抬頭選店 id `ap-store` 與 `pickStore()`（admin_audit.js:36-40）契約一致。

---

## 風險 / 注意

- **不動後端是鐵律**：全程只呼叫既有 API。code review 確認沒新增/改任何 `.py`。
- **`#ap-store` id 共用**：手機殼抬頭選店與桌面工作台選店同 id（不同時存在同頁，各自的殼獨立）——這是讓 `renderAudit` 唯讀分支 `pickStore()` 零改重用的關鍵；勿改名。
- **月報表交叉表重用**：`renderMonthReport` 會計/經理桌機/經理手機三處共用；本 plan 不改它，只在手機殼用 `.mb-admin-embed` 收橫捲。改它前確認三處都受影響。
- **舊碼不刪**：經理改走 `showSuperApp`（觸控裝置）後，`showAdminPanel` 桌機續用；本 plan 不刪 `admin.js` 任何分支。
- **PWA 快取**：每 task bump sw；本 plan 補 `super_app.js`/`month_report.js`/`reports_api.js`/`super_stores_mobile.js`。上線一次 bump 到最終版。
- **路由判一次**：登入後不因 resize/rotate 重路由（spec 定案）；桌機拉窄由 `showAdminPanel` 自身 `@media(max-width:900px)` fallback 頂著。
- **測試盲區**：手機 render 層無 DOM 單元測（靠後端 API 測 + 本機目視）；純函式維持行為、每 task 重跑 node 測。
