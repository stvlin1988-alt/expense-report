# expense-report（會計端-雜支自動化報表系統）

## 專案目標
實體門市雜支報帳無紙化 + 自動化辨識對帳：門市 PWA 拍單據 → Gemini 解析（品名摘要/分類/金額）→ 員工暫存區確認 → 原圖加密存 R2 → 店管理者交接班打勾稽核 → 會計紅綠燈核銷 → 月結報表。
與既有 webapp **完全隔離**（獨立 repo / DB / R2 bucket / URL / 記憶命名空間）。

設計文件：`docs/superpowers/specs/2026-07-01-expense-report-design.md`（Phase 1）。

## 技術棧
- 後端：Python / Flask，部署 Zeabur（2 CPU / 8GB，無 GPU）
- AI 辨識：Gemini API（無狀態），包在 `OCRProvider` 介面後，未來可換 Vertex / 地端模型
- 儲存：Cloudflare R2（私有 bucket + SSE）
- DB：PostgreSQL（prod）/ SQLite（本機 dev），schema 走 alembic
- 前端：PWA（公用手機/員工手機）

## 啟動 / 開發
- 本機啟動：`cp .env.example .env` 填 Gemini/R2 真值 → `FLASK_APP=wsgi.py python3 -m flask db upgrade` → `FLASK_APP=wsgi.py SECRET_KEY=dev python3 -m flask run --port 5001`
- 測試：後端 `python3 -m pytest -q`；前端純邏輯 `node --test tests/js/*.mjs`
- OCR/R2 本機真測：`.env` 設 `OCR_PROVIDER=gemini` / `STORAGE_BACKEND=r2`；不設則走 mock。真圖辨識驗證 `python3 tests/manual/verify_ocr.py`
- ⚠️ 測試完成後刪除 `.env` 內 Gemini/R2 真憑證

## 鐵律（Phase 1）
- 影像不落地：手機拍照記憶體直傳、不進相簿；伺服器 OCR 後不留影像
- 裝置認證用綁定碼+token，**fingerprint 永不作認證判斷**
- 前端不輪詢；狀態全進 DB（workers>1 不用 module-level dict）
- 時間 UI 一律台灣時間（DB 存 UTC）
- 營業日 08:00 分界
