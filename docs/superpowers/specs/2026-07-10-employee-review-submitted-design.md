# 員工「複查」區（唯讀）設計

日期：2026-07-10
狀態：定案，待實作

## 目標

讓員工在**主管尚未交班／結班**之前，回頭檢視自己這一班已送出（`submitted`）的單，複查金額。純唯讀：發現金額不對只能看、口頭告知主管，由主管在稽核端修正。

## 背景與現況

員工端目前只有「拍單」與「確認區」：
- 確認區（`GET /expenses/pending`）只顯示 `status ∈ {pending_ocr, draft}`。
- 員工按「送出」後 `status` 變 `submitted`，該單立即從確認區消失，員工再也看不到。
- 之後主管稽核（`check` → `audited`）、交班／結班（建 `Handover`、蓋 `handover_id`）。

缺口：送出後、交／結班前這段期間，員工無法複查自己送出的金額。

### 交班／結班機制（既有）

- 交班（shift）與結班（day）在後端都是 `POST /audit/handover`，各建一筆 `Handover`（`type` 分別為 `shift`／`day`），並把「本店 `status == 'audited'` 且 `handover_id IS NULL`」的單一次蓋上該 `handover_id`（`app/audit/routes.py`）。
- **注意漏洞**：主管沒核就交／結班的單（`submitted` 但未 `audited`）**不會**被蓋 `handover_id`（handover 的 UPDATE 只圈 `audited`）。這類單會滾到下一班／隔天，`handover_id` 仍為 NULL。

## 複查區資料範圍

一筆單出現在某員工複查區，當且僅當**全部**成立：

1. `created_by == 目前員工`（只看自己的）
2. `status ∈ {submitted, audited}`
3. `handover_id IS NULL`
4. `submitted_at` 晚於**本店最近一次 `Handover` 的 `closed_at`**；若本店還沒有任何 handover，則此條免除（全顯示）

第 4 條是關鍵：以「本店最後一次交／結班時間」為界，讓**交班與結班一致地清空複查區**——一旦主管按下交班或結班，該時刻之前送出的單（**含主管沒核到的 `submitted`**）全部從複查區消失，員工只剩「上次交／結班之後、這一班新送出」的單。第 3 條對已核單其實已由 handover 蓋 `handover_id` 涵蓋，保留作為明確保護。

排序：`day_seq` 遞增（同 `business_date` 內單號序），退而 `submitted_at`。

## 後端

新增 `GET /expenses/submitted`（掛在既有 `expense_bp`，`current_user` 認證，未登入 401）：

- 查詢：先取本店最近一次 `Handover.closed_at`（依 `store_id` 為員工的 `store_id`），組上述四條件。
- 回傳：沿用 `serialize_expense(e, storage, with_main=True)`（含 `image_url` 供放大原圖、`thumb_url`、`doc_no`、`amount`、`summary`、`created_at`），額外補 `category_name`（分類顯示名，唯讀，不給下拉；以一次 `Category` 批次查詢建 id→name map 注入）。
- **不回 status 標籤、不揭露主管核了沒**（依 user 定案，員工只複查金額，不需知道稽核狀態）。
- 純唯讀：不新增／不修改任何寫入端點，不動既有鎖定與 handover 邏輯。

## 前端

- `expenses_api.js`：加 `listSubmitted()` → `GET /expenses/submitted`。
- 新 `showReviewView(onBack)`（置於 `pending.js` 或新檔 `review.js`）：唯讀表格，欄位＝**單號 / 圖（可放大，共用 `lightbox.js`）/ 摘要 / 分類名 / 金額**。
  - 無任何輸入框、無下拉、無送出／丟棄／重新辨識鈕。
  - 頂部只有「↻ 重整」與「返回」。
  - 空資料顯示「本班沒有已送出的單」。
  - 金額、摘要、分類、單號全部 `escapeHtml` 純文字輸出（XSS 防護）。
- `showAppView`（`auth.js`）員工區新增按鈕「**複查**」，開 `showReviewView`；沿用既有 `cam.stop()` → 進畫面 → 返回回 `showAppView` 的模式。
- bump `sw.js` 快取版號（現 calc-v35）。

## 測試

後端 pytest（新測檔或加進 `test_audit_handover.py` 同區）：

1. 只回本人送出的單，看不到同店他人的（跨員工隔離）。
2. 只回 `submitted`／`audited`；`draft`／`pending_ocr` 不回。
3. `handover_id` 非空的不回。
4. 只回「最近一次 handover 之後送出」的：建一筆送出 → 交班 → 該單消失；交班後再送出的新單出現。
5. **結班同交班一致**：未核到的 `submitted` 單在結班後也從複查區消失（驗第 4 條時間界對 `day` 型 handover 同樣生效）。
6. 未登入 401。
7. 回傳含 `category_name`、`image_url`、`doc_no`。

前端唯讀渲染屬 DOM 膠合，本機 e2e 驗（員工登入 → 拍單送出 → 複查看到 → 主管交班 → 複查清空）。

## 非目標（YAGNI）

- 員工端不做任何編輯／退回／重送（唯讀）。
- 不顯示稽核狀態、不顯示軌跡（軌跡本就員工端不顯示）。
- 不做分頁／歷史查詢（只看「當班未交／結班」的窗）。
