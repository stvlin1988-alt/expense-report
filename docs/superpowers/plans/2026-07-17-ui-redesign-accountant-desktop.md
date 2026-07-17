# 會計桌機工作台 UI 重塑 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把會計核銷面板（`showReconcilePanel`）從現行共用 `.admin-panel`／`.ap-*` 殼（頂部 tab＋置中 900px）重塑成原型 `accountant-desktop.html` 的「208px 側邊欄工作台＋滿版主區＋sticky 毛玻璃工具列」設計系統，並一次打好後續各角色沿用的 token 化 CSS 地基與共通元件（app modal／桌機燈箱／收據縮圖語言）。

**Architecture:** 純前端／CSS／DOM 重塑，**不動後端、不改 API、不改任務流、不碰計算機幌子**。新增一套工作台設計系統（token + `.wk-*` 命名空間 class），與舊 `.ap-*` **並存**；只有會計核銷這一條 render 路徑（`reconcile.js`）改用新殼，其他角色暫留舊殼，後續 plan 逐一遷移。視覺 single source of truth = `docs/superpowers/ui-prototypes/accountant-desktop.html`。

**Tech Stack:** Vanilla ES module（無框架）、單一 `app/static/css/app.css`、Flask 模板、PWA service worker（`sw.js` 快取靜態清單）。

## 前端驗證策略（本 plan 對 TDD 的 adaptation）

此工作是視覺／DOM 重塑，非後端邏輯，故驗證分兩軌：
- **純函式改動** → `node --test tests/js/*.mjs`（本 repo 既有前端純邏輯測）。本 plan 幾乎不動純函式（`fmtAmount`/`groupTotals`/`applyAmountEdit`/`showResubmitBadge`/`periodBadge`/`formatCell`/`pickCell` 維持行為）；每個 task 結尾都要**重跑既有 node 測確認全綠**（沒被重塑打破）。
- **DOM／CSS 重塑** → 本機開 server + dev 登入會計，**對照原型 URL 逐項目視檢**（結構/class/視覺/互動）。

**本機啟動（harness `run_in_background: true`，勿用 shell `&`／nohup 會被 sandbox 殺 exit 144）：**
```
cd ~/projects/expense-report; set -a; . ./.env; set +a; export E2E_LOGIN_BYPASS=1 FLASK_APP=wsgi.py; python3 -m flask db upgrade; python3 -m flask run --port 5001 --no-reload
```
- 會計面板入口：`http://127.0.0.1:5001/dev/login-accountant`（dev 捷徑，繞過計算機+裝置閘，免相機測 UI）。
- 對照原型：本機直接開檔 `docs/superpowers/ui-prototypes/accountant-desktop.html`。
- **改前端後**：瀏覽器硬重整（避開 sw 快取）；每個 task 的最後一步 bump `sw.js` CACHE_NAME。

---

## Global Constraints

以下每個 task 都隱含適用（值逐字取自 spec `docs/superpowers/specs/2026-07-17-ui-redesign-design.md`）：

- **不碰計算機幌子**（`calculator.js`/`secret.js`/黑底 `#calc-app` 樣式），不改後端/API/任務流。
- **設計 token**：accent `#2E6BE6`(dark `#5B8DF0`)/ground `#F4F6FA`/surface `#FFFFFF`/ink `#1C2733`/muted `#5C6B80`；語意色（獨立於 accent）ok `#1E9E5A`/warn `#C7860A`/bad `#D6455A`（各 `-soft`/`-ink`）。字級 12/13/14/17/21。圓角 10/7。系統字。**token 完整值以原型 `accountant-desktop.html` 的 `:root` 三段（`prefers-color-scheme` + `data-theme=dark` + `data-theme=light`）為準，逐字搬。**
- **店別一律英文代號**（≤2 字母），**絕不露中文店名**。→ 注意：現行 render 多處用 `s.name`（見 `storeOptionsHtml`/`month_report.js` 表頭），重塑要改用 `s.code`。
- **時間台灣時間**（`formatDateTimeTW` from `audit_util.js`）；**營業日 08:00 分界**。
- **負數金額紅字**（`.rc-neg` → 工作台對應 `.num.neg`），金額 `tabular-nums`。
- **收據縮圖**：實作用**真 `<img>` thumb_url**（R2 縮圖），套原型收據縮圖的視覺語言（圓角/邊框/hover 放大鏡暗示/`cursor:zoom-in`）；原型裡 CSS 畫的假收據只是無真圖時的示意，不照搬。
- **卡片列表單欄滿版**、退回/封月確認**走 app modal**（取代 `window.prompt`/`confirm`）。
- **CSS 組織**：`app.css` 單檔分區（新增工作台段落，清楚註解），不拆多檔、不引入 partial。
- **每次改 css/js → bump `sw.js` CACHE_NAME**（現 `calc-v51` → 本 plan 依序 `calc-v52`…）。

---

## File Structure

| 檔案 | 動作 | 責任 |
|---|---|---|
| `app/static/css/app.css` | Modify（append 工作台段落，末尾 `.st-onoff` 之後） | 新增工作台設計系統：`:root` 三段 token、`.wk-*` 殼/側欄/工具列/卡片/表格/badge/modal/lightbox 元件層。舊 `.ap-*`/`.rc-*`/`.mr-*` 段落**保留不動**。 |
| `app/static/js/wk_modal.js` | **Create** | 新共用 app modal 元件：`wkConfirm({title,desc,okLabel,danger})→Promise<bool>`、`wkPrompt({title,desc,okLabel,placeholder,validate})→Promise<string\|null>`。取代 `window.confirm`/`window.prompt`。 |
| `app/static/js/reconcile.js` | Modify | `shellHtml()` 換工作台側欄殼；`groupsHtml`/`rowHtml` 收斂成 7 欄；`reconcileHtml` 工具列 sticky 化；退回/封月改 `wkConfirm`/`wkPrompt`；`storeOptionsHtml` 等改用 `s.code`。 |
| `app/static/js/month_report.js` | Modify | 交叉表套工作台 `.wk-xt` 樣式（sticky 首欄 `separate`）；表頭 `s.name`→`s.code`。 |
| `app/static/js/lightbox.js` | 檢視（多半不改） | 確認桌機滾輪縮放/拖曳/雙擊已支援；缺則補。 |
| `app/static/sw.js` | Modify（每 task） | bump CACHE_NAME。 |

**Task 邊界原則**：每個 task 是「一個可對照原型獨立目視驗收的交付」。CSS token 地基折入第一個需要它的 task（工作台殼）。

---

## Task 1: 工作台設計系統地基 + 會計殼改造（側欄 + 主區 + sticky 工具列）

把 `showReconcilePanel` 的 `.admin-panel` 殼換成原型的側欄工作台殼，並在 `app.css` 建立整套 token + 殼/側欄/工具列 CSS。這是後續 task 的地基。

**Files:**
- Modify: `app/static/css/app.css`（append，`.st-onoff` 之後）
- Modify: `app/static/js/reconcile.js`（`shellHtml` ~155-169、`mount` ~719-734、`renderActiveTab` ~710-717）
- Modify: `app/static/sw.js`（CACHE_NAME → `calc-v52`）

**Interfaces:**
- Produces: CSS class 契約供後續 task 用 — 殼 `.wk-app`/`.wk-sidebar`/`.wk-main`/`.wk-view`；側欄 `.wk-brand`/`.wk-nav`/`.wk-nav-item[aria-current=page]`/`.wk-side-foot`；工具列 `.wk-toolbar`(sticky 毛玻璃)/`.wk-toolbar-row`；按鈕 `.wk-btn`(`.wk-btn-primary`/`-secondary`/`-ghost`/`-danger-soft`)；卡片 `.wk-card`/`.wk-card-head`/`.wk-card-body`；金額 `.num`(`.num.neg` 紅)；店代號 `.wk-store-tag`。值逐字取自原型。
- Consumes: 無（第一個 task）。

- [ ] **Step 1: 搬 token + 殼/側欄/工具列 CSS 進 app.css**

在 `app/static/css/app.css` 末尾 append 一段（用註解分區），把原型 `accountant-desktop.html` `<style>` 內的 `:root` 三段（light 預設 + `@media(prefers-color-scheme:dark)` + `:root[data-theme=dark]` + `:root[data-theme=light]`）、`.sidebar`→改名 `.wk-sidebar`、`.main`→`.wk-main`、`.view`→`.wk-view`、`.toolbar`→`.wk-toolbar`、`.nav*`→`.wk-nav*`、`.btn*`→`.wk-btn*`、`.card*`→`.wk-card*`、`.num`、`.store-tag`→`.wk-store-tag` 逐段搬入並統一加 `wk-` 前綴（避免撞現有 `.tab`/`.card`? 現無 `.card`，但仍加前綴保持命名空間乾淨）。

分區標頭範例：
```css
/* ============================================================
   工作台設計系統（UI 重塑 2026-07；會計桌機 pilot，各角色沿用）
   token + 側欄工作台殼。與舊 .ap-*/.rc-*/.mr-* 並存。
   視覺 SoT: docs/superpowers/ui-prototypes/accountant-desktop.html
   ============================================================ */
:root{ --wk-accent:#2E6BE6; --wk-accent-ink:#1E4FB8; --wk-accent-soft:#E8EFFC;
  --wk-ground:#F4F6FA; --wk-surface:#FFFFFF; --wk-surface-2:#F8FAFD;
  --wk-ink:#1C2733; --wk-muted:#5C6B80; --wk-faint:#8896A8; --wk-line:#DDE4EE; --wk-line-soft:#E8EDF5;
  --wk-ok:#1E9E5A; --wk-ok-soft:#E3F5EB; --wk-ok-ink:#14713F;
  --wk-warn:#C7860A; --wk-warn-soft:#FCF2DC; --wk-warn-ink:#8F5E03;
  --wk-bad:#D6455A; --wk-bad-soft:#FCE9EC; --wk-bad-ink:#AF2B40;
  --wk-radius:10px; --wk-radius-sm:7px; --wk-sidebar-w:208px;
  --wk-toolbar-bg:rgba(244,246,250,.92);
  --wk-shadow:0 1px 2px rgba(28,39,51,.05),0 4px 16px rgba(28,39,51,.06); }
/* + dark 三段（prefers-color-scheme / data-theme=dark / data-theme=light），值照原型 */
```
> 注意：所有 `var(--x)` 引用同步改成 `var(--wk-x)`。`.wk-app` 需 `position:fixed;inset:0;z-index:50;background:var(--wk-ground);color:var(--wk-ink);overflow:auto`（取代 `.admin-panel` 的全屏定位角色）。`.wk-sidebar` 用 `position:fixed` 左側 208px；窄視窗 `@media(max-width:900px)` 轉頂列（照原型 fallback）。

- [ ] **Step 2: 改 `shellHtml()` 成側欄工作台殼**

`reconcile.js` `shellHtml()`（~155）改為輸出側欄殼：品牌「會計核銷」、側欄導覽（核銷/月結管理/我的密碼，`.wk-nav-item` data-tab）、側欄底部登入者 + 登出、主區 `.wk-main` 內含各 `.wk-view`（工具列由各 view render 塞）。骨架：
```js
function shellHtml() {
  const navBtns = tabs.map((t) =>
    `<button class="wk-nav-item${t.key === state.tab ? ' ' : ''}"${t.key === state.tab ? ' aria-current="page"' : ''} data-tab="${t.key}" type="button">${t.label}</button>`
  ).join('');
  return `
    <div class="wk-app">
      <aside class="wk-sidebar">
        <div class="wk-brand"><div class="wk-brand-name">會計核銷</div><div class="wk-brand-sub">核銷工作台</div></div>
        <nav class="wk-nav">${navBtns}</nav>
        <div class="wk-side-foot">
          <div class="wk-side-user"><span class="wk-avatar">${escapeHtml(identity.name.slice(0,1))}</span>
            <div><div class="wk-side-user-name">${escapeHtml(identity.name)}</div><div class="wk-side-user-role">會計</div></div></div>
          <button class="wk-btn wk-btn-secondary" id="rc-logout" type="button">登出</button>
        </div>
      </aside>
      <main class="wk-main"><div id="rc-body"></div></main>
    </div>`;
}
```
> 導覽點擊改綁 `.wk-nav-item`（`mount()` ~725 的 `.ap-tab` 選擇器改 `.wk-nav-item`，並改切 `aria-current` 而非 `.active` class）。`#rc-body` id 維持不變（各 render 函式不用改抓取）。

- [ ] **Step 3: 本機驗證殼**

開 server（見上），瀏覽器硬重整開 `/dev/login-accountant`。對照原型 `accountant-desktop.html`：
- 預期：左側 208px 側欄（品牌 + 核銷/月結管理/我的密碼 三導覽 + 底部姓名/登出），主區滿版淺色 ground，深/淺主題跟隨系統。導覽點擊會切換 view（內容下個 task 才重塑，先能切即可）。
- 檢查無 console error；`node --test tests/js/*.mjs` 全綠（沒動純函式，確認 import 沒斷）。

- [ ] **Step 4: bump sw + commit**
```bash
# sw.js: const CACHE_NAME = 'calc-v52';
git add app/static/css/app.css app/static/js/reconcile.js app/static/sw.js
git commit -m "feat(ui): 會計核銷改工作台側欄殼 + 工作台設計系統 token 地基"
```

---

## Task 2: 共用 app modal（取代 window.prompt / confirm）

**Files:**
- Create: `app/static/js/wk_modal.js`
- Modify: `app/static/css/app.css`（工作台段落 append modal 樣式，照原型 `.modal-backdrop`/`.modal`）
- Modify: `app/static/sw.js`（`calc-v53`）
- Modify: `app/templates/index.html`（若 modal 需掛載點；否則 modal 自建 backdrop append 到 body）

**Interfaces:**
- Produces:
  - `wkConfirm({title, desc, okLabel='確定', danger=false}) => Promise<boolean>`
  - `wkPrompt({title, desc, okLabel='送出', placeholder='', validate}) => Promise<string|null>`（取消回 null；`validate(value)` 回錯誤字串則不關閉、顯示錯誤）
- Consumes: Task 1 的 `.wk-btn*` 樣式。

- [ ] **Step 1: 寫 wk_modal.js**

自建 backdrop DOM append 到 `document.body`，Promise 化。骨架：
```js
export function wkConfirm({ title, desc = '', okLabel = '確定', danger = false } = {}) {
  return new Promise((resolve) => {
    const bd = document.createElement('div');
    bd.className = 'wk-modal-backdrop open';
    bd.innerHTML = `<div class="wk-modal" role="dialog" aria-modal="true">
      <div class="wk-modal-head"><div class="wk-modal-title">${escapeHtml(title)}</div>
        <button class="wk-modal-x" type="button" aria-label="關閉">×</button></div>
      <div class="wk-modal-body">${escapeHtml(desc)}</div>
      <div class="wk-modal-foot">
        <button class="wk-btn wk-btn-secondary" data-no type="button">取消</button>
        <button class="wk-btn ${danger ? 'wk-btn-danger' : 'wk-btn-primary'}" data-yes type="button">${escapeHtml(okLabel)}</button>
      </div></div>`;
    const done = (v) => { bd.remove(); document.removeEventListener('keydown', onKey); resolve(v); };
    const onKey = (e) => { if (e.key === 'Escape') done(false); };
    bd.querySelector('[data-yes]').addEventListener('click', () => done(true));
    bd.querySelector('[data-no]').addEventListener('click', () => done(false));
    bd.querySelector('.wk-modal-x').addEventListener('click', () => done(false));
    bd.addEventListener('click', (e) => { if (e.target === bd) done(false); });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(bd);
    bd.querySelector('[data-yes]').focus();
  });
}
```
`wkPrompt` 同構，body 內含 `<input class="wk-input">`，`data-yes` 時跑 `validate`，錯誤顯示在 `.wk-modal-err`、不 resolve。`escapeHtml` 從 `admin_util.js` import。

- [ ] **Step 2: modal CSS**

app.css 工作台段落 append `.wk-modal-backdrop`/`.wk-modal`/`.wk-modal-head`/`.wk-modal-title`/`.wk-modal-x`/`.wk-modal-body`/`.wk-modal-foot`/`.wk-input`/`.wk-btn-danger`，值照原型 `accountant-desktop.html` 的 modal 段。

- [ ] **Step 3: 接進 reconcile.js**

`wireRows` 的退回（~476-485）：`const reason = window.prompt(...)` → `const reason = await wkPrompt({title:'退回單據', desc:'請輸入退回原因（必填，200 字內）', okLabel:'退回', validate:(v)=> (v && v.trim()) ? '' : '請填寫退回原因'});`（`reason === null` 維持取消語意）。
`wirePeriodTab` 提前封月（~658）：`if (!window.confirm(...))` → `if (!(await wkConfirm({title:'提前封月', desc:\`這期還有 ${n} 筆沒打勾，封月後這些單不進帳，確定要封嗎？\`, okLabel:'確定封月', danger:true}))) return;`
頂部 `import { wkConfirm, wkPrompt } from './wk_modal.js';`。

- [ ] **Step 4: 驗證**

開 server → 會計核銷 → 對一張待核銷單按「退回」→ 出現 app modal（非原生 prompt），空白按退回顯示錯誤、填原因可送出。月結管理 →「提前封月」出現 danger modal。`node --test tests/js/*.mjs` 全綠。

- [ ] **Step 5: bump sw(`calc-v53`) + commit**
```bash
git add app/static/js/wk_modal.js app/static/css/app.css app/static/js/reconcile.js app/static/sw.js app/templates/index.html
git commit -m "feat(ui): app modal 取代原生 prompt/confirm（退回原因/提前封月）"
```

---

## Task 3: 核銷表 11 欄 → 7 欄 + 工具列 sticky 化

**Files:**
- Modify: `app/static/js/reconcile.js`（`rowHtml` ~265-300、`groupsHtml` ~302-317、`reconcileHtml` ~332-358、`periodBarHtml` ~319-330）
- Modify: `app/static/css/app.css`（工作台段落 append 核銷表 `.wk-rc-*` + 依營業日分組 day-head/日小計 樣式，照原型會計桌機核銷表）
- Modify: `app/static/sw.js`（`calc-v54`）

**Interfaces:**
- Consumes: Task 1 殼/工具列/卡片/`.num`、Task 2 modal。
- Produces: 7 欄核銷表結構（後續無下游依賴其 class）。

**7 欄收斂**（對照原型 + spec 5.1）：① 勾選 ② **單據**(縮圖 `<img>` + 摘要 + 單號/建立者/時間併一格) ③ 店別(code) ④ 分類 ⑤ 金額 ⑥ **燈號+狀態**(併一格) ⑦ 操作。日期改由「依營業日分組的組頭」承載（現行已分組），故單列不再有獨立日期欄。

- [ ] **Step 1: 改 `rowHtml` 成 7 欄**

保留所有既有互動 data 屬性/handler 契約（`data-id`/`data-status`/`.rc-sel`/`[data-f=category|amount|err]`/`[data-act=approve|reject|movenext]`/`.au-thumb[data-zoom]`），只重組 `<td>` 結構與 class。骨架：
```js
function rowHtml(e) {
  const editable = e.status === 'audited' || e.status === 'reconciled';
  const canApprove = e.status === 'audited';
  const thumb = e.thumb_url
    ? `<img src="${e.thumb_url}" loading="lazy" class="wk-rcp-thumb au-thumb" data-zoom="${e.image_url || ''}" alt="收據">`
    : '<span class="wk-rcp-none">—</span>';
  const { negative } = fmtAmount(e.amount);
  const meta = `${escapeHtml(e.doc_no || `#${e.id}`)} · ${escapeHtml(e.created_by_name || '')} · ${escapeHtml(formatDateTimeTW(e.created_at))}`;
  const rejectInfo = (e.status === 'rejected' && e.reject_reason) ? `<div class="rc-reject-reason">${escapeHtml(e.reject_reason)}</div>` : '';
  const resubmitBadge = showResubmitBadge(e) ? `<div class="rc-resubmit">🔄 主管已重送 ${escapeHtml(formatDateTimeTW(e.resubmitted_at))}</div>` : '';
  return `<tr data-id="${e.id}" data-status="${e.status}">
    <td class="wk-rc-sel">${canApprove ? '<input type="checkbox" class="rc-sel">' : ''}</td>
    <td><div class="wk-doc-cell">${thumb}
      <div class="wk-doc-meta"><span class="wk-doc-summary">${escapeHtml(e.summary || '')}${e.is_no_receipt ? ' <span class="au-mod">無單據</span>' : ''}</span>
        <span class="wk-doc-sub">${meta}</span></div></div></td>
    <td><span class="wk-store-tag">${escapeHtml(e.store_code || e.store_name || '')}</span></td>
    <td>${editable ? `<select data-f="category">${categoryOptionsHtml(state.categories, e.category_id)}</select>` : escapeHtml(e.category_name || '')}</td>
    <td class="num${negative ? ' neg' : ''}">${editable
      ? `<input value="${e.amount ?? ''}" inputmode="decimal" data-f="amount" class="wk-amt-input${negative ? ' neg' : ''}">`
      : fmtAmount(e.amount).text}</td>
    <td><div class="wk-lamp-cell">${lightLabel(e.light)}<span class="wk-status">${escapeHtml(STATUS_LABEL[e.status] || e.status)}</span>${rejectInfo}${resubmitBadge}</div></td>
    <td class="rc-rowbtns">
      ${canApprove ? '<button class="wk-btn wk-btn-sm wk-btn-primary" data-act="approve" type="button">核銷</button>' : ''}
      ${editable ? '<button class="wk-btn wk-btn-sm wk-btn-secondary" data-act="reject" type="button">退回</button>' : ''}
      ${(e.status === 'audited' || e.status === 'rejected') ? '<button class="wk-btn wk-btn-sm wk-btn-ghost" data-act="movenext" type="button">挪下期</button>' : ''}
      <div class="pd-row-err" data-f="err"></div>
    </td>
  </tr>`;
}
```
> ⚠️ **需要後端提供 `e.store_code` 與 `e.created_at`**：先確認 `rcApi.pending()` 回傳的 item 是否含這兩欄。若 `store_code` 缺，退而用現有 store 清單 `state.stores` 依 `e.store_id` 查 code（加一個 `storeCodeById(id)` helper，**不動後端**）；`created_at` 若缺則沿用單號/建立者不放時間。此檢查為 Step 0 前置。

- [ ] **Step 0（前置）: 確認 item 欄位**

`grep -n "store_code\|created_at\|store_name" app/reconcile/routes.py` 看 pending() 序列化欄位。決定 `store_code`/`created_at` 是走現成欄位或 client helper。記錄結論於 commit message。

- [ ] **Step 2: 改 `groupsHtml` 表頭成 7 欄 + 套 `.wk-card`/`.wk-rc-table`**
```js
function groupsHtml() {
  if (!state.groups.length) return '<div class="wk-empty">沒有符合條件的單據</div>';
  return state.groups.map((g, idx) => `
    <div class="wk-card wk-rc-group">
      <div class="wk-rc-dayhead">${escapeHtml(g.business_date)}<span class="wk-rc-daysub">日小計 <span id="rc-subtotal-${idx}" class="num">${fmtAmount(g.subtotal).text}</span></span></div>
      <div class="table-wrap"><table class="wk-rc-table">
        <thead><tr><th><input type="checkbox" class="rc-selall"></th><th>單據</th><th>店別</th><th>分類</th><th class="num-h">金額</th><th>燈號／狀態</th><th>操作</th></tr></thead>
        <tbody>${g.items.map(rowHtml).join('')}</tbody>
      </table></div>
    </div>`).join('');
}
```
> `#rc-subtotal-${idx}` id 維持（`wireRows` amount blur 更新它，契約不變）。`.wk-rc-table` 用 `border-collapse:separate;border-spacing:0`（避免日後加 sticky 踩雷）；`min-width:680px` 一頁看完。

- [ ] **Step 3: `reconcileHtml` 工具列 sticky 化**

把期間 bar + 篩選列 + 合計 pill 收進 `.wk-toolbar`（sticky top 毛玻璃）；手動新增/批次/groups 放 `.wk-view` body。合計顯示 id（`#rc-total-pending`/`-reconciled`/`-count`）維持不變。篩選 select/input 換 `.wk-select`/`.wk-input` class（樣式），id 全維持（`wireReconcile` 靠 id 抓）。

- [ ] **Step 4: 驗證（對照原型逐項）**

開 server → 會計核銷。對照 `accountant-desktop.html`：
- 7 欄、依營業日分組帶日小計、單據格=縮圖+摘要+單號/建立者/時間、店別英文代號、燈號+狀態併格、min-width 680 一頁看完免橫捲、負數紅字、金額 tabular-nums。
- 互動回歸：勾選+一鍵核銷、行內改分類/金額（金額 blur 後小計與合計即時更新、負數變紅）、退回(app modal)、挪下期、縮圖點開燈箱、篩選套用、切換期間、新增單據。
- `node --test tests/js/*.mjs` 全綠。

- [ ] **Step 5: bump sw(`calc-v54`) + commit**
```bash
git add app/static/js/reconcile.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 核銷表收斂成 7 欄 + 依營業日分組卡片 + sticky 工具列"
```

---

## Task 4: 月結管理 view 套工作台樣式

**Files:**
- Modify: `app/static/js/reconcile.js`（`periodTabHtml` ~585-625、`unprocessedTableHtml` ~565-583）
- Modify: `app/static/css/app.css`（工作台段落）
- Modify: `app/static/sw.js`（`calc-v55`）

**Interfaces:** Consumes Task 1 卡片/工具列/按鈕、Task 2 modal。

- [ ] **Step 1: `periodTabHtml` 各 section 改 `.wk-card`**

四個 `.rc-period-section` → `.wk-card`（card-head 標題 + card-body 內容）：目前期間（期間 label + `periodBadgeHtml` + 調整結束日 + 提前封月）／上期未處理單／月結設定（月結日 + 鎖定偏移 + 儲存）／月報表掛載點 `#rc-mr-report`（Task 5 處理）。輸入/按鈕換 `.wk-input`/`.wk-btn*`，id 全維持（`wirePeriodTab` 靠 id）。期間狀態 badge 沿用 `periodBadgeHtml`（現用 `.ap-badge`）→ 換 `.wk-badge`（新增對應 open/closing/closed 樣式）。

- [ ] **Step 2: `unprocessedTableHtml` 套 `.wk-card` + 縮圖語言**

表格 `<img>` 縮圖套 `.wk-rcp-thumb`，`store_name`→`store_code`（或 helper）。空狀態 `.wk-empty`。

- [ ] **Step 3: 驗證**

開 server → 會計「月結管理」。對照原型會計桌機月結管理：四張卡片版面、調整結束日/提前封月(app modal)/月結設定儲存 互動回歸、上期未處理單縮圖可點開燈箱。`node --test` 全綠。

- [ ] **Step 4: bump sw(`calc-v55`) + commit**
```bash
git add app/static/js/reconcile.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 月結管理 view 套工作台卡片樣式"
```

---

## Task 5: 月報表交叉表套工作台樣式（sticky 首欄）

**Files:**
- Modify: `app/static/js/month_report.js`（`tableHtml` ~66-85、`headerHtml` ~87-104、表頭 `s.name`→`s.code`）
- Modify: `app/static/css/app.css`（工作台段落 append `.wk-xt` 交叉表：sticky 首欄 `separate`）
- Modify: `app/static/sw.js`（`calc-v56`）

**Interfaces:** Consumes Task 1。月報表為會計/經理共用（經理電腦版 plan 會沿用此 `.wk-xt`）。

- [ ] **Step 1: `tableHtml` 套 `.wk-xt`，表頭改 code**

`class="pd-table mr-table..."` → `class="wk-xt${storeId ? ' wk-xt-one' : ''}"`；表頭 `s.name` → `s.code`（`footerRowHtml` 同步；spec 硬規則不露中文店名）。展開鈕 `.mr-toggle`/`.mr-child-row` 契約維持（`wireToggles` 不動）。
> ⚠️ 交叉表 sticky 首欄踩雷：`.wk-xt` 必須 `border-collapse:separate;border-spacing:0`，首欄 `position:sticky;left:0`。CSS 照原型 `.xt` 段。

- [ ] **Step 2: `headerHtml` 期間標題套工作台字級**

會計端（`showPicker=true`）門市下拉換 `.wk-select`；經理端（`lockStore`）維持外層控制。

- [ ] **Step 3: 驗證**

開 server →（A）會計「月結管理」內月報表；（B）`/dev/login-super` 經理「月結」月報表。對照原型交叉表：科目欄 sticky 釘左橫捲不跑掉、全部門市=各店一欄(code)+總計、單店=科目→金額窄表、展開子分類、負數紅字。`node --test tests/js/*.mjs` 全綠（`formatCell`/`pickCell` 測不受影響）。
> 註：此 task 動到共用 `month_report.js`，會同時改變經理手機/後台的月報表外觀——這是預期（月報表本就共用；經理電腦版 plan 會延續同樣式）。經理其他頁面仍是舊 `.ap-*` 殼，屬過渡期正常。

- [ ] **Step 4: bump sw(`calc-v56`) + commit**
```bash
git add app/static/js/month_report.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 月報表交叉表套工作台樣式 + 店別改英文代號"
```

---

## Task 6: 桌機燈箱 + 收據縮圖語言對齊 + 我的密碼 view

**Files:**
- Check/Modify: `app/static/js/lightbox.js`
- Modify: `app/static/js/reconcile.js`（`renderMyPassword` ~172-203 套工作台）
- Modify: `app/static/css/app.css`（`.wk-rcp-thumb` hover 放大鏡暗示 + 我的密碼卡片）
- Modify: `app/static/sw.js`（`calc-v57`）

**Interfaces:** Consumes Task 1。

- [ ] **Step 1: 確認/補桌機燈箱互動**

讀 `lightbox.js`：確認 `openImageLightbox` 桌機支援滾輪對準游標縮放(1x–4x)、拖曳平移、雙擊 1x↔放大、右上 44px X、Esc/點背景關。現有 `.au-lightbox*` 已支援縮放平移（見 app.css 182-192）；若缺桌機滾輪/雙擊則依原型 `#lb` 的 wheel/dblclick handler 補上。**只補缺口，不重寫既有行為**。

- [ ] **Step 2: 收據縮圖 hover 放大鏡**

`.wk-rcp-thumb`：圓角/邊框/`cursor:zoom-in`，hover 顯示右下放大鏡暗示（`::after` 或疊一個 `.wk-mag`）。照原型 `.rcp .mag` 視覺，但套在真 `<img>` 上。

- [ ] **Step 3: `renderMyPassword` 套工作台卡片**

`.ap-form` → `.wk-card` + `.wk-input` + `.wk-btn-primary`，id 維持（`#mp-old`/`#mp-new`/`#mp-submit`/`#mp-msg`）。

- [ ] **Step 4: 驗證**

開 server → 會計：核銷表/月結未處理單縮圖 hover 有放大鏡暗示、點開燈箱桌機滾輪縮放+拖曳+雙擊+Esc 關。我的密碼卡片版面、改密碼互動回歸。`node --test` 全綠。

- [ ] **Step 5: bump sw(`calc-v57`) + commit**
```bash
git add app/static/js/lightbox.js app/static/js/reconcile.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ui): 桌機燈箱/收據縮圖語言對齊 + 我的密碼卡片"
```

---

## Task 7: 全流程整合驗證 + 側欄導覽收尾

**Files:**
- Modify（如需）: `app/static/js/reconcile.js`、`app/static/css/app.css`
- Modify: `app/static/sw.js`（`calc-v58`）

- [ ] **Step 1: 側欄 active 態 + 導覽收尾**

確認 `.wk-nav-item[aria-current=page]` 高亮正確切換（核銷/月結管理/我的密碼），切換不殘留舊 view。窄視窗（<900px 平板直立）側欄轉頂列 fallback 可用。

- [ ] **Step 2: 會計全流程回歸（對照原型 + spec 5.1 清單逐項）**

開 server 走完：登入會計 → 核銷（篩選/切期間/勾選批次核銷/行內改分類金額/退回 modal/挪下期/新增單據/縮圖燈箱）→ 月結管理（調整結束日/提前封月 modal/月結設定儲存/上期未處理單/月報表交叉表）→ 我的密碼 → 登出。全程對照原型視覺、深/淺主題、無 console error、店別全英文代號、負數紅字、時間台灣時間。

- [ ] **Step 3: 全測試綠**
```
node --test tests/js/*.mjs
python3 -m pytest -q
```
Expected: 前端純邏輯測 + 後端測全綠（後端未動，確認沒誤傷）。

- [ ] **Step 4: bump sw(`calc-v58`) + commit**
```bash
git add -A app/static
git commit -m "feat(ui): 會計桌機工作台整合驗證 + 側欄導覽收尾"
```

---

## Self-Review（對照 spec）

**Spec coverage（會計桌機 pilot 部分）**：側欄工作台殼(Task1)✔ / sticky 毛玻璃工具列(Task1,3)✔ / 7 欄核銷表依營業日分組日小計(Task3)✔ / app modal 取代 prompt·confirm(Task2)✔ / 月結管理(Task4)✔ / 月報表交叉表 sticky 首欄(Task5)✔ / 桌機燈箱+收據縮圖語言(Task6)✔ / 店別英文代號(Task3,5)✔ / 負數紅字·tabular-nums(Task1,3)✔ / 深淺雙主題 token(Task1)✔ / bump sw(每 task)✔。
> 本 plan 僅涵蓋 spec 第 5.1 節（會計桌機）+ 第 2/3/4 節地基。經理電腦、手機三角色 = 後續獨立 plan（spec 第 8 節實作順序 ②③）。

**Placeholder scan**：無 TBD/TODO；每 code 步驟有骨架；驗證步驟有明確 URL/預期/對照對象。**唯一外部相依**：Task 3 Step 0 需先確認後端 pending() 是否回 `store_code`/`created_at`（已列為前置檢查 + fallback，不動後端）。

**Type consistency**：沿用既有 handler 契約（`data-id`/`data-status`/`.rc-sel`/`[data-f=*]`/`[data-act=*]`/`.au-thumb`/`#rc-subtotal-${idx}`/`#rc-total-*` id 全不改），只換外層結構/class；`wkConfirm`/`wkPrompt` 簽章跨 Task2→3→4 一致。

---

## 風險 / 注意

- **共用檔連帶影響**：`month_report.js`（Task5）為會計+經理共用，改它會同時變經理端月報表外觀——預期內、與後續經理電腦版 plan 一致。其餘會計改動集中在 `reconcile.js`（會計專屬 render），不影響其他角色。
- **後端欄位**：若 pending() 未回 `store_code`，用 client 端 `state.stores` 查 code helper（不動後端）；正式上線前可評估補後端欄位（另案）。
- **PWA 快取**：每 task bump sw + 硬重整；上線一次 bump 到最終版即可。
- 舊 `.ap-*`/`.rc-*`/`.mr-*` CSS 段落**本 plan 不刪**（其他角色仍用），待全角色遷移完的收尾 plan 再清理。
