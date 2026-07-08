# OCR 韌性 + 失敗軌跡 設計（OCR resilience）

> Phase 1 追加。獨立於稽核（Plan 5）。狀態：設計定案，待寫 plan、暫不實作（稽核先驗收 merge）。

## 1. 背景與問題

門市多支手機同時拍雜支單時，伺服器對 Gemini（`gemini-3.1-flash-lite`）併發呼叫做 OCR。現況（`app/ocr/gemini.py`、`app/expenses/tasks.py`）：

- **照片不會遺失**：拍照 → 壓縮 → **先同步存 R2（`image_key`）** → 建 `expense(pending_ocr)` → 才排 OCR。Gemini 失敗不影響已落地原圖。
- **附帶排隊**：OCR 丟進 module-level `ThreadPoolExecutor(max_workers=4)`，最多 4 個併發、其餘在程序內排隊。
- **兩個真缺口**：
  1. **無重試**：`_call_api` 只打一次，429（rate limit）/503（overloaded）/5xx/timeout 全被 `except Exception` 吞掉當普通失敗 → OCR 靜默放棄。Gemini API 本身**不排隊**，超量同步回 429/503。
  2. **失敗無感知**：失敗的單 `status` 直接變 `draft`、summary/金額/分類全空，混在正常暫存區裡，員工不知道是「OCR 失敗要手動補」還是「OCR 有跑只是沒抓到」。

**目標**：(a) 對可重試錯誤自動重試+退避；(b) 每次嘗試/失敗寫持久化 `ocr_log` 供事後 SQL 反查；(c) 徹底失敗的單以旗標標記，暫存區 UI 明確提示員工手動確認。

## 2. 範圍

**做**：Gemini 呼叫重試+退避、錯誤分類、`ocr_log` 表、`expense` 失敗旗標欄位、背景有限次重排（沿用 list-pull 收斂、不用 cron）、暫存區 UI 失敗提示 +（低成本）手動「重新辨識」鈕。

**不做**：改 concurrency 上限機制（維持 `ThreadPoolExecutor(max_workers=4)`，僅將重試納入）；失敗率 dashboard（`ocr_log` 為其鋪路，本次不建 UI）；換 OCR provider。

## 3. 鐵律 / 約束

- 不新增 Python 依賴（重試/退避用 stdlib；退避 `sleep` 需可注入，測試不真的等）。
- 時間存 UTC；`ocr_log.ts` 用 `datetime.now(timezone.utc)`。
- 前端不輪詢：背景重排沿用既有 `reconcile_stale`（暫存區列表被拉時就地收斂），不加 cron。手動「重新辨識」是使用者點擊，非輪詢。
- 影像不落地：背景重排需從 R2 重抓原圖（`image_key`）進記憶體 OCR 後即丟；R2 為 Plan 4 設計的加密原圖存放處，符合「伺服器不留影像」。
- `OCRProvider` 抽象不得知道 `ocr_log`/DB schema：DB 寫入只在 task 層。

## 4. 錯誤分類（新 `app/ocr/errors.py`）

一次 Gemini 嘗試的結果分三類：

| outcome | 觸發 | error_type 值 | 處置 |
|---|---|---|---|
| `success` | 200 + 可解析 dict | — | 用結果 |
| `retryable` | HTTP 429 / 500 / 502 / 503 / 504、timeout、`URLError`（連線層） | `rate_limit`(429) / `overloaded`(503) / `server`(5xx) / `timeout` | 退避後重試 |
| `fatal` | HTTP 400、JSON parse 失敗、responseSchema 不符、非 dict 回應 | `bad_request`(400) / `parse` / `schema` / `other` | 不重試（重打也沒用） |

- `OcrRetryableError(error_type, http_status)` / `OcrFatalError(error_type, http_status)` 兩個例外類別。
- `classify_exception(exc) -> OcrRetryableError | OcrFatalError`：把 `urllib.error.HTTPError`（依 code）、`URLError`、`socket.timeout`、`json.JSONDecodeError`、`ValueError` 對應到上表。

## 5. 重試+退避（`app/ocr/retry.py` + provider 改造）

**Provider 改造**：`GeminiProvider.recognize` 改為**單次嘗試**、成功回 fields dict、失敗**丟**分類後的例外（不再自己吞成 empty）。`_call_api` 的 `HTTPError`/`URLError`/timeout 經 `classify_exception` 拋出；parse/schema/非 dict 拋 `OcrFatalError`。`MockProvider` 不變（永遠 success）。

**共用重試包裝**（所有 provider 共用，未來 Vertex/地端免費得到重試）：

```
recognize_with_retry(provider, image_bytes, content_type, cfg, sleep=time.sleep) -> RetryResult
```

- 迴圈最多 `GEMINI_MAX_RETRIES`（預設 3）次：
  - `success` → 停，帶回 fields。
  - `OcrFatalError` → 停（不重試）。
  - `OcrRetryableError` 且還有次數 → `sleep(backoff)` 後再試；用完 → 停（exhausted）。
- 退避 = 指數 + jitter：`base * 2**(attempt-1) + random(0, jitter)`（`base`≈0.5s、上限 cap；`GEMINI_RETRY_BASE` 可調）。`sleep` 參數可注入 → 測試傳 no-op。
- `RetryResult`：
  ```
  { fields: dict | None,
    final_outcome: "success" | "fatal" | "exhausted",
    attempts: [ {attempt:int, outcome, error_type, http_status, duration_ms:int} ] }
  ```
  每次嘗試（含成功那次）都記一筆 attempt meta，供 task 層寫 `ocr_log`。

## 6. `ocr_log` 表（每次「嘗試」一筆）

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | PK | |
| expense_id | FK expenses, index | 哪張單 |
| store_id | FK stores, index | 哪店（冗餘存，方便依店彙整反查） |
| attempt | int | 該次 OCR 工作內的第幾次嘗試（1..N） |
| outcome | String(16) | `success` / `retryable` / `fatal` |
| error_type | String(16), nullable | §4 的 error_type（success 為 null） |
| http_status | int, nullable | HTTP 狀態碼（有的話） |
| duration_ms | int, nullable | 該次耗時 |
| ts | DateTime(tz) | UTC |

- 走 alembic migration。量估：1000 張 × 平均 ~1.x 次 ≈ 千餘列/天級，可接受。
- 反查範例（事後）：`SELECT store_id, error_type, count(*) FROM ocr_log WHERE outcome!='success' AND ts::date='2026-07-08' GROUP BY 1,2;` → 哪天哪店哪類錯誤幾次。

## 7. `expense` 新欄位 + 狀態機

新欄位（migration）：
- `ocr_attempts` int, NOT NULL default 0 — **OCR 工作「輪數」**（每次 `_run_ocr` 派工 +1；§5 的 in-call 重試不算輪，算同一輪內的 attempt）。
- `ocr_failed` bool, NOT NULL default False — 徹底失敗旗標。
- `ocr_last_error` String, nullable — 最後一次 error_type（給 UI/log 人看）。

**流程**（`_run_ocr`，仍在 app_context）：
1. 開頭 `e.ocr_attempts += 1`。
2. 呼叫 `recognize_with_retry(...)`，把每個 attempt 寫 `ocr_log`（expense_id/store_id/attempt/outcome/error_type/http_status/duration_ms）。
3. 依 `final_outcome`：
   - `success` → 填欄位、`status="draft"`、`ocr_failed=False`（同現況邏輯）。
   - `fatal` → `status="draft"`、`ocr_failed=True`、`ocr_last_error=<最後 error_type>`（重打無益，直接標失敗）。
   - `exhausted`（本輪可重試錯誤用完）：
     - 若 `ocr_attempts < OCR_MAX_ROUNDS`（預設 3）→ **維持 `pending_ocr`**（留給背景重排），`ocr_last_error` 記起來。
     - 否則（達輪數上限）→ `status="draft"`、`ocr_failed=True`、`ocr_last_error=<最後 error_type>`。

**背景重排（改 `reconcile_stale`，list-pull 驅動、不用 cron）**：
- 暫存區 `/expenses/pending` 被拉時，對逾時（`OCR_STALE_SECONDS`）仍 `pending_ocr` 的單：
  - 若 `ocr_attempts < OCR_MAX_ROUNDS` → **從 R2 重抓 `image_key` 原圖**（需新增 `storage.get(key)`），`schedule_ocr` 再跑一輪（走完整重試）。
  - 若 `ocr_attempts >= OCR_MAX_ROUNDS` → 收斂成 `status="draft"`、`ocr_failed=True`（不再無限等）。
- 需給 storage 介面加 `get(key) -> bytes`（`R2Storage` 用 boto3 get_object；`MockStorage` 回存放的 bytes）。

失敗的單是 `draft`＋`ocr_failed=True`：**員工照樣可在暫存區編輯金額/分類 → submit**，稽核/狀態機完全不受影響（不新增 status，不動 STATUSES）。

## 8. 暫存區 UI（`app/static/js/pending.js`）

- `serialize_expense` 多回 `ocr_failed`、`ocr_last_error`。
- `draft` 且 `ocr_failed` 的列：顯示明顯標記，例：紅字「⚠ OCR 失敗，請手動確認金額/分類」（與「OCR 有跑但沒抓到內容」＝ `ocr_failed=False` 的空 draft 區分）。
- 該列加一顆 **「重新辨識」** 鈕 → `POST /expenses/<id>/reocr`：後端從 R2 重抓原圖、重置 `ocr_attempts`/`ocr_failed`、`status` 回 `pending_ocr`、`schedule_ocr` 重跑。使用者點擊觸發（非輪詢），給員工當下的補救手段。
- bump `sw.js` CACHE_NAME。

## 9. 設定項（皆有預設，`.env` 可調）

- `GEMINI_MAX_RETRIES=3`（單輪內 in-call 重試次數）
- `GEMINI_RETRY_BASE=0.5`（退避基秒）
- `OCR_MAX_ROUNDS=3`（背景重排輪數上限）
- `OCR_STALE_SECONDS`（沿用既有）

## 10. 測試策略

- **重試/退避**：`recognize_with_retry` 純邏輯，注入假 provider（依序丟 429、429、成功 → 驗證重試 2 次後成功、attempts meta 3 筆）+ 注入 no-op sleep（測試不等）。fatal 不重試（丟 400 → attempts 1 筆、final_outcome=fatal）。
- **錯誤分類**：`classify_exception` 對 HTTPError(429/400/503)/URLError/timeout/JSONDecodeError 各一個斷言。
- **`ocr_log` 寫入**：`_run_ocr`（`EXPENSE_OCR_SYNC=true`）跑一次，驗證 ocr_log 列數/outcome/error_type、expense 狀態（success→draft、fatal→draft+ocr_failed、exhausted 未達上限→pending_ocr）。
- **背景重排**：`reconcile_stale` 對 `ocr_attempts<上限` 的 stale 單重排、達上限收斂成 draft+ocr_failed。
- **storage.get**：MockStorage put→get round-trip。
- **UI**：`pending.js` 純邏輯（若有）＋手動 e2e。

## 11. 檔案異動概覽

- 新：`app/ocr/errors.py`（例外+classify）、`app/ocr/retry.py`（recognize_with_retry）、`app/models/ocr_log.py`（OcrLog）、migration。
- 改：`app/ocr/gemini.py`（單次嘗試、拋分類例外）、`app/expenses/tasks.py`（`_run_ocr` 記 log+狀態機、`reconcile_stale` 重排）、`app/expenses/routes.py`（`POST /expenses/<id>/reocr`）、`app/expenses/serialize.py`（回 ocr_failed/ocr_last_error）、`app/models/expense.py`（3 新欄位）、`app/models/__init__.py`（export OcrLog）、`app/storage/r2.py`（`get`）、`app/static/js/pending.js`（UI 提示+重新辨識鈕）、`app/static/sw.js`（bump）、`.env.example`。

## 12. 決策紀錄

- **失敗建模＝`draft` + `ocr_failed` 旗標**（非新增 status）：改動面小、不動 STATUSES/稽核狀態機，員工照樣可編輯 submit。（user 定案）
- **log＝新 DB 表 `ocr_log`**（非 expense 欄位、非 log 檔）：可 SQL 反查、可跨單彙整、日後接 dashboard。（user 定案）
- **背景自動重排**：沿用 list-pull 收斂、不用 cron；有限輪數（`OCR_MAX_ROUNDS`）避免無限重試。（user 要求「背景自動重排」）
- **含 UI 失敗提示 + 手動重新辨識鈕**。（user 定案）
- 重試放**共用包裝**而非各 provider 內：所有 provider 免費得到重試，provider 只需拋分類例外。
