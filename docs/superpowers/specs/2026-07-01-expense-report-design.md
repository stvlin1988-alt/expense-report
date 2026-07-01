# 會計端-雜支自動化報表系統 — Phase 1 設計 (spec)

- 日期：2026-07-01
- 專案：expense-report（`~/projects/expense-report`，與 webapp 完全隔離）
- 範圍：**Phase 1 核心閉環**。Phase 2/3 僅列於文末 roadmap，各自之後再獨立 spec。

---

## 0. 目標與痛點

讓實體門市的雜支報帳**無紙化 + 自動化辨識對帳**：門市員工拍單據 → Gemini 解析（品名摘要 / 分類 / 金額）→ 員工暫存區確認 → 原圖加密存 R2 → **店管理者交接班打勾稽核** → **會計紅綠燈核銷**。系統在資安上做到「影像不進手機相簿、伺服器不留影像、私有加密儲存」。

本專案為**全新獨立系統**，與既有 webapp **零耦合**（獨立 repo / DB / R2 bucket / URL / 命名空間）。

---

## 1. 核心架構

- **前端（門市端）**：PWA，專為公用手機/員工手機設計，響應式。
- **後端**：Flask（Python），部署 Zeabur（2 CPU / 8GB，無 GPU）。未來可移地端。
- **AI 辨識**：**無狀態**呼叫 **Gemini API**，影像以 base64 送出、取回 JSON 後即拋，伺服器不留影像/日誌。包成 `OCRProvider` 介面，未來零改動切換 Vertex AI / 地端模型。
- **儲存**：Cloudflare R2 私有 bucket + 伺服器端加密（SSE）+ TLS；會計看圖用簽章短效 URL。
- **資料庫**：PostgreSQL（Zeabur），本機 dev 用 SQLite。Schema 走 **alembic 正規遷移**。

```
[門市 PWA] --base64--> [後端 API] --圖--> [Gemini OCR]（無狀態，記憶體即拋）
     |                     |--原圖 SSE--> [R2 私有 bucket]
     |                     |--資料------> [PostgreSQL]
[店管理者稽核頁] <---------|
[會計紅綠燈/覆核頁] <-------|
```

---

## 2. 角色與權限

| 角色 | 範圍 | 權責 |
|---|---|---|
| 員工 employee | 單店 | 拍照上傳、暫存區確認/修改、無單據建帳（附原因） |
| 店管理者 manager | 單店（**每店多位**） | 打勾稽核（只看未打勾、確認單筆 + 批次/日總額） |
| 會計 accountant | 全域（1 位） | 紅綠燈核銷、覆核頁；兼系統管理（管分類 / 綁裝置 / 開帳號） |

> **待 review 確認**：會計兼任系統管理（管分類/綁裝置/開帳號）是本 spec 的假設。若要獨立 super-admin 角色，review 時提出。

---

## 3. 資料模型（Phase 1）

- **stores**：id, name, code, active, created_at。seed 同名 webapp 店家（獨立資料，不連 webapp DB）。
- **users**：id, store_id(nullable，會計為 null), name, role(employee|manager|accountant), password_hash, active, created_at。
- **devices**：id, store_id, bound_user_id, token_hash, label, status(active|revoked), fingerprint(**僅稽核用，永不作認證判斷**), last_seen_at, created_at。
- **enrollment_codes**：id, store_id, code_hash, created_by, expires_at, used_at, device_id(nullable)。一次性綁定碼。
- **categories**：id, parent_id(nullable), name, level(1=會計科目 / 2=項目), active, sort。2 層、可增可改。seed 自使用者提供的 excel（見附錄 A）。
- **doc_types**：id, name, retention_days, physical_return_required(bool), purge_policy。單據類型 + 保存規則（見 §6）。
- **expenses**（核心）：
  - id, store_id, created_by
  - **category_id**, **doc_type_id**
  - **amount**（總額）
  - **summary**（品名摘要）
  - **business_date**（依 §5 規則計算）
  - created_at（實際上傳時間，UTC）
  - **has_receipt**(bool), no_receipt_reason(nullable)
  - ocr_raw_json, **ocr_confidence**, **is_modified_by_user**(bool)
  - r2_object_key(nullable；無圖時為 null)
  - **status**（見 §4 狀態機）
  - audited_by, audited_at（店管理者打勾）
  - reconciled_by, reconciled_at（會計核銷）
  - updated_at
- **audit_log**：id, expense_id, actor_user_id, action, before_json, after_json, ts。記錄覆寫軌跡 + 打勾 + 核銷全歷程。

> OCR 只填 summary / category_id(建議) / amount 三項；其餘由系統或人工補。廠商/統編 Phase 1 不做（Phase 2 再評估）。

---

## 4. 狀態機（expenses.status）

```
pending_ocr ──OCR完成──> draft ──員工送出──> submitted ──店管理者打勾──> audited ──會計核銷──> reconciled
                                    │                                        
無圖建帳直接進 submitted            └──(旁支) rejected / void
```

- `pending_ocr`：已收圖、Gemini 處理中。
- `draft`：OCR 完成，待員工在暫存區確認/修改。
- `submitted`：員工送出（原圖已存 R2）。無圖建帳直接進此狀態。
- `audited`：店管理者打勾稽核通過。
- `reconciled`：會計核銷完成。
- `rejected` / `void`：退回 / 作廢。

**兩層覆核**：店管理者打勾（營運自查、交接班增量）→ 會計核銷（帳務終核）。

---

## 5. 營業日與日結

- **營業日分界：每日 08:00**。
  - `business_date(expense)`：上傳時間（台灣時間）在 **00:00–08:00** → 前一日曆日；否則 → 當日曆日。
  - 即「昨天營業日」= `[昨天 08:00, 今天 08:00)`；活動集中在晚上 20:00 之後（夜間營業型態）。
- **每日結算一次**：把某營業日區間結掉、算出當日總額，供交接班打勾稽核確認總額。
- 打勾稽核頁預設只列 `submitted` 且**未打勾**者，顯示批次小計與（依 business_date 的）日總額。

---

## 6. 單據類型 → 保存 / 銷毀（retention）

| 單據類型 | 例子 | retention_days | 實體繳回 |
|---|---|---|---|
| 統一/電子發票 | 全家電子發票明細 | 30 | 否 |
| 收據 | 手寫收據 | 對完即銷（核銷後即刪） | 否 |
| 小白單（手寫估價/銷貨單） | 估價單、銷貨單 | 附件到期銷毀 | **是** |
| 水電/勞健保/規費 | 代書申報類 | 60（兩個月給代書） | **是** |

- Phase 1：schema 存好 `doc_type_id` 與保存政策欄位；**自動銷毀排程排入 Phase 3**。
- R2 lifecycle 不用單一 60 天粗規則，改由各 doc_type 的 retention 驅動（Phase 3 實作）。

---

## 7. OCR / Gemini 設計

- **抽取欄位（僅三項）**：`summary`（品名摘要）、`category`（Gemini 從分類清單建議會計科目+項目）、`amount`（總額）。
- **金額規則**：抓「最終應付的那個數」，優先辨識**紅筆圈選值**（門市 SOP：手寫單紅筆圈總額）。
- **強制 JSON 結構化輸出**；分類清單於 prompt 內提供，Gemini 回建議分類，員工在暫存區確認。
- **信心度 / 紅綠燈**：
  - 🟢 綠：印刷 + 高信心 + 員工未改 → 支援一鍵批次核銷。
  - 🟡 黃：某欄位低信心 → 該欄黃底提示。
  - 🔴 紅：手寫 or 員工改過金額/分類 or 金額 parse 失敗 → 強制人工覆核。
  - 信心判定 = 印刷/手寫訊號 + Gemini 自評 + 金額能否 parse 成合理數字。
- **覆寫軌跡**：員工若改動金額/分類，`is_modified_by_user=true` 並寫 audit_log。
- `OCRProvider` 介面：`recognize(image_bytes) -> {summary, category_suggestion, amount, confidence, raw}`。現接 Gemini API，未來換 Vertex/地端。

---

## 8. 核心流程

1. **上傳流（員工）**
   - 開 PWA → 裝置 token 驗證（無 token 擋下、要求重綁）。
   - 拍照：HTML5 `<input capture="environment">`，影像留記憶體、**不進相簿**。
   - `POST` base64 → 後端無狀態呼叫 Gemini → 建 `draft`（summary/分類建議/金額）。
   - 員工在**暫存區**確認/修改 → 送出 → 後端把原圖存 R2（SSE、私有）、狀態轉 `submitted`、記 is_modified。
   - **無圖建帳**：員工選「無單據」+ 原因 + 手填三欄 → 直接 `submitted`，has_receipt=false。
2. **稽核流（店管理者）**
   - 列本店 `submitted` 未打勾 → 逐筆確認金額 → 顯示批次小計 + 日總額 → 打勾（`audited`）。交接班多次、增量。
3. **核銷流（會計）**
   - 紅綠燈儀表板（可篩店/日期）→ 綠燈一鍵批次核銷；紅/黃燈開**左圖右表**覆核頁（簽章 URL 即時取圖、可放大）→ 核銷（`reconciled`）。

---

## 9. 資安

1. **影像不落地**：門市端拍照記憶體直傳，絕不存手機相簿。
2. **伺服器不留影像**：Gemini 無狀態辨識，取回 JSON 即拋，不寫暫存檔/日誌。
3. **儲存加密**：R2 私有 bucket + SSE + TLS；會計看圖用簽章短效 URL。
4. **裝置認證**：綁定碼 + 裝置 token（httpOnly cookie）綁「裝置＋員工＋店」；換機由會計/管理撤舊發新；**fingerprint 只記錄供稽核，永不作認證判斷**（記取碰撞教訓）。
5. **無圖不報帳（軟性）**：預設要圖；特定科目可標「無單據」+ 原因。
6. **CSE（客戶端加密）**：延 Phase 3（公用手機管金鑰風險高）。

---

## 10. 錯誤處理 & 容量

- **前端絕不輪詢**：拍完即走，draft 處理好後在暫存區列表出現（Phase 1 開列表拉一次，不用固定 setTimeout 賭時間）。避免「前端輪詢 + 後端重 pipeline」拖垮服務。
- Gemini 逾時/失敗 → 該筆進 `draft` 空欄 + 紅燈，員工手填，不卡前端。
- R2 上傳失敗 → 標記待重傳 / retry。
- 狀態全進 **DB**（workers>1 不用 module-level dict 存跨 request state）。
- OCR 走 API、不佔本機 CPU → 2 CPU / 8GB 安全；若有 CPU-heavy 本地處理（如影像壓縮）須走 gevent threadpool。
- 時間 UI 一律**台灣時間**（DB 存 UTC，顯示轉 TW_TZ）。
- config 檔（YAML/JSON/Dockerfile）commit 前**跑 parser 驗證**。

---

## 11. 測試策略（TDD）

- **單元**：Gemini 回傳 parser（mock）、金額 sanity、business_date 08:00 分界計算、狀態機轉移、店 scoped 權限隔離、retention 天數計算、裝置 token 驗證。
- **整合**：上傳流 end-to-end（mock Gemini + R2）、裝置綁定/換機、打勾稽核增量、綠燈批次核銷。
- **本機流程**：SQLite dev → 本機測試 → /dev 切帳號 → OK 才 push（依既有習慣）。

---

## 12. 部署 / 隔離

- 新 repo `~/projects/expense-report`；獨立 Zeabur PG、獨立 R2 bucket、獨立 blueprint/URL。
- **完全不碰 webapp**（DB/程式/記憶皆隔離）。
- Schema 用 **alembic**（新專案不背 webapp 的 inline-ALTER 債）。
- 依賴鎖版；影響 build/部署的改動動手前先告知。

---

## Roadmap（Phase 2 / 3，本次不設計）

- **Phase 2**：月結 Excel（樞紐 + 明細雙活頁簿）、管理 Dashboard（分類佔比 / 分店排行 / 異常激增）、綠燈一鍵批次核銷強化。
- **Phase 3**：到期自動銷毀排程（依 doc_type retention）、代書匯出、客戶端加密（CSE）、異常警示。

---

## 附錄 A：會計科目分類 seed（來源：使用者 excel 0626）

2 層：會計科目（大類）→ 項目（細項）。可增可改。

- **薪資費用**：員工薪資、薪資提存、津貼、離職員工薪資、留停員工薪資、員工介紹獎金、年終獎金、激勵獎金、生日禮金、結婚禮金、彌月禮金、端午禮金、中秋禮金、尾牙禮金、過年禮金、奠儀、住院慰問金、健檢費、員工旅遊、教育補助
- **租金支出**：房租、停車場租金、車位租金、管理費
- **郵電費**：視訊費、電信網路費
- **稅捐**：營業稅、娛樂稅、房屋稅、房屋租賃稅、綜所稅申報、汽燃稅、牌照稅
- **水電瓦斯**：水費、電費、瓦斯費
- **保險費用**：健保費、勞保費、勞退金、公共安全申報、消防安檢申報、公共意外險、產物險、其他保險費
- **活動費用**：現場獎、會員禮品、會員活動、節日禮品.活動
- **修繕費用**：店面維護費、車輛維護費、金磚維修費、其他機台維修費、掛畫維修
- **廚房支出**：食材、中廚食材、中廚物料、中廚禮品、中廚茶葉、中廚修繕費、中廚雜項支出
- **廣告支出**：廣告費、簡訊費、美工製作費
- **其他費用**：神秘彩金、擋退招/補客、代書帳務費、律師顧問費、裝修工程費、雜項支出、團康費用、公益活動、公關費、誤差

## 附錄 B：決策紀錄（2026-07-01）

1. OCR = Gemini API（`OCRProvider` 可抽換，上線後再評估 Vertex/地端）
2. 本次只定 Phase 1 核心閉環
3. 角色/規模：員工 3–5/店、店管理者多位/店、會計 1；多店（同 webapp）；每店 20–50 筆/日
4. 與 webapp 完全隔離（自寫裝置認證、seed 同名店、不用 fingerprint 自動認證）
5. 分類 = 2 層（11 會計科目 → 項目，可增可改）
6. 預設要圖、特定科目可標「無單據」
7. 一張單 = 一筆（取總額），明細為附帶資訊
8. 資安：裝置綁定碼+token、R2 SSE、覆核頁即時取圖；retention 用 §6 表
9. 打勾稽核由店管理者做（每店多位）；兩層覆核
10. OCR 只抓 品名摘要 / 分類 / 金額；日期不靠 OCR
11. 營業日 08:00 分界；每日結算 `[昨天08:00, 今天08:00)`
