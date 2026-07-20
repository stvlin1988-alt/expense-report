# 經理電腦版工作台 UI 重塑 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把經理／主管後台面板（`showAdminPanel`，`admin.js`）從現行 `.admin-panel`／`.ap-*`（頂欄＋水平分頁）重塑成原型 `manager-desktop.html` 的「208px 側邊欄工作台＋滿版主區＋sticky 毛玻璃工具列」，沿用會計桌機已建好的 `.wk-*` 設計系統，並補齊經理專屬共通元件（全域選店、`.wk-xt` 交叉表、店別管理表、稽核唯讀、月結設定唯讀、帳號/裝置/操作記錄 wk 化）。

**Architecture:** 純前端／CSS／DOM 重塑，**不動後端、不改 API、不改任務流、不碰計算機幌子、角色守門全沿用現況**。沿用會計 pilot 建好的 `.wk-*` 殼/token/卡片/按鈕/`wk_modal`（已在 `app/static/css/app.css` 就緒），只新增經理專屬的 `.wk-*` 元件段落。新殼**同時套用 manager（主管）+ super_admin（經理）兩角色**（user 定案）；nav 分頁與全域選店依 `isSuper` 分權（沿用現況：月報表/店別/月結＝經理專屬）。**稽核：主管可操作（沿用現行編輯/打勾/交班），經理唯讀（僅檢視，無操作鈕）**——依 spec 5.5 + 原型。`month_report.js` 交叉表改 `.wk-xt`（會計＋經理共用，一併升級會計月報表）。視覺 single source of truth = `docs/superpowers/ui-prototypes/manager-desktop.html`。

**Tech Stack:** Vanilla ES module（無框架）、單一 `app/static/css/app.css`、Flask 模板、PWA service worker（`sw.js` 快取靜態清單）。

## 前端驗證策略（本 plan 對 TDD 的 adaptation）

沿用會計桌機 plan 同一套：視覺／DOM 重塑非後端邏輯，故驗證分兩軌：
- **純函式改動** → `node --test tests/js/*.mjs`（既有前端純邏輯測）。本 plan 幾乎不動純函式（`month_report.js` 的 `formatCell`/`pickCell` 維持行為、只改 render 用的 class 與表頭欄位）；每個 task 結尾**重跑既有 node 測確認全綠**。
- **後端未動** → 每個 task 結尾（或整合 task）跑 `python3 -m pytest -q` 確認 561+ 綠沒被誤傷（本 plan 不改後端，僅防呆）。
- **DOM／CSS 重塑** → 本機開 server + dev 登入經理/主管，**對照原型 URL 逐項目視檢**（結構/class/視覺/互動）。

**本機啟動（harness `run_in_background: true`，勿用 shell `&`／nohup 會被 sandbox 殺 exit 144）：**
```
cd ~/projects/expense-report; set -a; . ./.env 2>/dev/null; set +a; export E2E_LOGIN_BYPASS=1 FLASK_APP=wsgi.py; python3 -m flask db upgrade; python3 -m flask run --port 5001 --no-reload
```
- **經理（super_admin）面板入口**：`http://127.0.0.1:5001/dev/login-super`（dev 捷徑，繞過計算機+裝置閘）。
- **主管（manager）面板入口**：`http://127.0.0.1:5001/dev/login-manager`（驗證稽核仍可操作）。
- 對照原型：本機直接開檔 `docs/superpowers/ui-prototypes/manager-desktop.html`。
- **改前端後**：瀏覽器硬重整（避開 sw 快取）；每個 task 的最後一步 bump `sw.js` CACHE_NAME（現 `calc-v54` → 本 plan 依序 `calc-v55`…`calc-v61`）。
- ⚠️ dev.db 目前可能只有 1 期、少量店/單；驗證交叉表/稽核多店時，若資料太少可先用會計/員工流建幾筆或多開幾家店（`/dev/login-super` → 店別管理新增 TP/TC/KH）。

---

## Global Constraints

以下每個 task 都隱含適用（值逐字取自 spec `docs/superpowers/specs/2026-07-17-ui-redesign-design.md` 與原型 `manager-desktop.html`）：

- **不碰計算機幌子**（`calculator.js`/`secret.js`），不改後端/API/任務流；**角色守門全沿用現況**（月報表 reports/monthly＝accountant+super_admin；月結 periods GET＝accountant+super_admin，PATCH 僅 accountant；店別 CRUD＝super_admin；稽核＝manager+super_admin；帳號/裝置/操作記錄＝manager+super_admin）。
- **設計 token 已就緒**：`app/static/css/app.css` 內 `--wk-*`（含 light/dark 三段）已由會計 pilot 建立，**本 plan 直接沿用、勿重定義**。經理原型 `manager-desktop.html` 的 `:root` 值與會計版**完全相同**（原型註解已載明「完全沿用 accountant-desktop.html 定案 token，勿改值」）。
- **店別一律英文代號**（`s.code`，≤2 字母），**絕不露中文店名**。→ 現行多處已用 `s.code`（admin.js `storeOpts`/`renderStores`），但 `month_report.js` 表頭仍用 `s.name`（見下 Task 2），重塑要改 `s.code`（後端 `build_cross_table` 回的 `stores[].name` 實際就是 code，見 reports/service.py，可直接用）。
- **時間台灣時間**（`formatDateTimeTW` from `audit_util.js`）；**營業日 08:00 分界**。
- **負數金額紅字**（`.num.neg`，U+2212 減號 `−`），金額 `tabular-nums`。
- **卡片/表格一律 `border-collapse:separate;border-spacing:0`**（sticky 首欄與 collapse 不相容的踩雷，交叉表/店別表/稽核表都適用）。
- **「刪除店」正式版不接給經理**（spec 第 8 節定案）：店別管理原型有刪除鈕，但**實作隱藏/停用**該鈕（保留「檢視顯示」+「對外連結」兩控制即可）。
- **CSS 組織**：`app.css` 單檔分區（新增「經理工作台元件」段落，清楚註解），不拆多檔、不引入 partial。
- **每次改 css/js → bump `sw.js` CACHE_NAME**（現 `calc-v54` → 本 plan 依序遞增）。

---

## File Structure

| 檔案 | 動作 | 責任 |
|---|---|---|
| `app/static/js/admin.js` | Modify | `shellHtml()` 換 `.wk-*` 側邊欄殼＋全域選店搬進側欄；`mount()` 綁定改新 class；`renderActiveTab()` 分頁改 key（`report`/`audit`/`stores`/`closing`/`accounts`/`devices`/`logs`/`mypw`）；`renderMonthly` 拆成 `renderReport`＋`renderClosing`；`renderStores` 改 `.wk-store-table`；`renderMyPassword` 改 `.wk-card`。 |
| `app/static/js/month_report.js` | Modify | 交叉表 `.pd-table mr-table` → `.wk-xt`（sticky 首欄 separate）；表頭 `s.name` → `s.code`；`.rc-amt/.rc-neg` → `.num/.num.neg`。`.mr-toggle/.mr-major-row/.mr-child-row/.mr-total-row` data 契約維持。**會計端共用、一併升級。** |
| `app/static/js/admin_audit.js` | Modify | `renderAudit` 內 `isSuper` 分流：經理→**唯讀 wk render**（依營業日分組、燈號+徽章、返回全部門市 bar、空狀態，無操作鈕/action bar）；主管→沿用現行可操作流程但套 `.wk-*` class。 |
| `app/static/js/admin_accounts.js` | Modify | `.ap-table/.ap-form/.ap-btn/.ap-badge` → `.wk-*` 對應；id/data-attr/handler 契約全維持。 |
| `app/static/js/admin_devices.js` | Modify | 同上（`.ap-*` → `.wk-*`）。 |
| `app/static/js/admin_logs.js` | Modify | `.pd-table/.au-day-nav/.ap-empty` → `.wk-*` 對應。 |
| `app/static/css/app.css` | Modify（append「經理工作台元件」段落，在會計 pilot 段落之後） | 新增：`.wk-store-scope*`、`.wk-nav-ico`/`.wk-nav-ro`、`.wk-badge*`、`.wk-xt*`（交叉表）、`.wk-store-table`/`.wk-sc-code`/`.wk-chk-inline`/`.wk-add-row`/`.wk-legend-hint`、`.wk-audit-table`/`.wk-day-head`/`.wk-lamp`/`.wk-dot*`/`.wk-chip`/`.wk-empty-tip`/`.wk-audit-back-bar`、`.wk-ro-banner`/`.wk-ro-card`/`.wk-kv-row`/`.wk-grid-2`、`.wk-pw-*`。舊 `.ap-*/.pd-*/.mr-*` 段落**保留不動**（會計月報表 tableHtml 若還用 `.pd-table-wrap` 外層也不影響）。 |
| `app/static/sw.js` | Modify（每 task） | bump CACHE_NAME。 |

**Task 邊界原則**：每個 task 是「一個可對照原型獨立目視驗收的交付」。新 CSS 段落折入第一個需要它的 task。**先做殼（Task 1）打底，之後各 view 逐一 wk 化，每步殼在但內容漸進**。

**共用 `ctx()` 契約（admin.js:62）不變**：`{identity, storeId, stores, api, reload, refreshStores}` 續傳給 `renderAccounts`/`renderDevices`。

---

## Task 1: 經理側邊欄工作台殼 + 全域選店 + nav 分權

把 `showAdminPanel` 的 `.admin-panel` 頂欄殼換成原型 `.wk-*` 側邊欄殼，全域選店（現 `#ap-store`）搬進側欄頂部，nav 依 `isSuper` 分權並改用原型的 8 分頁 key。這是後續 task 的地基。此 task 後各 view 內容仍是舊 `.ap-*` 樣式（過渡），只有「殼＋選店＋切分頁」是新的。

**Files:**
- Modify: `app/static/js/admin.js`（`tabs` ~29、`shellHtml` ~39、`renderMonthly` 拆分見下、`renderActiveTab` ~239、`mount` ~257）
- Modify: `app/static/css/app.css`（append「經理工作台元件」段落起頭：`.wk-store-scope*`、`.wk-nav-ico`、`.wk-nav-ro`、`.wk-badge*`）
- Modify: `app/static/sw.js`（CACHE_NAME → `calc-v55`）

**Interfaces:**
- Consumes: 會計 pilot 已建的 `.wk-app`/`.wk-sidebar`/`.wk-brand*`/`.wk-nav`/`.wk-nav-item`/`.wk-side-foot`/`.wk-side-user`/`.wk-avatar`/`.wk-main`/`.wk-btn*`（app.css 既有）。
- Produces: 新殼 DOM 契約供後續 task —— 主區內容掛載點 `#ap-body`（**id 維持不變**，各 render 函式不用改抓取）；全域選店 `#ap-store`（維持 id，change handler 沿用）；nav 按鈕 `.wk-nav-item[data-tab][aria-current=page]`；分頁 key＝`report`/`audit`/`stores`/`closing`/`accounts`/`devices`/`logs`/`mypw`。新 CSS class：`.wk-store-scope`/`.wk-store-scope-label`/`.wk-store-scope-sel`、`.wk-nav-ico`、`.wk-nav-ro`、`.wk-badge`(+`-open`/`-pending`/`-done`/`-bad`/`-neutral`/`-scope`/`-locked`)。

- [ ] **Step 1: 搬經理工作台元件 CSS 進 app.css（段落起頭 + 選店 + nav 裝飾 + badge）**

在 `app/static/css/app.css` 末尾（會計工作台段落之後）append，用註解分區。值逐字取自原型 `manager-desktop.html` `<style>`，class 統一加 `wk-` 前綴（原型是 `.store-scope`→`.wk-store-scope`、`.nav-ico`→`.wk-nav-ico`、`.nav-ro`→`.wk-nav-ro`、`.badge`→`.wk-badge`）：
```css
/* ============================================================
   經理工作台元件（UI 重塑 2026-07；super_admin/manager 桌機）
   沿用會計 pilot 的 --wk-* token 與殼；本段只新增經理專屬元件。
   視覺 SoT: docs/superpowers/ui-prototypes/manager-desktop.html
   ============================================================ */
/* 全域選店（側欄頂部；一個動作同時決定 稽核＋月報表） */
.wk-store-scope{ padding:14px 14px 12px; border-bottom:1px solid var(--wk-line-soft); }
.wk-store-scope-label{ display:block; font-size:12px; color:var(--wk-faint); margin-bottom:6px; letter-spacing:.03em; }
.wk-store-scope-sel{ width:100%; height:36px; padding:0 30px 0 12px; appearance:none; -webkit-appearance:none;
  border:1.5px solid var(--wk-accent); border-radius:var(--wk-radius-sm);
  background-color:var(--wk-accent-soft); color:var(--wk-accent-ink);
  font-size:13px; font-weight:700; letter-spacing:.03em; cursor:pointer;
  background-image:url("data:image/svg+xml;charset=utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%238896A8' stroke-width='1.6' stroke-linecap='round'/%3E%3C/svg%3E");
  background-repeat:no-repeat; background-position:right 10px center; }
.wk-store-scope-sel:focus{ box-shadow:0 0 0 3px var(--wk-accent-soft); outline:none; }
/* nav 圖示 + 唯讀標記 */
.wk-nav-ico{ width:18px; height:18px; flex:none; display:inline-block; }
.wk-nav-ico svg{ display:block; width:18px; height:18px; stroke:currentColor; fill:none; stroke-width:1.7; stroke-linecap:round; stroke-linejoin:round; }
.wk-nav-ro{ margin-left:auto; font-size:11px; color:var(--wk-faint); letter-spacing:.02em; }
/* 徽章 / pill */
.wk-badge{ display:inline-flex; align-items:center; gap:5px; padding:2px 9px; border-radius:999px;
  font-size:12px; font-weight:600; line-height:1.6; white-space:nowrap; }
.wk-badge-open,.wk-badge-done{ background:var(--wk-ok-soft); color:var(--wk-ok-ink); }
.wk-badge-pending{ background:var(--wk-warn-soft); color:var(--wk-warn-ink); }
.wk-badge-bad{ background:var(--wk-bad-soft); color:var(--wk-bad-ink); }
.wk-badge-neutral,.wk-badge-locked{ background:var(--wk-neutral-soft,#EDF1F7); color:var(--wk-muted); }
.wk-badge-scope{ background:var(--wk-accent-soft); color:var(--wk-accent-ink); font-variant-numeric:tabular-nums; }
```
> 註：`--wk-neutral-soft` 若會計段落未定義，於此段的 `:root`（沿用既有 :root）補 `--wk-neutral-soft:#EDF1F7`（dark `#252D39`），值取原型 `--neutral-soft`。

- [ ] **Step 2: 改 `tabs` 定義（8 分頁，分權，拆 monthly→report+closing）**

`admin.js` `tabs`（~29）改為（含原型 icon 之後在 shellHtml 塞；此處先定 key/label/是否 super-only）：
```js
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
```
> 預設分頁：`state.tab` 初值（~14）改為 `isSuper ? 'report' : 'audit'`（經理進站看月報表、主管看稽核）。

- [ ] **Step 3: 改 `shellHtml()` 成 `.wk-*` 側邊欄殼 + 全域選店進側欄**

`shellHtml()`（~39）改輸出側欄殼：品牌「雜支管理／經理工作台」、全域選店 `.wk-store-scope`（**僅 isSuper**）、nav（`.wk-nav-item[data-tab]`，唯讀分頁帶 `.wk-nav-ro`）、側欄底部登入者＋登出、主區 `.wk-main > #ap-body`。骨架：
```js
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
```
> `#ap-body`、`#ap-store`、`#ap-logout` id 全維持（`mount()`/`renderActiveTab`/`refreshStores` 靠這些 id）。原型的 nav 有 SVG icon——**先不放 icon**（純文字 label 即可過驗收；icon 屬視覺細節，可在整合 Task 收尾補，避免 Task 1 過肥）。若要放，用原型 `manager-desktop.html:494-510` 的 `<span class="wk-nav-ico"><svg…></span>`。

- [ ] **Step 4: 改 `renderActiveTab()` 分頁分派（report/closing 拆分）**

`renderActiveTab()`（~239）：`monthly` 分派拆成 `report`＋`closing`；其餘 key 對應現有 render（暫時仍畫舊樣式，後續 task 逐一 wk 化）。骨架：
```js
if (state.tab === 'accounts') renderAccounts(body, ctx());
else if (state.tab === 'devices') renderDevices(body, ctx());
else if (state.tab === 'audit') renderAudit(body, identity, state.storeId);
else if (state.tab === 'logs') renderLogs(body, identity, state.storeId);
else if (state.tab === 'stores') renderStores(body);
else if (state.tab === 'report') renderReport(body);       // Task 2（先放 stub：呼叫現行 renderMonthly 的月報表段）
else if (state.tab === 'closing') renderClosing(body);     // Task 3（先放 stub：呼叫現行 renderMonthly 的設定段）
else if (state.tab === 'mypw') renderMyPassword(body);
```
> **本 task 先把 `renderMonthly` 拆成兩個薄函式** `renderReport(container)`（畫月報表，內容沿用現行 `renderMonthReport(reportDiv,{storeId,lockStore:true})`）與 `renderClosing(container)`（畫月結設定純文字，沿用現行 `periodsApi.getSettings()` 那段）。**此 task 只搬程式、維持舊樣式**，wk 化留 Task 2/3。

- [ ] **Step 5: 改 `mount()` 綁定（nav 用 .wk-nav-item + aria-current）**

`mount()`（~257）：`root().querySelectorAll('.ap-tab')` → `.wk-nav-item`；active 態改切 `aria-current="page"`（非 `.active` class）。骨架：
```js
root().querySelectorAll('.wk-nav-item').forEach((btn) => {
  btn.addEventListener('click', () => {
    state.tab = btn.dataset.tab;
    root().querySelectorAll('.wk-nav-item').forEach((b) => b.removeAttribute('aria-current'));
    btn.setAttribute('aria-current', 'page');
    window.scrollTo(0, 0);
    renderActiveTab();
  });
});
```
> `#ap-logout`、`#ap-store` 的 change/click 綁定**不變**（id 沿用）。`renderActiveTab` 開頭停掉 live video track 那段（~242）保留。

- [ ] **Step 6: 本機驗證殼**

開 server（見上），瀏覽器硬重整。
- 開 `/dev/login-super`：對照原型 `manager-desktop.html`——左側 208px 側欄（品牌＋門市範圍下拉＋月報表/稽核/店別管理/月結設定🔒/帳號/裝置/操作記錄/我的密碼 nav＋底部姓名/登出），主區滿版淺色。點 nav 會切分頁（內容此時仍舊樣式，能切即可）。選店下拉改變會重繪當前分頁。深/淺主題跟隨系統。
- 開 `/dev/login-manager`：側欄**無**門市範圍下拉、nav 只有稽核/帳號/裝置/操作記錄/我的密碼（無月報表/店別/月結）。
- 無 console error；`node --test tests/js/*.mjs` 全綠。

- [ ] **Step 7: bump sw(`calc-v55`) + commit**
```bash
# sw.js: const CACHE_NAME = 'calc-v55';
git add app/static/js/admin.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 經理後台改工作台側邊欄殼 + 全域選店進側欄 + nav 分權"
```

---

## Task 2: 月報表交叉表 `.wk-xt`（sticky 首欄，會計＋經理共用升級）

把 `month_report.js` 交叉表從 `.pd-table mr-table` 升級成原型 `.wk-xt`（sticky 首欄、店別英文代號、可展開子分類），並讓經理月報表 view 套工作台工具列＋卡片，全域選店同步。**此檔會計端共用，一併升級會計月報表外觀。**

**Files:**
- Modify: `app/static/js/month_report.js`（`tableHtml` ~66、`headerHtml` ~87、`cellHtml` ~24、`majorRowHtml`/`childRowHtml`/`footerRowHtml`）
- Modify: `app/static/js/admin.js`（`renderReport` ~Task1：套工具列＋卡片＋工具列鏡像選店）
- Modify: `app/static/css/app.css`（經理段落 append `.wk-xt*`）
- Modify: `app/static/sw.js`（`calc-v56`）

**Interfaces:**
- Consumes: Task 1 殼/工具列/卡片/badge、`.num`/`.neg`。
- Produces: `.wk-xt` 交叉表（`.wk-xt-one` 單店窄表）。`renderMonthReport(container,{periodId,storeId,lockStore})` 簽章**不變**（會計端 reconcile.js 也呼叫，契約維持）。純函式 `formatCell`/`pickCell` 行為不變。

- [ ] **Step 1: `cellHtml`/`tableHtml` 套 `.wk-xt`，表頭改 code**

`month_report.js`：
- `cellHtml`（~24）：`<span class="rc-amt${negative?' rc-neg':''}">` → `<td class="num${negative?' neg':''}">…</td>`（原型金額 td 直接帶 class，不再包 span）。同步調整 `perStoreTds`/`majorRowHtml`/`childRowHtml`/`footerRowHtml` 產出的 td（現在 cellHtml 已回整個 `<td>`，改成回 `.num` td）。
- `tableHtml`（~66）：外層 `.pd-table-wrap` → `.table-wrap`；`<table class="pd-table mr-table${storeId?' mr-single':''}">` → `<table class="wk-xt${storeId?' wk-xt-one':''}">`；表頭首格「科目」保留、店別欄 `s.name` → `s.code`（`data.stores[].name` 實為 code，直接用，仍寫 `s.name` 取值但語意是 code——**加註解說明**；若要更清楚可 `s.code || s.name`）。展開鈕 `.mr-toggle`（~37）改用原型三角形：`<button class="wk-cat-toggle" data-idx="${idx}" aria-expanded="false"><span class="wk-tri"></span>${name}</button>`（保留 `data-idx` 契約，`wireToggles` 靠它）；子類列 `.mr-child-row` 保留（`wireToggles` 靠 `[data-parent-idx]`）。總計欄套 `.wk-xt-tot`。
> ⚠️ `.wk-xt` sticky 首欄踩雷：CSS 必 `border-collapse:separate;border-spacing:0`，首欄 `position:sticky;left:0`（見 Step 2 CSS，照原型 `.xt`）。
> ⚠️ `wireToggles`（~106）現用 `▶/▼` textContent 切換；改用三角形 CSS 後，`wireToggles` 內 `btn.textContent = expanded?'▶':'▼'` 這行**移除**（改由 `.wk-cat-toggle[aria-expanded] .wk-tri` CSS 旋轉），只留 `aria-expanded` 切換 + child rows `hidden` 切換。

- [ ] **Step 2: `.wk-xt` CSS（照原型 `.xt`，加 wk- 前綴）**

app.css 經理段落 append，值逐字取自原型 `manager-desktop.html:242-280`（`.xt`→`.wk-xt`、`.tot-col`→`.wk-xt-tot`、`.sub-row`→用既有 `.mr-child-row`? 不——原型用 class 標記，這裡沿用既有 `.mr-child-row`/`.mr-total-row` 選擇器套原型 sub-row/total-row 樣式；`.cat-toggle`→`.wk-cat-toggle`、`.tri`→`.wk-tri`）：
```css
.wk-xt{ border-collapse:separate; border-spacing:0; width:100%; min-width:640px; font-size:13px; }
.wk-xt th,.wk-xt td{ padding:10px 14px; text-align:right; border-bottom:1px solid var(--wk-line-soft);
  white-space:nowrap; background:var(--wk-surface); }
.wk-xt thead th{ font-size:12px; font-weight:600; color:var(--wk-faint); letter-spacing:.04em; border-bottom:1px solid var(--wk-line); }
.wk-xt th:first-child,.wk-xt td:first-child{ text-align:left; position:sticky; left:0; z-index:2;
  min-width:168px; box-shadow:var(--wk-sticky-col-shadow, 1px 0 0 0 var(--wk-line)); }
.wk-xt td{ font-variant-numeric:tabular-nums; }
.wk-xt tbody tr:hover td{ background:var(--wk-surface-2); }
.wk-xt .wk-xt-tot{ background:var(--wk-accent-soft); color:var(--wk-accent-ink); font-weight:700; }
.wk-xt tr.mr-total-row td{ font-weight:700; border-top:2px solid var(--wk-line); border-bottom:0; }
.wk-xt tr.mr-child-row td{ background:var(--wk-surface-2); color:var(--wk-muted); font-size:12px; font-weight:400; }
.wk-xt tr.mr-child-row td:first-child{ padding-left:38px; background:var(--wk-surface-2); }
.wk-cat-toggle{ background:none; border:0; padding:0; display:inline-flex; align-items:center; gap:7px;
  font-size:13px; font-weight:600; color:var(--wk-ink); }
.wk-tri{ width:0; height:0; border-left:5px solid var(--wk-faint); border-top:4px solid transparent;
  border-bottom:4px solid transparent; transition:transform .12s; flex:none; }
.wk-cat-toggle[aria-expanded="true"] .wk-tri{ transform:rotate(90deg); }
.wk-xt.wk-xt-one{ min-width:420px; max-width:560px; }
```
> `--wk-sticky-col-shadow`：若會計段落未定義，於 :root 補（值取原型 `--sticky-col-shadow`，light `1px 0 0 0 var(--wk-line),9px 0 12px -8px rgba(20,28,40,.14)`；dark 版同理）。

- [ ] **Step 3: `renderReport`（admin.js）套工具列＋卡片＋鏡像選店**

`renderReport(container)`（Task 1 建的薄函式）改為原型 `#view-report` 結構：`.wk-toolbar`（期間標題＋範圍徽章＋工具列鏡像選店 `#report-scope-sel`＋匯出 CSV 佔位可省）＋`.wk-page-body > .wk-card`（card-head「店 × 科目 交叉表」＋範圍 badge `#report-scope-badge`＋提示；card-body `#report-wrap` 掛 `renderMonthReport`）。工具列鏡像選店與側欄 `#ap-store` 同步：change 時 `state.storeId=…`、寫 localStorage、`refreshStores`? 不需——只需更新 `#ap-store.value`＋重繪 report。骨架：
```js
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
```
> `.wk-toolbar-title`/`.wk-spacer`/`.wk-filter-label`/`.wk-report-note` 若無，於 CSS 補小樣式（`title`＝17px/700；`spacer`＝`flex:1`；`filter-label`＝12px faint；`report-note`＝12px faint padding）。原型對應 `.period-title`/`.spacer`/`.filter-label`/`.report-note`。

- [ ] **Step 4: 驗證（對照原型）**

開 server →（A）`/dev/login-super` 月報表：交叉表科目欄 sticky 釘左橫捲不動、全部門市＝各店一欄(英文 code)+總計欄、選單店＝科目→金額窄表(`.wk-xt-one`)、點科目展開子分類（三角形轉向）、負數紅字、`tabular-nums`、側欄/工具列兩個選店同步。（B）`/dev/login-accountant` → 月報表分頁：確認會計端月報表也升級成同 `.wk-xt`（共用檔，預期一起變）、店別顯示 code。
- `node --test tests/js/*.mjs` 全綠（`formatCell`/`pickCell` 測不受影響）。

- [ ] **Step 5: bump sw(`calc-v56`) + commit**
```bash
git add app/static/js/month_report.js app/static/js/admin.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 月報表交叉表 .wk-xt sticky 首欄 + 店別英文代號（會計/經理共用升級）"
```

---

## Task 3: 月結設定 view（唯讀🔒）

`renderClosing` 改為原型 `#view-closing` 唯讀結構：鎖頭橫幅（僅會計可改）＋兩張唯讀卡（目前設定 kv／本期時程 kv）。資料＝`periodsApi.getSettings()`＋`periodsApi.list()`（取當期 label/end_date）。

**Files:**
- Modify: `app/static/js/admin.js`（`renderClosing`；頂部 `import { periodsApi } from './periods_api.js'` 已有）
- Modify: `app/static/css/app.css`（經理段落 append `.wk-ro-banner`/`.wk-ro-card`/`.wk-grid-2`/`.wk-kv-row`）
- Modify: `app/static/sw.js`（`calc-v57`）

**Interfaces:** Consumes Task 1 殼/卡片/badge。`periodsApi.getSettings()`→`{period_close_day, period_lock_offset_hours}`；`periodsApi.list()`→`{periods:[{id,label,status,start_date,end_date}]}`（GET /periods/，super_admin 可讀）。

- [ ] **Step 1: `.wk-ro-*` CSS（照原型）**

app.css 經理段落 append，值取原型 `manager-desktop.html:371-385`（`.ro-banner`→`.wk-ro-banner`、`.ro-card`→`.wk-ro-card`、`.grid-2`→`.wk-grid-2`、`.kv-row`→`.wk-kv-row`）：
```css
.wk-ro-banner{ display:flex; align-items:center; gap:10px; background:var(--wk-neutral-soft,#EDF1F7);
  border:1px solid var(--wk-line-soft); border-radius:var(--wk-radius); padding:12px 16px; font-size:13px; color:var(--wk-muted); }
.wk-ro-banner b{ color:var(--wk-ink); }
.wk-ro-card{ background:var(--wk-surface-2); }
.wk-grid-2{ display:grid; grid-template-columns:1fr 1fr; gap:18px; align-items:start; }
@media (max-width:1100px){ .wk-grid-2{ grid-template-columns:1fr; } }
.wk-kv-row{ display:flex; justify-content:space-between; gap:16px; padding:9px 0;
  border-bottom:1px dashed var(--wk-line-soft); font-size:13px; }
.wk-kv-row:last-child{ border-bottom:0; }
.wk-kv-row .k{ color:var(--wk-muted); }
.wk-kv-row .v{ font-weight:600; font-variant-numeric:tabular-nums; text-align:right; }
```

- [ ] **Step 2: 改 `renderClosing`（唯讀橫幅＋兩張 kv 卡）**

```js
async function renderClosing(container) {
  container.innerHTML = `
    <div class="wk-toolbar"><div class="wk-toolbar-row">
      <span class="wk-toolbar-title">月結設定</span>
      <span class="wk-badge wk-badge-locked">🔒 唯讀</span>
    </div></div>
    <div class="wk-page-body">
      <div class="wk-ro-banner"><span>月結設定僅供檢視——只有<b>會計</b>可修改月結日與鎖定偏移。如需調整請聯絡會計。</span></div>
      <div class="wk-grid-2" id="closing-cards"><div class="wk-empty">載入中…</div></div>
    </div>`;
  const cards = container.querySelector('#closing-cards');
  try {
    const [{ data: st }, { data: pl }] = await Promise.all([periodsApi.getSettings(), periodsApi.list()]);
    const cur = (pl.periods || [])[0] || null; // 清單新到舊，[0]=最新一期
    const closeDay = st.period_close_day, lockH = st.period_lock_offset_hours;
    cards.innerHTML = `
      <div class="wk-card wk-ro-card"><div class="wk-card-head"><span class="wk-card-title">目前設定</span>
        <span class="wk-badge wk-badge-locked">僅會計可改</span></div>
        <div class="wk-card-body">
          <div class="wk-kv-row"><span class="k">月結日</span><span class="v">每月 ${escapeHtml(String(closeDay))} 日</span></div>
          <div class="wk-kv-row"><span class="k">鎖定偏移</span><span class="v">封月後 ${escapeHtml(String(lockH))} 小時</span></div>
          <div class="wk-kv-row"><span class="k">營業日分界</span><span class="v">08:00（台灣時間）</span></div>
        </div></div>
      <div class="wk-card wk-ro-card"><div class="wk-card-head"><span class="wk-card-title">本期時程</span>
        <span class="wk-badge wk-badge-neutral">台灣時間</span></div>
        <div class="wk-card-body">
          <div class="wk-kv-row"><span class="k">期間</span><span class="v">${cur ? escapeHtml(cur.label) : '—'}</span></div>
          <div class="wk-kv-row"><span class="k">起訖</span><span class="v">${cur ? `${escapeHtml(cur.start_date)} – ${escapeHtml(cur.end_date)}` : '—'}</span></div>
          <div class="wk-kv-row"><span class="k">狀態</span><span class="v">${cur ? escapeHtml(cur.status) : '—'}</span></div>
        </div></div>`;
  } catch (e) {
    cards.innerHTML = '<div class="wk-empty">載入失敗，請重試</div>';
  }
}
```
> 原型「預計封月時間/封月後鎖定」用假時間；實作只放後端**確有回傳**的欄位（label/start/end/status），不自行推算封月時刻（避免露錯時間，違反時間硬規則）。`periodsApi.list` 若無此 method 需在 `periods_api.js` 確認（第二段 session 已加 `list()`，見 periods_api.js）。

- [ ] **Step 3: 驗證**

`/dev/login-super` → 月結設定：鎖頭橫幅 + 兩張唯讀卡（月結日/鎖定偏移/營業日分界 + 本期 label/起訖/狀態），無任何可編輯輸入。`node --test` 全綠。

- [ ] **Step 4: bump sw(`calc-v57`) + commit**
```bash
git add app/static/js/admin.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 經理月結設定 view 唯讀（鎖頭橫幅 + kv 卡）"
```

---

## Task 4: 店別管理 view（`.wk-store-table`；刪除鈕停用）

`renderStores` 改原型 `#view-stores` 結構：桌機表格（店別 code｜對外狀態｜檢視顯示打勾｜對外連結 kill-switch｜~~刪除~~停用）＋新增店＋說明並排卡。關閉對外連結走 `wk_modal` 確認（取代 `window.confirm`）。**刪除鈕依 spec 第 8 節隱藏/停用。**

**Files:**
- Modify: `app/static/js/admin.js`（`renderStores` ~121；頂部 `import { wkConfirm } from './wk_modal.js'`）
- Modify: `app/static/css/app.css`（經理段落 append `.wk-store-table`/`.wk-sc-code`/`.wk-chk-inline`/`.wk-add-row`/`.wk-legend-hint`）
- Modify: `app/static/sw.js`（`calc-v58`）

**Interfaces:** Consumes Task 1 殼/卡片/按鈕、`wk_modal` 的 `wkConfirm`（會計 pilot 已建）。API 契約不變：`api.getStores`/`setStoreViewable`/`setStoreActive`/`createStore`（`deleteStore` 不再接鈕）。

- [ ] **Step 1: `.wk-store-table` 等 CSS（照原型）**

app.css 經理段落 append，值取原型 `manager-desktop.html:282-306`（`.store-table`→`.wk-store-table`、`.sc-code`→`.wk-sc-code`、`.chk-inline`→`.wk-chk-inline`、`.add-row`→`.wk-add-row`、`.legend-hint`→`.wk-legend-hint`）。表格 `border-collapse:separate;border-spacing:0`。（完整規則照原型逐字搬，加 wk- 前綴、`var(--x)`→`var(--wk-x)`。）

- [ ] **Step 2: 改 `renderStores`（wk 表格 + kill-switch modal + 刪除停用）**

```js
async function renderStores(container) {
  const rows = state.stores.map((s, i) => {
    const view = s.viewable !== false, conn = s.active !== false;
    const st = conn ? '<span class="wk-badge wk-badge-open">連線中</span>' : '<span class="wk-badge wk-badge-bad">已關閉</span>';
    const linkBtn = conn
      ? `<button class="wk-btn wk-btn-danger-soft" data-conn="${s.id}" data-active="1" type="button">關閉對外連結</button>`
      : `<button class="wk-btn wk-btn-ok-soft" data-conn="${s.id}" data-active="0" type="button">開啟對外連結</button>`;
    return `<tr>
      <td><span class="wk-sc-code">${escapeHtml(s.code)}</span></td>
      <td>${st}</td>
      <td><label class="wk-chk-inline"><input type="checkbox" class="st-viewable" data-id="${s.id}"${view ? ' checked' : ''}>顯示於選單／月報表<span class="wk-chk-note">${view ? '' : '（已隱藏，不影響營運）'}</span></label></td>
      <td>${linkBtn}</td>
    </tr>`;
  }).join('');
  container.innerHTML = `
    <div class="wk-toolbar"><div class="wk-toolbar-row"><span class="wk-toolbar-title">店別管理</span>
      <span class="wk-filter-label">「檢視顯示」與「對外連結」為兩個獨立控制，僅經理可改</span></div></div>
    <div class="wk-page-body">
      <div class="wk-card"><div class="table-wrap"><table class="wk-store-table">
        <thead><tr><th style="width:110px">店別</th><th style="width:120px">對外狀態</th><th>檢視顯示（選單／月報表）</th><th>對外連結（kill-switch）</th></tr></thead>
        <tbody id="store-tbody">${rows || '<tr><td colspan="4" class="wk-empty">尚無店別</td></tr>'}</tbody>
      </table></div></div>
      <div class="wk-grid-2">
        <div class="wk-card"><div class="wk-card-head"><span class="wk-card-title">新增店</span></div>
          <div class="wk-card-body"><div class="wk-add-row">
            <input class="wk-input" id="st-code" maxlength="2" placeholder="店別英文代號（≤2 字母，如 TN）" autocomplete="off">
            <button class="wk-btn wk-btn-primary" id="st-add" type="button">新增</button>
          </div><div class="wk-msg" id="st-msg"></div></div></div>
        <div class="wk-card"><div class="wk-card-body wk-legend-hint">
          「<b>檢視顯示</b>」打勾＝這家店會出現在選店選單／月報表；取消只是隱藏，不影響營運。<br>
          「<b>對外連結</b>」關閉＝該店所有人員／主管立即被擋在計算機最外層（真正停用該店）。<br>兩者互不影響，可各自單獨切換。
        </div></div>
      </div>
    </div>`;
  const msg = container.querySelector('#st-msg');
  // 檢視顯示 checkbox（沿用現行 setStoreViewable 邏輯，class 換 st-viewable 保留）
  container.querySelectorAll('input.st-viewable').forEach((cb) => {
    cb.addEventListener('change', async () => { /* …沿用現行 admin.js:160-176 的 setStoreViewable 邏輯… */ });
  });
  // 對外連結 kill-switch：關閉走 wkConfirm modal（取代 confirm）
  container.querySelectorAll('button[data-conn]').forEach((b) => {
    b.addEventListener('click', async () => {
      msg.textContent = '';
      const id = parseInt(b.dataset.conn, 10);
      const next = b.dataset.active !== '1';
      const s = state.stores.find((x) => x.id === id) || {};
      if (!next && !(await wkConfirm({ title: `關閉 ${s.code} 對外連結？`, desc: `關閉後，${s.code} 所有人員／主管會立即被擋在計算機最外層（真正停用該店）。確定要關閉嗎？`, okLabel: '確定關閉', danger: true }))) return;
      try {
        const { status, data } = await api.setStoreActive(id, next);
        if (status === 200 && data.status === 'ok') { await refreshStores(); renderActiveTab(); }
        else { msg.style.color = '#c62828'; msg.textContent = '切換失敗'; }
      } catch (e) { msg.style.color = '#c62828'; msg.textContent = '切換失敗，請重試'; }
    });
  });
  container.querySelector('#st-add').addEventListener('click', async () => { /* …沿用現行 admin.js:191-209 新增店邏輯，code 先 .toUpperCase() + /^[A-Z]{1,2}$/ 驗證… */ });
}
```
> **刪除鈕移除**（spec 第 8 節：不接給經理）。原「操作」欄整欄拿掉（表頭也拿掉），故 colspan 由 5→4。`deleteStore` API 保留在 `admin_api.js` 不動（只是前端不呼叫）。`refreshStores`（~73）內重畫 `#ap-store` 下拉的邏輯保留；本 view 重繪靠 `renderActiveTab`。
> `.wk-btn-ok-soft`/`.wk-btn-danger-soft`：`danger-soft` 會計 pilot 已有；`ok-soft` 若無，於 CSS 補（照原型 `.btn-ok-soft`：`background:var(--wk-ok-soft);color:var(--wk-ok-ink);border-color:var(--wk-ok)`，hover 實心）。`.wk-msg` 若無沿用 `.wk-empty` 或補一個小 `.wk-msg{font-size:13px;margin-top:8px}`。

- [ ] **Step 3: 驗證**

`/dev/login-super` → 店別管理：wk 表格（店別 code pill／連線中·已關閉 badge／檢視顯示打勾／關閉對外連結鈕），**無刪除鈕**。切檢視顯示打勾 → 該店於月報表/選店下拉出現/消失。關閉對外連結 → 跳 `wk_modal` danger 確認、確定後 badge 變已關閉。新增店（1–2 英文字母、重複擋）。`node --test` 全綠。

- [ ] **Step 4: bump sw(`calc-v58`) + commit**
```bash
git add app/static/js/admin.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 店別管理 view wk 表格 + kill-switch app modal（刪除鈕依定案停用）"
```

---

## Task 5: 稽核 view（主管可操作套 wk；經理唯讀新 render）

`admin_audit.js` `renderAudit` 依 `isSuper` 分流：**經理（super_admin）→ 唯讀** wk render（依營業日分組、燈號+徽章、返回全部門市 bar、全部門市時空狀態，**無編輯輸入/打勾/交班 action bar**，照原型 `#view-audit`）；**主管（manager）→ 沿用現行可操作流程**（待稽核編輯/打勾/交班/總表），僅把 `.ap-*/.pd-*` class 套成 `.wk-*` 對照。

**Files:**
- Modify: `app/static/js/admin_audit.js`（`renderAudit` ~8 分流；新增 `renderAuditReadonly`；現行 pending/summary render 的 class wk 化）
- Modify: `app/static/css/app.css`（經理段落 append `.wk-audit-table`/`.wk-day-head`/`.wk-lamp`/`.wk-dot*`/`.wk-chip`/`.wk-empty-tip`/`.wk-empty-stores`/`.wk-audit-back-bar`）
- Modify: `app/static/sw.js`（`calc-v59`）

**Interfaces:** Consumes Task 1 殼、`.wk-store-tag`、`.num`；`openImageLightbox`（lightbox.js，桌機縮放已於會計 pilot 對齊）。API 契約不變（`auditByDate`/`auditPending`/`auditEdit`/`auditCheck`/`auditHandover`）。

- [ ] **Step 1: `.wk-audit-*` CSS（照原型）**

app.css 經理段落 append，值取原型 `manager-desktop.html:308-348`（`.audit-table`→`.wk-audit-table`、`.day-head`→`.wk-day-head`、`.doc-cell`→沿用會計 `.wk-doc-cell`? 原型 audit 的 doc-cell 略不同（min-width 220），可新增 `.wk-audit-doc`；`.lamp`→`.wk-lamp`、`.dot`→`.wk-dot`(+`-g`/`-y`)、`.chip`→`.wk-chip`、`.empty-tip`→`.wk-empty-tip`、`.empty-stores`→`.wk-empty-stores`、`.audit-back-bar`→`.wk-audit-back-bar`）。表格 `border-collapse:separate;border-spacing:0`。

- [ ] **Step 2: `renderAudit` 分流 + `renderAuditReadonly`（經理唯讀）**

`renderAudit`（~8）：`isSuper` 時走新唯讀 render；否則沿用現行（`audit-sub` 兩 tab → 待稽核/總表，可操作）。骨架：
```js
export async function renderAudit(container, identity, storeId) {
  const isSuper = identity.role === 'super_admin';
  if (isSuper) return renderAuditReadonly(container, storeId);
  // …主管：沿用現行 audit-sub + renderPending/renderSummary（class 於 Step 3 wk 化）…
}
```
`renderAuditReadonly(container, storeId)`：全部門市（storeId null）→ 空狀態卡＋各店快速鍵（照原型 `empty-tip`）；選定店 → 返回 bar ＋依營業日分組唯讀表（照原型 `renderAudit` 假資料版：doc-cell 收據縮圖 + 摘要/單號/建立者/時間 + 備註、店別 tag、分類 chip、金額 `.num`、燈號+徽章）。資料來源用 `api.auditByDate(sid, today)`（取當前營業日）或 `auditSummaryDates` + `auditByDate`（沿用現行 `renderSummary` 的取數方式），**只 render 不 wire 任何編輯**。收據縮圖用真 `<img class="au-thumb" data-zoom>`（點開 `openImageLightbox`），非原型 CSS 假收據。骨架（節錄核心列）：
```js
async function renderAuditReadonly(container, storeId) {
  if (storeId == null) {
    const btns = /* 各 viewable 店：<button class="wk-btn wk-btn-secondary" data-pick=id>code</button> */;
    container.innerHTML = `<div class="wk-toolbar"><div class="wk-toolbar-row"><span class="wk-toolbar-title">交接班稽核</span><span class="wk-badge wk-badge-locked">唯讀</span><span class="wk-spacer"></span><span class="wk-badge wk-badge-scope">全部門市</span></div></div>
      <div class="wk-page-body"><div class="wk-empty-tip">請先在左側「<b>門市範圍</b>」選擇一家店<br><span style="font-size:12px;color:var(--wk-faint)">選店同時決定稽核與月報表看哪家</span><div class="wk-empty-stores">${btns}</div></div></div>`;
    /* wire data-pick → 設 #ap-store.value + state.storeId + reload（呼叫 ctx().reload 或直接觸發 store change）*/
    return;
  }
  /* 取數：auditSummaryDates(sid) → today → auditByDate(sid, today) → shifts/items；
     render 依營業日/班別分組唯讀表：wk-audit-back-bar（返回全部門市→設 #ap-store=''）+ wk-card > wk-audit-table。
     每列：doc-cell(縮圖+摘要+單號·建立者·時間) | wk-store-tag | wk-chip 分類 | num 金額 | 燈號(wk-lamp+wk-dot)+徽章(wk-badge)。
     縮圖 .au-thumb 點擊 openImageLightbox。無操作鈕、無 action bar。*/
}
```
> 「返回全部門市」＝把側欄 `#ap-store` 設空 + `state.storeId=null` + 重繪。因 `renderAuditReadonly` 在 admin_audit.js（拿不到 admin.js 的 state），做法：**經理唯讀的返回/選店一律操作 `#ap-store` DOM 並 dispatch `change` 事件**（`document.getElementById('ap-store')` 設值後 `.dispatchEvent(new Event('change'))`，觸發 admin.js mount 綁的 handler → 更新 state + renderActiveTab）。這樣不需把 state 傳進來，契約最小。

- [ ] **Step 3: 主管流程 class wk 化（不改行為）**

現行 `renderPending`/`renderSummary`/`rowHtml`/`actionBar` 的 class 對照換：`.au-group`→`.wk-card`+`.wk-card-head`（日/班標頭）、`.pd-table`→`.wk-audit-table`、`.pd-table-wrap`→`.table-wrap`、`.ap-empty`→`.wk-empty`、`.modal-btn`→`.wk-btn`(action bar 交班/結班用 `.wk-btn-primary`、取消 `.wk-btn-secondary`)、金額/備註 input 換 `.wk-input`、打勾鈕 `.wk-btn wk-btn-sm wk-btn-primary`。**所有 `data-id`/`data-f`/`data-act`/`data-trail`/`.au-thumb`/`#au-subtotal` id 契約全維持**（`wireRows`/`wireTrails`/`actionBar` 不改邏輯）。
> 此步是機械 class swap，主管待稽核/總表/交班/打勾**行為完全不變**，只是外觀套 wk。

- [ ] **Step 4: 驗證（兩角色）**

- `/dev/login-super` → 稽核：全部門市時顯示空狀態＋各店快速鍵；選一家店（側欄門市範圍）→ 依營業日分組唯讀表、燈號+徽章、店別 tag、分類 chip、金額紅字負數、收據縮圖點開燈箱、頂部「‹ 返回全部門市」bar 可回。**完全無編輯/打勾/交班鈕**。
- `/dev/login-manager` → 稽核：待稽核仍可改分類/金額/備註、打勾、交班/結班/取消上一次、總表查詢，全部照舊能動（只是外觀 wk 化）。
- `node --test tests/js/*.mjs` 全綠；`python3 -m pytest -q` 全綠（後端未動）。

- [ ] **Step 5: bump sw(`calc-v59`) + commit**
```bash
git add app/static/js/admin_audit.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 稽核 view wk 化 + 經理唯讀 render（主管維持可操作）"
```

---

## Task 6: 帳號 / 裝置 / 操作記錄 view wk 化 + 我的密碼卡片

把三個 sub-renderer（`admin_accounts.js` / `admin_devices.js` / `admin_logs.js`）與 `renderMyPassword` 的 `.ap-*/.pd-*` 表格/表單套成 `.wk-*`。**純外觀 class swap，所有 id/data-attr/handler/API 契約維持。**

**Files:**
- Modify: `app/static/js/admin_accounts.js`（`renderAccounts` ~6）
- Modify: `app/static/js/admin_devices.js`（`renderDevices` ~5）
- Modify: `app/static/js/admin_logs.js`（`renderLogs` ~13）
- Modify: `app/static/js/admin.js`（`renderMyPassword` ~88）
- Modify: `app/static/css/app.css`（經理段落 append `.wk-pw-*`；必要時補 `.wk-table` 通用表格樣式供 accounts/devices 用）
- Modify: `app/static/sw.js`（`calc-v60`）

**Interfaces:** Consumes Task 1 殼/卡片/按鈕/輸入。`ctx()` 契約不變。

**class 對照表（三檔共用）：**
| 舊 | 新 |
|---|---|
| `.ap-table-wrap` | `.table-wrap` |
| `.ap-table` | `.wk-table`（新增通用：`border-collapse:separate;border-spacing:0`；th faint 12px；td 13px border-bottom line-soft；hover surface-2） |
| `.ap-form` | `.wk-card` + `.wk-card-body`（表單包成卡）或就地換 `.wk-input`/`.wk-btn` |
| `.ap-btn` / `.ap-btn.danger` | `.wk-btn wk-btn-secondary` / `.wk-btn wk-btn-danger-soft` |
| `.ap-badge` | `.wk-badge`（狀態對應 open/bad/neutral） |
| `.ap-msg` | `.wk-msg`（小字提示） |
| `.ap-rowbtns` | `.wk-rowbtns`（`display:flex;gap:6px` 或就地 inline） |
| `.ap-empty` | `.wk-empty` |
| `.ap-face-status` / `.ap-video`（accounts 人臉） | 保留原 class（人臉登記 UI 屬功能細節，僅確保不破版；可暫留舊樣式或補最小 wk 包裝） |
| `.au-day-nav` / `.au-time`（logs） | `.au-day-nav`→`.wk-toolbar-row`（日期選擇）；`.au-time` 保留（時間欄樣式無害） |

- [ ] **Step 1: 補通用 `.wk-table` + `.wk-pw-*` CSS**

app.css 經理段落 append：`.wk-table`（通用表格，值參照原型 `.store-table`/`.audit-table` 精神但通用化）、`.wk-msg{font-size:13px;margin-top:8px;color:var(--wk-muted)}`、`.wk-rowbtns{display:flex;gap:6px;flex-wrap:wrap}`、我的密碼 `.wk-pw-card{max-width:420px}`/`.wk-pw-field`/`.wk-pw-input`（照原型 `manager-desktop.html:387-392`）。

- [ ] **Step 2: `renderAccounts` / `renderDevices` class swap**

依對照表換 `admin_accounts.js`/`admin_devices.js` 內的 class 字串。**只改 class，不動 fetch/handler/id/data-attr**。逐一比對 render 後 DOM：帳號列表（角色/店別/停用/重設密碼/人臉狀態）、裝置列表（核准/撤銷/店別過濾）功能全在。

- [ ] **Step 3: `renderLogs` class swap**

`admin_logs.js`：`.pd-table`→`.wk-table`、`.pd-table-wrap`→`.table-wrap`、`.ap-empty`→`.wk-empty`、`.au-day-nav`→`.wk-toolbar-row`（或包 `.wk-toolbar`）。日期切換/店別過濾行為不變。

- [ ] **Step 4: `renderMyPassword`（admin.js）套 `.wk-card`**

`.ap-form`→`.wk-card wk-pw-card`+`.wk-card-body`；input→`.wk-input wk-pw-input`；button→`.wk-btn wk-btn-primary`；`.ap-msg`→`.wk-msg`。**id 維持**（`#mp-old`/`#mp-new`/`#mp-submit`/`#mp-msg`，改密碼邏輯不變）。骨架：
```js
function renderMyPassword(container) {
  container.innerHTML = `
    <div class="wk-toolbar"><div class="wk-toolbar-row"><span class="wk-toolbar-title">我的密碼</span>
      <span class="wk-filter-label">變更登入用 4 位數密碼</span></div></div>
    <div class="wk-page-body"><div class="wk-card wk-pw-card"><div class="wk-card-body">
      <div class="wk-pw-field"><label for="mp-old">舊密碼</label>
        <input class="wk-input wk-pw-input" id="mp-old" type="password" inputmode="numeric" maxlength="4" autocomplete="off" placeholder="••••"></div>
      <div class="wk-pw-field"><label for="mp-new">新密碼</label>
        <input class="wk-input wk-pw-input" id="mp-new" type="password" inputmode="numeric" maxlength="4" autocomplete="off" placeholder="••••">
        <span class="help">4 位數字，變更後其他裝置需重新登入。</span></div>
      <button class="wk-btn wk-btn-primary" id="mp-submit" type="button">變更密碼</button>
      <div class="wk-msg" id="mp-msg"></div>
    </div></div></div>`;
  /* …沿用現行 admin.js:96-118 的 input 過濾 + submit 邏輯（id 不變）… */
}
```

- [ ] **Step 5: 驗證**

`/dev/login-super` 逐分頁：帳號（列表/建帳號/重設密碼/停用/改角色/人臉狀態不破版）、裝置（核准/撤銷/店別過濾）、操作記錄（日期切換）、我的密碼（卡片版面、改密碼回歸）。`/dev/login-manager` 帳號/裝置/操作記錄/我的密碼亦正常。`node --test` + `pytest -q` 全綠。

- [ ] **Step 6: bump sw(`calc-v60`) + commit**
```bash
git add app/static/js/admin_accounts.js app/static/js/admin_devices.js app/static/js/admin_logs.js app/static/js/admin.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 帳號/裝置/操作記錄/我的密碼 view wk 化"
```

---

## Task 7: 整合驗證 + nav 收尾 + 窄視窗 fallback + nav icon

**Files:**
- Modify（如需）: `app/static/js/admin.js`、`app/static/css/app.css`
- Modify: `app/static/sw.js`（`calc-v61`）

- [ ] **Step 1: nav icon（可選）+ 窄視窗防爆**

若 Task 1 未放 nav icon，於 `shellHtml` 的 navBtns 依原型 `manager-desktop.html:494-510` 為各 key 補 `<span class="wk-nav-ico"><svg…></span>`（report/audit/stores/closing/password 五個原型有；accounts/devices/logs 用相近 icon 或省略）。確認 app.css 有原型 `@media(max-width:900px)` 側欄轉頂列 fallback（會計 pilot 應已建 `.wk-sidebar` fallback；若經理的 `.wk-store-scope`/`.wk-nav-ro` 在窄版需調整，補原型 `manager-desktop.html:466-478` 的窄版規則，加 wk- 前綴）。

- [ ] **Step 2: 經理全流程回歸（對照原型 + spec 5.5 逐項）**

`/dev/login-super` 走完：月報表（切全部門市/單店、展開子分類、匯出佔位、選店同步）→ 稽核（唯讀、選店/返回全部門市、燈箱）→ 店別管理（檢視打勾/kill-switch modal/新增、無刪除鈕）→ 月結設定（唯讀鎖頭+kv）→ 帳號/裝置/操作記錄 → 我的密碼 → 登出。全程對照原型視覺、深/淺主題、無 console error、**店別全英文代號**、負數紅字、時間台灣時間、nav active 高亮正確切換。

- [ ] **Step 3: 主管回歸 + 全測試綠**

`/dev/login-manager`：nav 僅稽核/帳號/裝置/操作記錄/我的密碼；稽核**可操作**（編輯/打勾/交班/總表）；其餘正常。
```
node --test tests/js/*.mjs
python3 -m pytest -q
```
Expected: 前端純邏輯測 + 後端測全綠（後端未動）。

- [ ] **Step 4: bump sw(`calc-v61`) + commit**
```bash
git add -A app/static
git commit -m "feat(ui): 經理電腦版工作台整合驗證 + nav 收尾 + 窄視窗 fallback"
```

---

## Self-Review（對照 spec 5.5 + 原型）

**Spec 5.5 coverage**：側欄工作台殼(Task1)✔ / 側欄順序 月報表→稽核→店別→月結→我的密碼(Task1 nav)✔ / 全域選店放側欄頂部+工具列鏡像(Task1,2)✔ / 月報表交叉表 sticky 首欄+可展開子分類+店別 code+單店窄表(Task2)✔ / 店別管理桌機表格 檢視打勾+kill-switch(Task4)✔ / **刪除店停用(spec §8)**(Task4)✔ / 稽核唯讀 依營業日分組+返回全部門市 bar+空狀態(Task5)✔ / 月結設定唯讀鎖頭橫幅+kv(Task3)✔ / 負數紅字·tabular-nums(Task2,5)✔ / 深淺雙主題 token(沿用會計 pilot)✔ / bump sw(每 task)✔。
**額外決策覆蓋**：帳號/裝置/操作記錄含進新殼(user 定案)(Task6)✔ / 主管也套新殼、稽核仍可操作(user 定案)(Task1,5)✔。
> 本 plan 涵蓋 spec 第 5.5 節（經理電腦）。經理手機（super-mobile.html，spec 5.4）+ 員工/主管手機 = 後續獨立 plan（實作順序 ③）。

**Placeholder scan**：無 TBD/TODO。機械 class swap 的步驟（Task5 Step3、Task6）以「class 對照表 + 契約維持（id/data-attr/handler 不動）」描述並附代表骨架，沿用會計桌機 plan 同一 altitude。Task5 `renderAuditReadonly` 節錄核心列骨架 + 明確資料來源(auditByDate)與返回機制(#ap-store dispatchEvent)。

**Type consistency**：`#ap-body`/`#ap-store`/`#ap-logout`/`#mp-*`/`.st-viewable`/`data-conn`/`data-id`/`data-f`/`data-act`/`data-trail`/`.au-thumb` id 與 data 契約全程不改；`renderMonthReport(container,{periodId,storeId,lockStore})` 簽章跨 Task2 與會計 reconcile.js 一致；`wkConfirm({title,desc,okLabel,danger})` 沿用會計 pilot 簽章；tab key `report/audit/stores/closing/accounts/devices/logs/mypw` 跨 Task1 tabs/renderActiveTab/mount 一致。

---

## 風險 / 注意

- **共用檔連帶影響**：`month_report.js`（Task2）為會計＋經理共用，改它同時升級會計月報表——預期內、與 spec「月報表本就共用」一致。
- **稽核雙角色**：經理唯讀 render 與主管可操作 render 在同一檔分流（`isSuper`）。經理唯讀的「返回/選店」透過操作 `#ap-store` DOM + `dispatchEvent('change')` 回呼 admin.js 的 state，避免跨檔傳 state。驗證務必兩角色都測（super 唯讀 / manager 可操作）。
- **後端角色守門**：月報表(reports/monthly)、月結(periods GET) 對 manager 是 403——但 manager 的 nav 本就不含這兩個分頁（Task1 分權），不會誤打。
- **資料量**：dev.db 可能店少/單少，交叉表與稽核分組要多店多單才看得出效果；驗證前先在店別管理開 TP/TC/KH 幾家、或跑員工/主管流補幾筆。
- **PWA 快取**：每 task bump sw + 硬重整；上線一次 bump 到最終版即可。
- 舊 `.ap-*/.pd-*/.mr-*` CSS 段落**本 plan 不刪**（會計月結管理 view 目前仍部分用 `.ap-*`、其他過渡畫面也用）；待全角色遷移完的收尾 plan 再清理。
- **會計 pilot 尚未 100% wk 化**（月結管理/我的密碼 view 仍 `.ap-*`、Task 4/6 未做）——與本 plan 無強相依（本 plan 只沿用已建的殼/卡片/modal/`.wk-xt`(Task2 建)）；會計剩餘 view 的 wk 化可另案補。
