# Phase 1 — 拍單 + OCR + 暫存區 + 送出（Plan 4）

> 狀態：設計定案（2026-07-07），待寫實作計畫。
> 前置：Plan 1（foundation）、Plan 2（認證/裝置）、Plan 3a（終端登入）、Plan 3b（後台管理 UI）皆已完成並 merge master。
> 範圍切分：本份 = **雜支系統本體第一刀**（員工拍單→辨識→暫存區確認→送出存 R2）。稽核（店管理者打勾）、核銷（會計紅綠燈）、月結另立 Plan 5 / 6 / Phase 2。

---

## 1. 目標與定位

登入後目前停在占位頁（Plan 3a `showAppView`）。本 plan 把**雜支系統本體的入口段**接上：員工在門市 PWA 拍雜支單據 → Gemini 辨識出（摘要 / 分類 / 金額）→ 員工在暫存區用表格批次確認/修改 → 送出 → 原圖壓縮加密存 R2、狀態轉 `submitted`。

完成後可端到端驗證：登入 → 拍一疊單 → 背景辨識 → 回暫存區逐列比對確認 → 送出 → 資料落 DB、圖落 R2。

全程遵守既有鐵律：**影像不落地**（記憶體→壓縮→R2 直上，不寫暫存檔）、**前端不輪詢**、**時間 UI 台灣時間 / DB 存 UTC**、**營業日 08:00 分界**、狀態全進 DB。

### 非目標（明確排除）
- 稽核流（店管理者打勾 `audited`、交接班日總額）→ Plan 5。
- 核銷流（會計紅綠燈儀表板、綠燈批次核銷、左圖右表覆核 `reconciled`）→ Plan 6。
- 月結 Excel / Dashboard → Phase 2。
- `doc_type` 選擇 UI 與 R2 retention 生命週期 → Phase 3（本 plan 只留欄位）。
- `audit_log` 全表軌跡 → Plan 5（本 plan 用 `is_modified_by_user` 旗標即足）。

---

## 2. 核心流程（Flow B：拍完即走、伺服器背景辨識）

**決策（user 拍板 2026-07-07）**：員工按「完成」後**可立即離開**，辨識在伺服器背景進行，晚點回暫存區看結果——彈性大。

### 2.1 拍單（前端「無腦版」）
1. 拍照 view：點快門拍一張（`camera.js` 單張 base64、記憶體、不進相簿）→ 出現兩鍵 **[完成] [下一張]**。
2. [下一張] → 再拍，累積在**手機記憶體陣列**，可連拍多張。
3. [完成] → 前端**逐張** `POST /api/v1/expenses`（可小並發加速），每張請求：
   - 後端解 base64 → `process_upload_image` 壓縮出 main+thumb（CPU-heavy，走 ThreadPoolExecutor+timeout）→ 上傳 R2（SSE 私有）→ 建 `expenses` row（`pending_ocr`）→ **丟背景 daemon thread**（帶 app_context、開新 DB session）呼叫 Gemini → **立刻回 202 `{id}`**。
   - 前端「上傳中 k/N」進度隨每個 202 遞增（**天生不輪詢**：進度來自請求自身返回，非戳狀態端點）。
4. 全部 202 收齊 → 前端顯示「已送出背景辨識，可離開，稍後到暫存區確認」→ 員工可走。
5. 背景 thread：Gemini 回 → 更新 row 成 `draft`（填 summary/category_id/amount/信心訊號/ocr_raw）；逾時或失敗 → `draft` 空欄 + 紅燈訊號。

### 2.2 暫存區確認（前端表格）
1. 員工開暫存區 view → `GET /api/v1/expenses/pending` **拉一次**（不輪詢）→ 回本人所有 `draft` + 尚在 `pending_ocr` 者，含 thumb 簽章 URL。
2. **列表拉取時順手收斂 orphan**：凡 `pending_ocr` 且 `created_at` 逾 `OCR_STALE_SECONDS`（預設 120s）仍無結果 → 就地標成 `draft` 空欄 + 紅燈（涵蓋 worker 重啟 / thread 死掉，無需 cron）。
3. 表格每列一張單：**縮圖 / 摘要(可改) / 分類(2 層下拉) / 金額(可改) / 燈號 / 動作**。點縮圖開 main 簽章 URL 大圖比對。
4. 改動 summary/category/amount → `PATCH /api/v1/expenses/<id>` → 設 `is_modified_by_user=true`（燈號轉紅）。
5. 每列 [送出] 或底部 [全部送出] → `POST /api/v1/expenses/<id>/submit` → `draft`→`submitted`、算 `business_date`。[丟棄] → `DELETE`（連 R2 物件一併刪）。
6. 表格上方 **[＋無單據建帳]** → 表單（摘要/金額/分類/原因）→ `POST /api/v1/expenses/no-receipt` → 直接建 `submitted`（無圖、無 OCR）。

### 2.3 為何前端逐張同步上傳 + 伺服器背景 OCR
- 前端逐張上傳給「上傳中 k/N」真實進度且不輪詢；伺服器背景跑 Gemini 讓員工按完成即走。
- R2 存在「拍照當下（上傳時）」而非「送出時」——因為批次確認時實體單已不在手，暫存區必須看得到圖才能核對。廢棄（未送出）draft 的圖暫留 R2，等 Phase 3 retention 清。

---

## 3. 狀態機（本 plan 使用區段）

```
pending_ocr ──Gemini完成──> draft ──員工送出──> submitted
     │                        ▲
     └──逾時/失敗/orphan收斂──┘（draft 空欄+紅燈）

無單據建帳 ──────────────────────────────> submitted（直接）
```

`audited` / `reconciled` 由 Plan 5 / 6 接續，本 plan 不觸及。

---

## 4. 資料模型：新增 `expenses` 表（+ alembic migration）

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | int PK | |
| store_id | FK stores | 由裝置綁定 / 使用者帶入 |
| created_by | FK users | 上傳者 |
| created_at | datetime (UTC) | 上傳時間 |
| business_date | date, nullable | 送出時依台灣時間 08:00 分界算出（§5）；draft 階段 null |
| summary | text, nullable | 品名摘要（OCR 或人工） |
| category_id | FK categories, nullable | 分類建議 / 人工選（指向 level=2 項目，亦允許 level=1） |
| amount | Numeric(12,2), nullable | 金額 |
| currency | str, default 'TWD' | Phase 1 雜支預設台幣，保留欄位 |
| status | str | `pending_ocr` / `draft` / `submitted`（enum 驗證於應用層） |
| image_key | str, nullable | R2 main（壓縮原圖）物件 key；無單據建帳 = null |
| thumb_key | str, nullable | R2 縮圖物件 key |
| ocr_confidence | float, nullable | Gemini 自評信心 0–1 |
| ocr_is_handwritten | bool, nullable | 手寫訊號 |
| amount_parse_ok | bool, nullable | 金額能否 parse 成合理數字 |
| is_modified_by_user | bool, default false | 員工是否改過金額/分類 |
| ocr_raw | JSON, nullable | Gemini 原始回應存查（文字非影像，符合鐵律） |
| no_receipt_reason | text, nullable | 無單據建帳原因 |
| doc_type_id | FK doc_types, nullable | 保留欄位，本 plan 無 UI |
| submitted_at | datetime (UTC), nullable | 送出時間 |

索引：`(store_id, status)`、`(created_by, status)`、`(store_id, business_date)`。

### 4.1 紅綠燈計算（讀取時，helper 純函式）
依 §7 設計文件：
- 🟢 綠：`not ocr_is_handwritten` and `ocr_confidence >= GREEN_THRESHOLD`(預設 0.85) and `amount_parse_ok` and `not is_modified_by_user`
- 🔴 紅：`ocr_is_handwritten` or `is_modified_by_user` or `not amount_parse_ok`
- 🟡 黃：其餘（印刷但信心中等、未改）

燈號 helper 回 `'green'|'yellow'|'red'`，暫存區與未來核銷共用。

---

## 5. 營業日（§5，本 plan 落地送出時計算）

`business_date(created_at)`：把 `created_at`(UTC) 轉台灣時間，若落在 **00:00–08:00** → 前一日曆日；否則當日曆日。用既有 `TW_TZ` pattern。單元測試涵蓋 07:59 / 08:00 / 08:01 邊界與跨日。

---

## 6. OCR 設計（Gemini，包在 `OCRProvider` 後）

### 6.1 介面
```
class OCRProvider:
    def recognize(self, image_bytes: bytes, content_type: str) -> OCRResult
```
`OCRResult = {summary, category_id, amount, confidence, is_handwritten, raw}`。
- `GeminiProvider`：stdlib `urllib` 打 Gemini REST（**不加 Python 依賴**，與 `app/fx/service.py` 一致、保持 build 精簡），強制 `responseSchema` 結構化 JSON 輸出。模型由 `GEMINI_MODEL` 控（預設 `gemini-2.5-flash`）。
- `MockProvider`：測試用，回可控結果、不呼叫外部。

由 `OCR_PROVIDER`(gemini|mock) 選實作。

### 6.2 抽取欄位（僅三項，§7）
`summary`（品名摘要）、`category`（從分類清單建議）、`amount`（總額）。**不抽日期 / 廠商 / 統編**（created_at 用上傳時間，順帶避開民國年解析坑）。

### 6.3 Prompt 要點（依 5 張真實樣本淬煉）
> 真實樣本已存 `tests/fixtures/receipts/`（進 .gitignore、不 commit），涵蓋：全家印刷熱感收據、手寫估價單（TV/保養費/音響器材）、印刷銷貨單（調味料 8 品項）。

- **金額規則（最重要）**：抓「**最終應付/合計/實付金額/銷貨金額/總計**」那個數；**明確排除**「現金、找零、付款、找回、應稅/未稅/稅額拆項」——例：全家單有「現金 2000 / 找零 710 / 小計 1290 / 實付 1290」，正解 1290，**不可抓最大值 2000**。
- **摘要濃縮**：多品項摘要成一句（例：8 項調味料 → 「調味料雜貨等 8 項」），非逐條羅列。
- **只辨識主要單據**：畫面常有多張單疊放，聚焦最主要/最完整那張。
- **金額正規化**：去千分位逗號（5,230→5230）、可解讀中式金額欄與大寫國字（肆萬伍仟→45000）交叉驗證。
- **分類建議**：prompt 內注入 2 層分類清單（`{id, 大類, 項目}`，來自 seed），要求 Gemini 回最匹配的 `category_id`；無合適則回 null，員工在暫存區補選。
- **信心與訊號**：回 `confidence`(0–1) 與 `is_handwritten`（印刷/手寫）供紅綠燈。
- **紅圈方式移除**（user 決定 2026-07-07）：不做像素級紅色偵測、SOP 不要求紅筆圈；靠語意抓合計。若日後準度不足再議增強手段。

### 6.4 容錯（§10）
Gemini 逾時/失敗 → 該筆進 `draft` 空欄 + 紅燈，員工手填，不卡流程。金額 parse 失敗 → `amount_parse_ok=false`（紅燈）。

---

## 7. 影像處理（`app/images/image_utils.py`，純函式）

介面：`process_upload_image(raw_bytes, content_type) -> (main_bytes, thumb_bytes)`（expense-report 自有等效檔，**不與 webapp 共用**，鐵律隔離）。

- **main（壓縮原圖）**：長邊 > **3200** 才縮到 3200、`MAIN_QUALITY=85`（保留單據細節供辨識/稽核）。
- **thumb（縮圖）**：長邊 **640**、`THUMB_QUALITY=78`、**一律 JPEG**。
- Pillow：`ImageOps.exif_transpose` 修正方向 → `thumbnail((edge,edge), LANCZOS)`；**不放大**。
- 只處理 jpeg/png/webp；壞 bytes/任何錯誤 → 回 `(raw_bytes, None)` 記 log、不中斷上傳。
- CPU-heavy → 呼叫端用 ThreadPoolExecutor + timeout（比照 `app/face/engine.py`），不卡 worker。
- thumb key = main key 去副檔名 + `_thumb.jpg`。

---

## 8. 儲存（Cloudflare R2，`app/storage/r2.py`）

- 用 **boto3**（S3 相容）。⚠️ **build 影響已報備**：boto3+botocore 使 image 變大、pip 解析略慢，鎖版進 requirements。這是本 plan 唯一新增重量級依賴（Gemini 走 stdlib）。
- `put_object`：私有 bucket + SSE（伺服器端加密）+ TLS。
- `presigned_url(key, expires)`：短效簽章 URL 供暫存區看圖（thumb 列表 / main 點開）。
- 物件 key 規則：`expenses/<store_id>/<yyyymm>/<uuid>.<ext>`，thumb 對應 `_thumb.jpg`。
- 可切 `STORAGE_BACKEND`(r2|mock)：mock backend（本地暫存 dict / 假 URL）供測試與無憑證本機開發。

---

## 9. 後端路由（`app/expenses/` blueprint）

所有路由需登入（既有 `current_user` + gate），store scoped（只能操作本店/本人）。

| 方法 路由 | 動作 | 狀態轉移 |
|---|---|---|
| `POST /api/v1/expenses` | 拍單上傳：壓縮→R2→建 row→背景 OCR→回 202 `{id}` | →`pending_ocr` |
| `POST /api/v1/expenses/no-receipt` | 無單據建帳 | →`submitted` |
| `GET /api/v1/expenses/pending` | 暫存區列表（本人 draft+pending_ocr，收斂 orphan，thumb 簽章 URL） | pending_ocr 逾時→draft |
| `GET /api/v1/expenses/<id>` | 明細（main 簽章 URL） | — |
| `PATCH /api/v1/expenses/<id>` | 改 summary/category/amount（限 draft，本人） | 設 is_modified |
| `POST /api/v1/expenses/<id>/submit` | 送出（限 draft，本人），算 business_date | draft→submitted |
| `DELETE /api/v1/expenses/<id>` | 丟棄 draft（連 R2 物件刪） | — |

授權：物件級檢查（`created_by == current_user` 且同店）先於欄位驗證。

---

## 10. 前端（延續 Plan 3a SPA view state）

登入後 `main.js` 導覽新增兩個 view：
- **拍單 view**：沿用 `camera.js`（單張 base64 記憶體、不落地）；快門→[完成]/[下一張]；[完成] 逐張上傳＋進度條；完成提示可離開。
- **暫存區 view**：表格渲染 `GET /pending`；縮圖 lazy、點開 main；欄內編輯→PATCH；紅綠燈 badge；[送出]/[全部送出]/[丟棄]；[＋無單據建帳] 表單。

前端切檔（ESM，延續 `app/static/js/`）：`capture.js`（拍單流程/連拍/上傳批次）、`pending.js`（暫存區表格/編輯/送出）、`expenses_api.js`（fetch 包裝）。純邏輯（金額格式化、燈號、business_date 顯示）用 `node --test tests/js/*.mjs` TDD；DOM 膠合手動瀏覽器 e2e。

PWA sw.js：`/api/v1/expenses*` 全部 network-first、**絕不快取**（延續既有 auth/face/api 規則）。

---

## 11. 環境變數（新增）

| 變數 | 說明 |
|---|---|
| `GEMINI_API_KEY` | Gemini 金鑰（.env，不 commit） |
| `GEMINI_MODEL` | 預設 `gemini-2.5-flash` |
| `OCR_PROVIDER` | `gemini`(prod) / `mock`(測試) |
| `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET` / `R2_ENDPOINT` | R2 憑證（.env，不 commit） |
| `STORAGE_BACKEND` | `r2`(prod) / `mock`(測試) |
| `OCR_STALE_SECONDS` | pending_ocr orphan 收斂門檻，預設 120 |
| `GREEN_THRESHOLD` | 綠燈信心門檻，預設 0.85 |

> **憑證安全**：`.env` 已在 `.gitignore`。本機端到端測試用 user 真實憑證；**Plan 4 全部測完後主動提醒 user 刪除 `.env` 憑證**（user 明確要求）。

---

## 12. 測試策略（TDD，§11）

**單元**
- OCR JSON parser（mock Gemini 回傳 → OCRResult；缺欄/壞 JSON 容錯）
- 金額 parse：千分位逗號、中式金額欄、大寫國字、「現金/找零」排除邏輯
- `business_date` 08:00 分界（07:59/08:00/08:01/跨日）
- 狀態機轉移合法性（pending_ocr→draft→submitted；非法轉移拒絕）
- store scoped 權限隔離（跨店/跨人 403）
- `process_upload_image` 尺寸/方向/不放大/壞圖回退
- R2 key 推導、紅綠燈 helper

**整合**
- 拍單 e2e（mock Gemini + mock R2）：POST→pending_ocr→背景更新 draft→PATCH→submit→submitted
- 無單據建帳 → submitted
- stale pending_ocr 於 GET /pending 收斂成紅燈 draft
- PATCH 設 is_modified、燈號轉紅
- DELETE draft 連帶刪 R2 物件

**真圖手動驗證**（非 CI，需真憑證）
- 腳本跑 `tests/fixtures/receipts/` 5 張真單過真 Gemini，人工核對辨識準度，重點驗全家單「1290 而非 2000」陷阱、手寫單金額、8 品項摘要濃縮。

**前端 JS**（`node --test`）：金額格式化、燈號對應、business_date 台灣時間顯示。

---

## 13. 依賴與部署影響

- 新增 `boto3`（鎖版）。Gemini 走 stdlib urllib、Pillow 已有 → 無其他新增。
- boto3 使 Docker image 變大、pip 解析略慢，**動 requirements/Dockerfile 前先驗語法**（YAML/Dockerfile 工具驗證）。
- Zeabur prod 需設 `GEMINI_API_KEY` / `GEMINI_MODEL` / R2 五項 / `OCR_PROVIDER=gemini` / `STORAGE_BACKEND=r2`，並延續 `APP_ENV=production` + `SECRET_KEY` + `SESSION_COOKIE_SECURE=true`。

---

## 14. 決策紀錄（2026-07-07）

1. Plan 4 邊界 = 拍單→OCR→暫存區→送出(存R2) + 無單據建帳；稽核/核銷另開。
2. Flow B：拍完即走、伺服器背景 OCR、晚點回暫存區看（彈性大）。
3. 圖存在「上傳當下」非「送出」——批次確認要看得到圖核對；廢棄 draft 圖等 Phase 3 retention 清。
4. orphan 收斂靠 GET /pending 就地處理，不用 cron，維持不輪詢。
5. 前端逐張同步上傳給真實進度＋不輪詢；伺服器背景 thread（app_context+新 session）跑 Gemini。
6. Gemini 走 stdlib urllib（零依賴）；R2 走 boto3（唯一新增重量級依賴，已報備 build 影響）。
7. 移除紅圈辨識，改語意抓合計（明確排除現金/找零）；準度不足再議。
8. OCR 只抽 summary/category/amount 三項，不抽日期（避民國年坑）。
9. 燈號給員工看；暫存區確認用表格。
10. audit_log 全表、doc_type picker、retention 延後（Plan 5 / Phase 3）。
