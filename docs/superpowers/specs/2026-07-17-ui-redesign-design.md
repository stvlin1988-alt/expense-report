# PWA UI 重設計 — 設計 spec（2026-07-17）

> 狀態：**設計定稿**（5 份原型經 user 逐一核准）。本文件是實作前的 single source of truth，
> 下一步 → `writing-plans` 拆實作 plan → 進真前端。
> 對應原型：`docs/superpowers/ui-prototypes/*.html`（commit `c964090`，feat/ui-redesign）。
> 相關記憶：`ui_redesign_progress`、`project_status`。

---

## 1. 目標與範圍

**目標**：現行 PWA UI 是 mobile-first 單版、未針對裝置/角色適配；資料密集畫面（會計核銷、月報表交叉表）在手機上擠。用精緻的系統淡色語言，per-角色×裝置重塑「解鎖後」的面板。

**明確在範圍內**
- 解鎖後各角色面板的視覺/版面/互動重塑。
- 依裝置重排版（會計=桌機；經理=手機+電腦；員工/主管=手機+平板）。
- 統一設計 token、共通元件（收據縮圖/燈箱/卡片/主題）。

**明確不在範圍內（鐵律）**
- **計算機幌子（覆蓋層入口 + 暗號 078*2）維持原樣，一律不動。**
- **不改任務流、不動後端、不改 API。**純前端/CSS/DOM 重塑。
- 角色分流、端點、權限邏輯全部沿用現況。

**裝置×角色對應**

| 角色 (role) | 裝置 | 主原型 |
|---|---|---|
| 員工 employee | 手機 + 平板 | `employee-mobile.html` |
| 主管 manager | 手機 + 平板 | `manager-audit.html` |
| 經理 super_admin | 手機 + 電腦 | `super-mobile.html` + `manager-desktop.html` |
| 會計 accountant | 電腦 | `accountant-desktop.html`（pilot，設計語言基準） |

---

## 2. 設計 token（已核准，實作時原封落地）

- **accent 系統藍** `#2E6BE6`（dark `#5B8DF0`）／`-ink` `#1E4FB8`／`-soft` `#E8EFFC`
- **ground** 冷白 `#F4F6FA`／**surface** `#FFFFFF`／**surface-2** `#F8FAFD`
- **ink** `#1C2733`／**muted** `#5C6B80`／**faint** `#8896A8`／**line** `#DDE4EE`
- **語意色（獨立於 accent，只用在燈號/狀態）**：ok `#1E9E5A`／warn `#C7860A`／bad `#D6455A`（各有 `-soft`/`-ink` 變體）
- **字級 scale** 12 / 13 / 14（基準）/ 17 / 21
- **金額** `font-variant-numeric: tabular-nums`；圓角 `radius 10` / `sm 7`
- **字型** 系統字：`-apple-system, BlinkMacSystemFont, "PingFang TC", "Segoe UI", "Microsoft JhengHei", sans-serif`
- **深淺雙主題**：`@media (prefers-color-scheme: dark)` + `:root[data-theme=dark]` + `:root[data-theme=light]` 三處都要覆蓋（見原型 `:root` 三段）。

完整 token 值以 `accountant-desktop.html` / `manager-desktop.html` 的 `:root` 區塊為準（含 shadow、toolbar 毛玻璃、sticky-col-shadow）。

---

## 3. 硬規則（user 明確要求，違反會被打回）

1. **店別一律英文代號顯示**（TP/TC/KH，≤2 字母），**絕不露中文店名**。
2. **時間 UI 一律台灣時間**（DB 存 UTC，轉換用既有 `TW_TZ` pattern）；**營業日 08:00 分界**。
3. **負數金額紅字**（`.num.neg`，用 U+2212 減號 `−`）。
4. **卡片列表一律單欄滿版**（一列一張橫幅，不分兩欄）——員工/主管閱讀版面。
5. **收據縮圖**：CSS 畫的迷你收據（非灰塊）＋右下放大鏡暗示；點開燈箱放大。
6. 改前端 → **bump sw 版本 + 硬重整**（現 `calc-v51`）。

---

## 4. 共通元件（三份桌機/多份手機原型一致，實作要抽成共用）

### 4.1 收據縮圖
- 純 CSS 迷你收據：深色抬頭條 + 數條灰線 + 虛線分隔 + 右下放大鏡（`.rcp` 家族）。**不是灰塊 placeholder。**
- 點擊 → 開燈箱放大版（`.rcp-big`，280×390）。

### 4.2 燈箱（對齊真實 `lightbox.js`，本就支援縮放平移）
- **手機**：pinch 縮放 + 拖曳平移。
- **桌機**：滑鼠滾輪對準游標縮放 + 拖曳平移。
- 雙擊 1x↔放大；範圍 1x–4x；開啟重置置中；右上 44px X；點背景/Esc 也可關。

### 4.3 主題
- 跟隨系統 + 可手動切（`data-theme`）。三處 `:root` 覆蓋，dark/light 都要顯式。

### 4.4 卡片/表格/modal/toast
- 卡片 `.card`（surface + line-soft + shadow + radius）。
- 退回原因、封月確認、關店/刪店確認 → **app 內 modal**（取代原生 `prompt/confirm`）。
- toast 輕提示。

---

## 5. 各角色×裝置畫面規格

### 5.1 會計・桌機（pilot，`accountant-desktop.html`）
- **左側 208px 細長側邊欄**：核銷 / 月結管理 / 月報表 / 我的密碼；底部登入者 + 登出。主區滿版。
- 主區頂部 **sticky 毛玻璃工具列**（期間 + 篩選 + 合計 pill）。
- **核銷表**：依營業日分組帶日小計；11 欄收斂成 **7 欄**（單據=縮圖+摘要+單號/建立者/時間併格；燈號+狀態併格）；min-width 680px 一頁看完免橫捲；**操作欄不固定**（試過 sticky 右釘，拿掉）。
- 金額 nowrap 容 7 位數；負數紅字；店別 ≤2 英文字母。
- 月結管理可編輯（月結日/鎖定偏移）；退回/封月走 app modal。

### 5.2 員工・手機/平板（`employee-mobile.html`）
- 卡片式確認區/複查、**底部 tab** 導覽。
- 拍單直式＋橫式：**橫式=左側導覽 rail＋右側快門＋2 欄卡片**。
- ⚠️ 踩雷：橫式**別把 tab bar 藏掉**（否則其他分頁進不去）。

### 5.3 主管・手機/平板（`manager-audit.html`）
- 稽核打勾卡片 + **常駐 action bar**（交班/結班）。
- 總表查詢。鎖本店單店、無選店。

### 5.4 經理・手機（`super-mobile.html`）
- 選店抬頭 + 月報表交叉表（科目欄 sticky 釘左／單店清單）+ 月結設定唯讀🔒 + 店別管理（檢視打勾 + 對外連結 kill-switch）+ 稽核唯讀。

### 5.5 經理・電腦（`manager-desktop.html`，2026-07-17 定案）
- 沿用會計桌機側欄工作台。**側欄順序：月報表 → 稽核(唯讀) → 店別管理 → 月結設定🔒 → 我的密碼。**
- **全域選店放側欄頂部**（同時決定稽核＋月報表看哪家）；月報表工具列另有同步的鏡像下拉。
- **月報表交叉表**：科目欄 sticky 釘左；科目可展開子分類（三角形 toggle）；「全部門市」=各店一欄+總計欄，選單店=收成「科目→金額」窄表置左；負數紅字、tabular-nums。
- **店別管理**：桌機表格（店別｜對外狀態｜檢視顯示打勾｜對外連結 kill-switch｜刪除）；新增店 + 說明並排；關店/刪店走確認 modal。
- **稽核唯讀**：依營業日分組表格，只有燈號+徽章、零操作按鈕；**單店檢視頂部有「‹ 返回全部門市」bar**；「全部門市」時為空狀態（要先選店，附店別快速鍵）。
- **月結設定唯讀**：頂部鎖頭橫幅（僅會計可改）+ 唯讀 kv 卡。

---

## 6. 踩過的雷（實作務必避）

- `position:sticky` 用在 table cell 上跟 `border-collapse:collapse` **不相容**（sticky 欄被裁掉）→ 交叉表/店別表/稽核表一律 `border-collapse:separate; border-spacing:0`，邊框靠 `border-bottom`。
- 橫式員工拍單別藏底部 tab bar。

---

## 7. 實作落地映射（現行前端 → 重塑範圍）

現行：單一 `app/static/css/app.css`（257 行）+ 依角色拆的 vanilla ES module JS（無框架）。

| 畫面/角色 | 現行檔案 | 重塑動作 |
|---|---|---|
| 計算機幌子 | `calculator.js` / `secret.js` | **不動** |
| 登入/解鎖 | `auth.js` | 不動流程，僅視覺（若面板共用殼） |
| 員工拍單/確認/複查 | `capture.js` `camera.js` `pending.js` `review.js` `main.js`(`showAppView`) | 重塑 DOM/CSS：底部 tab、卡片、橫式 rail |
| 主管稽核 | `admin.js` `admin_audit.js` `audit_util.js` | 打勾卡片 + 常駐 action bar |
| 經理（選店/月報表/店別/稽核唯讀/月結唯讀） | `admin.js` `admin_*.js` `month_report.js` `reports_api.js` | 手機沿用 + **新增電腦側欄工作台**佈局 |
| 會計核銷/月結/月報表 | `reconcile.js`(737) `month_report.js` `reconcile_api.js` `periods_api.js` | 側欄工作台 + 7 欄核銷表 + app modal |
| 共通燈箱 | `lightbox.js` | 對齊原型互動（本就支援縮放平移） |

**CSS 策略**：app.css 257 行 → 需擴充成 token 化系統（`:root` 三段主題 + 元件層）。決定要不要拆多檔（建議：token/base 一檔 + 各角色版面段落分區註解），plan 階段定。

**Responsive 策略**：桌機側欄工作台在窄視窗要有防爆 fallback（見 manager-desktop `@media(max-width:900px)` 把側欄轉頂列）。員工/主管手機↔平板用彈性斷點。

**部署注意**：純前端改動；**每次改 css/js 要 bump `sw.js` CACHE_NAME**（現 `calc-v51`）+ 硬重整。量不小（多角色 render 重寫），plan 要切成可獨立驗證的小步。

---

## 8. 定案決策（2026-07-17，user「用你建議的」）

- **CSS 組織＝單檔分區**：`app.css` 維持單檔，重塑成 token 化系統——`:root` 三段主題 + base + 元件層 + 各角色版面段落，用清楚註解分區。**暫不拆多檔**：現行無 build step（vanilla ES module + sw 快取靜態清單），拆多檔徒增 sw 快取清單/請求管理負擔；規模真的過大再拆。
- **CSS 機制**：沿用 CSS custom properties（token 已是此做法），**不引入額外 partial/預處理機制**（維持無框架、hands-off）。
- **「刪除店」正式版不接給經理**：UI 原型保留但實作停用/隱藏該按鈕。理由：已有「檢視顯示(隱藏)」+「對外連結(停用 kill-switch)」兩個控制涵蓋日常需求；刪店是高風險破壞性操作，真要刪走後台/DB，降低誤刪。
- **實作順序**：① 會計桌機 pilot 先落地（驗證整套設計系統/token/共通元件）→ ② 經理電腦（沿用同側欄工作台）→ ③ 手機三角色（員工/主管/經理手機）。每步可獨立本機驗證 + bump sw。

---

## 9. 原型即視覺 SoT

5 份原型（`docs/superpowers/ui-prototypes/`）是每個畫面的視覺/互動 single source of truth。實作時對照原型的 DOM 結構、class、互動 JS，**不重新發明視覺**。原型用假資料，實作接現行 API。
