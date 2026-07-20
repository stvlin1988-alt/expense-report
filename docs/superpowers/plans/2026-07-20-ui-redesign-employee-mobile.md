# 員工手機 App UI 重塑 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把員工端（拍單／確認區／複查）從現行「首頁三顆按鈕 + 逐頁 `.modal-box` 疊層 + 桌機式 `<table>`（`min-width:460px` 手機橫捲）」重塑成原型 `employee-mobile.html` 的「常駐手機殼（抬頭 + 內容 pane + 底部 tab bar）+ 單欄卡片 + 取景框拍單」，並把拍單相機從自拍前鏡頭改成後鏡頭 + 取景框。

**Architecture:** 純前端／CSS／DOM 重塑，**不動後端、不改 API、不改任務流、不碰計算機幌子、影像維持記憶體不落地（不進相簿）**。新增一套**手機設計層（`.mb-*` 命名空間，沿用既有 `--wk-*` token）**與新殼 `employee_app.js`（`showEmployeeApp`），把現行 `capture.js`/`pending.js`/`review.js` 從「render 進 `#modal-root` 的 modal」重構成「render 進殼傳入的 pane 容器」的函式（`renderShootPane`/`renderConfirmPane`/`renderReviewPane`），三個 pane 由底部 tab 切換。**所有後端呼叫、`data-f`/`data-act` 契約、`Camera`(記憶體直傳) 全沿用。** 主管/會計/經理入口不動（仍走 admin/reconcile 殼）。視覺 SoT = `docs/superpowers/ui-prototypes/employee-mobile.html`。

**Tech Stack:** Vanilla ES module（無框架）、單一 `app/static/css/app.css`、Flask 模板、PWA service worker（`sw.js`）、`getUserMedia`+canvas 拍照（記憶體 base64、不落地）。

## 前端驗證策略（本 plan 對 TDD 的 adaptation）

- **純函式改動** → `node --test tests/js/*.mjs`（既有前端純邏輯測）。本 plan 幾乎不動純函式（`formatAmount`/`sumAmounts`/`parseAmountInput`/`lightLabel`/`categoryOptionsHtml` 維持行為）；每個 task 結尾**重跑既有 node 測確認全綠**。
- **後端未動** → 每個 task（或整合 task）跑 `python3 -m pytest -q`（員工端 API 測試 test_expense_* 全綠，確認沒誤傷）。
- **DOM／CSS 重塑 + 相機** → 本機開 server + dev 登入員工，**對照原型 URL 逐項目視檢**（含真機/手機模擬器測後鏡頭 + 拍照不落地）。

**本機啟動（harness `run_in_background: true`，勿用 shell `&`／nohup）：**
```
cd ~/projects/expense-report; set -a; . ./.env 2>/dev/null; set +a; export E2E_LOGIN_BYPASS=1 FLASK_APP=wsgi.py SECRET_KEY=${SECRET_KEY:-dev}; python3 -m flask db upgrade; python3 -m flask run --port 5001 --no-reload
```
- **員工面板入口**：`http://127.0.0.1:5001/dev/login-test`（dev 捷徑，建/登入測試員工，繞過計算機+裝置閘）。
- 對照原型：本機直接開檔 `docs/superpowers/ui-prototypes/employee-mobile.html`。
- ⚠️ **相機**：桌機瀏覽器 `facingMode:'environment'` 可能 fallback 到唯一鏡頭；真正驗後鏡頭要用手機或 DevTools 裝置模擬。`camera.js` 的 `setE2ESample` 可注入假圖跳過實體相機測 UI 流程。
- 改前端後：瀏覽器硬重整（避 sw 快取）；每個 task 最後 bump `sw.js` CACHE_NAME（現 `calc-v61` → 本 plan `calc-v62`…`calc-v67`）並**補新檔進 STATIC_URLS 預快取清單**。

---

## Global Constraints

以下每個 task 都隱含適用（值逐字取自原型 `employee-mobile.html` 與 CLAUDE.md 鐵律）：

- **不碰計算機幌子**（`calculator.js`/`secret.js`），**不改後端/API/任務流**；主管/會計/經理入口（admin/reconcile 殼）不動。
- **影像不落地、不進相簿**：拍照一律 `getUserMedia`（即時串流）→ `canvas.drawImage` → `canvas.toDataURL('image/jpeg',0.85)`（記憶體 base64）→ 直接 POST。**絕不用 `<input type="file" capture>`（那會經系統相機、可能存進相簿）**；不 `<a download>`、不寫檔案系統。拍完/離開一律 `cam.stop()` 關串流。
- **設計 token 沿用既有 `--wk-*`**（app.css 已定義 light/dark 三段）；原型 `:root` 的 `--accent/--ground/...` 值＝現有 `--wk-*` 值。本 plan **不重定義 token**，`.mb-*` 元件一律引用 `var(--wk-x)`。原型另有 `--stage/--cam/--cam-2/--thumb-a/--thumb-b/--r/--r-sm/--shadow` 等手機專用變數，於 `.mb-*` 段落的 `:root` 補上（值照原型；`--r`→用既有 `--wk-radius`、`--r-sm`→`--wk-radius-sm`，其餘 stage/cam/thumb 新增 `--mb-*`）。
- **店別英文代號** ≤2 字母、絕不露中文店名；**負數紅字**（員工端多為正數，仍用 `.mb-amt.neg` / `--wk-bad`）、金額 `tabular-nums`；**時間台灣時間**（`formatDateTimeTW`）。⚠️ 原型抬頭的「早班·07/16」班別/日期與收據假資料**不得照搬造假**——只顯示 `identity` 與後端實際回傳的欄位（見 Task 1）。
- **底部 tab bar 橫式不可藏**（原型踩雷：橫式改左側直向 rail 常駐，別把 tab 藏掉否則其他分頁進不去）。
- **卡片列表單欄滿版**（一列一張，不分兩欄；平板/橫式亦單欄，照原型 `.cardlist{flex-direction:column}`）。
- **收據縮圖用真 `<img> thumb_url`**（R2 縮圖）套原型縮圖視覺（圓角/邊框/放大鏡暗示 `zoom-badge`/`cursor:zoom-in`），點開走既有 `openImageLightbox`（lightbox.js，手機 pinch/縮放已支援）。原型 CSS 畫的假收據只是無真圖時示意，**不照搬**；無縮圖（pending_ocr）用 placeholder（🕓/skeleton）。
- **CSS 組織**：`app.css` 單檔分區（新增「手機設計層 `.mb-*`」段落，清楚註解），不拆多檔。與舊 `.pd-*/.rv-*/.nr-*/.modal-*` 及 `.wk-*` 並存。
- **每次改 css/js → bump `sw.js` CACHE_NAME + 補新檔進 `STATIC_URLS`**（現 `calc-v61`；⚠️ 現行 STATIC_URLS 未含 `review.js`/`lightbox.js`/`wk_modal.js`/`employee_app.js`，重塑要補齊）。

---

## File Structure

| 檔案 | 動作 | 責任 |
|---|---|---|
| `app/static/js/employee_app.js` | **Create** | 員工手機殼 `showEmployeeApp(identity)`：抬頭（店代號/姓名/更新人臉/登出/直橫切換）+ 內容（3 pane 容器）+ 底部 tab bar + pane 切換 + tab 待確認 badge。呼叫 `renderShootPane`/`renderConfirmPane`/`renderReviewPane`。 |
| `app/static/js/capture.js` | Modify（改簽章） | `showCaptureView(onDone)` → `renderShootPane(container, { onUploaded })`：render 進 pane 容器（非 modal），取景框 + 快門 + 多拍 + 上傳進度。沿用 `Camera`/`captureUpload`。 |
| `app/static/js/pending.js` | Modify（改簽章） | `showPendingView(onBack)` → `renderConfirmPane(container, { onCountChange })`：卡片式確認區 + 無單據建帳卡。沿用全部 API 與 `data-f`/`data-act` 契約。 |
| `app/static/js/review.js` | Modify（改簽章） | `showReviewView(onBack)` → `renderReviewPane(container)`：唯讀卡片 + 合計 bar。沿用 `listSubmitted`/`sumAmounts`。 |
| `app/static/js/camera.js` | Modify | `facingMode:'user'` → `'environment'`（後鏡頭拍收據），加不支援時 fallback。其餘（記憶體 base64、`setE2ESample`）不動。 |
| `app/static/js/auth.js` | Modify（2 行） | 密碼登入成功分派：employee → `showEmployeeApp`（原 `showAppView`）。`showAppView` 保留給非員工 fallback。 |
| `app/static/js/main.js` | Modify（2 行） | 暗號 re-entry 分派：employee → `showEmployeeApp`。 |
| `app/static/css/app.css` | Modify（append「手機設計層」段落） | 新增 `.mb-*`：殼/抬頭/tab bar/pane/取景框/快門/上傳/卡片/欄位/唯讀卡/合計 bar/toast/直橫。舊 `.pd-*/.rv-*/.nr-*/.modal-*` 段落**保留不動**（複查/確認舊碼移除後成孤兒，待清理 plan）。 |
| `app/static/sw.js` | Modify（每 task） | bump CACHE_NAME + STATIC_URLS 補 employee_app.js/review.js/lightbox.js/wk_modal.js。 |

**Task 邊界原則**：每個 task 是「一個可對照原型獨立目視驗收的交付」。`.mb-*` CSS 折入第一個需要它的 task。**先做殼（Task 1）打底，之後各 pane 逐一實作。**

---

## Task 1: 手機殼 + `.mb-*` 設計層 + 底部 tab + 抬頭（人臉/登出/直橫）

新建 `employee_app.js` 的常駐手機殼，路由員工進來，建立 `.mb-*` CSS 地基。此 task 後 3 個 pane 內容為空（Task 2/3/5 填），但殼/tab 切換/抬頭（含更新人臉、登出、直橫切換）可動。

**Files:**
- Create: `app/static/js/employee_app.js`
- Modify: `app/static/js/auth.js`（`submit()` 分派 ~146-147）、`app/static/js/main.js`（re-entry 分派 ~168-169）
- Modify: `app/static/css/app.css`（append「手機設計層」段落起頭：token 補充 + 殼/抬頭/content/pane/tabbar/tab/btn/toast/orient）
- Modify: `app/static/sw.js`（CACHE_NAME → `calc-v62`；STATIC_URLS 補 `/static/js/employee_app.js`）

**Interfaces:**
- Consumes: `Camera`(camera.js)、`escapeHtml`(admin_util.js)、`postJSON`(自建或從 auth 複用) for `/face/enroll` 與 `/auth/logout`。
- Produces: `export function showEmployeeApp(identity)`；殼 DOM 契約供 Task 2/3/5 —— pane 容器 id `#mb-pane-shoot`/`#mb-pane-confirm`/`#mb-pane-review`；tab 按鈕 `.mb-tab[data-tab=shoot|confirm|review]`；tab 切換函式（內部）+ 對外可呼叫 `showTab(name)`（掛在殼 state 或 module 級）；確認區 badge `#mb-confirm-badge`；供 pane 呼叫的 `setConfirmBadge(n)`。新 CSS class：`.mb-app`/`.mb-appbar`/`.mb-who`/`.mb-store-badge`/`.mb-appbar-actions`/`.mb-icon-btn`/`.mb-orient`/`.mb-content`/`.mb-pane`(+`.active`)/`.mb-tabbar`/`.mb-tab`(+`.active`)/`.mb-badge`/`.mb-btn`(+`-primary`/`-danger`/`-ghost`/`-sm`)/`.mb-toast`/`.mb-app.land`。

- [ ] **Step 1: 手機設計層 CSS 進 app.css（token 補充 + 殼/抬頭/tab/pane/btn/toast/orient）**

app.css 末尾 append，用註解分區。值逐字取自原型 `employee-mobile.html` `<style>`，class 統一加 `mb-` 前綴、`var(--x)`→`var(--wk-x)`（`--r`→`--wk-radius`、`--r-sm`→`--wk-radius-sm`）；原型手機專用變數新增 `--mb-*`：
```css
/* ============================================================
   手機設計層（UI 重塑 2026-07；員工/主管/經理手機共用基底）
   沿用既有 --wk-* token；本段新增手機殼/抬頭/tab/卡片/取景框等 .mb-* 元件。
   視覺 SoT: docs/superpowers/ui-prototypes/employee-mobile.html
   ============================================================ */
:root{
  --mb-stage:#E3E8F0; --mb-cam:#232B36; --mb-cam-2:#2C3542;
  --mb-thumb-a:#E1E7F0; --mb-thumb-b:#CFD8E5;
  --mb-shadow:0 18px 44px rgba(28,39,51,.18);
}
:root[data-theme="dark"]{ --mb-stage:#0C0F14; --mb-cam:#0E1319; --mb-cam-2:#1A222D;
  --mb-thumb-a:#252E3B; --mb-thumb-b:#1E2632; --mb-shadow:0 18px 44px rgba(0,0,0,.5); }
@media (prefers-color-scheme: dark){ :root{ --mb-stage:#0C0F14; --mb-cam:#0E1319; --mb-cam-2:#1A222D;
  --mb-thumb-a:#252E3B; --mb-thumb-b:#1E2632; --mb-shadow:0 18px 44px rgba(0,0,0,.5); } }
/* 殼：滿版（非原型的 phone 外框——那只是原型展示用）。#modal-root 掛載。 */
.mb-app{ position:fixed; inset:0; z-index:50; display:flex; flex-direction:column;
  background:var(--wk-ground); color:var(--wk-ink);
  font-family:-apple-system,BlinkMacSystemFont,"PingFang TC","Segoe UI","Microsoft JhengHei",sans-serif; }
.mb-appbar{ flex:none; display:flex; align-items:center; justify-content:space-between; gap:8px;
  padding:12px 14px 10px; background:var(--wk-surface); border-bottom:1px solid var(--wk-line); }
.mb-who{ display:flex; align-items:center; gap:9px; min-width:0; }
.mb-store-badge{ flex:none; display:inline-flex; align-items:center; justify-content:center;
  width:32px; height:32px; border-radius:9px; background:var(--wk-accent-soft); color:var(--wk-accent-ink);
  font-weight:700; font-size:13px; letter-spacing:.05em; }
.mb-who .mb-name{ font-weight:600; font-size:15px; }
.mb-who .mb-sub{ font-size:11px; color:var(--wk-faint); display:block; margin-top:1px; }
.mb-appbar-actions{ display:flex; gap:6px; }
.mb-icon-btn{ width:44px; height:44px; border:1px solid var(--wk-line); background:var(--wk-surface-2);
  border-radius:var(--wk-radius-sm); display:inline-flex; align-items:center; justify-content:center; color:var(--wk-muted); }
.mb-orient{ flex:none; display:flex; background:var(--wk-surface-2); border:1px solid var(--wk-line);
  border-radius:999px; padding:2px; gap:2px; }
.mb-orient button{ min-height:40px; padding:0 11px; border:none; border-radius:999px; background:none;
  color:var(--wk-muted); font-size:12.5px; font-weight:600; }
.mb-orient button[aria-pressed="true"]{ background:var(--wk-accent); color:#fff; }
.mb-content{ flex:1; overflow-y:auto; overflow-x:hidden; position:relative; overscroll-behavior:contain; }
.mb-pane{ display:none; padding:14px 14px 20px; }
.mb-pane.active{ display:block; }
.mb-pane-title{ font-size:16px; font-weight:700; margin:2px 2px 4px; }
.mb-pane-sub{ font-size:12px; color:var(--wk-muted); margin:0 2px 12px; }
.mb-tabbar{ flex:none; display:flex; background:var(--wk-surface); border-top:1px solid var(--wk-line);
  padding:6px 8px calc(8px + env(safe-area-inset-bottom,6px)); }
.mb-tab{ flex:1; min-height:52px; border:none; background:none; border-radius:var(--wk-radius-sm);
  display:flex; flex-direction:column; align-items:center; justify-content:center; gap:3px;
  color:var(--wk-faint); font-size:11.5px; font-weight:600; position:relative; }
.mb-tab svg{ width:23px; height:23px; }
.mb-tab.active{ color:var(--wk-accent); background:var(--wk-accent-soft); }
.mb-badge{ position:absolute; top:4px; left:calc(50% + 8px); min-width:18px; height:18px; padding:0 5px;
  border-radius:999px; background:var(--wk-bad); color:#fff; font-size:11px; display:flex; align-items:center;
  justify-content:center; font-variant-numeric:tabular-nums; }
.mb-badge.zero{ display:none; }
.mb-btn{ min-height:44px; padding:0 16px; border-radius:var(--wk-radius-sm); border:1px solid var(--wk-line);
  background:var(--wk-surface); font-size:14.5px; font-weight:600; color:var(--wk-ink);
  display:inline-flex; align-items:center; justify-content:center; gap:6px; }
.mb-btn-primary{ background:var(--wk-accent); border-color:var(--wk-accent); color:#fff; }
.mb-btn-danger{ color:var(--wk-bad-ink); border-color:var(--wk-line); background:var(--wk-surface); }
.mb-btn-ghost{ background:var(--wk-surface-2); color:var(--wk-muted); font-weight:500; }
.mb-btn-sm{ font-size:13.5px; padding:0 13px; }
.mb-amt{ font-variant-numeric:tabular-nums; } .mb-amt.neg{ color:var(--wk-bad); }
.mb-toast{ position:fixed; left:50%; bottom:86px; transform:translateX(-50%) translateY(8px);
  background:var(--wk-ink); color:var(--wk-ground); font-size:13px; padding:9px 16px; border-radius:999px;
  opacity:0; pointer-events:none; white-space:nowrap; transition:opacity .25s,transform .25s; z-index:90;
  max-width:88%; overflow:hidden; text-overflow:ellipsis; }
.mb-toast.show{ opacity:.96; transform:translateX(-50%) translateY(0); }
```
> 取景框/快門/上傳/卡片/欄位/唯讀/合計/直橫 等 CSS 於 Task 2/3/5 各自 append（折入需要它的 task）。`.mb-app.land` 橫式 rail 於 Task 2 append（拍單橫式最需要）。

- [ ] **Step 2: 寫 `employee_app.js` 殼**

`showEmployeeApp(identity)`：清空 `#modal-root`、render 殼、綁 tab 切換 + 抬頭動作。骨架：
```js
import { Camera } from './camera.js';
import { escapeHtml } from './admin_util.js';
import { renderShootPane } from './capture.js';       // Task 2 提供
import { renderConfirmPane } from './pending.js';      // Task 3 提供
import { renderReviewPane } from './review.js';        // Task 5 提供

const root = () => document.getElementById('modal-root');
async function postJSON(url, body) {
  const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  return { status: res.status, data: await res.json().catch(() => ({})) };
}

export function showEmployeeApp(identity) {
  const store = identity.store_code || '';   // 只用 identity 實際欄位；無則不顯示店徽（不造假）
  root().innerHTML = `
    <div class="mb-app" id="mb-app">
      <header class="mb-appbar">
        <div class="mb-who">
          ${store ? `<span class="mb-store-badge">${escapeHtml(store)}</span>` : ''}
          <span><span class="mb-name">${escapeHtml(identity.name)}</span><span class="mb-sub">員工</span></span>
        </div>
        <div class="mb-orient" role="group" aria-label="拍攝方向">
          <button type="button" id="mb-opt-portrait" aria-pressed="true">直式</button>
          <button type="button" id="mb-opt-landscape" aria-pressed="false">橫式</button>
        </div>
        <div class="mb-appbar-actions">
          <button class="mb-icon-btn" id="mb-reface" title="更新人臉" aria-label="更新人臉">🙂</button>
          <button class="mb-icon-btn" id="mb-logout" title="登出" aria-label="登出">⎋</button>
        </div>
      </header>
      <main class="mb-content">
        <section class="mb-pane active" id="mb-pane-shoot" aria-label="拍單"></section>
        <section class="mb-pane" id="mb-pane-confirm" aria-label="確認區"></section>
        <section class="mb-pane" id="mb-pane-review" aria-label="複查"></section>
      </main>
      <nav class="mb-tabbar" aria-label="主功能">
        <button class="mb-tab active" data-tab="shoot" type="button">拍單</button>
        <button class="mb-tab" data-tab="confirm" type="button">確認區<span class="mb-badge zero" id="mb-confirm-badge">0</span></button>
        <button class="mb-tab" data-tab="review" type="button">複查</button>
      </nav>
      <div class="mb-toast" id="mb-toast" role="status" aria-live="polite"></div>
    </div>`;

  const panes = { shoot: document.getElementById('mb-pane-shoot'), confirm: document.getElementById('mb-pane-confirm'), review: document.getElementById('mb-pane-review') };
  let rendered = { shoot: false, confirm: false, review: false };
  function showTab(name) {
    document.querySelectorAll('.mb-tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
    Object.entries(panes).forEach(([k, el]) => el.classList.toggle('active', k === name));
    renderPane(name);
  }
  function renderPane(name) {
    if (name === 'shoot') renderShootPane(panes.shoot, { onUploaded: () => { rendered.confirm = false; showTab('confirm'); } });
    else if (name === 'confirm') renderConfirmPane(panes.confirm, { onCountChange: setConfirmBadge });
    else if (name === 'review') renderReviewPane(panes.review);
  }
  function setConfirmBadge(n) {
    const b = document.getElementById('mb-confirm-badge');
    b.textContent = String(n); b.classList.toggle('zero', !n);
  }
  document.querySelectorAll('.mb-tab').forEach((t) => t.addEventListener('click', () => showTab(t.dataset.tab)));
  // 直橫切換：切 .land（Task 2 有橫式 CSS），停在當前 tab
  const setLand = (land) => { document.getElementById('mb-app').classList.toggle('land', land);
    document.getElementById('mb-opt-portrait').setAttribute('aria-pressed', String(!land));
    document.getElementById('mb-opt-landscape').setAttribute('aria-pressed', String(land)); };
  document.getElementById('mb-opt-portrait').addEventListener('click', () => setLand(false));
  document.getElementById('mb-opt-landscape').addEventListener('click', () => setLand(true));
  // 登出
  document.getElementById('mb-logout').addEventListener('click', async () => { await postJSON('/auth/logout'); location.reload(); });
  // 更新人臉：inline 相機（記憶體不落地）→ /face/enroll（沿用 showAppView 邏輯，見 Step 3）
  wireReface(identity);
  showTab('shoot');   // 進站預設拍單
}
```
> `toast(msg)` 小工具（module 級，操作 `#mb-toast`）供各 pane 用——export 出去或掛 window 皆可；建議 `export function mbToast(msg)`。`identity.store_code`：若後端 index 的 identity 未含 store_code（現為 {id,name,role,store_id}），店徽不顯示即可（**不動後端、不造假**）；未來後端補 store_code 再自然顯示。

- [ ] **Step 3: 更新人臉（inline 相機，沿用 showAppView 的 enroll 邏輯）**

`wireReface(identity)`：點「更新人臉」→ 開 `Camera`（記憶體）→ 再點一次 capture → `POST /face/enroll { face_image }` → toast 結果 → `cam.stop()`。**沿用 `auth.js:showAppView` 49-74 的兩段式流程**（第一次 start+提示、第二次 capture+enroll+finally stop）。可用一個隱藏 `<video>/<canvas>`（append 進殼或 modal）。**影像不落地**：finally 一律 stop。

- [ ] **Step 4: 路由員工進新殼**

- `auth.js`：頂部 `import { showEmployeeApp } from './employee_app.js';`；`submit()` 內 employee 分派（現 `showAppView({name, role})`，~147）改 `showEmployeeApp(identity)`（用完整 identity；若該處只有 {name,role}，補帶 identity 物件——確認 submit 拿得到 role/store_id）。**非員工 fallback 仍呼叫 `showAppView`。**
- `main.js`：re-entry 分派（~168）employee 改 `showEmployeeApp(identity)`。
> `showAppView`（auth.js）**保留不刪**（非員工 fallback）。員工不再走它。

- [ ] **Step 5: 本機驗證殼**

開 server，硬重整 `/dev/login-test`。對照原型：滿版手機殼、抬頭（姓名 + 更新人臉 + 登出 + 直式/橫式切換）、底部 3 tab（拍單/確認區[badge]/複查）可切換（pane 內容此時空白，Task 2/3/5 才填）。更新人臉可開相機、enroll。登出可用。無 console error；`node --test tests/js/*.mjs` 全綠。

- [ ] **Step 6: bump sw(`calc-v62`) + STATIC_URLS 補 employee_app.js + commit**
```bash
# sw.js: CACHE_NAME='calc-v62'；STATIC_URLS 加 '/static/js/employee_app.js'
git add app/static/js/employee_app.js app/static/js/auth.js app/static/js/main.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 員工手機殼 + 底部 tab + 手機 .mb-* 設計層地基"
```

---

## Task 2: 拍單 pane（後鏡頭 + 取景框 + 多拍 + 上傳 + 橫式）

把 `capture.js` 從 modal 版重構成 `renderShootPane(container, {onUploaded})`：取景框 UI + 快門 + 多拍 + 上傳進度，相機改後鏡頭。

**Files:**
- Modify: `app/static/js/capture.js`（`showCaptureView` → `renderShootPane`）
- Modify: `app/static/js/camera.js`（facingMode environment + fallback）
- Modify: `app/static/css/app.css`（手機段落 append 取景框/快門/cam-dock/上傳 + `.mb-app.land` 橫式）
- Modify: `app/static/sw.js`（`calc-v63`）

**Interfaces:**
- Consumes: Task 1 殼（pane 容器、`mbToast`、`showTab`）、`Camera`(camera.js)、`captureUpload`(expenses_api.js)。
- Produces: `export function renderShootPane(container, { onUploaded })`（取代 `showCaptureView`）；上傳完成呼叫 `onUploaded()`（殼會切到確認區）。

- [ ] **Step 1: camera.js 改後鏡頭 + fallback**

`camera.js` `start()`（~17）：`facingMode:'user'` → `facingMode:{ ideal:'environment' }`（後鏡頭拍收據；`ideal` 讓桌機/單鏡頭裝置自動 fallback 不 throw）。其餘（`_e2eSample` 旁路、`toDataURL`、`stop`）**不動**。保持記憶體不落地。
```js
this.stream = await navigator.mediaDevices.getUserMedia({
  video: { facingMode: { ideal: 'environment' } }, audio: false,
});
```

- [ ] **Step 2: 取景框/快門/上傳 CSS（照原型）**

app.css 手機段落 append `.mb-viewfinder`/`.mb-vf-frame`(+`b` 四角)/`.mb-vf-hint`/`.mb-vf-flash`/`.mb-shot-count`/`.mb-cam-dock`/`.mb-shutter`/`.mb-cam-side`/`.mb-upload-panel`(+`.show`)/`.mb-upl-line`/`.mb-upl-bar`(+`i`)/`.mb-upl-done`(+`.show`/`.ok-chip`)，值照原型 `employee-mobile.html:117-158`（`.viewfinder`/`.vf-*`/`.shot-count`/`.cam-dock`/`.shutter`/`.upload-panel`/`.upl-*`），加 mb- 前綴、`var(--wk-x)`/`var(--mb-x)`（相機深色背景用 `--mb-cam`/`--mb-cam-2`）。`#mb-pane-shoot.active{padding:0;display:flex;flex-direction:column;height:100%}`（原型 `#pane-shoot`）。
橫式 `.mb-app.land`：append 原型 `:330-364` 的橫式規則（tab bar → 左側 rail、appbar/content 讓開、拍單相機填滿 + 快門右側垂直置中）加 mb- 前綴。**⚠️ 橫式 tab bar 轉左 rail 常駐、不可 display:none。**

- [ ] **Step 3: 重構 `renderShootPane`**

`capture.js` 改：render 進 `container`（非 `root()` modal）。骨架（沿用 Camera 多拍 + captureUpload 迴圈；UI 換取景框/快門/上傳）：
```js
import { Camera } from './camera.js';
import { captureUpload } from './expenses_api.js';
import { mbToast } from './employee_app.js';   // Task 1 export

export function renderShootPane(container, { onUploaded } = {}) {
  container.innerHTML = `
    <div class="mb-viewfinder">
      <span class="mb-shot-count" id="mb-shot-count">已拍 0 張</span>
      <div class="mb-vf-frame" aria-hidden="true"><b></b></div>
      <p class="mb-vf-hint">將單據對準框內，光線充足、拍清楚金額</p>
      <div class="mb-vf-flash" id="mb-vf-flash" aria-hidden="true"></div>
      <video id="mb-cap-video" autoplay playsinline muted style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:-1"></video>
      <canvas id="mb-cap-canvas" style="display:none"></canvas>
    </div>
    <div class="mb-cam-dock" id="mb-cam-dock">
      <div class="mb-cam-side"><button class="mb-btn mb-btn-ghost mb-btn-sm" id="mb-next" type="button">下一張</button></div>
      <button class="mb-shutter" id="mb-shutter" aria-label="快門" type="button"></button>
      <div class="mb-cam-side"><button class="mb-btn mb-btn-primary mb-btn-sm" id="mb-finish" type="button">完成</button></div>
    </div>
    <div class="mb-upload-panel" id="mb-upload">
      <div id="mb-upl-progress"><p class="mb-upl-line" id="mb-upl-line">上傳中…</p><div class="mb-upl-bar"><i id="mb-upl-fill"></i></div></div>
      <div class="mb-upl-done" id="mb-upl-done"><span class="ok-chip" id="mb-upl-chip"></span>
        <p class="big">背景辨識中，稍後到「確認區」確認</p>
        <button class="mb-btn mb-btn-primary" id="mb-go-confirm" type="button" style="width:100%">前往確認區</button>
        <button class="mb-btn mb-btn-ghost mb-btn-sm" id="mb-shoot-again" type="button" style="width:100%">繼續拍下一批</button></div>
    </div>`;
  const cam = new Camera(container.querySelector('#mb-cap-video'), container.querySelector('#mb-cap-canvas'));
  const shots = [];
  cam.start().catch(() => mbToast('無法開啟鏡頭'));
  const flash = () => { const f = container.querySelector('#mb-vf-flash'); f.classList.remove('on'); void f.offsetWidth; f.classList.add('on'); };
  container.querySelector('#mb-shutter').addEventListener('click', () => {
    if (!cam.isRecording) return;
    shots.push(cam.capture()); flash();                      // base64 記憶體、不落地
    container.querySelector('#mb-shot-count').textContent = `已拍 ${shots.length} 張`;
  });
  container.querySelector('#mb-next').addEventListener('click', () => mbToast('請拍下一張'));
  container.querySelector('#mb-finish').addEventListener('click', async () => {
    if (!shots.length) { mbToast('還沒拍任何單據'); return; }
    cam.stop();
    container.querySelector('#mb-cam-dock').style.display = 'none';
    container.querySelector('#mb-upload').classList.add('show');
    const fill = container.querySelector('#mb-upl-fill'); const line = container.querySelector('#mb-upl-line');
    let ok = 0;
    for (let i = 0; i < shots.length; i++) {
      line.textContent = `上傳中 ${i + 1}/${shots.length}…`;
      try { const { status } = await captureUpload(shots[i]); if (status === 202) ok += 1; } catch (e) { /* 單張失敗略過 */ }
      fill.style.width = `${((i + 1) / shots.length) * 100}%`;
    }
    container.querySelector('#mb-upl-progress').style.display = 'none';
    container.querySelector('#mb-upl-chip').textContent = `✓ 已送出 ${ok}/${shots.length} 張`;
    container.querySelector('#mb-upl-done').classList.add('show');
  });
  container.querySelector('#mb-go-confirm').addEventListener('click', () => { if (onUploaded) onUploaded(); });
  container.querySelector('#mb-shoot-again').addEventListener('click', () => renderShootPane(container, { onUploaded }));
}
```
> ⚠️ 離開拍單 tab 時要 `cam.stop()`——殼切 tab 會重繪其他 pane，但拍單 pane 的相機串流需在切走時關。做法：`renderShootPane` 回傳 cleanup 或殼在切 tab 前對舊 pane 停相機。**簡單解：殼 `showTab` 切走 shoot 前，`container.querySelector('video')?.srcObject?.getTracks().forEach(t=>t.stop())`**（沿用 admin renderActiveTab 停 video 的既有 pattern，見 admin.js:242）。此 Step 要在殼 `showTab`（Task 1）補這段停相機（回頭改 Task 1 殼或在此 task 補）。

- [ ] **Step 4: 驗證（對照原型 + 相機）**

開 server → `/dev/login-test` → 拍單 tab。對照原型：取景框四角 + 提示 + 後鏡頭畫面（手機/DevTools 裝置模擬驗後鏡頭）、快門拍照有 flash + 計數、完成→上傳進度→已送出 chip→前往確認區。切到別的 tab 再回來相機重啟、離開時串流有關（DevTools 看 camera 指示燈熄）。**確認無 `<input capture>`、無下載**（拍照不進相簿）。`node --test` 全綠。

- [ ] **Step 5: bump sw(`calc-v63`) + commit**
```bash
git add app/static/js/capture.js app/static/js/camera.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 拍單 pane 取景框+後鏡頭+多拍上傳（記憶體不落地）"
```

---

## Task 3: 確認區 pane（卡片 + 行內編輯 + 送出/丟棄/重新辨識 + tab badge + 縮圖燈箱）

把 `pending.js` 重構成 `renderConfirmPane(container, {onCountChange})`：單欄卡片取代表格，沿用全部 API 與 `data-f`/`data-act` 契約。

**Files:**
- Modify: `app/static/js/pending.js`（`showPendingView` → `renderConfirmPane`；`showNoReceiptForm` 留給 Task 4）
- Modify: `app/static/css/app.css`（手機段落 append 卡片 `.mb-card`/`.mb-card-head`/`.mb-thumb`/`.mb-dot`/`.mb-card-meta`/`.mb-field`/`.mb-field-row`/`.mb-card-actions`/`.mb-status-strip`/`.mb-skeleton`/`.mb-toolbar`/`.mb-cardlist`/`.mb-zoom-badge`/`.mb-empty-state`）
- Modify: `app/static/sw.js`（`calc-v64`）

**Interfaces:**
- Consumes: Task 1 殼/`mbToast`、`listPending`/`listCategories`/`patchExpense`/`submitExpense`/`discardExpense`/`reocrExpense`(expenses_api.js)、`categoryOptionsHtml`/`parseAmountInput`/`lightLabel`(expenses_util.js)、`formatDateTimeTW`(audit_util.js)、`escapeHtml`(admin_util.js)、`openImageLightbox`(lightbox.js)。
- Produces: `export function renderConfirmPane(container, { onCountChange })`（取代 `showPendingView`）；render 後 + 每次卡片增減呼叫 `onCountChange(pendingCount)`（更新 tab badge）。

- [ ] **Step 1: 卡片 CSS（照原型）**

app.css 手機段落 append，值照原型 `:172-279`（`.toolbar`→`.mb-toolbar`、`.cardlist`→`.mb-cardlist`、`.card`→`.mb-card`、`.card-head`→`.mb-card-head`、`.thumb`(+`.placeholder`)→`.mb-thumb`、`.zoom-badge`→`.mb-zoom-badge`、`.dot`(+`-ok/-warn/-bad`)→`.mb-dot`、`.thumb-wrap`→`.mb-thumb-wrap`、`.card-meta/.card-time`→`.mb-card-meta/.mb-card-time`、`.field(-row)/.f-amt`→`.mb-field(-row)/.mb-f-amt`、`.card-actions`→`.mb-card-actions`、`.status-strip`(+`.pending/.fail`)→`.mb-status-strip`、`.skeleton`→`.mb-skeleton`、`.sent-chip`→`.mb-sent-chip`、`.empty-state`→`.mb-empty-state`），加 mb- 前綴、`var(--wk-x)`。收據縮圖用真 `<img>`（見 Step 2），不搬原型 CSS 假收據。

- [ ] **Step 2: 重構 `renderConfirmPane`（卡片 + 契約沿用）**

`pending.js` 改：三種卡（`pending_ocr` 骨架卡／正常可編輯卡／`ocr_failed` 卡）。**保留所有 handler 契約**（`data-f=summary|category|amount|note|err`、`data-act=submit|del|reocr`、`.au-thumb data-zoom`），只換外層結構/class。骨架（節錄正常卡 + 布線；沿用現行 pending.js 的 change/submit/del/reocr 邏輯）：
```js
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
  container.querySelector('#mb-noreceipt').addEventListener('click', () => showNoReceiptForm(container, tree, () => renderConfirmPane(container, { onCountChange })));  // Task 4
  const list = container.querySelector('#mb-confirm-list');
  const items = data.expenses || [];
  const report = () => { if (onCountChange) onCountChange(list.querySelectorAll('.mb-card:not(.sent)').length); };
  items.forEach((e) => list.appendChild(cardFor(e, tree, report)));
  container.querySelector('#mb-confirm-empty').style.display = items.length ? 'none' : 'block';
  report();
}
```
`cardFor(e, tree, report)` 建一張卡（`document.createElement('div').className='mb-card'`）：
- `pending_ocr`：placeholder 縮圖(🕓 + `.mb-dot.mb-dot-warn`) + `.mb-status-strip.pending`「🕓 辨識中…」+ `.mb-skeleton`，**無 input/按鈕**。
- 正常/`ocr_failed`：真 `<img class="mb-thumb au-thumb" data-zoom>`（無則 placeholder）+ `.mb-dot`(ok/bad) + 拍攝時間 `formatDateTimeTW(e.created_at)` + 摘要 input(`data-f=summary`) + 分類 select(`data-f=category`, `categoryOptionsHtml(tree,e.category_id)`) + 金額 input(`data-f=amount`) + 備註 input(`data-f=note`) + `ocr_failed` 時 `.mb-status-strip.fail`「⚠ OCR 失敗…」+ 動作（`data-act=submit`「送出」/`data-act=del`「丟棄」/`ocr_failed` 加 `data-act=reocr`「重新辨識」）+ `data-f=err`。
布線**沿用現行 pending.js 45-127 的邏輯**：分類 change→`patchExpense(e.id,{category_id})`、備註 change→`patchExpense(e.id,{note})`、送出→`patchExpense`+`submitExpense`（成功移除卡 + `report()`）、丟棄→`discardExpense`（成功移除卡 + `report()`）、重新辨識→`reocrExpense`、縮圖→`openImageLightbox(dataset.zoom)`。送出成功可加 `.mb-sent-chip` 或直接移除卡（原型是換 sent-chip；沿用現行「移除卡」即可，較簡單、與後端一致）。

- [ ] **Step 3: 驗證**

開 server →拍幾張(或 dev sample) → 確認區 tab。對照原型：單欄卡片、辨識中骨架卡、正常卡可改摘要/分類/金額/備註（change 即時存、失敗出聲）、送出移除卡 + tab badge -1、丟棄移除、OCR 失敗卡有重新辨識、縮圖點開燈箱、重整、空狀態。`node --test` + `pytest -q`（後端未動）全綠。

- [ ] **Step 4: bump sw(`calc-v64`) + commit**
```bash
git add app/static/js/pending.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 確認區 pane 卡片化 + 行內編輯/送出/丟棄/重新辨識 + tab badge"
```

---

## Task 4: 無單據建帳 card

把 `showNoReceiptForm` 重構成確認區內的卡片表單（toggle），沿用 `noReceipt` + 可選佐證照（Camera 記憶體）。

**Files:**
- Modify: `app/static/js/pending.js`（`showNoReceiptForm` → 卡片版，簽章 `showNoReceiptForm(container, tree, onDone)`）
- Modify: `app/static/css/app.css`（手機段落 append `.mb-manual-card`）
- Modify: `app/static/sw.js`（`calc-v65`）

**Interfaces:** Consumes Task 1/3。`noReceipt`(expenses_api.js)、`Camera`、`parseAmountInput`/`categoryOptionsHtml`。

- [ ] **Step 1: `.mb-manual-card` CSS**（照原型 `#manualCard` :270-274：accent 邊框 + accent-soft 光暈）。

- [ ] **Step 2: 重構 `showNoReceiptForm(container, tree, onDone)`**

render 進 `#mb-noreceipt-form`（確認區內），一張卡：摘要 input(`#mb-nr-summary`) + 分類 select(`#mb-nr-category`, `categoryOptionsHtml(tree,null)`) + 金額 input(`#mb-nr-amount`) + 原因 input(`#mb-nr-reason`) + 「📷 拍照（選填）」(inline Camera，記憶體，`stopCam` 收) + 送出/取消 + `#mb-nr-err`。**沿用現行 pending.js 135-201 的 noReceipt 提交 + 佐證照邏輯**（`payload={summary,amount,category_id,reason}`，有照片加 `payload.image`；成功 `onDone()` 重繪確認區）。**影像不落地**：拍完/取消/送出一律 `cam.stop()`。

- [ ] **Step 3: 驗證**

確認區「＋無單據建帳」→ 卡片展開、填摘要/分類/金額/原因、可選拍佐證照（相機記憶體、可移除）、送出→建帳成功重繪、取消收合。`node --test` + `pytest -q` 全綠。

- [ ] **Step 4: bump sw(`calc-v65`) + commit**
```bash
git add app/static/js/pending.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 無單據建帳卡片（可選佐證照，記憶體不落地）"
```

---

## Task 5: 複查 pane（唯讀卡片 + 合計 bar + 縮圖燈箱）

把 `review.js` 重構成 `renderReviewPane(container)`：唯讀卡片 + sticky 合計 bar。

**Files:**
- Modify: `app/static/js/review.js`（`showReviewView` → `renderReviewPane`）
- Modify: `app/static/css/app.css`（手機段落 append `.mb-ro-card`/`.mb-ro-line`/`.mb-chip`/`.mb-ro-amt`/`.mb-total-bar`）
- Modify: `app/static/sw.js`（`calc-v66`；STATIC_URLS 若未含 review.js 補上）

**Interfaces:** Consumes Task 1。`listSubmitted`(expenses_api.js)、`formatAmount`/`sumAmounts`(expenses_util.js)、`escapeHtml`、`openImageLightbox`。
- Produces: `export function renderReviewPane(container)`（取代 `showReviewView`）。

- [ ] **Step 1: 唯讀卡/合計 CSS**（照原型 `:281-296`：`.ro-card`→`.mb-ro-card`、`.ro-line/.k/.v`→`.mb-ro-line`、`.chip`→`.mb-chip`、`.ro-amt`→`.mb-ro-amt`、`.total-bar`(sticky bottom)→`.mb-total-bar`）。

- [ ] **Step 2: 重構 `renderReviewPane`**

```js
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
```

- [ ] **Step 3: 驗證**

複查 tab：唯讀卡片（單號/縮圖/摘要/分類 chip/備註/金額）、縮圖點開燈箱、底部 sticky 合計 bar（筆數 + 總額）、空狀態。`node --test` + `pytest -q` 全綠。

- [ ] **Step 4: bump sw(`calc-v66`) + STATIC_URLS 補 review/lightbox/wk_modal + commit**
```bash
git add app/static/js/review.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 複查 pane 唯讀卡片 + 合計 bar"
```

---

## Task 6: 整合驗證 + sw 預快取收尾 + 橫式/平板

**Files:**
- Modify（如需）: `app/static/js/employee_app.js`、`app/static/css/app.css`
- Modify: `app/static/sw.js`（`calc-v67`；確認 STATIC_URLS 含 employee_app/capture/pending/review/camera/lightbox/wk_modal/month_report 等新/漏檔）

- [ ] **Step 1: sw 預快取清單收尾**

核對 `sw.js` STATIC_URLS 涵蓋員工手機用到的全部 JS/CSS（`employee_app.js`/`capture.js`/`pending.js`/`review.js`/`camera.js`/`lightbox.js`/`expenses_api.js`/`expenses_util.js`/`audit_util.js`/`admin_util.js`/`app.css`）。補齊漏的。bump `calc-v67`。

- [ ] **Step 2: 橫式/平板 fallback 收尾**

確認 `.mb-app.land`（橫式）：底部 tab → 左側直向 rail 常駐（**不藏**）、拍單相機填滿 + 快門右側、確認/複查內容讓開左 rail 單欄卡片可上下捲。平板寬視窗（原型 `@media(min-width:1024px)`）：內容仍單欄滿版（user 明確要求單欄）。切直/橫停在當前 tab。

- [ ] **Step 3: 員工全流程回歸（對照原型 + spec 5.2）**

`/dev/login-test` 走完：拍單（後鏡頭/取景框/多拍/上傳→前往確認區）→ 確認區（辨識中骨架/正常卡改欄位送出/丟棄/OCR 失敗重新辨識/無單據建帳/縮圖燈箱/tab badge）→ 複查（唯讀卡+合計）→ 更新人臉 → 登出。全程對照原型視覺、深/淺主題、無 console error、時間台灣時間、**拍照不進相簿**（無 `<input capture>`/下載；相機串流離開即關）。橫式不藏 tab。

- [ ] **Step 4: 全測試綠 + commit**
```
node --test tests/js/*.mjs
python3 -m pytest -q
```
Expected：前端純邏輯測 + 後端 test_expense_* 全綠（後端未動）。
```bash
git add -A app/static
git commit -m "feat(ui): 員工手機整合驗證 + sw 預快取收尾 + 橫式/平板"
```

---

## Self-Review（對照 spec 5.2 + 原型）

**Spec 5.2 / 原型 coverage**：常駐手機殼+底部 tab(Task1)✔ / 卡片式確認區·複查(Task3,5)✔ / 拍單直式取景框+快門+多拍上傳(Task2)✔ / 橫式左 rail+右快門+不藏 tab(Task2,6)✔ / 後鏡頭(Task2)✔ / 無單據建帳(Task4)✔ / 收據縮圖真圖+燈箱(Task3,5)✔ / tab 待確認 badge(Task1,3)✔ / 更新人臉·登出(Task1)✔ / 深淺主題 token 沿用(Task1)✔ / 影像不落地不進相簿(Task2,4 全程 getUserMedia+canvas，無 input capture)✔ / bump sw+補預快取(每 task+Task6)✔。
> 本 plan 僅涵蓋 spec 5.2（員工手機）。經理手機(super-mobile)、主管手機(manager-audit) = 後續獨立 plan。

**Placeholder scan**：無 TBD/TODO；每 code 步驟有骨架；驗證步驟有 URL/預期/對照對象。**外部相依/待確認**：(a) `identity` 是否含 `store_code`（無則店徽不顯示，不動後端）——Task1 已處理；(b) 相機 `facingMode:environment` 真後鏡頭需手機/模擬器驗——Task2/6 已標。

**Type consistency**：`renderShootPane(container,{onUploaded})`/`renderConfirmPane(container,{onCountChange})`/`renderReviewPane(container)`/`showNoReceiptForm(container,tree,onDone)`/`mbToast(msg)`/`showEmployeeApp(identity)` 簽章跨 Task1↔2/3/4/5 一致；沿用既有 `data-f`/`data-act`/`.au-thumb data-zoom`/expenses_api 函式名全不改；`onCountChange` 回 pendingCount → 殼 `setConfirmBadge`。

---

## 風險 / 注意

- **相機串流生命週期**：拍單 pane 有 live `getUserMedia`；切 tab／離開必 `cam.stop()`（Task2 Step3 已在殼 showTab 補停 video 的 pattern）。忘了關＝相機一直亮 + 耗電。
- **影像不落地是鐵律**：全程 `getUserMedia`+canvas（記憶體 base64）；**嚴禁**改用 `<input type=file capture>`（會進系統相機/相簿）。code review 要特別確認這點。
- **舊碼孤兒**：重構後 `showCaptureView`/`showPendingView`/`showReviewView` 舊 modal 版被取代、舊 `.pd-*/.rv-*/.nr-*/.modal-*` CSS 對員工端成孤兒——**本 plan 不刪**（`showAppView` 非員工 fallback 仍用部分 `.modal-*`；且會計/主管殼另用）。待全角色遷移完的收尾 plan 清理。
- **PWA 快取**：每 task bump sw + **補 STATIC_URLS**（現行漏 review/lightbox/wk_modal）；上線一次 bump 到最終版。
- **後端欄位**：`identity.store_code`/班別若後端未回，店徽/班別**不顯示、不造假**（時間鐵律）。未來要顯示需另案補後端（不在本 plan）。
- **測試盲區**：員工 render 層無 DOM 單元測（靠後端 API 測 + 本機目視）；純函式(formatAmount/sumAmounts/parseAmountInput) 維持行為、每 task 重跑 node 測。
