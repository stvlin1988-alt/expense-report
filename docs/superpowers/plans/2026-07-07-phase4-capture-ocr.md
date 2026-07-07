# Plan 4 — 拍單 + OCR + 暫存區 + 送出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓門市員工在 PWA 連拍雜支單據 → 伺服器背景 Gemini 辨識出摘要/分類/金額 → 員工在暫存區表格批次確認修改 → 送出，原圖壓縮加密存 R2、狀態轉 `submitted`。

**Architecture:** 前端逐張同步上傳（給真實進度、不輪詢），後端每張請求壓縮存 R2、建 `pending_ocr` 列、丟背景 daemon thread 跑 Gemini 後更新為 `draft`，回 202。暫存區 `GET /pending` 拉一次即渲染，並就地收斂逾時 orphan。OCR 與儲存各包在 provider/backend 介面後（Gemini/Mock、R2/Mock），測試走 mock、本機/prod 走真實。

**Tech Stack:** Flask 3.1 + SQLAlchemy 2.0 + Flask-Migrate、Pillow（影像壓縮）、stdlib urllib（Gemini REST，不加依賴）、boto3（R2 S3 相容，唯一新增依賴）、前端 ESM + `node --test`。

## Global Constraints

- **影像不落地**：記憶體 → 壓縮 → R2 直上，全程不寫暫存檔/日誌；OCR 用完的記憶體影像即拋。
- **前端不輪詢**：進度來自逐張請求自身返回；暫存區「開列表拉一次」，orphan 靠 list-pull 就地收斂，不用 cron/setTimeout 賭時間。
- **時間**：DB 存 UTC；UI 顯示台灣時間（UTC+8）。營業日 08:00 分界（00:00–08:00 記前一日）。
- **狀態全進 DB**：workers>1 不用 module-level dict 存跨 request 狀態。
- **路由前綴用 `/expenses`（非 `/api/v1/`）**：`app/auth/gates.py` 的 `_EXEMPT_PREFIXES` 已豁免 `/api/v1/`（計算機幌子用），expense 端點必須走裝置閘＋idle 閘，故用 `/expenses`，且每路由自檢 `current_user()`。
- **依賴鎖版**：`boto3` 在 requirements.txt 鎖版；不新增其他 Python 依賴（Gemini 走 stdlib urllib）。
- **與 webapp 完全隔離**：`image_utils` 等寫 expense-report 自有等效檔，不共用 webapp 檔。
- **憑證**：`.env` 已在 `.gitignore`；真憑證僅本機測試用，測完提醒 user 刪除。
- **PIN/密碼規則不變**：本 plan 不動認證。

**影像尺寸基準（照抄，勿改）**：main 長邊 3200 / quality 85；thumb 長邊 640 / quality 78 / 一律 JPEG；不放大；`ImageOps.exif_transpose` 修正方向。

**紅綠燈（§7）**：🟢=印刷 and 信心≥`GREEN_THRESHOLD`(0.85) and 金額可 parse and 未經員工改；🔴=手寫 or 員工改過 or 金額 parse 失敗；🟡=其餘。

**狀態機（本 plan 區段）**：`pending_ocr` →(Gemini/逾時)→ `draft` →(送出)→ `submitted`；無單據建帳直接 `submitted`。

---

## File Structure

新增：
- `app/models/expense.py` — Expense model（+ 註冊 `app/models/__init__.py`）
- `migrations/versions/<rev>_expenses.py` — alembic migration
- `app/expenses/__init__.py` — blueprint `expense_bp`
- `app/expenses/logic.py` — 純函式：`TW_TZ`、`compute_business_date`、`traffic_light`
- `app/expenses/routes.py` — 7 路由
- `app/expenses/tasks.py` — 背景 OCR 排程 `schedule_ocr` / `_run_ocr` / `reconcile_stale`
- `app/expenses/serialize.py` — `serialize_expense`（含燈號 + 簽章 URL）
- `app/images/__init__.py`、`app/images/image_utils.py` — `process_upload_image` 純函式 + async 包裝
- `app/storage/__init__.py`、`app/storage/r2.py` — `get_storage()` / `R2Storage` / `MockStorage`
- `app/ocr/__init__.py`、`app/ocr/provider.py` — `OCRProvider` / `get_provider()` / `MockProvider` / `coerce_amount`
- `app/ocr/prompt.py` — `build_prompt` / `build_response_schema`
- `app/ocr/gemini.py` — `GeminiProvider`
- `app/static/js/expenses_util.js` — 純邏輯（金額格式化/燈號/營業日顯示），node 可 import
- `app/static/js/expenses_api.js` — fetch 包裝
- `app/static/js/capture.js` — 拍單流程
- `app/static/js/pending.js` — 暫存區表格
- `tests/test_expense_*.py`、`tests/js/expenses.mjs`、`tests/manual/verify_ocr.py`、`tests/fixtures/receipts/`（gitignore）

修改：
- `app/config.py` — 新增 config vars
- `app/__init__.py` — 註冊 `expense_bp`
- `app/static/js/auth.js` — `showAppView` 加「拍單／暫存區」導覽（員工）
- `app/static/sw.js` — `/expenses/` 進 network-first 絕不快取；STATIC_URLS 加新 JS；bump `CACHE_NAME`
- `requirements.txt` — 加 `boto3`
- `.gitignore` — 加 `tests/fixtures/receipts/`
- `.env.example`（新增）

---

## Task 1: Expense model + migration

**Files:**
- Create: `app/models/expense.py`
- Modify: `app/models/__init__.py`
- Create: `migrations/versions/<rev>_expenses.py`（autogenerate）
- Test: `tests/test_expense_model.py`

**Interfaces:**
- Produces: `Expense`（`__tablename__="expenses"`），欄位見下；`Expense.STATUSES = ("pending_ocr","draft","submitted")`；`Expense.AUDIT_STATUSES`（保留給後續，不定義）。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_expense_model.py
from datetime import datetime, timezone
from app.extensions import db
from app.models import Expense, Store, User


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A"); db.session.add(s); db.session.commit()
        u = User(name="員工A", role="employee", store_id=s.id); u.set_password("0000")
        db.session.add(u); db.session.commit()
        return s.id, u.id


def test_expense_defaults(app):
    sid, uid = _seed(app)
    with app.app_context():
        e = Expense(store_id=sid, created_by=uid, status="pending_ocr",
                    created_at=datetime.now(timezone.utc))
        db.session.add(e); db.session.commit()
        got = db.session.get(Expense, e.id)
        assert got.status == "pending_ocr"
        assert got.currency == "TWD"
        assert got.is_modified_by_user is False
        assert got.amount is None and got.summary is None
        assert got.business_date is None


def test_expense_status_constants():
    assert Expense.STATUSES == ("pending_ocr", "draft", "submitted")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_expense_model.py -v`
Expected: FAIL（`ImportError: cannot import name 'Expense'`）

- [ ] **Step 3: Write the model**

```python
# app/models/expense.py
from app.extensions import db


class Expense(db.Model):
    __tablename__ = "expenses"

    STATUSES = ("pending_ocr", "draft", "submitted")

    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey("stores.id"), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False)
    submitted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    business_date = db.Column(db.Date, nullable=True)

    summary = db.Column(db.Text, nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    amount = db.Column(db.Numeric(12, 2), nullable=True)
    currency = db.Column(db.String(8), nullable=False, default="TWD")

    status = db.Column(db.String(16), nullable=False, default="pending_ocr", index=True)

    image_key = db.Column(db.String(255), nullable=True)
    thumb_key = db.Column(db.String(255), nullable=True)

    ocr_confidence = db.Column(db.Float, nullable=True)
    ocr_is_handwritten = db.Column(db.Boolean, nullable=True)
    amount_parse_ok = db.Column(db.Boolean, nullable=True)
    is_modified_by_user = db.Column(db.Boolean, nullable=False, default=False)
    ocr_raw = db.Column(db.JSON, nullable=True)

    no_receipt_reason = db.Column(db.Text, nullable=True)
    doc_type_id = db.Column(db.Integer, db.ForeignKey("doc_types.id"), nullable=True)

    __table_args__ = (
        db.Index("ix_expenses_store_status", "store_id", "status"),
        db.Index("ix_expenses_created_by_status", "created_by", "status"),
        db.Index("ix_expenses_store_bizdate", "store_id", "business_date"),
    )
```

在 `app/models/__init__.py` 加：

```python
from app.models.expense import Expense
```
並把 `"Expense"` 加進 `__all__`。

- [ ] **Step 4: Run model test (no migration yet, uses create_all)**

Run: `python3 -m pytest tests/test_expense_model.py -v`
Expected: PASS

- [ ] **Step 5: Autogenerate migration**

Run: `FLASK_APP=wsgi.py python3 -m flask db migrate -m "expenses"`
開啟新生成的 `migrations/versions/<rev>_expenses.py`，確認：
- `down_revision = 'b7f3c1a9d2e4'`（目前 head）
- `op.create_table('expenses', ...)` 含上述所有欄位與三個 index
- 無誤刪其他表的操作（autogen 偶爾多產東西 → 刪掉非 expenses 的變更）

- [ ] **Step 6: Apply migration to a fresh DB and verify upgrade works**

Run:
```bash
rm -f instance/dev.db
FLASK_APP=wsgi.py python3 -m flask db upgrade
FLASK_APP=wsgi.py python3 -c "from app import create_app; from app.extensions import db; import sqlalchemy as sa; a=create_app(); ctx=a.app_context(); ctx.push(); print('expenses' in sa.inspect(db.engine).get_table_names())"
```
Expected: 最後印出 `True`

- [ ] **Step 7: Commit**

```bash
git add app/models/expense.py app/models/__init__.py migrations/versions/ tests/test_expense_model.py
git commit -m "feat(expense): Expense model + migration"
```

---

## Task 2: 純邏輯 — 營業日 + 紅綠燈

**Files:**
- Create: `app/expenses/__init__.py`（暫時空 blueprint 佔位）
- Create: `app/expenses/logic.py`
- Test: `tests/test_expense_logic.py`

**Interfaces:**
- Produces:
  - `TW_TZ = timezone(timedelta(hours=8))`
  - `compute_business_date(created_at_utc: datetime) -> date`
  - `traffic_light(is_handwritten, confidence, amount_parse_ok, is_modified, green_threshold=0.85) -> str`（`"green"|"yellow"|"red"`）

- [ ] **Step 1: Write the failing test**

```python
# tests/test_expense_logic.py
from datetime import datetime, timezone, date
from app.expenses.logic import compute_business_date, traffic_light, TW_TZ


def _utc(y, m, d, hh, mm):
    # 給台灣時間，轉回 UTC 存
    from datetime import timedelta
    return datetime(y, m, d, hh, mm, tzinfo=TW_TZ).astimezone(timezone.utc)


def test_business_date_before_8am_counts_prev_day():
    # 台灣 2026-07-07 07:59 → 前一日 07-06
    assert compute_business_date(_utc(2026, 7, 7, 7, 59)) == date(2026, 7, 6)


def test_business_date_at_8am_counts_same_day():
    assert compute_business_date(_utc(2026, 7, 7, 8, 0)) == date(2026, 7, 7)


def test_business_date_after_8am_counts_same_day():
    assert compute_business_date(_utc(2026, 7, 7, 8, 1)) == date(2026, 7, 7)


def test_business_date_naive_treated_as_utc():
    # 無 tzinfo 的 UTC（SQLite 取回）→ 當 UTC。台灣 00:30 = 前一日 UTC 16:30
    naive = datetime(2026, 7, 6, 16, 30)  # UTC，台灣為 07-07 00:30
    assert compute_business_date(naive) == date(2026, 7, 6)


def test_traffic_light_green():
    assert traffic_light(False, 0.9, True, False) == "green"


def test_traffic_light_red_handwritten():
    assert traffic_light(True, 0.99, True, False) == "red"


def test_traffic_light_red_modified():
    assert traffic_light(False, 0.99, True, True) == "red"


def test_traffic_light_red_parse_fail():
    assert traffic_light(False, 0.99, False, False) == "red"


def test_traffic_light_yellow_low_conf():
    assert traffic_light(False, 0.5, True, False) == "yellow"


def test_traffic_light_none_signals_yellow_or_red():
    # 尚未辨識（全 None）當保守：紅（parse 未知）
    assert traffic_light(None, None, None, False) == "red"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_expense_logic.py -v`
Expected: FAIL（`ModuleNotFoundError: app.expenses.logic`）

- [ ] **Step 3: Implement**

```python
# app/expenses/__init__.py
# blueprint 於 Task 7 補；此檔先留空供 logic 子模組匯入路徑成立。
```

```python
# app/expenses/logic.py
from datetime import datetime, timezone, timedelta, date

TW_TZ = timezone(timedelta(hours=8))
BUSINESS_DAY_START_HOUR = 8


def _aware_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def compute_business_date(created_at_utc: datetime) -> date:
    """UTC → 台灣時間；台灣時間落在 00:00–08:00 記前一日曆日，否則當日。"""
    local = _aware_utc(created_at_utc).astimezone(TW_TZ)
    if local.hour < BUSINESS_DAY_START_HOUR:
        return (local - timedelta(days=1)).date()
    return local.date()


def traffic_light(is_handwritten, confidence, amount_parse_ok,
                  is_modified, green_threshold: float = 0.85) -> str:
    if is_handwritten or is_modified or amount_parse_ok is not True:
        return "red"
    if confidence is not None and confidence >= green_threshold:
        return "green"
    return "yellow"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_expense_logic.py -v`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
git add app/expenses/__init__.py app/expenses/logic.py tests/test_expense_logic.py
git commit -m "feat(expense): business_date 08:00 分界 + 紅綠燈純邏輯"
```

---

## Task 3: 影像壓縮純函式

**Files:**
- Create: `app/images/__init__.py`（空）
- Create: `app/images/image_utils.py`
- Test: `tests/test_image_utils.py`

**Interfaces:**
- Produces:
  - `process_upload_image(raw_bytes: bytes, content_type: str) -> tuple[bytes, bytes | None]`（回 `(main_bytes, thumb_bytes)`；壞圖回 `(raw_bytes, None)`）
  - `process_upload_image_async(raw_bytes, content_type, timeout=10.0) -> tuple[bytes, bytes | None]`
  - 常數 `MAIN_EDGE=3200, MAIN_QUALITY=85, THUMB_EDGE=640, THUMB_QUALITY=78`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_image_utils.py
import io
from PIL import Image
from app.images.image_utils import (
    process_upload_image, process_upload_image_async,
    MAIN_EDGE, THUMB_EDGE,
)


def _jpeg(w, h):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 130, 140)).save(buf, format="JPEG")
    return buf.getvalue()


def _dims(b):
    return Image.open(io.BytesIO(b)).size


def test_large_image_downscaled_to_main_edge():
    raw = _jpeg(5000, 2500)
    main, thumb = process_upload_image(raw, "image/jpeg")
    assert max(_dims(main)) == MAIN_EDGE           # 長邊縮到 3200
    assert max(_dims(thumb)) == THUMB_EDGE          # 縮圖長邊 640


def test_small_image_not_upscaled():
    raw = _jpeg(400, 300)
    main, thumb = process_upload_image(raw, "image/jpeg")
    assert _dims(main) == (400, 300)                # 不放大
    assert max(_dims(thumb)) == 300                 # thumb 也不放大（原長邊<640）


def test_thumb_is_jpeg():
    raw = _jpeg(1000, 800)
    _, thumb = process_upload_image(raw, "image/jpeg")
    assert Image.open(io.BytesIO(thumb)).format == "JPEG"


def test_corrupt_bytes_returns_raw_and_none():
    main, thumb = process_upload_image(b"not-an-image", "image/jpeg")
    assert main == b"not-an-image"
    assert thumb is None


def test_async_matches_sync_dims():
    raw = _jpeg(5000, 2500)
    main, thumb = process_upload_image_async(raw, "image/jpeg")
    assert max(_dims(main)) == MAIN_EDGE
    assert max(_dims(thumb)) == THUMB_EDGE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_image_utils.py -v`
Expected: FAIL（模組不存在）

- [ ] **Step 3: Implement**

```python
# app/images/image_utils.py
import io
import logging
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

MAIN_EDGE = 3200
MAIN_QUALITY = 85
THUMB_EDGE = 640
THUMB_QUALITY = 78
_SUPPORTED = {"image/jpeg", "image/png", "image/webp"}
_executor = ThreadPoolExecutor(max_workers=2)


def _encode_jpeg(img: Image.Image, quality: int) -> bytes:
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _resized(img: Image.Image, edge: int) -> Image.Image:
    out = img.copy()
    out.thumbnail((edge, edge), Image.LANCZOS)  # thumbnail 只縮不放大
    return out


def process_upload_image(raw_bytes: bytes, content_type: str):
    """回 (main_bytes, thumb_bytes)；不支援型別或壞 bytes → (raw_bytes, None)。"""
    if content_type not in _SUPPORTED:
        return raw_bytes, None
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img = ImageOps.exif_transpose(img)      # 修正方向
        main = _encode_jpeg(_resized(img, MAIN_EDGE), MAIN_QUALITY)
        thumb = _encode_jpeg(_resized(img, THUMB_EDGE), THUMB_QUALITY)
        return main, thumb
    except Exception as e:
        logger.warning("process_upload_image failed: %s", e)
        return raw_bytes, None


def process_upload_image_async(raw_bytes: bytes, content_type: str, timeout: float = 10.0):
    """在 thread executor 跑壓縮（CPU-heavy），逾時/失敗回 (raw_bytes, None)。"""
    try:
        return _executor.submit(process_upload_image, raw_bytes, content_type).result(timeout=timeout)
    except Exception as e:
        logger.warning("process_upload_image_async failed: %s", e)
        return raw_bytes, None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_image_utils.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/images/ tests/test_image_utils.py
git commit -m "feat(images): process_upload_image 壓縮原圖+縮圖(3200/85,640/78)"
```

---

## Task 4: 儲存後端（R2 + Mock）+ boto3 依賴 + config

**Files:**
- Create: `app/storage/__init__.py`（空）
- Create: `app/storage/r2.py`
- Modify: `app/config.py`
- Modify: `requirements.txt`
- Test: `tests/test_storage.py`

**Interfaces:**
- Produces:
  - `get_storage()` — 依 `STORAGE_BACKEND`(r2|mock) 回實例；mock 每個 app 用同一實例（module-level）以便測試斷言
  - backend 介面：`put(key, data: bytes, content_type: str) -> None`、`presigned_url(key, expires=300) -> str`、`delete(key) -> None`
  - `MockStorage.objects`（dict）供測試斷言

- [ ] **Step 1: Add config + dependency**

在 `app/config.py` `Config` 內新增：

```python
    # 儲存（R2 / mock）
    STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "mock")
    R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
    R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
    R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
    R2_BUCKET = os.environ.get("R2_BUCKET", "")
    R2_ENDPOINT = os.environ.get("R2_ENDPOINT", "")
    R2_URL_EXPIRE_SECONDS = int(os.environ.get("R2_URL_EXPIRE_SECONDS", "300"))
```

`TestConfig` 內確認 `STORAGE_BACKEND` 維持 `"mock"`（繼承即可；不覆寫）。

在 `requirements.txt` 末尾加（鎖版）：

```
boto3==1.35.*
```

安裝：`python3 -m pip install "boto3==1.35.*"`

- [ ] **Step 2: Write the failing test**

```python
# tests/test_storage.py
from app.storage.r2 import get_storage, MockStorage


def test_mock_put_get_url_delete(app):
    with app.app_context():
        s = get_storage()
        assert isinstance(s, MockStorage)
        s.put("expenses/1/202607/abc.jpg", b"data", "image/jpeg")
        assert "expenses/1/202607/abc.jpg" in s.objects
        url = s.presigned_url("expenses/1/202607/abc.jpg")
        assert "abc.jpg" in url
        s.delete("expenses/1/202607/abc.jpg")
        assert "expenses/1/202607/abc.jpg" not in s.objects


def test_presigned_url_missing_key_still_returns_str(app):
    with app.app_context():
        s = get_storage()
        assert isinstance(s.presigned_url("nope.jpg"), str)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m pytest tests/test_storage.py -v`
Expected: FAIL（模組不存在）

- [ ] **Step 4: Implement**

```python
# app/storage/r2.py
import logging
from flask import current_app

logger = logging.getLogger(__name__)


class MockStorage:
    """記憶體儲存，供測試/無憑證本機開發。"""
    def __init__(self):
        self.objects = {}

    def put(self, key, data, content_type):
        self.objects[key] = {"data": data, "content_type": content_type}

    def presigned_url(self, key, expires=300):
        return f"/mock-storage/{key}"

    def delete(self, key):
        self.objects.pop(key, None)


class R2Storage:
    def __init__(self, cfg):
        import boto3
        self.bucket = cfg["R2_BUCKET"]
        self.expire = cfg.get("R2_URL_EXPIRE_SECONDS", 300)
        self._client = boto3.client(
            "s3",
            endpoint_url=cfg["R2_ENDPOINT"],
            aws_access_key_id=cfg["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=cfg["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )

    def put(self, key, data, content_type):
        self._client.put_object(
            Bucket=self.bucket, Key=key, Body=data,
            ContentType=content_type, ServerSideEncryption="AES256",
        )

    def presigned_url(self, key, expires=None):
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires or self.expire,
        )

    def delete(self, key):
        self._client.delete_object(Bucket=self.bucket, Key=key)


_mock_singleton = None


def get_storage():
    backend = current_app.config.get("STORAGE_BACKEND", "mock")
    if backend == "r2":
        return R2Storage(current_app.config)
    global _mock_singleton
    if _mock_singleton is None:
        _mock_singleton = MockStorage()
    return _mock_singleton
```

> 註：MockStorage 用 module-level singleton，讓路由 put 後、測試再 `get_storage()` 拿到同一份 `objects`。每個測試若需乾淨狀態，於測試開頭 `import app.storage.r2 as r2; r2._mock_singleton = None`。

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_storage.py -v`
Expected: PASS

- [ ] **Step 6: Validate requirements syntax**

Run: `python3 -m pip install --dry-run -r requirements.txt >/dev/null && echo OK`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add app/storage/ app/config.py requirements.txt tests/test_storage.py
git commit -m "feat(storage): R2/Mock 儲存後端 + boto3 依賴 + config"
```

---

## Task 5: OCR provider 介面 + MockProvider + prompt/schema + 金額 coerce

**Files:**
- Create: `app/ocr/__init__.py`（空）
- Create: `app/ocr/provider.py`
- Create: `app/ocr/prompt.py`
- Modify: `app/config.py`
- Test: `tests/test_ocr_provider.py`、`tests/test_ocr_prompt.py`

**Interfaces:**
- Produces:
  - `OCRResult`（dict）鍵：`summary, category_id, amount, confidence, is_handwritten, raw`
  - `get_provider()` — 依 `OCR_PROVIDER`(gemini|mock) 回實例；`recognize(image_bytes: bytes, content_type: str) -> dict`
  - `MockProvider(result=None)` — 回固定/可注入結果
  - `coerce_amount(value) -> tuple[float | None, bool]`（處理數字/字串/千分位逗號；失敗回 `(None, False)`）
  - `prompt.build_prompt(categories: list[dict]) -> str`、`prompt.build_response_schema() -> dict`

- [ ] **Step 1: Add config**

`app/config.py` `Config` 內新增：

```python
    # OCR
    OCR_PROVIDER = os.environ.get("OCR_PROVIDER", "mock")
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    GEMINI_TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT", "30"))
    # 暫存區/燈號
    OCR_STALE_SECONDS = int(os.environ.get("OCR_STALE_SECONDS", "120"))
    GREEN_THRESHOLD = float(os.environ.get("GREEN_THRESHOLD", "0.85"))
    EXPENSE_OCR_SYNC = os.environ.get("EXPENSE_OCR_SYNC", "false").lower() == "true"
```

`TestConfig` 內新增（讓整合測試背景 OCR 同步跑、可預測）：

```python
    EXPENSE_OCR_SYNC = True
    OCR_PROVIDER = "mock"
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_ocr_provider.py
from app.ocr.provider import get_provider, MockProvider, coerce_amount


def test_coerce_amount_plain_int():
    assert coerce_amount(1290) == (1290.0, True)


def test_coerce_amount_comma_string():
    assert coerce_amount("5,230") == (5230.0, True)


def test_coerce_amount_float_string():
    assert coerce_amount("45000.0") == (45000.0, True)


def test_coerce_amount_garbage():
    assert coerce_amount("約？") == (None, False)


def test_coerce_amount_none():
    assert coerce_amount(None) == (None, False)


def test_mock_provider_default(app):
    with app.app_context():
        p = get_provider()
        assert isinstance(p, MockProvider)
        r = p.recognize(b"img", "image/jpeg")
        assert set(r) >= {"summary", "category_id", "amount", "confidence", "is_handwritten", "raw"}
```

```python
# tests/test_ocr_prompt.py
from app.ocr.prompt import build_prompt, build_response_schema


def test_prompt_injects_categories_and_amount_rule():
    cats = [{"id": 3, "科目": "廚房支出", "項目": "食材"}]
    p = build_prompt(cats)
    assert "食材" in p and "3" in p
    # 金額規則：抓合計、排除現金/找零
    assert "合計" in p or "實付" in p
    assert "現金" in p and "找零" in p


def test_response_schema_shape():
    s = build_response_schema()
    props = s["properties"]
    assert {"summary", "category_id", "amount", "confidence", "is_handwritten"} <= set(props)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_ocr_provider.py tests/test_ocr_prompt.py -v`
Expected: FAIL（模組不存在）

- [ ] **Step 4: Implement provider + coerce**

```python
# app/ocr/provider.py
from flask import current_app


def coerce_amount(value):
    """→ (float|None, ok)。接受 int/float/字串（可含千分位逗號、貨幣符號）。"""
    if value is None:
        return None, False
    if isinstance(value, (int, float)):
        return float(value), True
    s = str(value).strip().replace(",", "").replace("NT$", "").replace("$", "")
    try:
        return float(s), True
    except ValueError:
        return None, False


class OCRProvider:
    def recognize(self, image_bytes, content_type):  # pragma: no cover - 介面
        raise NotImplementedError


class MockProvider(OCRProvider):
    def __init__(self, result=None):
        self._result = result

    def recognize(self, image_bytes, content_type):
        if self._result is not None:
            return dict(self._result)
        return {
            "summary": "測試單據", "category_id": None, "amount": 100,
            "confidence": 0.9, "is_handwritten": False, "raw": {"mock": True},
        }


def get_provider():
    if current_app.config.get("OCR_PROVIDER") == "gemini":
        from app.ocr.gemini import GeminiProvider   # Task 6
        return GeminiProvider(current_app.config)
    return MockProvider()
```

```python
# app/ocr/prompt.py
import json


def build_prompt(categories):
    """categories: [{'id', '科目', '項目'}]。回給 Gemini 的指示字串。"""
    cat_lines = "\n".join(
        f'  - id={c["id"]}: {c["科目"]} / {c["項目"]}' for c in categories
    )
    return (
        "你是台灣門市雜支單據的辨識助理。以下影像是一張收據/發票/估價單/銷貨單。\n"
        "只辨識畫面中『最主要、最完整』的那一張單據（常有多張單疊放，忽略邊角殘單）。\n"
        "\n"
        "抽三個欄位：\n"
        "1) summary：品名摘要，一句話。多品項請濃縮（例：8 項調味料→『調味料雜貨等 8 項』），不要逐條羅列。\n"
        "2) amount：這張單『最終應付的總金額』。\n"
        "   - 認明『合計 / 總計 / 實付金額 / 銷貨金額 / 應付』這類欄位。\n"
        "   - 【重要】務必排除『現金、付現、找零、找回、收現』等收付款欄位——那不是花費金額。\n"
        "     例：單上有『現金 2000 / 找零 710 / 小計 1290 / 實付金額 1290』時，正解是 1290，絕不是 2000。\n"
        "   - 金額回純數字（去千分位逗號、去貨幣符號）。\n"
        "3) category_id：從下列清單挑最符合的 id；若都不合，回 null。\n"
        f"{cat_lines}\n"
        "\n"
        "另外回：confidence（0–1，你對辨識的信心）、is_handwritten（此單金額是否為手寫）。\n"
        "以 JSON 結構化輸出。"
    )


def build_response_schema():
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "category_id": {"type": ["integer", "null"]},
            "amount": {"type": ["number", "string", "null"]},
            "confidence": {"type": "number"},
            "is_handwritten": {"type": "boolean"},
        },
        "required": ["summary", "amount", "confidence", "is_handwritten"],
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_ocr_provider.py tests/test_ocr_prompt.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/ocr/__init__.py app/ocr/provider.py app/ocr/prompt.py app/config.py tests/test_ocr_provider.py tests/test_ocr_prompt.py
git commit -m "feat(ocr): OCRProvider 介面 + MockProvider + prompt/schema + coerce_amount"
```

---

## Task 6: GeminiProvider（urllib REST）

**Files:**
- Create: `app/ocr/gemini.py`
- Test: `tests/test_ocr_gemini.py`

**Interfaces:**
- Consumes: `app/ocr/prompt.build_prompt/build_response_schema`、`app/ocr/provider.OCRProvider`、`app/models.Category`
- Produces: `GeminiProvider(cfg).recognize(image_bytes, content_type) -> dict`（同 OCRResult 形狀）；內部 `_call_api(payload) -> dict` 可 monkeypatch 供測試（不打真網路）

- [ ] **Step 1: Write the failing test**（monkeypatch `_call_api`，不打真網路）

```python
# tests/test_ocr_gemini.py
import json
from app.extensions import db
from app.models import Category
from app.ocr.gemini import GeminiProvider


def _seed_categories(app):
    with app.app_context():
        db.create_all()
        parent = Category(name="廚房支出", level=1, sort=1)
        db.session.add(parent); db.session.commit()
        child = Category(name="食材", level=2, parent_id=parent.id, sort=1)
        db.session.add(child); db.session.commit()
        return child.id


def _fake_api_response(obj):
    # 模擬 Gemini generateContent 回傳結構
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}]}


def test_gemini_maps_response_to_ocrresult(app, monkeypatch):
    cid = _seed_categories(app)
    with app.app_context():
        p = GeminiProvider(app.config)
        monkeypatch.setattr(p, "_call_api", lambda payload: _fake_api_response({
            "summary": "牛肉角等2項", "category_id": cid, "amount": "1,290",
            "confidence": 0.92, "is_handwritten": False,
        }))
        r = p.recognize(b"imgbytes", "image/jpeg")
        assert r["summary"] == "牛肉角等2項"
        assert r["category_id"] == cid
        assert r["amount"] in (1290, 1290.0, "1,290")  # 原值傳回，coerce 在 tasks 做
        assert r["confidence"] == 0.92
        assert r["is_handwritten"] is False
        assert r["raw"] is not None


def test_gemini_bad_json_returns_empty_result(app, monkeypatch):
    _seed_categories(app)
    with app.app_context():
        p = GeminiProvider(app.config)
        monkeypatch.setattr(p, "_call_api", lambda payload: {"candidates": [{"content": {"parts": [{"text": "非JSON"}]}}]})
        r = p.recognize(b"img", "image/jpeg")
        assert r["summary"] is None and r["amount"] is None
        assert r["confidence"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_ocr_gemini.py -v`
Expected: FAIL（模組不存在）

- [ ] **Step 3: Implement**

```python
# app/ocr/gemini.py
import base64
import json
import logging
import urllib.request

from app.models import Category
from app.ocr.provider import OCRProvider
from app.ocr.prompt import build_prompt, build_response_schema

logger = logging.getLogger(__name__)
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"


def _load_categories():
    rows = (Category.query
            .filter_by(active=True)
            .order_by(Category.sort).all())
    by_id = {r.id: r for r in rows}
    out = []
    for r in rows:
        if r.level == 2:
            parent = by_id.get(r.parent_id)
            out.append({"id": r.id, "科目": parent.name if parent else "", "項目": r.name})
    return out


class GeminiProvider(OCRProvider):
    def __init__(self, cfg):
        self.model = cfg.get("GEMINI_MODEL", "gemini-2.5-flash")
        self.key = cfg.get("GEMINI_API_KEY", "")
        self.timeout = cfg.get("GEMINI_TIMEOUT", 30)

    def _call_api(self, payload):
        url = _ENDPOINT.format(model=self.model, key=self.key)
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def recognize(self, image_bytes, content_type):
        categories = _load_categories()
        payload = {
            "contents": [{"parts": [
                {"text": build_prompt(categories)},
                {"inline_data": {"mime_type": content_type,
                                 "data": base64.b64encode(image_bytes).decode("ascii")}},
            ]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": build_response_schema(),
            },
        }
        empty = {"summary": None, "category_id": None, "amount": None,
                 "confidence": None, "is_handwritten": None, "raw": None}
        try:
            resp = self._call_api(payload)
            text = resp["candidates"][0]["content"]["parts"][0]["text"]
            obj = json.loads(text)
        except Exception as e:
            logger.warning("Gemini recognize failed: %s", e)
            return empty
        return {
            "summary": obj.get("summary"),
            "category_id": obj.get("category_id"),
            "amount": obj.get("amount"),
            "confidence": obj.get("confidence"),
            "is_handwritten": obj.get("is_handwritten"),
            "raw": obj,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_ocr_gemini.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ocr/gemini.py tests/test_ocr_gemini.py
git commit -m "feat(ocr): GeminiProvider urllib REST + responseSchema"
```

---

## Task 7: 拍單路由 POST /expenses + 背景 OCR + blueprint 註冊

**Files:**
- Create: `app/expenses/tasks.py`
- Create: `app/expenses/serialize.py`
- Modify: `app/expenses/__init__.py`（定義 `expense_bp`）
- Create: `app/expenses/routes.py`
- Modify: `app/__init__.py`（註冊 blueprint）
- Test: `tests/test_expense_capture.py`

**Interfaces:**
- Consumes: `process_upload_image_async`、`get_storage`、`get_provider`、`coerce_amount`、`Expense`、`current_user`
- Produces:
  - `expense_bp`（`url_prefix="/expenses"`）
  - `POST /expenses` body `{image: base64, content_type?}` → `202 {status:"ok", id}`；未登入 401；無圖 400；無 store 400
  - `tasks.schedule_ocr(expense_id, image_bytes, content_type)`、`tasks._run_ocr(app, expense_id, image_bytes, content_type)`
  - `serialize.serialize_expense(e, storage, with_main=False) -> dict`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_expense_capture.py
import io, base64, time
from PIL import Image
from app.extensions import db
from app.models import Expense, Store, User, Device
import app.storage.r2 as r2mod


def _b64_jpeg(w=1200, h=900):
    buf = io.BytesIO(); Image.new("RGB", (w, h), (200, 180, 160)).save(buf, "JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A"); db.session.add(s); db.session.commit()
        u = User(name="員工A", role="employee", store_id=s.id); u.set_password("0000")
        dev = Device(client_uid="devEmp", store_id=s.id, is_approved=True)
        db.session.add_all([u, dev]); db.session.commit()
        return s.id, u.id


def _client(app, uid_cookie="devEmp", user_id=None):
    c = app.test_client(); c.set_cookie("device_uid", uid_cookie)
    if user_id:
        with c.session_transaction() as sess:
            sess["user_id"] = user_id; sess["_last_request_at"] = int(time.time())
    return c


def test_capture_creates_draft_via_sync_ocr(app):
    r2mod._mock_singleton = None
    sid, uid = _seed(app)
    c = _client(app, user_id=uid)
    resp = c.post("/expenses", json={"image": _b64_jpeg()})
    assert resp.status_code == 202
    eid = resp.get_json()["id"]
    with app.app_context():
        e = db.session.get(Expense, eid)
        # TestConfig EXPENSE_OCR_SYNC=True + MockProvider → 已轉 draft
        assert e.status == "draft"
        assert e.summary == "測試單據"        # MockProvider 預設
        assert e.amount is not None
        assert e.image_key and e.thumb_key
        assert e.image_key in r2mod._mock_singleton.objects


def test_capture_requires_login(app):
    _seed(app)
    c = _client(app)  # 無 session user
    resp = c.post("/expenses", json={"image": _b64_jpeg()})
    assert resp.status_code == 401


def test_capture_no_image_400(app):
    sid, uid = _seed(app)
    c = _client(app, user_id=uid)
    assert c.post("/expenses", json={}).status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_expense_capture.py -v`
Expected: FAIL（404 / blueprint 未註冊）

- [ ] **Step 3: Implement tasks + serialize + blueprint + route**

```python
# app/expenses/tasks.py
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

from flask import current_app
from app.extensions import db
from app.models import Expense
from app.ocr.provider import get_provider, coerce_amount

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=4)


def _valid_category_id(cid):
    if cid is None:
        return None
    from app.models import Category
    return cid if db.session.get(Category, cid) is not None else None


def _run_ocr(app, expense_id, image_bytes, content_type):
    with app.app_context():
        try:
            result = get_provider().recognize(image_bytes, content_type)
        except Exception as e:
            logger.warning("OCR run failed: %s", e); result = None
        e = db.session.get(Expense, expense_id)
        if e is None or e.status != "pending_ocr":
            return
        if not result:
            e.status = "draft"; e.amount_parse_ok = False
        else:
            amount, ok = coerce_amount(result.get("amount"))
            e.summary = result.get("summary")
            e.category_id = _valid_category_id(result.get("category_id"))
            e.amount = amount
            e.amount_parse_ok = ok
            e.ocr_confidence = result.get("confidence")
            e.ocr_is_handwritten = result.get("is_handwritten")
            e.ocr_raw = result.get("raw")
            e.status = "draft"
        db.session.commit()


def schedule_ocr(expense_id, image_bytes, content_type):
    app = current_app._get_current_object()
    if app.config.get("EXPENSE_OCR_SYNC"):
        _run_ocr(app, expense_id, image_bytes, content_type)   # 測試/可預測
    else:
        _executor.submit(_run_ocr, app, expense_id, image_bytes, content_type)


def reconcile_stale(user_id):
    """暫存區列表拉取時就地收斂：逾時仍 pending_ocr → draft 空欄紅燈。"""
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=current_app.config.get("OCR_STALE_SECONDS", 120))
    stale = (Expense.query
             .filter(Expense.created_by == user_id,
                     Expense.status == "pending_ocr",
                     Expense.created_at < cutoff).all())
    for e in stale:
        e.status = "draft"; e.amount_parse_ok = False
    if stale:
        db.session.commit()
```

```python
# app/expenses/serialize.py
from flask import current_app
from app.expenses.logic import traffic_light


def serialize_expense(e, storage, with_main=False):
    light = traffic_light(
        e.ocr_is_handwritten, e.ocr_confidence, e.amount_parse_ok,
        e.is_modified_by_user,
        green_threshold=current_app.config.get("GREEN_THRESHOLD", 0.85),
    )
    d = {
        "id": e.id, "status": e.status,
        "summary": e.summary, "category_id": e.category_id,
        "amount": float(e.amount) if e.amount is not None else None,
        "light": light,
        "is_modified_by_user": e.is_modified_by_user,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "thumb_url": storage.presigned_url(e.thumb_key) if e.thumb_key else None,
    }
    if with_main:
        d["image_url"] = storage.presigned_url(e.image_key) if e.image_key else None
    return d
```

```python
# app/expenses/__init__.py
from flask import Blueprint

expense_bp = Blueprint("expenses", __name__, url_prefix="/expenses")

from app.expenses import routes  # noqa: E402,F401  綁定路由
```

```python
# app/expenses/routes.py
import base64
import uuid
from datetime import datetime, timezone

from flask import request, jsonify, current_app
from app.extensions import db
from app.models import Expense
from app.auth.decorators import current_user
from app.images.image_utils import process_upload_image_async
from app.storage.r2 import get_storage
from app.expenses import expense_bp
from app.expenses.tasks import schedule_ocr


def _make_key(store_id):
    yyyymm = datetime.now(timezone.utc).strftime("%Y%m")
    return f"expenses/{store_id}/{yyyymm}/{uuid.uuid4().hex}.jpg"


@expense_bp.post("")
def capture():
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    if user.store_id is None:
        return jsonify(status="error", message="no store"), 400
    data = request.get_json(silent=True) or {}
    image = data.get("image")
    if not image:
        return jsonify(status="error", message="no image"), 400
    try:
        raw = base64.b64decode(str(image).split(",")[-1])
    except Exception:
        return jsonify(status="error", message="bad image"), 400
    content_type = data.get("content_type", "image/jpeg")

    main_bytes, thumb_bytes = process_upload_image_async(raw, content_type)
    storage = get_storage()
    key = _make_key(user.store_id)
    thumb_key = key[:-4] + "_thumb.jpg" if thumb_bytes else None
    storage.put(key, main_bytes, "image/jpeg")
    if thumb_bytes:
        storage.put(thumb_key, thumb_bytes, "image/jpeg")

    e = Expense(store_id=user.store_id, created_by=user.id, status="pending_ocr",
                image_key=key, thumb_key=thumb_key,
                created_at=datetime.now(timezone.utc))
    db.session.add(e); db.session.commit()
    schedule_ocr(e.id, main_bytes, "image/jpeg")
    return jsonify(status="ok", id=e.id), 202
```

在 `app/__init__.py` 的 blueprint 註冊區（`fx_bp` 之後）加：

```python
    from app.expenses import expense_bp
    app.register_blueprint(expense_bp)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_expense_capture.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/expenses/ app/__init__.py tests/test_expense_capture.py
git commit -m "feat(expense): POST /expenses 拍單上傳 + 背景 OCR + blueprint 註冊"
```

---

## Task 8: 暫存區列表 GET /pending（含 orphan 收斂）+ GET /<id>

**Files:**
- Modify: `app/expenses/routes.py`
- Test: `tests/test_expense_pending.py`

**Interfaces:**
- Consumes: `reconcile_stale`、`serialize_expense`、`get_storage`
- Produces:
  - `GET /expenses/pending` → `{status:"ok", expenses:[...]}`（本人 `pending_ocr`+`draft`，倒序，thumb 簽章 URL）
  - `GET /expenses/<int:eid>` → `{status:"ok", expense:{...image_url}}`；非本人 403；不存在 404

- [ ] **Step 1: Write the failing test**

```python
# tests/test_expense_pending.py
import time
from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models import Expense, Store, User, Device
import app.storage.r2 as r2mod


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A"); db.session.add(s); db.session.commit()
        u = User(name="員工A", role="employee", store_id=s.id); u.set_password("0000")
        u2 = User(name="員工B", role="employee", store_id=s.id); u2.set_password("0000")
        dev = Device(client_uid="devEmp", store_id=s.id, is_approved=True)
        db.session.add_all([u, u2, dev]); db.session.commit()
        return s.id, u.id, u2.id


def _client(app, user_id):
    c = app.test_client(); c.set_cookie("device_uid", "devEmp")
    with c.session_transaction() as sess:
        sess["user_id"] = user_id; sess["_last_request_at"] = int(time.time())
    return c


def test_pending_lists_own_draft_and_pending(app):
    r2mod._mock_singleton = None
    sid, uid, uid2 = _seed(app)
    with app.app_context():
        now = datetime.now(timezone.utc)
        db.session.add_all([
            Expense(store_id=sid, created_by=uid, status="draft", created_at=now, thumb_key="t1.jpg"),
            Expense(store_id=sid, created_by=uid, status="pending_ocr", created_at=now),
            Expense(store_id=sid, created_by=uid, status="submitted", created_at=now),   # 不列
            Expense(store_id=sid, created_by=uid2, status="draft", created_at=now),      # 他人不列
        ]); db.session.commit()
    c = _client(app, uid)
    body = c.get("/expenses/pending").get_json()
    assert body["status"] == "ok"
    statuses = sorted(e["status"] for e in body["expenses"])
    assert statuses == ["draft", "pending_ocr"]
    row = next(e for e in body["expenses"] if e["status"] == "draft")
    assert row["thumb_url"] and "t1.jpg" in row["thumb_url"]
    assert "light" in row


def test_pending_reconciles_stale_pending_ocr(app):
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        old = datetime.now(timezone.utc) - timedelta(seconds=999)
        db.session.add(Expense(store_id=sid, created_by=uid, status="pending_ocr", created_at=old))
        db.session.commit()
    c = _client(app, uid)
    body = c.get("/expenses/pending").get_json()
    row = body["expenses"][0]
    assert row["status"] == "draft"        # 逾時被收斂
    assert row["light"] == "red"           # amount_parse_ok=False → 紅


def test_get_detail_own_returns_image_url(app):
    r2mod._mock_singleton = None
    sid, uid, uid2 = _seed(app)
    with app.app_context():
        e = Expense(store_id=sid, created_by=uid, status="draft",
                    created_at=datetime.now(timezone.utc), image_key="m1.jpg")
        db.session.add(e); db.session.commit(); eid = e.id
    c = _client(app, uid)
    body = c.get(f"/expenses/{eid}").get_json()
    assert body["status"] == "ok"
    assert "m1.jpg" in body["expense"]["image_url"]


def test_get_detail_other_user_403(app):
    r2mod._mock_singleton = None
    sid, uid, uid2 = _seed(app)
    with app.app_context():
        e = Expense(store_id=sid, created_by=uid2, status="draft",
                    created_at=datetime.now(timezone.utc))
        db.session.add(e); db.session.commit(); eid = e.id
    c = _client(app, uid)
    assert c.get(f"/expenses/{eid}").status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_expense_pending.py -v`
Expected: FAIL（404 路由不存在）

- [ ] **Step 3: Implement — append to `app/expenses/routes.py`**

```python
from app.auth.decorators import current_user as _cu  # 已 import current_user，可直接用
from app.expenses.serialize import serialize_expense
from app.expenses.tasks import reconcile_stale


def _load_owned(eid, user):
    e = db.session.get(Expense, eid)
    if e is None:
        return None, (jsonify(status="error", message="not found"), 404)
    if e.created_by != user.id:
        return None, (jsonify(status="error", message="forbidden"), 403)
    return e, None


@expense_bp.get("/pending")
def pending():
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    reconcile_stale(user.id)
    rows = (Expense.query
            .filter(Expense.created_by == user.id,
                    Expense.status.in_(["pending_ocr", "draft"]))
            .order_by(Expense.created_at.desc()).all())
    storage = get_storage()
    return jsonify(status="ok",
                   expenses=[serialize_expense(e, storage) for e in rows])


@expense_bp.get("/<int:eid>")
def detail(eid):
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    e, err = _load_owned(eid, user)
    if err:
        return err
    return jsonify(status="ok", expense=serialize_expense(e, get_storage(), with_main=True))
```

> 註：`_cu` import 不必要時可省略；`current_user`、`db`、`jsonify`、`get_storage`、`Expense` 皆已於檔案上半部 import。

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_expense_pending.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/expenses/routes.py tests/test_expense_pending.py
git commit -m "feat(expense): GET /pending(收斂 orphan) + GET /<id> 明細"
```

---

## Task 9: 編輯 PATCH + 送出 submit + 丟棄 DELETE

**Files:**
- Modify: `app/expenses/routes.py`
- Test: `tests/test_expense_edit_submit.py`

**Interfaces:**
- Consumes: `_load_owned`、`compute_business_date`、`get_storage`
- Produces:
  - `PATCH /expenses/<int:eid>` body `{summary?, category_id?, amount?}`（限 draft、本人）→ 改動 amount/category 設 `is_modified_by_user=True` → `{status:"ok", expense}`
  - `POST /expenses/<int:eid>/submit`（限 draft、本人）→ `draft`→`submitted`、算 `business_date`、`submitted_at` → `{status:"ok"}`
  - `DELETE /expenses/<int:eid>`（限 draft、本人）→ 刪 R2 物件 + 刪列 → `{status:"ok"}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_expense_edit_submit.py
import time
from datetime import datetime, timezone
from app.extensions import db
from app.models import Expense, Store, User, Device, Category
import app.storage.r2 as r2mod


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A"); db.session.add(s); db.session.commit()
        u = User(name="員工A", role="employee", store_id=s.id); u.set_password("0000")
        dev = Device(client_uid="devEmp", store_id=s.id, is_approved=True)
        cat = Category(name="食材", level=1, sort=1)
        db.session.add_all([u, dev, cat]); db.session.commit()
        return s.id, u.id, cat.id


def _client(app, user_id):
    c = app.test_client(); c.set_cookie("device_uid", "devEmp")
    with c.session_transaction() as sess:
        sess["user_id"] = user_id; sess["_last_request_at"] = int(time.time())
    return c


def _draft(app, sid, uid, **kw):
    with app.app_context():
        e = Expense(store_id=sid, created_by=uid, status="draft",
                    created_at=datetime.now(timezone.utc), **kw)
        db.session.add(e); db.session.commit(); return e.id


def test_patch_amount_sets_modified_and_red(app):
    r2mod._mock_singleton = None
    sid, uid, cid = _seed(app)
    eid = _draft(app, sid, uid, amount=100, amount_parse_ok=True,
                 ocr_is_handwritten=False, ocr_confidence=0.9)
    c = _client(app, uid)
    body = c.patch(f"/expenses/{eid}", json={"amount": 250}).get_json()
    assert body["status"] == "ok"
    assert body["expense"]["amount"] == 250.0
    assert body["expense"]["is_modified_by_user"] is True
    assert body["expense"]["light"] == "red"


def test_patch_only_summary_not_modified(app):
    r2mod._mock_singleton = None
    sid, uid, cid = _seed(app)
    eid = _draft(app, sid, uid, amount=100, amount_parse_ok=True,
                 ocr_is_handwritten=False, ocr_confidence=0.9)
    c = _client(app, uid)
    body = c.patch(f"/expenses/{eid}", json={"summary": "改摘要"}).get_json()
    assert body["expense"]["is_modified_by_user"] is False   # 只改摘要不算改金額/分類
    assert body["expense"]["light"] == "green"


def test_patch_rejects_non_draft(app):
    r2mod._mock_singleton = None
    sid, uid, cid = _seed(app)
    eid = _draft(app, sid, uid)
    with app.app_context():
        db.session.get(Expense, eid).status = "submitted"; db.session.commit()
    c = _client(app, uid)
    assert c.patch(f"/expenses/{eid}", json={"amount": 9}).status_code == 409


def test_submit_transitions_and_sets_business_date(app):
    r2mod._mock_singleton = None
    sid, uid, cid = _seed(app)
    # 台灣 07:59 → 前一日
    from app.expenses.logic import TW_TZ
    created = datetime(2026, 7, 7, 7, 59, tzinfo=TW_TZ).astimezone(timezone.utc)
    eid = _draft(app, sid, uid, amount=100, amount_parse_ok=True)
    with app.app_context():
        db.session.get(Expense, eid).created_at = created; db.session.commit()
    c = _client(app, uid)
    assert c.post(f"/expenses/{eid}/submit").get_json()["status"] == "ok"
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "submitted"
        assert e.business_date.isoformat() == "2026-07-06"
        assert e.submitted_at is not None


def test_delete_removes_row_and_r2(app):
    r2mod._mock_singleton = None
    sid, uid, cid = _seed(app)
    eid = _draft(app, sid, uid, image_key="m.jpg", thumb_key="m_thumb.jpg")
    from app.storage.r2 import get_storage
    with app.app_context():
        get_storage().put("m.jpg", b"x", "image/jpeg")
        get_storage().put("m_thumb.jpg", b"x", "image/jpeg")
    c = _client(app, uid)
    assert c.delete(f"/expenses/{eid}").get_json()["status"] == "ok"
    with app.app_context():
        assert db.session.get(Expense, eid) is None
        assert "m.jpg" not in r2mod._mock_singleton.objects
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_expense_edit_submit.py -v`
Expected: FAIL

- [ ] **Step 3: Implement — append to `app/expenses/routes.py`**

```python
from decimal import Decimal, InvalidOperation
from app.expenses.logic import compute_business_date


@expense_bp.patch("/<int:eid>")
def edit(eid):
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    e, err = _load_owned(eid, user)
    if err:
        return err
    if e.status != "draft":
        return jsonify(status="error", message="not editable"), 409
    data = request.get_json(silent=True) or {}
    if "summary" in data:
        e.summary = data["summary"]
    if "category_id" in data:
        e.category_id = data["category_id"]
        e.is_modified_by_user = True
    if "amount" in data:
        try:
            e.amount = None if data["amount"] is None else Decimal(str(data["amount"]))
            e.amount_parse_ok = e.amount is not None
        except (InvalidOperation, ValueError):
            e.amount = None; e.amount_parse_ok = False
        e.is_modified_by_user = True
    db.session.commit()
    return jsonify(status="ok", expense=serialize_expense(e, get_storage()))


@expense_bp.post("/<int:eid>/submit")
def submit(eid):
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    e, err = _load_owned(eid, user)
    if err:
        return err
    if e.status != "draft":
        return jsonify(status="error", message="not submittable"), 409
    e.status = "submitted"
    e.business_date = compute_business_date(e.created_at)
    e.submitted_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(status="ok")


@expense_bp.delete("/<int:eid>")
def discard(eid):
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    e, err = _load_owned(eid, user)
    if err:
        return err
    if e.status != "draft":
        return jsonify(status="error", message="not deletable"), 409
    storage = get_storage()
    for k in (e.image_key, e.thumb_key):
        if k:
            try:
                storage.delete(k)
            except Exception:
                pass
    db.session.delete(e); db.session.commit()
    return jsonify(status="ok")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_expense_edit_submit.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/expenses/routes.py tests/test_expense_edit_submit.py
git commit -m "feat(expense): PATCH 編輯(標 modified) + submit(算 business_date) + DELETE(連 R2)"
```

---

## Task 10: 無單據建帳 POST /expenses/no-receipt

**Files:**
- Modify: `app/expenses/routes.py`
- Test: `tests/test_expense_no_receipt.py`

**Interfaces:**
- Produces: `POST /expenses/no-receipt` body `{summary, amount, category_id?, reason}`（限登入、本人本店）→ 直接建 `submitted`（無圖）、算 `business_date` → `{status:"ok", id}`；缺 `reason` 400；缺 `amount` 400

- [ ] **Step 1: Write the failing test**

```python
# tests/test_expense_no_receipt.py
import time
from app.extensions import db
from app.models import Expense, Store, User, Device


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A"); db.session.add(s); db.session.commit()
        u = User(name="員工A", role="employee", store_id=s.id); u.set_password("0000")
        dev = Device(client_uid="devEmp", store_id=s.id, is_approved=True)
        db.session.add_all([u, dev]); db.session.commit()
        return s.id, u.id


def _client(app, user_id):
    c = app.test_client(); c.set_cookie("device_uid", "devEmp")
    with c.session_transaction() as sess:
        sess["user_id"] = user_id; sess["_last_request_at"] = int(time.time())
    return c


def test_no_receipt_creates_submitted(app):
    sid, uid = _seed(app)
    c = _client(app, uid)
    resp = c.post("/expenses/no-receipt",
                  json={"summary": "計程車", "amount": 250, "reason": "臨時叫車無收據"})
    assert resp.status_code == 200
    eid = resp.get_json()["id"]
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "submitted"
        assert e.image_key is None
        assert e.no_receipt_reason == "臨時叫車無收據"
        assert e.business_date is not None
        assert float(e.amount) == 250.0


def test_no_receipt_requires_reason(app):
    sid, uid = _seed(app)
    c = _client(app, uid)
    r = c.post("/expenses/no-receipt", json={"summary": "x", "amount": 1})
    assert r.status_code == 400


def test_no_receipt_requires_amount(app):
    sid, uid = _seed(app)
    c = _client(app, uid)
    r = c.post("/expenses/no-receipt", json={"summary": "x", "reason": "y"})
    assert r.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_expense_no_receipt.py -v`
Expected: FAIL

- [ ] **Step 3: Implement — append to `app/expenses/routes.py`**

```python
@expense_bp.post("/no-receipt")
def no_receipt():
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    if user.store_id is None:
        return jsonify(status="error", message="no store"), 400
    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip()
    if not reason:
        return jsonify(status="error", message="reason required"), 400
    amount, ok = None, False
    if data.get("amount") is not None:
        try:
            amount = Decimal(str(data["amount"])); ok = True
        except (InvalidOperation, ValueError):
            ok = False
    if not ok:
        return jsonify(status="error", message="amount required"), 400
    now = datetime.now(timezone.utc)
    e = Expense(
        store_id=user.store_id, created_by=user.id, status="submitted",
        created_at=now, submitted_at=now, business_date=compute_business_date(now),
        summary=data.get("summary"), category_id=data.get("category_id"),
        amount=amount, amount_parse_ok=True, is_modified_by_user=True,
        no_receipt_reason=reason,
    )
    db.session.add(e); db.session.commit()
    return jsonify(status="ok", id=e.id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_expense_no_receipt.py -v`
Expected: PASS

- [ ] **Step 5: Run full backend suite (guard regressions)**

Run: `python3 -m pytest -q`
Expected: 全綠（既有 + 新增）

- [ ] **Step 6: Commit**

```bash
git add app/expenses/routes.py tests/test_expense_no_receipt.py
git commit -m "feat(expense): 無單據建帳 POST /no-receipt 直接 submitted"
```

---

## Task 11: 前端 — 純邏輯模組 + JS 測試 + 拍單/暫存區 view + sw.js

**Files:**
- Create: `app/static/js/expenses_util.js`
- Create: `app/static/js/expenses_api.js`
- Create: `app/static/js/capture.js`
- Create: `app/static/js/pending.js`
- Modify: `app/static/js/auth.js`（`showAppView` 加導覽）
- Modify: `app/static/sw.js`（network-first + STATIC_URLS + bump CACHE_NAME）
- Test: `tests/js/expenses.mjs`

**Interfaces:**
- Produces（純邏輯，node 可測）：
  - `formatAmount(n) -> string`（千分位；null → `'—'`）
  - `lightLabel(light) -> string`（green→`'🟢'`, yellow→`'🟡'`, red→`'🔴'`）
  - `businessDateDisplay(iso) -> string`（台灣時間 `YYYY-MM-DD`）

- [ ] **Step 1: Write the failing JS test**

```javascript
// tests/js/expenses.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatAmount, lightLabel, businessDateDisplay } from '../../app/static/js/expenses_util.js';

test('formatAmount thousands + null', () => {
  assert.equal(formatAmount(1290), '1,290');
  assert.equal(formatAmount(5230.5), '5,230.5');
  assert.equal(formatAmount(null), '—');
});

test('lightLabel maps', () => {
  assert.equal(lightLabel('green'), '🟢');
  assert.equal(lightLabel('yellow'), '🟡');
  assert.equal(lightLabel('red'), '🔴');
});

test('businessDateDisplay taiwan', () => {
  // 台灣 07:59 的 UTC = 2026-07-06T23:59Z → 顯示日期 2026-07-07（此函式只格式化日期，不做 08:00 分界）
  assert.equal(businessDateDisplay('2026-07-06T23:59:00+00:00'), '2026-07-07');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/js/expenses.mjs`
Expected: FAIL（模組不存在）

- [ ] **Step 3: Implement pure module**

```javascript
// app/static/js/expenses_util.js
export function formatAmount(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return Number(n).toLocaleString('en-US');
}

export function lightLabel(light) {
  return { green: '🟢', yellow: '🟡', red: '🔴' }[light] || '⚪';
}

export function businessDateDisplay(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(d);
  const get = (t) => parts.find((p) => p.type === t).value;
  return `${get('year')}-${get('month')}-${get('day')}`;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test tests/js/expenses.mjs`
Expected: PASS

- [ ] **Step 5: Implement API wrapper + capture + pending views (DOM glue, 手動 e2e)**

```javascript
// app/static/js/expenses_api.js
async function jsonFetch(url, opts) {
  const res = await fetch(url, opts);
  return { status: res.status, data: await res.json().catch(() => ({})) };
}
export const captureUpload = (image) => jsonFetch('/expenses', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ image }),
});
export const listPending = () => jsonFetch('/expenses/pending');
export const patchExpense = (id, patch) => jsonFetch(`/expenses/${id}`, {
  method: 'PATCH', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(patch),
});
export const submitExpense = (id) => jsonFetch(`/expenses/${id}/submit`, { method: 'POST' });
export const discardExpense = (id) => jsonFetch(`/expenses/${id}`, { method: 'DELETE' });
export const noReceipt = (payload) => jsonFetch('/expenses/no-receipt', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
});
```

```javascript
// app/static/js/capture.js
import { Camera } from './camera.js';
import { captureUpload } from './expenses_api.js';

const root = () => document.getElementById('modal-root');

// 無腦拍單：快門 → [完成]/[下一張]；完成後逐張上傳、進度條；可離開。
export function showCaptureView(onDone) {
  root().innerHTML = `
    <div class="modal-backdrop"><div class="modal-box">
      <h2>拍單</h2>
      <video id="cap-video" autoplay playsinline muted></video>
      <canvas id="cap-canvas" style="display:none;"></canvas>
      <div id="cap-count" class="app-view-info">已拍 0 張</div>
      <div id="cap-actions">
        <button class="modal-btn" id="cap-shot" type="button">拍照</button>
      </div>
      <div id="cap-after" style="display:none;">
        <button class="modal-btn secondary" id="cap-next" type="button">下一張</button>
        <button class="modal-btn" id="cap-done" type="button">完成</button>
      </div>
      <div class="modal-msg" id="cap-msg"></div>
      <button class="modal-btn secondary" id="cap-back" type="button" style="margin-top:10px;">返回</button>
    </div></div>`;

  const cam = new Camera(document.getElementById('cap-video'), document.getElementById('cap-canvas'));
  const shots = [];
  const msg = document.getElementById('cap-msg');
  const count = document.getElementById('cap-count');
  const after = document.getElementById('cap-after');
  const shotBtn = document.getElementById('cap-shot');

  cam.start().catch(() => { msg.textContent = '無法開啟鏡頭'; });

  function takeShot() {
    if (!cam.isRecording) return;
    shots.push(cam.capture());           // base64 記憶體，不落地
    count.textContent = `已拍 ${shots.length} 張`;
    shotBtn.style.display = 'none';
    after.style.display = 'block';
  }
  shotBtn.addEventListener('click', takeShot);
  document.getElementById('cap-next').addEventListener('click', () => {
    after.style.display = 'none';
    shotBtn.style.display = 'block';
  });
  document.getElementById('cap-back').addEventListener('click', () => { cam.stop(); onDone(); });

  document.getElementById('cap-done').addEventListener('click', async () => {
    cam.stop();
    after.style.display = 'none'; shotBtn.style.display = 'none';
    let ok = 0;
    for (let i = 0; i < shots.length; i++) {
      msg.textContent = `上傳中 ${i + 1}/${shots.length}…`;
      try { const { status } = await captureUpload(shots[i]); if (status === 202) ok += 1; }
      catch (e) { /* 單張失敗略過，續傳其餘 */ }
    }
    msg.textContent = `已送出 ${ok}/${shots.length} 張，背景辨識中，稍後到暫存區確認`;
    setTimeout(onDone, 1200);
  });
}
```

```javascript
// app/static/js/pending.js
import { escapeHtml } from './admin_util.js';
import { formatAmount, lightLabel } from './expenses_util.js';
import { listPending, patchExpense, submitExpense, discardExpense } from './expenses_api.js';

const root = () => document.getElementById('modal-root');

export async function showPendingView(onBack) {
  root().innerHTML = `
    <div class="modal-backdrop"><div class="modal-box wide">
      <h2>暫存區</h2>
      <div id="pd-msg" class="modal-msg"></div>
      <table id="pd-table"><thead><tr>
        <th>圖</th><th>摘要</th><th>金額</th><th>燈</th><th></th>
      </tr></thead><tbody></tbody></table>
      <button class="modal-btn secondary" id="pd-back" type="button">返回</button>
    </div></div>`;
  document.getElementById('pd-back').addEventListener('click', onBack);

  const { data } = await listPending();
  const tbody = document.querySelector('#pd-table tbody');
  (data.expenses || []).forEach((e) => {
    const tr = document.createElement('tr');
    const thumb = e.thumb_url
      ? `<img src="${e.thumb_url}" loading="lazy" width="48">`
      : (e.status === 'pending_ocr' ? '🕓' : '—');
    tr.innerHTML = `
      <td>${thumb}</td>
      <td><input value="${escapeHtml(e.summary || '')}" data-f="summary"></td>
      <td><input value="${e.amount ?? ''}" inputmode="decimal" data-f="amount" style="width:80px"></td>
      <td>${lightLabel(e.light)}</td>
      <td><button data-act="submit">送出</button><button data-act="del">丟棄</button></td>`;
    tr.querySelector('[data-act="submit"]').addEventListener('click', async () => {
      const summary = tr.querySelector('[data-f="summary"]').value;
      const amount = tr.querySelector('[data-f="amount"]').value;
      await patchExpense(e.id, { summary, amount: amount === '' ? null : Number(amount) });
      const { status } = await submitExpense(e.id);
      if (status === 200) tr.remove();
    });
    tr.querySelector('[data-act="del"]').addEventListener('click', async () => {
      const { status } = await discardExpense(e.id);
      if (status === 200) tr.remove();
    });
    tbody.appendChild(tr);
  });
  if (!(data.expenses || []).length) {
    document.getElementById('pd-msg').textContent = '暫存區沒有待確認單據';
  }
}
```

- [ ] **Step 6: Wire nav into `showAppView`（`app/static/js/auth.js`）**

在 `auth.js` 頂部 import：

```javascript
import { showCaptureView } from './capture.js';
import { showPendingView } from './pending.js';
```

在 `showAppView` 的 `root().innerHTML` 內、`av-reface` 按鈕之前，插入員工導覽鈕：

```html
        <button class="modal-btn" id="av-capture" type="button">拍單</button>
        <button class="modal-btn" id="av-pending" type="button">暫存區</button>
```

並在 `showAppView` 函式尾端（`av-logout` handler 之後）加：

```javascript
  document.getElementById('av-capture').addEventListener('click', () => {
    cam.stop();
    showCaptureView(() => showAppView(identity));
  });
  document.getElementById('av-pending').addEventListener('click', () => {
    cam.stop();
    showPendingView(() => showAppView(identity));
  });
```

- [ ] **Step 7: Update `app/static/sw.js`**

- `CACHE_NAME` 由 `'calc-v10'` bump 成 `'calc-v11'`
- `STATIC_URLS` 加入四支新檔：
```javascript
  '/static/js/expenses_util.js',
  '/static/js/expenses_api.js',
  '/static/js/capture.js',
  '/static/js/pending.js',
```
- network-first 判斷加 `/expenses/`（注意：`POST /expenses`（無斜線）也要涵蓋 → 用 `=== '/expenses'` 併判）：
```javascript
  if (url.pathname.startsWith('/auth/') ||
      url.pathname.startsWith('/face/') ||
      url.pathname.startsWith('/api/') ||
      url.pathname === '/expenses' ||
      url.pathname.startsWith('/expenses/')) {
    event.respondWith(networkFirst(event.request));
    return;
  }
```

- [ ] **Step 8: Run JS test + full backend suite**

Run: `node --test tests/js/*.mjs && python3 -m pytest -q`
Expected: JS 全綠、pytest 全綠

- [ ] **Step 9: Commit**

```bash
git add app/static/js/expenses_util.js app/static/js/expenses_api.js app/static/js/capture.js app/static/js/pending.js app/static/js/auth.js app/static/sw.js tests/js/expenses.mjs
git commit -m "feat(expense-ui): 拍單/暫存區 view + 純邏輯 JS 測試 + sw.js network-first"
```

---

## Task 12: .env.example + 真圖手動 OCR 驗證腳本 + fixtures + docs

**Files:**
- Create: `.env.example`
- Modify: `.gitignore`
- Create: `tests/manual/verify_ocr.py`
- Create: `tests/fixtures/receipts/`（放 5 張真圖，gitignore）
- Modify: `CLAUDE.md`（補啟動/環境變數說明）

**Interfaces:** 無（工具/文件）。

- [ ] **Step 1: Add `.env.example`**

```bash
# .env.example — 複製成 .env 填真值（.env 不進 git）
APP_ENV=development
SECRET_KEY=dev-insecure-key

# OCR（Gemini）
OCR_PROVIDER=gemini
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

# 儲存（Cloudflare R2）
STORAGE_BACKEND=r2
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET=
R2_ENDPOINT=

# 暫存區/燈號調校（可留預設）
OCR_STALE_SECONDS=120
GREEN_THRESHOLD=0.85
```

- [ ] **Step 2: Update `.gitignore`**

在 `.gitignore` 末尾加：

```
tests/fixtures/receipts/
```

Run 驗證 fixtures 不會被追蹤（先建目錄放圖後）：
```bash
mkdir -p tests/fixtures/receipts
git check-ignore tests/fixtures/receipts/ && echo IGNORED
```
Expected: `IGNORED`

- [ ] **Step 3: 放入 5 張真圖**

把 user 提供的 5 張單據複製進 `tests/fixtures/receipts/`（檔名建議 `01_familymart.jpg`…`05_estimate.jpg`）。

- [ ] **Step 4: Manual OCR verify script**

```python
# tests/manual/verify_ocr.py
"""手動跑真 Gemini 驗辨識準度（需 .env 有 GEMINI_API_KEY，OCR_PROVIDER=gemini）。
用法：FLASK_APP=wsgi.py OCR_PROVIDER=gemini python3 tests/manual/verify_ocr.py
不進 CI（無金鑰）。重點驗全家單金額=1290(非2000)、手寫單金額、多品項摘要濃縮。"""
import glob
import os
from app import create_app
from app.extensions import db
from app.ocr.gemini import GeminiProvider

app = create_app()
with app.app_context():
    provider = GeminiProvider(app.config)
    for path in sorted(glob.glob("tests/fixtures/receipts/*.jpg")):
        with open(path, "rb") as f:
            raw = f.read()
        r = provider.recognize(raw, "image/jpeg")
        print(f"\n=== {os.path.basename(path)} ===")
        print(f"  summary   : {r['summary']}")
        print(f"  amount    : {r['amount']}")
        print(f"  category  : {r['category_id']}")
        print(f"  handwritten: {r['is_handwritten']}  conf: {r['confidence']}")
```

- [ ] **Step 5: Run manual verify (needs real key; skip if unavailable)**

Run: `FLASK_APP=wsgi.py python3 tests/manual/verify_ocr.py`
Expected（人工核對）：`01_familymart` 的 `amount` ≈ 1290（**不是 2000**）；手寫單金額合理；多品項單 summary 是一句濃縮。
> 若辨識明顯偏差（尤其 1290 vs 2000），回頭調 `app/ocr/prompt.py` 的金額規則措辭後重跑。

- [ ] **Step 6: Update `CLAUDE.md` 啟動段**

在 `## 啟動 / 開發` 段補：

```markdown
- 本機啟動：`cp .env.example .env` 填 Gemini/R2 真值 → `FLASK_APP=wsgi.py python3 -m flask db upgrade` → `FLASK_APP=wsgi.py SECRET_KEY=dev python3 -m flask run --port 5001`
- 測試：後端 `python3 -m pytest -q`；前端純邏輯 `node --test tests/js/*.mjs`
- OCR/R2 本機真測：`.env` 設 `OCR_PROVIDER=gemini` / `STORAGE_BACKEND=r2`；不設則走 mock。真圖辨識驗證 `python3 tests/manual/verify_ocr.py`
- ⚠️ 測試完成後刪除 `.env` 內 Gemini/R2 真憑證
```

- [ ] **Step 7: Commit**

```bash
git add .env.example .gitignore tests/manual/verify_ocr.py CLAUDE.md
git commit -m "chore(expense): .env.example + 真圖 OCR 手動驗證腳本 + 啟動文件"
```

---

## Self-Review（作者已檢查）

**Spec coverage：**
- §2 拍單/暫存區/送出流程 → Task 7/8/9；無單據建帳 §2 → Task 10 ✅
- §3 狀態機 → Task 1 常數 + Task 7/8/9 轉移 ✅
- §4 expenses 全欄位 → Task 1 ✅
- §5 business_date 08:00 → Task 2 + Task 9 submit ✅
- §6 OCRProvider/Gemini/prompt/紅圈移除/金額排除現金找零 → Task 5/6 ✅
- §7 image_utils 3200/640/85/78 → Task 3 ✅
- §8 R2 boto3/SSE/簽章 → Task 4 ✅
- §9 七路由（前綴改 /expenses，安全修正）→ Task 7/8/9/10 ✅
- §10 前端 view + sw.js network-first + JS 測試 → Task 11 ✅
- §11 環境變數 → Task 4/5 config + Task 12 .env.example ✅
- §12 測試策略（單元+整合+真圖手動）→ 各 Task 測試 + Task 12 ✅
- §13 boto3 依賴/build 影響 → Task 4 ✅

**Placeholder scan：** 無 TBD/TODO；每個 code step 均含實際程式碼。

**Type consistency：** `serialize_expense(e, storage, with_main=False)`、`schedule_ocr(expense_id, image_bytes, content_type)`、`traffic_light(is_handwritten, confidence, amount_parse_ok, is_modified, green_threshold)`、`coerce_amount(value)->(float|None,bool)`、`process_upload_image(raw,ct)->(main,thumb)` 跨 Task 一致。OCRResult 鍵在 Task 5/6/7 一致。

**安全修正（相對 spec）：** 路由前綴 `/api/v1/`→`/expenses`（避開 gate 豁免）；sw.js 對應加 `/expenses` network-first。已於 Global Constraints 與 Task 11 註記。
