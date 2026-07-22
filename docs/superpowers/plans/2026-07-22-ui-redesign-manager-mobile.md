# 主管手機 App UI 重塑 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把主管（manager）端從現行「與經理共用的桌面側邊欄工作台（`showAdminPanel`，`admin.js`）」重塑成原型 `manager-audit.html` 的「常駐手機殼（抬頭＋可橫捲主分頁＋內容 pane＋常駐底部 action bar）＋單欄卡片稽核」，主管登入一律走新手機殼。

**Architecture:** 純前端／CSS／DOM 重塑，**不動後端、不改 API、不改任務流、不碰計算機幌子、角色守門全沿用現況**。新增手機殼 `manager_app.js`（`showManagerApp`），沿用員工端已建的 `.mb-*` 手機設計層（把 `mbToast`/`stopPaneCamera` 抽到共用 `mb_util.js`），新增主管專屬 `.mb-*` 元件（可橫捲主分頁／segmented 子分頁／稽核卡／常駐 action bar／唯讀班別卡／佔位卡）。稽核（待稽核可編輯打勾＋總表唯讀＋交班/結班/取消）全部**沿用 `admin_api.js` 既有 audit 端點與 `admin_audit.js` 的資料流邏輯**，只把 render 從桌面 `.wk-audit-table` 換成手機 `.mb-*` 卡片。帳號/裝置/操作記錄 pane **直接重用現有 `renderAccounts`/`renderDevices`/`renderLogs`**（主管現有可操作權限完全保留），套一層 `.mb-admin-embed` 讓桌面元件在手機殼內可用。我的密碼 pane 自寫小表單（`api.changeMyPassword`）。**經理（super_admin）不動**：仍走 `showAdminPanel`（經理電腦版），其手機版是後續獨立 plan（super-mobile）。視覺 SoT = `docs/superpowers/ui-prototypes/manager-audit.html`。

**Tech Stack:** Vanilla ES module（無框架）、單一 `app/static/css/app.css`、Flask 模板、PWA service worker（`sw.js` 快取靜態清單）。

## 前端驗證策略（本 plan 對 TDD 的 adaptation）

沿用員工手機／經理電腦版 plan 同一套（DOM／CSS 重塑非後端邏輯，故驗證分軌）：
- **純函式改動** → `node --test tests/js/*.mjs`（既有前端純邏輯測）。本 plan **不動任何純函式**（`formatMoney`/`formatDateTimeTW`/`parseAmountInput`/`lightLabel`/`categoryOptionsHtml`/`status_label` 維持行為）；每個 task 結尾**重跑既有 node 測確認全綠（71 passed 基準）**。
- **後端未動** → 每個 task 結尾跑 `python3 -m pytest -q` 確認 **567 passed** 沒被誤傷（本 plan 不改後端，僅防呆）。
- **DOM／CSS 重塑** → 本機開 server + dev 登入主管，**對照原型 URL 逐項目視檢**（結構/class/視覺/互動）。

**本機啟動（harness `run_in_background: true`，勿用 shell `&`／nohup）：**
```
cd ~/project/report; set -a; . ./.env 2>/dev/null; set +a; export E2E_LOGIN_BYPASS=1 FLASK_APP=wsgi.py SECRET_KEY=${SECRET_KEY:-dev}; .venv/bin/python -m flask db upgrade; .venv/bin/python -m flask run --port 5001 --no-reload
```
- **主管面板入口**：`http://127.0.0.1:5001/dev/login-manager`（dev 捷徑，繞過計算機+裝置閘，建/登入測試主管）。
- 對照原型：本機直接開檔 `docs/superpowers/ui-prototypes/manager-audit.html`。
- ⚠️ dev.db 資料可能很少；驗證待稽核/總表時若無單，先用 `/dev/login-test`（員工）拍幾筆或 `/dev/sample-receipt` 樣本圖建單，再回主管稽核。
- 改前端後：瀏覽器**硬重整**（避 sw 快取）；每個 task 最後 bump `sw.js` CACHE_NAME（現 `calc-v68` → 本 plan 依序 `calc-v69`…`calc-v73`）並**補新檔進 STATIC_URLS 預快取清單**。

---

## Global Constraints

以下每個 task 都隱含適用（值逐字取自 spec `docs/superpowers/specs/2026-07-17-ui-redesign-design.md` §5.3 與原型 `manager-audit.html`）：

- **不碰計算機幌子**（`calculator.js`/`secret.js`），不改後端/API/任務流；**角色守門全沿用現況**（稽核＝manager+super_admin；帳號/裝置/操作記錄＝manager+super_admin；改密碼＝本人）。主管永遠鎖本店（稽核 API 一律傳 `sid=undefined`，後端用本店），**無選店、無跨店**。
- **設計 token 沿用既有 `--wk-*`**（app.css 已定義 light/dark 三段）；員工手機已建 `.mb-*` 段落與 `--mb-*` 變數。本 plan **不重定義 token**，主管專屬 `.mb-*` 元件一律引用 `var(--wk-x)`／既有 `--mb-*`。
- **店別英文代號**（`s.code`，≤2 字母），**絕不露中文店名**。主管抬頭店徽用「本店 code」（由 `identity.store_id` 對 `getStores` 結果查表得 code；查不到就不顯示店徽，不造假）。
- **時間台灣時間**（`formatDateTimeTW` from `audit_util.js`）；營業日 08:00 分界。**不得照搬原型的假班別/假日期**——只顯示後端實際回傳欄位。
- **負數金額紅字**（`.num.neg` / `.mb-amt.neg`，U+2212 減號由 `formatMoney` 產出），金額 `tabular-nums`。
- **卡片列表一律單欄滿版**（一列一張，不分兩欄；平板/寬視窗亦單欄，照原型 `@media(min-width:768px){.cards{grid-template-columns:1fr}}`）。
- **可橫捲主分頁不可藏**（原型 `.tabs{overflow-x:auto}`；分頁多於視窗寬時橫捲，別 `display:none` 藏任何分頁）。
- **收據縮圖用真 `<img> thumb_url`**（既有 `.au-thumb data-zoom`），點開走既有 `openImageLightbox`（lightbox.js，手機縮放已支援）。無縮圖用 placeholder（—）。
- **CSS 組織**：`app.css` 單檔分區（新增「手機設計層－主管稽核 `.mb-au-*`」段落，清楚註解），沿用員工段落的 `.mb-app`/`.mb-appbar`/`.mb-content`/`.mb-pane`/`.mb-toast` 等基底；舊 `.wk-audit-*`/`.au-*` 段落**保留不動**（經理桌面版仍用）。
- **每次改 css/js → bump `sw.js` CACHE_NAME + 補新檔進 `STATIC_URLS`**（現 `calc-v68`；⚠️ 現行 STATIC_URLS **未含**任何 `admin*.js`/`periods_api.js`——主管手機用得到的檔要在 Task 5 補齊）。

---

## File Structure

| 檔案 | 動作 | 責任 |
|---|---|---|
| `app/static/js/mb_util.js` | **Create** | 手機殼共用小工具：`mbToast(msg)`、`stopPaneCamera(container)`、`postJSON(url,body)`。從 `employee_app.js` 抽出，員工/主管共用。 |
| `app/static/js/employee_app.js` | Modify（去重） | 移除本地 `mbToast`/`stopPaneCamera`/`postJSON` 定義，改 `import`＋`export` 轉出自 `mb_util.js`（保持 `import { mbToast } from './employee_app.js'` 的既有下游不破）。 |
| `app/static/js/manager_app.js` | **Create** | 主管手機殼 `showManagerApp(identity)`：抬頭（店徽/姓名·主管/我的密碼/登出）＋可橫捲主分頁（稽核/操作記錄/帳號/裝置/我的密碼）＋內容 pane 容器＋常駐底部 action bar（僅稽核顯示）＋toast。組 `ctx()` 供帳號/裝置重用。 |
| `app/static/js/manager_audit_mobile.js` | **Create** | 主管稽核手機版 render：`renderAuditPane(container, { onSubtotalChange })`（子分頁 待稽核/總表）＋`wireActionBar(barEl, { onSubtotalChange })`。沿用 `admin_api.js` audit 端點與 `admin_audit.js` 同一資料流，DOM 換 `.mb-au-*` 卡片。 |
| `app/static/js/auth.js` | Modify（2 行） | 密碼登入成功分派：`manager` → `showManagerApp(identity)`（原 `showAdminPanel`）。`super_admin` 維持 `showAdminPanel`。 |
| `app/static/js/main.js` | Modify（2 行） | 暗號 re-entry 分派：`manager` → `showManagerApp(identity)`。`super_admin` 維持 `showAdminPanel`。 |
| `app/static/css/app.css` | Modify（append「手機設計層－主管稽核」段落） | 新增 `.mb-toptabs`/`.mb-toptab`、`.mb-subtabs`/`.mb-subtab`、`.mb-au-card`/`.mb-au-fields`/`.mb-au-check`/`.mb-au-flag`/`.mb-au-edit`/`.mb-au-hist*`、`.mb-actionbar`/`.mb-ab-*`、`.mb-ro-card`/`.mb-ro-*`（總表）、`.mb-day-head`/`.mb-overdue`、`.mb-ph-card`/`.mb-log-line`/`.mb-form-field`/`.mb-admin-embed`。舊段落不動。 |
| `app/static/sw.js` | Modify（每 task） | bump CACHE_NAME；Task 5 補齊 STATIC_URLS（manager_app/manager_audit_mobile/mb_util/admin_api/admin_audit/admin_accounts/admin_devices/admin_logs/periods_api）。 |

**Task 邊界原則**：每個 task 是「一個可對照原型獨立目視驗收的交付」。`.mb-au-*` CSS 折入第一個需要它的 task。**先做殼＋抽共用（Task 1）打底，之後各 pane 逐一實作。**

---

## Task 1: 抽共用 `mb_util.js` + 主管手機殼 + 可橫捲主分頁 + 抬頭 + action bar 殼 + 路由

抽出 `mb_util.js` 共用工具，新建 `manager_app.js` 常駐手機殼，路由主管進來，建立主管 `.mb-*` CSS 地基。此 task 後 5 個 pane 內容為空（Task 2/3/4/5 填），但殼／主分頁橫捲切換／抬頭（我的密碼捷徑、登出）／action bar 顯隱（僅稽核）可動。

**Files:**
- Create: `app/static/js/mb_util.js`
- Modify: `app/static/js/employee_app.js`（移除本地 `mbToast`/`stopPaneCamera`/`postJSON`，改 re-export）
- Create: `app/static/js/manager_app.js`
- Modify: `app/static/js/auth.js`（`submit()` 分派）、`app/static/js/main.js`（re-entry 分派）
- Modify: `app/static/css/app.css`（append「手機設計層－主管稽核」段落起頭：主分頁/子分頁/pane 標題/action bar 殼/佔位）
- Modify: `app/static/sw.js`（CACHE_NAME → `calc-v69`）

**Interfaces:**
- Consumes: `escapeHtml`(admin_util.js)、`api`(admin_api.js，取 `getStores` 查本店 code)、既有 `.mb-app`/`.mb-appbar`/`.mb-content`/`.mb-pane`/`.mb-toast`/`.mb-store-badge`/`.mb-icon-btn` CSS（員工段落已建）。
- Produces:
  - `mb_util.js`：`export function mbToast(msg)`、`export function stopPaneCamera(container)`、`export async function postJSON(url, body)`。
  - `employee_app.js`：續 `export { mbToast, stopPaneCamera, postJSON } from './mb_util.js'`（下游 `capture.js`/`pending.js` 的 `import { mbToast } from './employee_app.js'` 不破）。
  - `manager_app.js`：`export function showManagerApp(identity)`。殼 DOM 契約供 Task 2-5 —— pane 容器 id `#mb-pane-audit`/`#mb-pane-logs`/`#mb-pane-accounts`/`#mb-pane-devices`/`#mb-pane-mypw`；主分頁 `.mb-toptab[data-tab]`；action bar 容器 `#mb-actionbar`（僅 `audit` tab 顯示）；`showTab(name)`；`ctx()` 回 `{ identity, storeId:null, stores, api, reload, refreshStores }`。新 CSS class：`.mb-toptabs`/`.mb-toptab`(+`.active`)/`.mb-actionbar`(+`[hidden]`)/`.mb-ph-card`（佔位用）。

- [ ] **Step 1: 建 `mb_util.js`（從 employee_app.js 原樣搬三個工具）**

新建 `app/static/js/mb_util.js`，內容＝把 `employee_app.js` 現有的 `mbToast`（:22-31）、`stopPaneCamera`（:33-43）、`postJSON`（:13-20）逐字搬出並 export：
```js
// 手機殼共用小工具（員工/主管手機殼共用）。原定義於 employee_app.js，抽出去重。
let toastTimer = null;
export function mbToast(msg) {
  const el = document.getElementById('mb-toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2200);
}

// 切走 pane 前停止該 pane 容器內任何 live 相機串流（影像不落地）。
export function stopPaneCamera(container) {
  if (!container) return;
  container.querySelectorAll('video').forEach((v) => {
    if (v.srcObject) {
      v.srcObject.getTracks().forEach((t) => t.stop());
      v.srcObject = null;
    }
  });
}

export async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  return { status: res.status, data: await res.json().catch(() => ({})) };
}
```

- [ ] **Step 2: `employee_app.js` 去重、改 re-export（不破下游）**

`employee_app.js`：
- 刪除本地 `postJSON`（:13-20）、`mbToast`＋`toastTimer`（:22-31）、`stopPaneCamera`（:33-43）三段定義。
- 頂部 import 區（:5-9 之後）加：
```js
import { mbToast, stopPaneCamera, postJSON } from './mb_util.js';
export { mbToast, stopPaneCamera };   // 保留對外名稱：capture.js/pending.js 仍 `import { mbToast } from './employee_app.js'`
```
> `postJSON` 員工端內部仍用（`wireReface`/登出），import 進來即可，不需 re-export。改完 `employee_app.js` 行為完全不變（同名函式、同實作，只是移到共用檔）。

- [ ] **Step 3: 主管手機殼 CSS 進 app.css（主分頁/子分頁/action bar 殼/佔位）**

`app.css` 末尾 append，用註解分區。值取自原型 `manager-audit.html` `<style>`，class 加 `mb-` 前綴、`var(--x)`→`var(--wk-x)`（`--r`→`--wk-radius`、`--rs`→`--wk-radius-sm`）：
```css
/* ============================================================
   手機設計層－主管稽核（UI 重塑 2026-07；manager 手機/平板）
   沿用員工手機段落的 .mb-app/.mb-appbar/.mb-content/.mb-pane/.mb-toast 基底。
   本段新增主管專屬：可橫捲主分頁 / segmented 子分頁 / 稽核卡 / 常駐 action bar /
   唯讀班別卡 / 佔位卡。視覺 SoT: docs/superpowers/ui-prototypes/manager-audit.html
   ============================================================ */
/* 可橫捲主分頁（原型 .tabs/.tab；置於 .mb-appbar 下方） */
.mb-toptabs{ flex:none; display:flex; gap:2px; padding:0 8px; background:var(--wk-surface);
  border-bottom:1px solid var(--wk-line); overflow-x:auto; scrollbar-width:none; -webkit-overflow-scrolling:touch; }
.mb-toptabs::-webkit-scrollbar{ display:none; }
.mb-toptab{ flex:none; min-height:46px; padding:0 14px; border:0; background:none;
  color:var(--wk-muted); font-weight:600; font-size:14.5px; white-space:nowrap;
  border-bottom:2.5px solid transparent; margin-bottom:-1px; }
.mb-toptab.active{ color:var(--wk-accent-ink); border-bottom-color:var(--wk-accent); }
/* segmented 子分頁（原型 .subtabs/.subtab；稽核用 待稽核/總表） */
.mb-subtabs{ display:flex; gap:4px; padding:4px; margin-bottom:12px;
  background:var(--wk-surface-2); border:1px solid var(--wk-line); border-radius:var(--wk-radius); }
.mb-subtab{ flex:1; min-height:40px; border:0; border-radius:var(--wk-radius-sm); background:none;
  font-weight:600; font-size:14px; color:var(--wk-muted); }
.mb-subtab.active{ background:var(--wk-surface); color:var(--wk-accent-ink); box-shadow:var(--mb-shadow,0 1px 2px rgba(28,39,51,.08)); }
/* 常駐底部 action bar（原型 .actionbar/.ab-*；僅稽核分頁顯示） */
.mb-actionbar{ flex:none; background:var(--wk-surface); border-top:1px solid var(--wk-line);
  padding:9px 12px calc(10px + env(safe-area-inset-bottom,0px)); box-shadow:0 -4px 16px rgba(20,30,45,.08); }
.mb-actionbar[hidden]{ display:none; }
.mb-ab-sub{ display:flex; justify-content:space-between; align-items:baseline;
  font-size:12.5px; color:var(--wk-muted); padding:0 2px 8px; }
.mb-ab-sub b{ font-size:15px; color:var(--wk-ink); font-variant-numeric:tabular-nums; }
.mb-ab-btns{ display:flex; gap:8px; }
.mb-ab-btn{ flex:1; min-height:46px; border-radius:var(--wk-radius-sm); border:1px solid transparent;
  font-weight:700; font-size:14.5px; }
.mb-ab-primary{ background:var(--wk-accent); color:#fff; border-color:var(--wk-accent); }
.mb-ab-secondary{ background:var(--wk-accent-soft); color:var(--wk-accent-ink);
  border-color:color-mix(in srgb, var(--wk-accent) 30%, transparent); }
.mb-ab-err{ display:block; font-size:12px; color:var(--wk-bad); padding:6px 2px 0; min-height:1em; }
/* 佔位卡（Task 5 前，帳號/裝置/操作記錄/我的密碼 pane 暫時空殼用） */
.mb-ph-card{ background:var(--wk-surface); border:1px solid var(--wk-line); border-radius:var(--wk-radius);
  box-shadow:var(--mb-shadow,0 1px 2px rgba(28,39,51,.08)); padding:14px; margin-bottom:12px; }
.mb-ph-card h3{ margin:0 0 10px; font-size:14.5px; }
```
> 稽核卡／唯讀卡／佔位 log-line／表單／embed 等 CSS 於 Task 2/3/4/5 各自 append（折入需要它的 task）。

- [ ] **Step 4: 寫 `manager_app.js` 殼**

新建 `app/static/js/manager_app.js`：
```js
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
    wireActionBar(actionbar, { onSubtotalChange: paintSubtotal }); // Task 2 提供；Task 1 若尚未有可先 no-op
  });
}
```
> ⚠️ Task 1 尚無 `manager_audit_mobile.js`（Task 2/3 建）。為讓 Task 1 殼可獨立驗收，**Task 1 先建 `manager_audit_mobile.js` 的 stub**：`export function renderAuditPane(container){ container.innerHTML = '<div class="mb-ph-card"><h3>稽核（待實作）</h3></div>'; }` 與 `export function wireActionBar(){}`。Task 2/3 再填真內容。`renderLogs`/`renderAccounts`/`renderDevices` 已存在（import 得到），Task 4 前直接呼叫它們會 render 桌面樣式進 pane——**Task 1 驗收時只點稽核 tab**（其餘 tab 先不點，或接受暫時桌面樣式）；正式 mb 化在 Task 4。

- [ ] **Step 5: 路由主管進新殼（auth.js / main.js）**

- `auth.js`：頂部加 `import { showManagerApp } from './manager_app.js';`。`submit()` 內 role 分派（現 `manager`/`super_admin` 都 `showAdminPanel(identity)`，auth.js:125）改成：`manager` → `showManagerApp(identity)`；`super_admin` 維持 `showAdminPanel(identity)`。
```js
else if (data.role === 'super_admin') showAdminPanel(identity);
else if (data.role === 'manager') showManagerApp(identity);
```
- `main.js`：re-entry 分派（main.js:167）同樣拆分：`super_admin` → `showAdminPanel`；`manager` → `showManagerApp`。頂部補 `import { showManagerApp } from './manager_app.js';`。
> `showAdminPanel` **保留不動**（經理續用）。主管不再走它。

- [ ] **Step 6: 本機驗證殼**

開 server，硬重整 `/dev/login-manager`。對照原型 `manager-audit.html`：
- 滿版手機殼、抬頭（店徽[本店 code，若 dev 主管有綁店]＋姓名＋主管＋🔑我的密碼＋⎋登出）。
- 主分頁列可橫捲：稽核/操作記錄/帳號/裝置/我的密碼，點擊切換、active 底線在 accent。
- 底部 action bar 僅「稽核」分頁顯示（交班/結班/取消 + 小計 $0/0 筆），切到別的分頁隱藏。
- 稽核 pane 顯示 stub 佔位卡；🔑 可跳到我的密碼 pane（佔位）。登出可用。
- 無 console error；`node --test tests/js/*.mjs` 全綠（71 passed）；`python3 -m pytest -q` 全綠（567，後端未動）。
> 員工端回歸：另開 `/dev/login-test`，確認員工手機（拍單/確認/複查/toast/更新人臉/登出）完全照舊——`mbToast` 抽檔後行為不變。

- [ ] **Step 7: bump sw(`calc-v69`) + commit**
```bash
# sw.js: const CACHE_NAME = 'calc-v69';（STATIC_URLS 待 Task 5 統一補齊）
git add app/static/js/mb_util.js app/static/js/employee_app.js app/static/js/manager_app.js \
  app/static/js/manager_audit_mobile.js app/static/js/auth.js app/static/js/main.js \
  app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 主管手機殼 + 可橫捲主分頁 + action bar 殼 + 抽 mb_util 共用"
```

---

## Task 2: 稽核·待稽核 mb 卡片 + action bar 接線（交班/結班/取消 + 即時小計）

把 `manager_audit_mobile.js` 的 stub 換成真內容：待稽核以 `.mb-au-card` 卡片取代桌面表格（可編輯分類/金額/備註 + 打勾 + 退回旗標 + 歷程），並把 action bar 的交班/結班/取消與即時小計接上。**沿用 `admin_api.js` audit 端點與 `admin_audit.js` 同一資料流與 `data-f`/`data-act` 契約**，只換 DOM/class。

**Files:**
- Modify: `app/static/js/manager_audit_mobile.js`（`renderAuditPane` 真作 + `wireActionBar` 真作 + 待稽核卡）
- Modify: `app/static/css/app.css`（手機段落 append 稽核卡 `.mb-au-*` + `.mb-day-head`/`.mb-overdue`）
- Modify: `app/static/sw.js`（`calc-v70`）

**Interfaces:**
- Consumes: Task 1 殼（pane 容器、`#mb-actionbar` 內的 `#mb-ab-shift`/`#mb-ab-day`/`#mb-ab-undo`/`#mb-ab-total`/`#mb-ab-count`/`#mb-ab-err`）、`mbToast`(mb_util)、`api`(admin_api)、`escapeHtml`(admin_util)、`categoryOptionsHtml`/`parseAmountInput`/`lightLabel`(expenses_util)、`formatMoney`/`formatDateTimeTW`(audit_util)、`openImageLightbox`(lightbox)。
- Produces: `export async function renderAuditPane(container, { onSubtotalChange })`（子分頁 待稽核/總表；本 task 只作待稽核，總表 Task 3）；`export function wireActionBar(barEl, { onSubtotalChange })`。內部 `refreshSubtotal(onSubtotalChange)` 讀 `api.auditSummary(undefined)` 的 `open` bucket → 回 `{ subtotalText, count }` 給殼 `paintSubtotal`。

- [ ] **Step 1: 稽核卡 CSS（照原型 .card 家族 + action bar 已於 Task 1）**

app.css 手機段落 append，值照原型 `manager-audit.html` `.card`/`.card-top`/`.thumb`/`.dot`/`.zoom`/`.card-meta`/`.doc-no`/`.byline`/`.summary`/`.flag-bad`/`.fields`/`.field`/`.chip`/`.edit-note`/`.check-btn`/`.hist-toggle`/`.hist`/`.day-head`/`.banner`（加 `mb-au-`／`mb-` 前綴、`var(--x)`→`var(--wk-x)`；收據縮圖用真 `<img>`，不搬原型 CSS 假收據）：
```css
.mb-day-head{ display:flex; justify-content:space-between; align-items:baseline; padding:2px 4px 8px; margin-top:6px; }
.mb-day-head .d{ font-weight:700; font-size:14px; color:var(--wk-muted); }
.mb-day-head .sum{ font-size:13px; color:var(--wk-faint); } .mb-day-head .sum b{ color:var(--wk-ink); font-weight:700; }
.mb-overdue{ display:flex; gap:10px; align-items:flex-start; background:var(--wk-warn-soft);
  border:1px solid color-mix(in srgb, var(--wk-warn) 35%, transparent); color:var(--wk-warn-ink);
  border-radius:var(--wk-radius); padding:11px 13px; margin-bottom:14px; font-size:13.5px; font-weight:600; }
.mb-au-card{ background:var(--wk-surface); border:1px solid var(--wk-line); border-radius:var(--wk-radius);
  box-shadow:var(--mb-shadow,0 1px 2px rgba(28,39,51,.08)); padding:12px; display:flex; flex-direction:column; gap:10px; margin-bottom:12px; }
.mb-au-top{ display:flex; gap:10px; align-items:flex-start; }
.mb-au-thumb{ width:56px; height:56px; flex:none; border-radius:var(--wk-radius-sm); object-fit:cover;
  border:1px solid var(--wk-line); cursor:zoom-in; background:var(--wk-surface-2); }
.mb-au-thumb.none{ display:flex; align-items:center; justify-content:center; color:var(--wk-faint); font-size:12px; }
.mb-au-meta{ flex:1; min-width:0; }
.mb-au-docno{ font-weight:700; font-size:14.5px; letter-spacing:.2px; font-variant-numeric:tabular-nums; }
.mb-au-byline{ font-size:12px; color:var(--wk-faint); margin-top:2px; }
.mb-au-summary{ font-size:14.5px; color:var(--wk-ink); }
.mb-au-flag{ display:flex; gap:8px; align-items:flex-start; font-size:13px; font-weight:600;
  background:var(--wk-bad-soft); color:var(--wk-bad-ink);
  border:1px solid color-mix(in srgb, var(--wk-bad) 30%, transparent); border-radius:var(--wk-radius-sm); padding:8px 10px; }
.mb-au-fields{ display:grid; grid-template-columns:1fr 116px; gap:8px; }
.mb-au-field{ display:flex; flex-direction:column; gap:4px; min-width:0; }
.mb-au-field.full{ grid-column:1 / -1; }
.mb-au-field label{ font-size:11.5px; color:var(--wk-faint); }
.mb-au-field select,.mb-au-field input{ min-height:44px; width:100%; border:1px solid var(--wk-line);
  border-radius:var(--wk-radius-sm); background:var(--wk-surface-2); padding:0 10px; font-size:14.5px; color:var(--wk-ink); }
.mb-au-field input.amt{ text-align:right; font-variant-numeric:tabular-nums; font-weight:700; }
.mb-au-check{ min-height:48px; border:0; border-radius:var(--wk-radius-sm); background:var(--wk-accent);
  color:#fff; font-weight:700; font-size:15.5px; }
.mb-au-hist-toggle{ align-self:flex-start; min-height:40px; padding:0 4px; border:0; background:none;
  color:var(--wk-accent-ink); font-size:13px; font-weight:600; }
.mb-au-hist{ border-top:1px dashed var(--wk-line); padding-top:9px; font-size:12.5px; color:var(--wk-muted); }
.mb-au-hist[hidden]{ display:none; }
.mb-au-err{ font-size:12px; color:var(--wk-bad); min-height:1em; }
.mb-au-lastmod{ font-size:12px; color:var(--wk-warn-ink); }
```

- [ ] **Step 2: `renderAuditPane` + 待稽核卡（沿用 admin_audit.js 資料流）**

`manager_audit_mobile.js` 改寫（取代 stub）。頂部 import：
```js
import { api } from './admin_api.js';
import { escapeHtml } from './admin_util.js';
import { categoryOptionsHtml, lightLabel, parseAmountInput } from './expenses_util.js';
import { formatMoney, formatDateTimeTW } from './audit_util.js';
import { openImageLightbox } from './lightbox.js';

const SID = undefined; // 主管鎖本店，後端用本店

export async function renderAuditPane(container, { onSubtotalChange } = {}) {
  container.innerHTML = `
    <div class="mb-subtabs" role="tablist" aria-label="稽核子功能">
      <button class="mb-subtab active" data-sub="pending" type="button">待稽核</button>
      <button class="mb-subtab" data-sub="summary" type="button">總表查詢</button>
    </div>
    <div id="mb-au-body"></div>`;
  const body = container.querySelector('#mb-au-body');
  const subs = container.querySelectorAll('.mb-subtab');
  const setSub = (name) => {
    subs.forEach((b) => b.classList.toggle('active', b.dataset.sub === name));
    if (name === 'pending') renderPending(body, onSubtotalChange);
    else renderSummary(body);                    // Task 3 提供
  };
  subs.forEach((b) => b.addEventListener('click', () => setSub(b.dataset.sub)));
  setSub('pending');
}

async function overdueHtml() {
  try {
    const { status, data } = await api.auditOverdue(SID);
    if (status === 200 && data && data.count > 0) {
      return `<div class="mb-overdue"><span>有 ${data.count} 筆 ${escapeHtml(data.oldest_business_date || '')} 以前的單還沒打勾，請優先處理。</span></div>`;
    }
  } catch { /* 逾期提醒非關鍵路徑，靜默略過 */ }
  return '';
}

async function renderPending(body, onSubtotalChange) {
  body.innerHTML = '<div class="mb-empty-state" style="display:block">載入中…</div>';
  const [{ data }, banner] = await Promise.all([api.auditPending(SID), overdueHtml()]);
  const catResp = await fetch('/expenses/categories').then((r) => r.json()).catch(() => ({}));
  const tree = (catResp && catResp.categories) || [];
  const groups = (data && data.groups) || [];
  if (!groups.length) {
    body.innerHTML = banner + '<div class="mb-empty-state" style="display:block">沒有待稽核單據</div>';
    if (onSubtotalChange) refreshSubtotal(onSubtotalChange);
    return;
  }
  body.innerHTML = banner + groups.map((g) => `
    <div class="mb-day-head"><span class="d">${escapeHtml(g.business_date)}</span>
      <span class="sum">日小計 <b class="num">${formatMoney(g.subtotal)}</b></span></div>
    <div class="mb-cardlist">${g.items.map((e) => cardHtml(e, tree)).join('')}</div>`).join('');
  wireCards(body, onSubtotalChange);
  if (onSubtotalChange) refreshSubtotal(onSubtotalChange);
}

function cardHtml(e, tree) {
  const thumb = e.thumb_url
    ? `<img src="${e.thumb_url}" loading="lazy" class="mb-au-thumb au-thumb" data-zoom="${e.image_url || ''}" alt="收據">`
    : '<span class="mb-au-thumb none">—</span>';
  const reject = e.is_rejected
    ? `<div class="mb-au-flag"><span>會計退回：${escapeHtml(e.reject_reason || '')}</span></div>` : '';
  const mgrEdit = e.is_modified_by_manager ? ' <span class="chip chip-warn">主管改</span>' : '';
  return `<article class="mb-au-card" data-id="${e.id}">
    <div class="mb-au-top">
      ${thumb}
      <div class="mb-au-meta"><div class="mb-au-docno">${escapeHtml(e.doc_no || `#${e.id}`)}</div>
        <div class="mb-au-byline">${escapeHtml(e.created_by_name || '')} · ${formatDateTimeTW(e.created_at)}</div></div>
    </div>
    ${reject}
    <div class="mb-au-summary">${escapeHtml(e.summary || '')}${e.is_no_receipt ? ' <span class="au-mod">無單據</span>' : ''}</div>
    <div class="mb-au-fields">
      <div class="mb-au-field"><label>分類</label><select data-f="category">${categoryOptionsHtml(tree, e.category_id)}</select></div>
      <div class="mb-au-field"><label>金額${mgrEdit}</label><input class="amt num" inputmode="decimal" data-f="amount" value="${e.amount ?? ''}"></div>
      <div class="mb-au-field full"><label>備註</label><input data-f="note" maxlength="200" placeholder="備註（可留空）" value="${escapeHtml(e.note || '')}"></div>
    </div>
    <div class="mb-au-light">${lightLabel(e.light)}</div>
    ${e.has_audit_log ? '<button class="mb-au-hist-toggle" data-act="hist" type="button">▶ 歷程</button><div class="mb-au-hist" hidden></div>' : ''}
    <button class="mb-au-check" data-act="check" type="button">✓ 打勾</button>
    <div class="mb-au-err" data-f="err"></div>
  </article>`;
}
```
> 卡片 DOM 契約與桌面完全一致（`data-id`/`data-f=category|amount|note|err`/`data-act=check|hist`/`.au-thumb data-zoom`），故 `wireCards` 幾乎是 `admin_audit.js:wireRows`（:316-359）的搬移版，只把「移除 `<tr>`」改成「移除 `.mb-au-card`」。

- [ ] **Step 3: `wireCards` + `refreshSubtotal`（沿用 wireRows 邏輯）**

```js
function wireCards(body, onSubtotalChange) {
  body.querySelectorAll('.mb-au-card').forEach((card) => {
    const id = Number(card.dataset.id);
    const err = card.querySelector('[data-f="err"]');
    const cat = card.querySelector('[data-f="category"]');
    const note = card.querySelector('[data-f="note"]');
    const thumbEl = card.querySelector('.au-thumb');
    if (thumbEl) thumbEl.addEventListener('click', () => openImageLightbox(thumbEl.dataset.zoom));
    cat.addEventListener('change', async () => {
      err.textContent = '';
      const categoryId = cat.value === '' ? null : Number(cat.value);
      try { const { status } = await api.auditEdit(id, { category_id: categoryId }, SID);
        if (status !== 200) err.textContent = '分類儲存失敗'; } catch { err.textContent = '分類儲存失敗'; }
    });
    note.addEventListener('change', async () => {
      err.textContent = '';
      try { const { status } = await api.auditEdit(id, { note: note.value }, SID);
        if (status !== 200) err.textContent = '備註儲存失敗'; } catch { err.textContent = '備註儲存失敗'; }
    });
    const histBtn = card.querySelector('[data-act="hist"]');
    if (histBtn) histBtn.addEventListener('click', async () => {
      const box = card.querySelector('.mb-au-hist');
      if (!box.hidden) { box.hidden = true; return; }
      box.hidden = false; box.textContent = '載入中…';
      try { const { data } = await api.expenseLogs(id);
        box.innerHTML = (data.logs || []).map((l) =>
          `<div>${escapeHtml(formatDateTimeTW(l.created_at))} · ${escapeHtml(l.actor_name || '')} · ${escapeHtml(l.action || '')}</div>`).join('') || '無歷程';
      } catch { box.textContent = '歷程載入失敗'; }
    });
    card.querySelector('[data-act="check"]').addEventListener('click', async () => {
      err.textContent = '';
      const parsed = parseAmountInput(card.querySelector('[data-f="amount"]').value);
      if (!parsed.valid) { err.textContent = '金額格式不正確'; return; }
      const categoryId = cat.value === '' ? null : Number(cat.value);
      try {
        const editRes = await api.auditEdit(id, { amount: parsed.value, category_id: categoryId, note: note.value }, SID);
        if (editRes.status !== 200) { err.textContent = '金額/分類/備註儲存失敗'; return; }
        const { status } = await api.auditCheck(id, SID);
        if (status === 200) { card.remove(); if (onSubtotalChange) refreshSubtotal(onSubtotalChange); }
        else err.textContent = '打勾失敗';
      } catch { err.textContent = '打勾失敗'; }
    });
  });
}

async function refreshSubtotal(onSubtotalChange) {
  try {
    const { data } = await api.auditSummary(SID);
    const open = (data && data.open) || { subtotal: 0, count: 0 };
    onSubtotalChange({ subtotalText: formatMoney(open.subtotal), count: open.count });
  } catch { /* 小計非關鍵，失敗不擋 */ }
}
```
> `expenseLogs` 回的欄位名（`actor_name`/`action`/`created_at`）：若與後端實際不符，改用既有 `renderTrailRows(data.logs)`（audit_util.js:41）產字串（桌面就是用它）。**保守作法：直接 `import { renderTrailRows } from './audit_util.js'` 並 `box.innerHTML = renderTrailRows(data.logs)`**，與桌面一致、免猜欄位。

- [ ] **Step 4: `wireActionBar`（交班/結班/取消 + 小計，沿用 actionBar 邏輯）**

`manager_audit_mobile.js` append：
```js
export function wireActionBar(barEl, { onSubtotalChange } = {}) {
  const err = barEl.querySelector('#mb-ab-err');
  const doClose = async (type) => {
    err.textContent = '';
    const { status, data } = await api.auditHandover(type, SID);
    err.textContent = status === 200 ? `已${type === 'day' ? '結班' : '交班'}（${data.count} 筆）` : '沒有可歸班的單據';
    if (status === 200 && onSubtotalChange) refreshSubtotal(onSubtotalChange);
  };
  barEl.querySelector('#mb-ab-shift').addEventListener('click', () => doClose('shift'));
  barEl.querySelector('#mb-ab-day').addEventListener('click', () => doClose('day'));
  barEl.querySelector('#mb-ab-undo').addEventListener('click', async () => {
    err.textContent = '';
    const { status, data } = await api.auditUndo(SID);
    err.textContent = status === 200 ? `已取消，退回 ${data.reopened} 筆` : '沒有可取消的交班';
    if (status === 200 && onSubtotalChange) refreshSubtotal(onSubtotalChange);
  });
  if (onSubtotalChange) refreshSubtotal(onSubtotalChange);
}
```
> `refreshSubtotal` 需在 `wireActionBar` 可見——它已於本檔 module 級定義（Step 3），同檔直接呼叫即可。

- [ ] **Step 5: 驗證（對照原型 5.2 待稽核）**

開 server → `/dev/login-manager` → 稽核（待稽核）。對照原型：逾期 banner（若有）、依營業日分組（日小計）、單欄卡片（縮圖/單號/建立者·時間/摘要/退回旗標/分類 select/金額 input/備註 input/燈號/歷程/打勾）。改分類/備註即時存；打勾＝先 `auditEdit` 再 `auditCheck`、成功移除卡 + action bar 小計更新；縮圖點開燈箱；歷程展開。action bar：交班/結班/取消可動、小計即時更新、錯誤訊息顯示。`node --test` + `pytest -q` 全綠。

- [ ] **Step 6: bump sw(`calc-v70`) + commit**
```bash
git add app/static/js/manager_audit_mobile.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 主管稽核待稽核 mb 卡片 + action bar 交班/結班/取消 + 即時小計"
```

---

## Task 3: 稽核·總表查詢 mb 唯讀班別卡 + 日期切換

`manager_audit_mobile.js` 補 `renderSummary`：依營業日 + 班別分組的唯讀卡片（照原型 `.rcard` 家族 + `.day-total`），日期選擇器切換。沿用 `api.auditSummaryDates`/`api.auditByDate`（同 `admin_audit.js:renderSummary` 資料流）。

**Files:**
- Modify: `app/static/js/manager_audit_mobile.js`（補 `renderSummary`）
- Modify: `app/static/css/app.css`（手機段落 append `.mb-ro-card`/`.mb-ro-*`/`.mb-shift-head`/`.mb-day-total`）
- Modify: `app/static/sw.js`（`calc-v71`）

**Interfaces:** Consumes Task 2 的 import 群 + `api.auditSummaryDates`/`api.auditByDate`。Produces：module 內 `renderSummary(body)`（Task 2 `setSub('summary')` 已呼叫）。

- [ ] **Step 1: 唯讀卡 CSS（照原型 .rcard / .shift-head / .day-total）**

app.css 手機段落 append，值照原型 `manager-audit.html` `.shift-head`/`.rcards`/`.rcard`/`.r-top`/`.r-main`/`.r-line1`/`.r-amt`/`.r-sum`/`.r-tags`/`.chip`/`.r-note`/`.r-audit`/`.day-total`（加 `mb-`／`mb-ro-` 前綴、`var(--x)`→`var(--wk-x)`；`.chip`/`.chip-ok`/`.chip-warn`/`.chip-bad`/`.chip-line` 若 Task 2 未建則於此補，值照原型 `.chip*`）。收據縮圖用真 `<img class="mb-au-thumb au-thumb">`（沿用 Task 2）。

- [ ] **Step 2: `renderSummary`（唯讀班別卡 + 日期切換）**

`manager_audit_mobile.js` append（沿用 `admin_audit.js:renderSummary` :182-211 的取數；render 換卡片）：
```js
function shiftLabel(sh) {
  if (sh.handover_id === null) return '當前未歸班';
  const kind = sh.type === 'day' ? '結班' : '交班';
  return `第 ${sh.seq} 班（${kind} ${formatDateTimeTW(sh.closed_at)}）`;
}
const CHIP = { reconciled: 'chip-ok', rejected: 'chip-bad', audited: 'chip-line', submitted: 'chip-warn' };
function roCardHtml(e) {
  const thumb = e.thumb_url
    ? `<img src="${e.thumb_url}" loading="lazy" class="mb-au-thumb au-thumb" data-zoom="${e.image_url || ''}" alt="收據">`
    : '<span class="mb-au-thumb none">—</span>';
  const amt = Number(e.amount); const neg = Number.isFinite(amt) && amt < 0;
  return `<article class="mb-ro-card">
    <div class="mb-ro-top">${thumb}
      <div class="mb-ro-main">
        <div class="mb-ro-line1"><span class="mb-au-docno">${escapeHtml(e.doc_no || `#${e.id}`)}</span>
          <span class="mb-ro-amt num${neg ? ' neg' : ''}">${formatMoney(e.amount)}</span></div>
        <div class="mb-ro-sum">${escapeHtml(e.summary || '')}${e.is_no_receipt ? ' <span class="au-mod">無單據</span>' : ''}</div>
        <div class="mb-ro-tags"><span class="chip chip-line">${escapeHtml(e.category_name || '未分類')}</span>
          <span class="chip ${CHIP[e.status] || 'chip-line'}">${escapeHtml(status_label(e.status))}</span></div>
        ${e.note ? `<div class="mb-ro-note">備註：${escapeHtml(e.note)}</div>` : ''}
        <div class="mb-ro-audit">稽核：${escapeHtml(e.audited_by_name || '—')}</div>
      </div></div></article>`;
}
async function renderSummary(body, dateStr) {
  body.innerHTML = '<div class="mb-empty-state" style="display:block">載入中…</div>';
  const { data: dd } = await api.auditSummaryDates(SID);
  const dates = (dd && dd.dates) || [];
  const today = dates[0] || '';
  const sel = dateStr || today;
  const { data } = sel ? await api.auditByDate(SID, sel) : { data: { shifts: [], total: 0, count: 0 } };
  const shifts = data.shifts || [];
  const blocks = shifts.map((sh) => `
    <div class="mb-shift-head"><span class="s">${escapeHtml(shiftLabel(sh))}</span>
      <span class="sum">小計 <b class="num">${formatMoney(sh.subtotal)}</b>（${sh.count} 筆）</span></div>
    <div class="mb-cardlist">${sh.items.map(roCardHtml).join('')}</div>`).join('');
  body.innerHTML = `
    <div class="mb-au-daynav">營業日 <input type="date" id="mb-au-date" value="${sel}"${today ? ` max="${today}"` : ''}></div>
    ${blocks || '<div class="mb-empty-state" style="display:block">當天沒有單據</div>'}
    <div class="mb-day-total"><span class="l">當日總額</span><span class="v num">${formatMoney(data.total)}（${data.count} 筆）</span></div>`;
  const dinp = body.querySelector('#mb-au-date');
  if (dinp) dinp.addEventListener('change', (ev) => { if (ev.target.value) renderSummary(body, ev.target.value); });
  body.querySelectorAll('.au-thumb').forEach((img) => img.addEventListener('click', () => openImageLightbox(img.dataset.zoom)));
}
```
> 頂部 import 補 `status_label`：`import { formatMoney, formatDateTimeTW, status_label } from './audit_util.js';`（Task 2 只 import 了 `formatMoney`/`formatDateTimeTW`，此處加 `status_label`）。`.mb-au-daynav` 小樣式於 CSS 補（`input[type=date]` min-height 44 + `.mb-au-daynav` margin-bottom 12）。

- [ ] **Step 3: 驗證**

`/dev/login-manager` → 稽核 → 總表查詢：日期選擇器（預設今日、max 今日）、依班別分組（班標頭 + 小計）、唯讀卡片（單號/金額[負數紅字]/摘要/分類 chip+狀態 chip/備註/稽核者）、當日總額 bar、縮圖點開燈箱、切日期重載。**無任何編輯/打勾**。`node --test` + `pytest -q` 全綠。

- [ ] **Step 4: bump sw(`calc-v71`) + commit**
```bash
git add app/static/js/manager_audit_mobile.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 主管稽核總表查詢 mb 唯讀班別卡 + 日期切換"
```

---

## Task 4: 操作記錄 / 帳號 / 裝置 pane（重用現有 render，主管權限完整保留）

三個 pane 直接重用現有 `renderLogs`/`renderAccounts`/`renderDevices`（主管既有可操作能力全保留），套一層 `.mb-admin-embed` 讓桌面 `.wk-*`/`.ap-*`/`.pd-*` 元件在手機殼內排版可用（單欄、可捲、觸控尺寸）。

**Files:**
- Modify: `app/static/js/manager_app.js`（`renderPane` 的 logs/accounts/devices 分支包一層 `.mb-admin-embed` 容器再呼叫現有 render）
- Modify: `app/static/css/app.css`（手機段落 append `.mb-admin-embed` + `.mb-log-line`? 見下）
- Modify: `app/static/sw.js`（`calc-v72`）

**Interfaces:** Consumes 既有 `renderLogs(container, identity, storeId)`、`renderAccounts(container, ctx)`、`renderDevices(container, ctx)`（簽章不改）、Task 1 的 `ctx()`。

- [ ] **Step 1: `.mb-admin-embed` CSS（讓桌面元件在手機 pane 內可用）**

app.css 手機段落 append：一個外層 wrapper，把內部桌面表格/表單改為單欄、可橫捲、觸控尺寸。**不改桌面元件本身**，只在此 scope 內覆蓋關鍵幾點：
```css
.mb-admin-embed{ padding:2px; }
.mb-admin-embed .wk-toolbar,.mb-admin-embed .wk-page-body{ padding-left:0; padding-right:0; }
.mb-admin-embed .table-wrap{ overflow-x:auto; -webkit-overflow-scrolling:touch; }
.mb-admin-embed table{ min-width:520px; }            /* 表格窄於視窗就橫捲，不擠壓 */
.mb-admin-embed input,.mb-admin-embed select,.mb-admin-embed button{ min-height:40px; } /* 觸控尺寸 */
.mb-admin-embed .wk-card{ margin-bottom:12px; }
```
> 這是「重用優先」的取捨：帳號/裝置/操作記錄在原型是純唯讀佔位（無 pixel-exact 目標），且主管既有能力（改密碼/停用/核准裝置）完全靠現有 render——重用它們可零風險保留全部功能，外觀用 `.mb-admin-embed` 收進手機殼即可。全 mb 卡片化屬未來 polish，非本 plan 範圍。

- [ ] **Step 2: `manager_app.js` renderPane 包 embed 容器**

`renderPane` 的三個分支改為先建 `.mb-admin-embed` 再呼叫現有 render：
```js
} else if (name === 'logs') {
  el.innerHTML = '<div class="mb-pane-title" style="padding:12px 14px 0">操作記錄</div><div class="mb-admin-embed"></div>';
  renderLogs(el.querySelector('.mb-admin-embed'), identity, null);
} else if (name === 'accounts') {
  el.innerHTML = '<div class="mb-pane-title" style="padding:12px 14px 0">帳號</div><div class="mb-admin-embed"></div>';
  renderAccounts(el.querySelector('.mb-admin-embed'), ctx());
} else if (name === 'devices') {
  el.innerHTML = '<div class="mb-pane-title" style="padding:12px 14px 0">裝置</div><div class="mb-admin-embed"></div>';
  renderDevices(el.querySelector('.mb-admin-embed'), ctx());
}
```
> `ctx()` 的 `reload` 會 `renderPane(state.tab)`（重繪當前 pane）；`refreshStores` 會重抓店清單並更新抬頭店徽——帳號/裝置操作後（如改店別）能刷新。`.mb-pane-title` 員工段落已有。

- [ ] **Step 3: 驗證**

`/dev/login-manager`：
- 操作記錄 pane：顯示本店近期操作記錄（`renderLogs` 內容），可捲。
- 帳號 pane：本店人員清單，主管既有能力可用（重設密碼/啟停用/改店別依現有權限）；表格窄於視窗可橫捲、觸控尺寸夠。
- 裝置 pane：本店綁定裝置，核准/撤銷依現有能力可用。
- 切換這三個 pane 無 console error；操作後 `reload` 能重繪。`node --test` + `pytest -q` 全綠。

- [ ] **Step 4: bump sw(`calc-v72`) + commit**
```bash
git add app/static/js/manager_app.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 主管手機 操作記錄/帳號/裝置 pane 重用現有 render（能力完整保留）"
```

---

## Task 5: 我的密碼 pane + sw 預快取收尾 + 整合驗證 + 橫式/平板

補我的密碼 mb 表單（`api.changeMyPassword`），補齊 sw STATIC_URLS（主管手機用到的全部 JS），整合回歸。

**Files:**
- Modify: `app/static/js/manager_app.js`（`renderMyPasswordPane` 真作）
- Modify: `app/static/css/app.css`（手機段落 append `.mb-form-field`/`.mb-pw-btn`）
- Modify: `app/static/sw.js`（`calc-v73` + STATIC_URLS 補齊）

**Interfaces:** Consumes `api.changeMyPassword`（admin_api.js:32）、`mbToast`。

- [ ] **Step 1: `.mb-form-field`/`.mb-pw-btn` CSS（照原型 .form-field/.pw-btn）**

app.css 手機段落 append，值照原型 `manager-audit.html` `.form-field`/`.pw-btn`（加 `mb-` 前綴、`var(--x)`→`var(--wk-x)`）：
```css
.mb-form-field{ display:flex; flex-direction:column; gap:5px; margin-bottom:12px; }
.mb-form-field label{ font-size:12.5px; color:var(--wk-muted); font-weight:600; }
.mb-form-field input{ min-height:44px; border:1px solid var(--wk-line); border-radius:var(--wk-radius-sm);
  background:var(--wk-surface-2); padding:0 12px; font-size:15px; color:var(--wk-ink); }
.mb-pw-btn{ width:100%; min-height:46px; border:0; border-radius:var(--wk-radius-sm);
  background:var(--wk-accent); color:#fff; font-weight:700; font-size:15px; }
```

- [ ] **Step 2: `renderMyPasswordPane`（改密碼表單）**

`manager_app.js` 內把 Task 1 的佔位 `renderMyPasswordPane` 換成真作（沿用 admin.js `renderMyPassword` :109 的 `api.changeMyPassword` 流程）：
```js
function renderMyPasswordPane(el) {
  el.innerHTML = `
    <div class="mb-ph-card"><h3>變更我的密碼</h3>
      <div class="mb-form-field"><label for="mb-pw-old">舊密碼</label><input type="password" id="mb-pw-old" autocomplete="current-password"></div>
      <div class="mb-form-field"><label for="mb-pw-new">新密碼</label><input type="password" id="mb-pw-new" autocomplete="new-password"></div>
      <div class="mb-form-field"><label for="mb-pw-new2">確認新密碼</label><input type="password" id="mb-pw-new2" autocomplete="new-password"></div>
      <button class="mb-pw-btn" id="mb-pw-submit" type="button">更新密碼</button>
      <div class="mb-au-err" id="mb-pw-err"></div></div>`;
  el.querySelector('#mb-pw-submit').addEventListener('click', async () => {
    const oldp = el.querySelector('#mb-pw-old').value;
    const np = el.querySelector('#mb-pw-new').value;
    const np2 = el.querySelector('#mb-pw-new2').value;
    const err = el.querySelector('#mb-pw-err');
    err.textContent = '';
    if (!np || np.length < 4) { err.textContent = '新密碼至少 4 碼'; return; }
    if (np !== np2) { err.textContent = '兩次新密碼不一致'; return; }
    try {
      const { status } = await api.changeMyPassword(oldp, np);
      if (status === 200) { mbToast('密碼已更新'); el.querySelector('#mb-pw-old').value = ''; el.querySelector('#mb-pw-new').value = ''; el.querySelector('#mb-pw-new2').value = ''; }
      else err.textContent = '更新失敗（舊密碼可能不正確）';
    } catch { err.textContent = '更新失敗，請重試'; }
  });
}
```
> ⚠️ 確認 `api.changeMyPassword` 的參數簽章（admin_api.js:32-33）：若是 `changeMyPassword(oldPw, newPw)` 如上；若是 `changeMyPassword({old, new})` 物件則對應調整。**實作前先讀 admin_api.js:32-33 對齊**。密碼最短長度沿用後端規則（若後端非 4 碼，改對齊；純前端防呆不阻擋後端）。

- [ ] **Step 3: sw STATIC_URLS 補齊（主管手機全部 JS）**

`sw.js`：CACHE_NAME → `calc-v73`；`STATIC_URLS`（:11-）補入主管手機用到、目前缺的檔：
```
'/static/js/mb_util.js',
'/static/js/manager_app.js',
'/static/js/manager_audit_mobile.js',
'/static/js/admin_api.js',
'/static/js/admin_audit.js',
'/static/js/admin_accounts.js',
'/static/js/admin_devices.js',
'/static/js/admin_logs.js',
'/static/js/periods_api.js',
```
> `admin_util.js`/`audit_util.js`/`expenses_util.js`/`lightbox.js`/`wk_modal.js` 已在清單（Task 前確認）。`admin.js`（經理桌面殼）主管手機不載入，可不加。

- [ ] **Step 4: 整合回歸（對照原型 + spec §5.3）**

`/dev/login-manager` 走完：
- 稽核：待稽核（逾期 banner/分組/卡片編輯/打勾/退回旗標/歷程/縮圖燈箱）→ 總表查詢（日期切換/班別卡/當日總額）→ action bar（交班/結班/取消/即時小計）。
- 操作記錄/帳號/裝置：重用內容可用、能力保留。
- 我的密碼：改密碼成功 toast、防呆（長度/一致）。
- 全程對照原型視覺、深/淺主題、無 console error、時間台灣時間、店別英文代號、負數紅字。
- **橫式/平板**：主分頁列橫捲不藏；卡片單欄滿版（平板寬視窗仍單欄，照原型 `@media(min-width:768px)`）。
- **員工端回歸**：`/dev/login-test` 員工手機完全照舊。
- **經理端回歸**：`/dev/login-super` 仍走桌面工作台（`showAdminPanel`）完全照舊。

- [ ] **Step 5: 全測試綠 + commit**
```
node --test tests/js/*.mjs
python3 -m pytest -q
```
Expected：前端純邏輯測 71 passed + 後端 567 passed（皆未動）。
```bash
git add app/static/js/manager_app.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 主管手機 我的密碼 pane + sw 預快取收尾 + 整合驗證"
```

---

## Self-Review（對照 spec §5.3 + 原型）

**Spec §5.3 / 原型 coverage**：常駐手機殼 + 可橫捲主分頁（Task1）✔ / 稽核打勾卡片（Task2）✔ / 常駐 action bar 交班/結班/取消（Task1 殼 + Task2 接線）✔ / 總表查詢唯讀班別卡（Task3）✔ / 鎖本店·無選店（全程 `SID=undefined`）✔ / 操作記錄·帳號·裝置·我的密碼（Task4,5）✔ / 收據縮圖真圖 + 燈箱（Task2,3）✔ / 主管既有能力保留（Task4 重用）✔ / 深淺主題 token 沿用（Task1）✔ / 店別英文代號·時間台灣·負數紅字·單欄滿版（Global Constraints，各 task 落地）✔ / bump sw + 補預快取（每 task + Task5）✔。
> 本 plan 僅涵蓋 spec §5.3（主管手機）。經理手機（super-mobile，§5.4）= 後續獨立 plan（含 super_admin 依螢幕寬度路由）。

**Placeholder scan**：無 TBD/TODO；每 code 步驟有完整程式碼；驗證步驟有 URL/預期/對照對象。**外部相依/待確認**（實作時對齊，非 placeholder）：(a) `api.changeMyPassword` 參數簽章（Task5 Step2 已標「實作前讀 admin_api.js:32-33」）；(b) `expenseLogs` 歷程欄位——Task2 Step3 已給保守解「用 `renderTrailRows`」；(c) dev 主管是否綁店（無則店徽不顯示，不造假，Task1 已處理）。

**Type consistency**：`showManagerApp(identity)` / `renderAuditPane(container,{onSubtotalChange})` / `wireActionBar(barEl,{onSubtotalChange})` / `refreshSubtotal(onSubtotalChange)`→`{subtotalText,count}` / `paintSubtotal(open)` 簽章跨 Task1↔2/3 一致；沿用既有 `data-f`/`data-act`/`.au-thumb data-zoom`/`admin_api` 函式名全不改；`ctx()`→`{identity,storeId:null,stores,api,reload,refreshStores}` 與 `renderAccounts`/`renderDevices` 期望一致。

---

## 風險 / 注意

- **不動後端是鐵律**：全程只呼叫既有 `admin_api.js` 端點，`sid=undefined`（主管本店）。code review 確認沒新增/改後端。
- **舊碼孤兒**：主管改走 `showManagerApp` 後，`admin.js` 的 manager 分支（稽核可操作那段、`admin_audit.js:renderAudit` 的非 super 分支）對主管成孤兒——**本 plan 不刪**（`showAdminPanel` 經理續用；`renderAudit` 的 super 分支仍用）。待經理手機 plan 完成後的收尾 plan 再評估清理。
- **重用 vs 卡片化**：帳號/裝置/操作記錄用 `.mb-admin-embed` 收桌面元件（Task4）——保留全部能力、零風險，但外觀非純 mb 卡片。若日後要 pixel-perfect，另開 polish plan。
- **PWA 快取**：每 task bump sw；Task5 一次補齊 STATIC_URLS（現行漏 admin*/periods_api）。上線一次 bump 到最終版。
- **相機生命週期**：主管殼無拍照（`stopPaneCamera` 只是防呆，帳號 pane 的 `renderAccounts` 若有更新人臉相機，切走時殼會停）。
- **測試盲區**：主管 render 層無 DOM 單元測（靠後端 API 測 + 本機目視）；純函式維持行為、每 task 重跑 node 測。
