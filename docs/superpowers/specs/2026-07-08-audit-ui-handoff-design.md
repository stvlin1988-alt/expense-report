# 稽核 UI 交接核對強化 設計（audit UI handoff）

> Phase 1 稽核（Plan 5）的 UI 補強。疊在 branch `feat/phase1-audit` 上（與稽核/OCR 一起 e2e、一起 merge）。緣起＝user e2e 回饋。

## 1. 背景

Plan 5 稽核已上線，但 user 實測交接核對時發現幾個 spec 有寫或該有、但前端沒做的功能。本設計補齊，聚焦「店管理者交接班時能逐班核對明細」。

## 2. 範圍（要做）

1. **待稽核 / 明細顯示建立時間**（台灣時間）。
2. **當日總表 inline 展開看每班明細**（spec §152）：點某交班區間或「當前未歸班」→ 就地展開該群組的每一筆單。
3. **翻閱歷史稽核日**（spec §122/§154，後端 `?before=` 已支援）：當日總表加「稽核日」下拉，選已結班的過去日看該日總表。
4. **放大看原單**：待稽核列與明細列的縮圖可點開看原始收據大圖。
5. **暫存區重整鈕 + 辨識中標示**：拍完背景 OCR 未完成時，`pending_ocr` 列標「🕓 辨識中…」，並加「重整」鈕（前端不輪詢，靠手動重整）。
6. 明細列一併顯示 **稽核者 / 稽核時間 / 主管是否改過**（`audited_by` 姓名、`audited_at`、`is_modified_by_manager`）——交接核對關鍵資訊，資料庫已存、目前無處可見。

## 3. 範圍外（不做，屬後續階段）

退回/駁回 submitted、作廢、會計核銷紅綠燈、月結/Dashboard、reconciled 實際生效、搜尋/篩選。

## 4. 鐵律 / 約束

- 時間 UI 一律台灣時間（Asia/Taipei）顯示，DB 存 UTC。時間格式化用純函式（可 `node --test`）。
- per-store scope 沿用 `_scope_store_id`：manager 用本店、super_admin 需選定 store_id；跨店 403。
- 前端不輪詢：暫存區靠「重整」鈕手動刷新，不加輪詢/cron。
- 影像不落地：放大原圖用 R2 presigned URL（短效），不落伺服器檔案系統。
- 不新增 Python 依賴。
- 每次改前端 JS/CSS 必 bump `app/static/sw.js` 的 `CACHE_NAME`。
- 沿用回傳慣例 `jsonify(status="ok", ...)`；沿用既有 `serialize_expense`。

## 5. 後端

### 5.1 明細序列化（含稽核欄位 + 原圖 URL）
新 `app/audit/serialize.py` `serialize_audit_item(e, storage, actor_name_by_id)`：
- 以既有 `serialize_expense(e, storage, with_main=True)` 為基底（已含 id/status/summary/category_id/amount/light/created_at/thumb_url/**image_url**）。
- 疊加：`audited_by`（id）、`audited_by_name`（查 User.name，用預載 dict 避免 N+1，null→None）、`audited_at`（isoformat|null）、`is_modified_by_manager`（bool）、`business_date`（isoformat|null）。

### 5.2 端點（全部 `@role_required("manager","super_admin")`，scope 統一）
| 端點 | 作用 |
|---|---|
| `GET /audit/handover/<int:hid>/items {store_id?}` | 某交班/結班區間的明細。驗 handover 屬本 scope store（否則 404/403）；回 `{status:"ok", items:[serialize_audit_item...]}`，依 `submitted_at`/`created_at` 排序。 |
| `GET /audit/open-items {store_id?}` | 當前未歸班明細＝該店 `status='audited' 且 handover_id IS NULL`。回 `{status:"ok", items:[...]}`。 |
| `GET /audit/days {store_id?}` | 歷史稽核日下拉用。回該店 `type='day'` handover 清單（結班日），依 `closed_at desc`：`{status:"ok", days:[{handover_id, closed_at}]}`。前端組「今日(當前)」+ 各結班日日期。 |

（`GET /audit/summary?before=<day-close handover_id>` 已存在、不動——選過去日就打它。）

## 6. 前端（`app/static/js/admin_audit.js` 為主）

### 6.1 時間格式化（純函式）
`app/static/js/audit_util.js` 加 `formatDateTimeTW(iso)` → `MM/DD HH:mm`（`toLocaleString('zh-TW',{timeZone:'Asia/Taipei',...})`，null/空→`'—'`）。`node --test` 覆蓋。

### 6.2 待稽核（`renderPending`/`rowHtml`）
- 表頭與每列加「建立時間」欄（`formatDateTimeTW(e.created_at)`）。
- 縮圖包成可點：點 → 放大原圖（見 6.5）。`/audit/pending` 序列化改用 `serialize_audit_item`（帶 image_url；建立時間已在 created_at）。

### 6.3 當日總表 inline 展開明細（`renderSummary`）
- 每個 interval 列與「當前未歸班」列改為可點展開。點該列 → fetch（interval 打 `/audit/handover/<hid>/items`；當前未歸班打 `/audit/open-items`）→ 就地在該列下方插入子表，再點收合。
- 子表每列：建立時間 / 縮圖(可放大) / 摘要 / 分類名 / 金額 / 燈號 / **稽核者(audited_by_name)** / **稽核時間(audited_at, TW)** / **改過**（`is_modified_by_manager` → 顯示標記如「主管改」）。
- 展開狀態純前端（class toggle）；同一列重複點在展開/收合間切換；重取資料即可（低量，不快取）。

### 6.4 歷史稽核日下拉（`renderSummary`）
- 子區頂部加 `<select id="au-day-select">`：第一個 option =「今日（當前）」(value 空)；其後每個 `/audit/days` 的結班日一個 option（label＝`formatDateTimeTW(closed_at)` 的日期部分，value＝handover_id）。
- change → 重繪 summary：value 空 → `auditSummary(sid)`（今日）；否則 `auditSummary(sid, handoverId)`（`?before=`）。展開明細在過去日一樣可用（interval 打 items 端點）。

### 6.5 放大原圖（lightbox）
- `admin_audit.js` 加 `openImageLightbox(url)`：全螢幕半透明遮罩 + 置中大圖 + 點遮罩/Esc 關閉。無 url 時不開。
- 待稽核縮圖、明細縮圖點擊 → `openImageLightbox(e.image_url)`。純前端、無新依賴。

### 6.6 暫存區重整 + 辨識中（`app/static/js/pending.js`）
- 標題列加「重整」鈕 → 重新 `showPendingView(onBack)`（重拉清單）。
- `status==='pending_ocr'` 的列：燈號/摘要欄顯示「🕓 辨識中…」提示（縮圖已是 🕓），讓 user 知道背景 OCR 未完成、稍後重整。

### 6.7 admin_api 方法
`app/static/js/admin_api.js` 加：`auditHandoverItems(hid, storeId)`、`auditOpenItems(storeId)`、`auditDays(storeId)`（沿用 `req`/`withStore`）。

### 6.8 CSS + sw
`app/static/css/app.css` 加 lightbox 遮罩、展開子表、可點縮圖 cursor、建立時間欄樣式（配既有 `.ap-*`/`.pd-*` 亮色）。每個動前端的 task bump `app/static/sw.js` `CACHE_NAME`。

## 7. 測試策略

- **純邏輯**：`formatDateTimeTW`（`node --test`：正常 iso→MM/DD HH:mm、null→'—'）。
- **後端**：`/audit/handover/<hid>/items`（回該班單、跨店 handover→403/404）；`/audit/open-items`（只回 audited+handover_id null）；`/audit/days`（只回 type='day'、依序）；`serialize_audit_item`（含 audited_by_name/audited_at/is_modified_by_manager/image_url，N+1 預載正確）。
- **DOM 膠合**（展開/下拉/lightbox/重整）：手動 e2e（`/dev/login-manager`、`/dev/login-test`）。

## 8. 檔案異動概覽

- 新：`app/audit/serialize.py`（serialize_audit_item）、`tests/test_audit_items.py`、`tests/test_audit_days.py`、`tests/js/audit.mjs` 補 formatDateTimeTW。
- 改：`app/audit/routes.py`（3 端點 + pending 改用 serialize_audit_item）、`app/static/js/admin_audit.js`（建立時間欄/展開明細/歷史下拉/lightbox）、`app/static/js/admin_api.js`（3 方法）、`app/static/js/audit_util.js`（formatDateTimeTW）、`app/static/js/pending.js`（重整+辨識中）、`app/static/css/app.css`、`app/static/sw.js`（bump）。

## 9. 決策紀錄

- 展開明細＝**inline 就地展開**（非彈窗）：交接時同頁對照，不打斷。（user 定案）
- 歷史稽核日＝**日期下拉清單**（非上/下一日翻頁）：直接跳指定日。（user 定案）
- 暫存區＝**重整鈕 + 辨識中標示**（不輪詢）：符合鐵律。（user 定案）
- 放大原圖＝**納入**（lightbox，presigned URL）。（user 定案）
- 明細一併顯示稽核者/時間/主管改過標記：資料已存、交接核對高價值、成本低，故納入。
