# 經理手機 App UI 設計 spec（super-mobile，2026-07-23）

> 對應母 spec：`docs/superpowers/specs/2026-07-17-ui-redesign-design.md` §5.4（經理・手機）。
> 視覺 single source of truth：`docs/superpowers/ui-prototypes/super-mobile.html`。
> 前置依賴：經理電腦版（`2026-07-20-ui-redesign-manager-desktop.md`，已落地）已把所有可重用 render 建成 `.wk-*`；主管手機版（`2026-07-22-ui-redesign-manager-mobile.md`，已落地）已建 `.mb-*` 手機設計層與 `mb_util.js` 共用工具。

## 1. 目標與範圍

把經理（super_admin）在**手機/平板**上的體驗，從現行「一律進桌面側邊欄工作台（`showAdminPanel`，`admin.js`）」重塑成原型 `super-mobile.html` 的「常駐手機殼（抬頭跨店選店 ＋ 可橫捲主分頁 ＋ 內容 pane）」。經理在桌機仍走既有 `showAdminPanel` 工作台（不動）。

**只涵蓋 §5.4（經理手機）。** 經理電腦（§5.5）已於 manager-desktop plan 落地，本 spec 不動它。

## 2. 架構

純前端／CSS／DOM 重塑，**不動後端、不改 API、不改任務流、不碰計算機幌子（`calculator.js`/`secret.js`）、角色守門全沿用現況**。

- 新增 `app/static/js/super_app.js`：`export function showSuperApp(identity)`，經理手機殼。沿用員工/主管已建的 `.mb-app`/`.mb-appbar`/`.mb-content`/`.mb-pane`/`.mb-toast` 基底與主管的 `.mb-toptabs` 橫捲主分頁；共用工具 `mbToast`/`stopPaneCamera`/`postJSON` 取自 `mb_util.js`。
- 沿用經理電腦版已建好的 render：`renderMonthReport`（`month_report.js`）、`renderAudit` 的 isSuper 唯讀分支（`admin_audit.js`）、`renderAccounts`/`renderDevices`（`admin_accounts.js`/`admin_devices.js`）、`renderLogs`（`admin_logs.js`）、店別管理 API（`api.setStoreViewable`/`setStoreActive`/`createStore`）、`api.changeMyPassword`。
- 桌面工作台 `showAdminPanel` **保留不動**（經理電腦續用；主管走 `showManagerApp` 不受影響）。

### 2.1 登入路由（依裝置判一次）

`auth.js`（密碼登入成功，:126）與 `main.js`（暗號 re-entry，:169）現行 `super_admin` 分支一律 `showAdminPanel(identity)`。改為**登入當下判一次**：

```js
// super_admin：觸控裝置（手機/平板）→ 手機殼；滑鼠桌機 → 側欄工作台
else if (data.role === 'super_admin') {
  if (window.matchMedia('(pointer: coarse)').matches) showSuperApp(identity);
  else showAdminPanel(identity);
}
```

- **主訊號＝`pointer: coarse`**（觸控為主），不是純寬度：手機**橫放仍是手機**（手機永遠 coarse，橫放寬度可達 ~932px 會誤判為桌機，故不能只看寬度）。平板（也是 coarse）走手機殼——主管手機殼已有「≥768px 框住 760px 置中」處理，平板剛好。
- **判一次，不即時切**：登入後不因 resize/rotate 重新路由。桌機使用者把視窗拉窄時，由 `showAdminPanel` 自身的 `@media(max-width:900px)` fallback（側欄轉頂列）頂著，不需換殼。
- `main.js` / `auth.js` 頂部補 `import { showSuperApp } from './super_app.js';`。

## 3. 選店抬頭（經理專屬跨店）

經理與主管最大差異：**主管鎖本店（`sid=undefined`），經理可跨店選任一店**。

- 抬頭放**選店 `<select>`**：`全部門市` + 各 `viewable !== false` 店的 `code`（英文代號，≤2 字母，**絕不露中文店名**）。
- 殼層 `state.storeId`（`null`＝全部門市）。選店 change → 更新 `state.storeId` + `localStorage`（沿用桌面 `admin_store_id` key）→ 重繪當前 pane。
- **同時決定「稽核」與「月報表」看哪家**（對齊原型抬頭語意 `aria-label="選擇門市（同時決定稽核與月報表）"`）。切到其他 pane（店別/帳號/裝置/操作記錄/我的密碼）不受選店影響。

## 4. 主分頁與 pane（混合策略）

主分頁（`.mb-toptabs` 可橫捲，**不可藏任何分頁**）：**稽核 / 月結 / 店別 / 帳號 / 裝置 / 操作記錄 / 我的密碼**（對齊原型 tab 順序）。進站預設「月結」（原型 `aria-selected="true"` 在 month）。

| Pane | 做法 | 內容 |
|---|---|---|
| **月結** | 🆕 原生殼 + ♻️ 重用交叉表 | 原生「月結設定唯讀卡」（🔒 banner：僅會計可改；kv：月結日等，資料同 `admin.js:renderClosing` 的 periods GET）+ segmented 範圍（全部門市／單店，與抬頭選店連動）+ `renderMonthReport(el, { storeId: state.storeId!=null?String(state.storeId):'', lockStore:true })`（產 `.wk-xt`，科目 sticky 首欄＋橫捲，套 `.mb-admin-embed`／橫捲框）。 |
| **稽核（唯讀）** | ♻️ 重用 embed | `renderAudit(el, identity, state.storeId, state.stores)` 的 **isSuper 唯讀分支**（依營業日分組、燈號＋徽章、零操作鈕、「全部門市」空狀態要先選店），包 `.mb-admin-embed`。 |
| **店別管理** | 🆕 原生 `.mb-*` 卡片 | 店別卡：對外狀態徽章 + **檢視顯示打勾 toggle**（`api.setStoreViewable`）+ **對外連結 kill-switch**（`api.setStoreActive`，關閉走確認）+ 新增店 form（`api.createStore`）。**不接刪店**（見 §6）。 |
| **帳號 / 裝置 / 操作記錄** | ♻️ 重用 embed | `renderAccounts(el, ctx())`／`renderDevices(el, ctx())`／`renderLogs(el, identity, state.storeId)`，包 `.mb-admin-embed`（原型本就標「佔位示意」）。 |
| **我的密碼** | 🆕 自寫小表單 | `api.changeMyPassword`（同主管手機 `renderMyPasswordPane`；純前端防呆：長度／兩次一致）。 |

**月報表交叉表決策（重用 `renderMonthReport`）**：與桌面共用。全部門市模式的 `.wk-xt` 已「科目 sticky 首欄＋橫捲」＝原型手機交叉表行為，且**還多了大類展開子分類**（原型全部門市模式反而沒有）；單店模式的 `.wk-xt-one` 兩欄小表在手機上很窄、不需橫捲、堪用。手刻 `.mb-xt` 只換到單店「單欄清單 vs 兩欄小表」的細微觸感，卻要複製交叉表消費/DOM 邏輯、與桌面雙軌漂移，故不手刻。

**`ctx()` 契約**（供 `renderAccounts`/`renderDevices` 重用，與桌面一致）：`{ identity, storeId: state.storeId, stores: state.stores, api, reload, refreshStores }`。

## 5. CSS / sw / 測試

- `app/static/css/app.css` append「手機設計層－經理」段落（原生元件：`.mb-store-card` 家族／kill-switch／`.mb-closing-*` 月結唯讀卡／segmented 範圍等），沿用既有 `--wk-*`／`--mb-*` token，**不重定義 token**。舊段落不動。
- 每 task bump `sw.js` CACHE_NAME；收尾補 `super_app.js`／`month_report.js`／`reports_api.js`／`periods_api.js` 進 `STATIC_URLS`（`admin_audit.js`/`admin_accounts.js`/`admin_devices.js`/`admin_logs.js`/`mb_util.js` 主管手機 plan 已補齊，確認即可）。
- **驗證分軌**（同員工/主管手機 plan）：純函式不動（`formatCell`/`pickCell` 維持行為）→ 每 task 重跑 `node --test tests/js/*.mjs`（71 passed 基準）；後端未動 → `python3 -m pytest -q`（567 passed 基準，防呆）；DOM/CSS → 本機 `/dev/login-super` 對照 `super-mobile.html` 逐項目視。
  - ⚠️ 手機殼路由用 `pointer:coarse`，桌機瀏覽器目視驗證時可用裝置模擬（touch）或暫時在 `showSuperApp` 加臨時入口；驗證後移除。

## 6. 定案決策

- **刪店不接**（沿用母 spec §8）：原型店別卡的刪除鈕不實作、不出現。理由：「檢視顯示(隱藏)」+「對外連結(kill-switch)」已涵蓋日常；刪店高風險。
- **月報表交叉表重用 `renderMonthReport`**（§4，user 定案「重用」）。
- **登入判一次、不即時切**（§2.1，user 定案）；路由主訊號 `pointer:coarse`（手機橫放仍手機，user 提出並確認）。
- **混合策略**（§4，user 定案「混合」）：店別／月結殼原生，稽核唯讀／帳號／裝置／操作記錄重用 embed，我的密碼自寫。

## 7. 風險 / 注意

- **不動後端是鐵律**：只呼叫既有 API。code review 確認無新增/改 `.py`。
- **跨店語意**：經理 `state.storeId` 可為任一店或 null（全部門市）；稽核與月報表都吃它。對照主管的 `sid=undefined`（鎖本店）——兩者路徑不同，勿混用。
- **舊碼不刪**：經理改走 `showSuperApp`（手機）後，`showAdminPanel` 桌面續用（經理電腦＋任何 fine pointer）；本 plan 不刪 `admin.js` 任何分支。
- **PWA 快取**：每 task bump sw；收尾補 STATIC_URLS。
- **測試盲區**：手機 render 層無 DOM 單元測（靠後端 API 測 + 本機目視）；純函式維持行為、每 task 重跑 node 測。

## 8. 原型即視覺 SoT

`docs/superpowers/ui-prototypes/super-mobile.html` 是每個畫面的視覺/互動 SoT。實作對照原型 DOM 結構、class、互動；原型用假資料，實作接現行 API（`reports_api`/`periods_api`/`admin_api`）。原型的假班別/假日期/假金額**不照搬**，只顯示後端實際回傳欄位。
