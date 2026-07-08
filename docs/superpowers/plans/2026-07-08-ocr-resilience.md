# OCR 韌性 + 失敗軌跡 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 OCR 對 Gemini 的 429/503/5xx/timeout 自動重試+退避、每次嘗試寫 `ocr_log` 供事後反查、徹底失敗的單以 `ocr_failed` 旗標標記並在暫存區提示員工手動確認/重新辨識。

**Architecture:** 錯誤分類（`app/ocr/errors.py`）+ 共用重試包裝（`app/ocr/retry.py`，所有 provider 共用、退避 sleep 可注入）+ provider 改為單次嘗試拋分類例外；task 層（`_run_ocr`）用重試結果寫 `ocr_log`、跑新狀態機（success→draft／fatal→draft+ocr_failed／exhausted→留 pending 待背景重排或達輪數上限收斂）；背景重排沿用 list-pull 的 `reconcile_stale`（從 R2 重抓原圖，需給 storage 加 `get()`），不用 cron；暫存區 UI 標示失敗並提供手動「重新辨識」。

**Tech Stack:** Flask / Flask-SQLAlchemy 2.0 / Flask-Migrate(alembic) / pytest；OCR 走 stdlib `urllib`；前端 ESM + `node --test`。系統 python3.12，無 venv。

依據 spec：`docs/superpowers/specs/2026-07-08-ocr-resilience-design.md`。

## Global Constraints

- 不新增 Python 依賴（重試/退避用 stdlib `time`/`random`；退避 `sleep` 需可注入，測試傳 no-op、絕不真的等）。
- 時間存 UTC：`datetime.now(timezone.utc)`；DateTime 欄位 `db.DateTime(timezone=True)`。
- **Migration 加 NOT NULL 欄位到既有 `expenses` 表**：Boolean 用 `server_default=sa.false()`（**不可**用 `sa.text('0')`——Postgres `BOOLEAN NOT NULL DEFAULT 0` 會炸、SQLite 測不到）；Integer 用 `server_default=sa.text('0')`。SQLite 加 FK 欄位/表用 `batch_alter_table`、具名 FK 約束。
- 前端不輪詢：背景重排靠 `reconcile_stale`（暫存區列表被拉時就地收斂），不加 cron；手動「重新辨識」是使用者點擊。
- 影像不落地：重抓 R2 原圖進記憶體 OCR 後即丟；不寫伺服器檔案系統。
- `OCRProvider` 抽象不得知道 `ocr_log`/DB：DB 寫入只在 task 層。
- 沿用回傳慣例 `jsonify(status="ok"/"error", ...)`；owner-scope 沿用 `_load_owned`。
- 每次改前端 JS 必 bump `app/static/sw.js` 的 `CACHE_NAME`。
- 測試：後端 `python3 -m pytest -q`；前端純邏輯 `node --test tests/js/*.mjs`。
- 從 master（稽核 merge 後）或現行 branch 開 branch `feat/ocr-resilience`。

---

### Task 1: 錯誤分類（errors.py）

**Files:**
- Create: `app/ocr/errors.py`
- Test: `tests/test_ocr_errors.py`

**Interfaces:**
- Produces:
  - `class OcrError(Exception)`：`.error_type: str`、`.http_status: int|None`
  - `class OcrRetryableError(OcrError)`、`class OcrFatalError(OcrError)`
  - `classify_exception(exc) -> OcrRetryableError | OcrFatalError`

- [ ] **Step 1: 寫失敗測試**

`tests/test_ocr_errors.py`：
```python
import json
import socket
import urllib.error
from app.ocr.errors import OcrRetryableError, OcrFatalError, classify_exception


def _http(code):
    return urllib.error.HTTPError("u", code, "msg", {}, None)


def test_http_429_retryable_rate_limit():
    e = classify_exception(_http(429))
    assert isinstance(e, OcrRetryableError)
    assert e.error_type == "rate_limit" and e.http_status == 429


def test_http_503_retryable_overloaded():
    e = classify_exception(_http(503))
    assert isinstance(e, OcrRetryableError) and e.error_type == "overloaded"


def test_http_500_retryable_server():
    assert isinstance(classify_exception(_http(500)), OcrRetryableError)


def test_http_400_fatal_bad_request():
    e = classify_exception(_http(400))
    assert isinstance(e, OcrFatalError) and e.error_type == "bad_request"


def test_urlerror_retryable():
    assert isinstance(classify_exception(urllib.error.URLError("boom")), OcrRetryableError)


def test_timeout_retryable():
    e = classify_exception(socket.timeout())
    assert isinstance(e, OcrRetryableError) and e.error_type == "timeout"


def test_jsondecode_fatal_parse():
    e = classify_exception(json.JSONDecodeError("x", "y", 0))
    assert isinstance(e, OcrFatalError) and e.error_type == "parse"


def test_valueerror_fatal_schema():
    e = classify_exception(ValueError("non-dict"))
    assert isinstance(e, OcrFatalError) and e.error_type == "schema"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_ocr_errors.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.ocr.errors'`）

- [ ] **Step 3: 實作 errors.py**

`app/ocr/errors.py`：
```python
import json
import socket
import urllib.error

_RETRYABLE_STATUS = {429: "rate_limit", 500: "server", 502: "server",
                     503: "overloaded", 504: "server"}


class OcrError(Exception):
    def __init__(self, error_type, http_status=None):
        super().__init__(f"{error_type} (http={http_status})")
        self.error_type = error_type
        self.http_status = http_status


class OcrRetryableError(OcrError):
    pass


class OcrFatalError(OcrError):
    pass


def classify_exception(exc):
    """把一次 Gemini 嘗試的例外分類成 retryable / fatal。"""
    # HTTPError 是 URLError 子類，必須先判
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        if code in _RETRYABLE_STATUS:
            return OcrRetryableError(_RETRYABLE_STATUS[code], code)
        if code == 400:
            return OcrFatalError("bad_request", code)
        return OcrFatalError("other", code)
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return OcrRetryableError("timeout", None)
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return OcrRetryableError("timeout", None)
        return OcrRetryableError("server", None)
    if isinstance(exc, json.JSONDecodeError):
        return OcrFatalError("parse", None)
    if isinstance(exc, ValueError):
        return OcrFatalError("schema", None)
    return OcrFatalError("other", None)
```
（注意：`json.JSONDecodeError` 是 `ValueError` 子類，必須先判 `JSONDecodeError`。）

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_ocr_errors.py -q`
Expected: PASS

- [ ] **Step 5: commit**

```bash
git add app/ocr/errors.py tests/test_ocr_errors.py
git commit -m "feat(ocr): 錯誤分類 classify_exception(retryable/fatal)"
```

---

### Task 2: 重試+退避包裝（retry.py）

**Files:**
- Create: `app/ocr/retry.py`
- Test: `tests/test_ocr_retry.py`

**Interfaces:**
- Consumes: `app.ocr.errors.OcrRetryableError`, `OcrFatalError`
- Produces:
  - `recognize_with_retry(provider, image_bytes, content_type, cfg, sleep=time.sleep, rand=random.random, clock=time.monotonic) -> dict`
  - 回傳 `{"fields": dict|None, "final_outcome": "success"|"fatal"|"exhausted", "attempts": [ {"attempt":int, "outcome":str, "error_type":str|None, "http_status":int|None, "duration_ms":int} ]}`
  - `cfg.get("GEMINI_MAX_RETRIES", 3)`、`cfg.get("GEMINI_RETRY_BASE", 0.5)`

- [ ] **Step 1: 寫失敗測試**

`tests/test_ocr_retry.py`：
```python
from app.ocr.errors import OcrRetryableError, OcrFatalError
from app.ocr.retry import recognize_with_retry


class _FakeProvider:
    """依序丟出 side_effects：例外就 raise，dict 就 return。"""
    def __init__(self, side_effects):
        self._se = list(side_effects)
        self.calls = 0

    def recognize(self, image_bytes, content_type):
        self.calls += 1
        item = self._se.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


_CFG = {"GEMINI_MAX_RETRIES": 3, "GEMINI_RETRY_BASE": 0.5}
_NO_SLEEP = lambda *_a, **_k: None
_FIELDS = {"summary": "x", "amount": 100}


def test_success_first_try():
    p = _FakeProvider([_FIELDS])
    r = recognize_with_retry(p, b"img", "image/jpeg", _CFG, sleep=_NO_SLEEP)
    assert r["final_outcome"] == "success" and r["fields"] == _FIELDS
    assert len(r["attempts"]) == 1 and r["attempts"][0]["outcome"] == "success"
    assert p.calls == 1


def test_retry_then_success():
    p = _FakeProvider([OcrRetryableError("rate_limit", 429), _FIELDS])
    r = recognize_with_retry(p, b"img", "image/jpeg", _CFG, sleep=_NO_SLEEP)
    assert r["final_outcome"] == "success"
    assert len(r["attempts"]) == 2
    assert r["attempts"][0]["outcome"] == "retryable" and r["attempts"][0]["error_type"] == "rate_limit"
    assert p.calls == 2


def test_exhausted_all_retryable():
    p = _FakeProvider([OcrRetryableError("overloaded", 503)] * 3)
    r = recognize_with_retry(p, b"img", "image/jpeg", _CFG, sleep=_NO_SLEEP)
    assert r["final_outcome"] == "exhausted" and r["fields"] is None
    assert len(r["attempts"]) == 3 and p.calls == 3


def test_fatal_no_retry():
    p = _FakeProvider([OcrFatalError("bad_request", 400), _FIELDS])
    r = recognize_with_retry(p, b"img", "image/jpeg", _CFG, sleep=_NO_SLEEP)
    assert r["final_outcome"] == "fatal" and r["fields"] is None
    assert len(r["attempts"]) == 1 and p.calls == 1  # 不重試


def test_sleep_called_between_retries():
    slept = []
    p = _FakeProvider([OcrRetryableError("server", 500), _FIELDS])
    recognize_with_retry(p, b"img", "image/jpeg", _CFG,
                         sleep=lambda s: slept.append(s), rand=lambda: 0.0)
    assert slept == [0.5]  # base * 2**0 + 0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_ocr_retry.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.ocr.retry'`）

- [ ] **Step 3: 實作 retry.py**

`app/ocr/retry.py`：
```python
import random
import time

from app.ocr.errors import OcrRetryableError, OcrFatalError


def recognize_with_retry(provider, image_bytes, content_type, cfg,
                         sleep=time.sleep, rand=random.random, clock=time.monotonic):
    """對 provider.recognize 做有限次重試。retryable 才退避重試，fatal 立即停。
    退避 = base * 2**(attempt-1) + rand()*base（sleep 可注入，測試傳 no-op）。"""
    max_retries = cfg.get("GEMINI_MAX_RETRIES", 3)
    base = cfg.get("GEMINI_RETRY_BASE", 0.5)
    attempts = []
    for attempt in range(1, max_retries + 1):
        start = clock()

        def _dur():
            return int((clock() - start) * 1000)

        try:
            fields = provider.recognize(image_bytes, content_type)
        except OcrFatalError as ex:
            attempts.append({"attempt": attempt, "outcome": "fatal",
                             "error_type": ex.error_type, "http_status": ex.http_status,
                             "duration_ms": _dur()})
            return {"fields": None, "final_outcome": "fatal", "attempts": attempts}
        except OcrRetryableError as ex:
            attempts.append({"attempt": attempt, "outcome": "retryable",
                             "error_type": ex.error_type, "http_status": ex.http_status,
                             "duration_ms": _dur()})
            if attempt < max_retries:
                sleep(base * (2 ** (attempt - 1)) + rand() * base)
            continue
        attempts.append({"attempt": attempt, "outcome": "success",
                         "error_type": None, "http_status": None, "duration_ms": _dur()})
        return {"fields": fields, "final_outcome": "success", "attempts": attempts}
    return {"fields": None, "final_outcome": "exhausted", "attempts": attempts}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_ocr_retry.py -q`
Expected: PASS

- [ ] **Step 5: commit**

```bash
git add app/ocr/retry.py tests/test_ocr_retry.py
git commit -m "feat(ocr): recognize_with_retry 重試+退避(sleep 可注入)"
```

---

### Task 3: Gemini provider 改單次嘗試、拋分類例外

**Files:**
- Modify: `app/ocr/gemini.py`（`recognize`）
- Test: `tests/test_ocr_gemini.py`

**Interfaces:**
- Consumes: `app.ocr.errors.classify_exception`
- Produces: `GeminiProvider.recognize` 單次嘗試；成功回 fields dict；失敗**拋** `OcrRetryableError`/`OcrFatalError`（不再自己吞成 empty）。`MockProvider` 不變。

**注意（回歸風險）**：舊 `recognize` 失敗回 `empty` dict、舊 `_run_ocr` 靠 `if not result` 判失敗。改成拋例外後，`_run_ocr` 於 Task 6 改寫。若既有測試（如 `tests/test_ocr_*` 或 capture 測試）直接斷言「recognize 失敗回 empty」，需一併改為斷言拋例外。先掃 `grep -rn "recognize" tests/` 找出受影響測試。

- [ ] **Step 1: 寫失敗測試**

`tests/test_ocr_gemini.py`：
```python
import json
import urllib.error
import pytest
from app.ocr.errors import OcrRetryableError, OcrFatalError


def _provider(app):
    with app.app_context():
        from app.ocr.gemini import GeminiProvider
        return GeminiProvider({"GEMINI_MODEL": "m", "GEMINI_API_KEY": "k"})


def _resp(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_success_returns_fields(app, monkeypatch):
    p = _provider(app)
    monkeypatch.setattr(p, "_call_api",
                        lambda payload: _resp(json.dumps({"summary": "全家", "amount": 1290})))
    with app.app_context():
        out = p.recognize(b"img", "image/jpeg")
    assert out["summary"] == "全家" and out["amount"] == 1290


def test_http_429_raises_retryable(app, monkeypatch):
    p = _provider(app)
    def boom(payload):
        raise urllib.error.HTTPError("u", 429, "rate", {}, None)
    monkeypatch.setattr(p, "_call_api", boom)
    with app.app_context(), pytest.raises(OcrRetryableError):
        p.recognize(b"img", "image/jpeg")


def test_non_dict_raises_fatal(app, monkeypatch):
    p = _provider(app)
    monkeypatch.setattr(p, "_call_api", lambda payload: _resp(json.dumps([1, 2, 3])))
    with app.app_context(), pytest.raises(OcrFatalError):
        p.recognize(b"img", "image/jpeg")
```
（`_load_categories` 會查 DB，測試的 `app` fixture 需已 `db.create_all()`；沿用既有 conftest 的 `app` fixture。若 `_load_categories` 在空 DB 回空 list 即可，不影響本測試。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_ocr_gemini.py -q`
Expected: FAIL（目前 recognize 吞例外回 empty，不會 raise）

- [ ] **Step 3: 改 recognize**

`app/ocr/gemini.py`：檔頭 import 改為含：
```python
import base64
import json
import socket
import urllib.error
import urllib.request

from app.models import Category
from app.ocr.provider import OCRProvider
from app.ocr.prompt import build_prompt, build_response_schema
from app.ocr.errors import classify_exception
```
把 `recognize` 改成（移除 `logger`/`empty`/吞例外，改拋分類例外）：
```python
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
                "thinkingConfig": {"thinkingBudget": self.thinking_budget},
            },
        }
        try:
            resp = self._call_api(payload)
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            raise classify_exception(e) from e
        try:
            text = resp["candidates"][0]["content"]["parts"][0]["text"]
            obj = json.loads(text)
            if not isinstance(obj, dict):
                raise ValueError("non-dict response")
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError) as e:
            raise classify_exception(e) from e
        return {
            "summary": obj.get("summary"),
            "category_id": obj.get("category_id"),
            "amount": obj.get("amount"),
            "confidence": obj.get("confidence"),
            "is_handwritten": obj.get("is_handwritten"),
            "raw": obj,
        }
```
（`urllib.error.HTTPError` 是 `URLError` 子類，`except urllib.error.URLError` 會接到，`classify_exception` 內先判 HTTPError。可移除舊的 `import logging` / `logger` 若不再使用。）

- [ ] **Step 4: 跑測試 + 掃回歸**

Run:
```bash
python3 -m pytest tests/test_ocr_gemini.py -q
grep -rn "recognize" tests/    # 找舊「失敗回 empty」斷言，若有則改成 raises
python3 -m pytest -q
```
Expected: 新測試 PASS；全套 PASS（若有舊測試斷言舊行為，於本 task 內改掉並記在報告）。

- [ ] **Step 5: commit**

```bash
git add app/ocr/gemini.py tests/test_ocr_gemini.py
git commit -m "feat(ocr): Gemini recognize 單次嘗試改拋分類例外(不再吞成 empty)"
```

---

### Task 4: OcrLog model + expenses 失敗欄位 + migration

**Files:**
- Create: `app/models/ocr_log.py`
- Modify: `app/models/expense.py`（加 3 欄）
- Modify: `app/models/__init__.py`（export `OcrLog`）
- Create: migration（autogenerate）
- Test: `tests/test_ocr_log_model.py`

**Interfaces:**
- Produces:
  - `OcrLog(id, expense_id, store_id, attempt, outcome, error_type, http_status, duration_ms, ts)`
  - `Expense.ocr_attempts:int(default 0)`、`Expense.ocr_failed:bool(default False)`、`Expense.ocr_last_error:str|None`

- [ ] **Step 1: 寫失敗測試**

`tests/test_ocr_log_model.py`：
```python
from datetime import datetime, timezone
from app.extensions import db
from app.models import Store, User, Expense, OcrLog


def test_ocr_log_and_expense_fields(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="e", role="employee", store_id=s.id); u.set_password("1234")
        db.session.add(u); db.session.commit()
        e = Expense(store_id=s.id, created_by=u.id, status="pending_ocr",
                    created_at=datetime.now(timezone.utc))
        db.session.add(e); db.session.commit()

        # 新欄位預設
        assert db.session.get(Expense, e.id).ocr_attempts == 0
        assert db.session.get(Expense, e.id).ocr_failed is False

        e.ocr_attempts = 2; e.ocr_failed = True; e.ocr_last_error = "overloaded"
        log = OcrLog(expense_id=e.id, store_id=s.id, attempt=1, outcome="retryable",
                     error_type="overloaded", http_status=503, duration_ms=120,
                     ts=datetime.now(timezone.utc))
        db.session.add(log); db.session.commit()

        assert OcrLog.query.filter_by(expense_id=e.id, outcome="retryable").count() == 1
        assert db.session.get(Expense, e.id).ocr_last_error == "overloaded"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_ocr_log_model.py -q`
Expected: FAIL（`ImportError: cannot import name 'OcrLog'`）

- [ ] **Step 3: 建 OcrLog model**

`app/models/ocr_log.py`：
```python
from app.extensions import db


class OcrLog(db.Model):
    __tablename__ = "ocr_log"

    id = db.Column(db.Integer, primary_key=True)
    expense_id = db.Column(db.Integer, db.ForeignKey("expenses.id"), nullable=False, index=True)
    store_id = db.Column(db.Integer, db.ForeignKey("stores.id"), nullable=False, index=True)
    attempt = db.Column(db.Integer, nullable=False)
    outcome = db.Column(db.String(16), nullable=False)      # success | retryable | fatal
    error_type = db.Column(db.String(16), nullable=True)    # rate_limit | overloaded | server | timeout | parse | schema | bad_request | other
    http_status = db.Column(db.Integer, nullable=True)
    duration_ms = db.Column(db.Integer, nullable=True)
    ts = db.Column(db.DateTime(timezone=True), nullable=False)
```

- [ ] **Step 4: 加 Expense 欄位**

`app/models/expense.py`：在 OCR 相關欄位附近加：
```python
    ocr_attempts = db.Column(db.Integer, nullable=False, default=0)
    ocr_failed = db.Column(db.Boolean, nullable=False, default=False)
    ocr_last_error = db.Column(db.String(32), nullable=True)
```

- [ ] **Step 5: export**

`app/models/__init__.py`：於 `from app.models.audit_log import AuditLog` 之後加 `from app.models.ocr_log import OcrLog`，並把 `"OcrLog"` 加入 `__all__`。

- [ ] **Step 6: 產 migration + 修 default**

Run:
```bash
FLASK_APP=wsgi.py python3 -m flask db migrate -m "ocr: ocr_log table + expenses ocr_failed fields"
```
打開新產生的 migration，確認 / 手改：
- `op.create_table("ocr_log", ...)` + 兩個 index（expense_id、store_id）。
- `expenses` 加欄用 `with op.batch_alter_table("expenses") as batch_op:` 包住（SQLite）。
- **`ocr_failed` 必須 `server_default=sa.false()`**（不可 `sa.text('0')`）；`ocr_attempts` 用 `server_default=sa.text('0')`（Integer 沒問題）：
```python
    with op.batch_alter_table("expenses") as batch_op:
        batch_op.add_column(sa.Column("ocr_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")))
        batch_op.add_column(sa.Column("ocr_failed", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("ocr_last_error", sa.String(length=32), nullable=True))
```

- [ ] **Step 7: upgrade + 跑測試 + round-trip 驗證**

Run:
```bash
FLASK_APP=wsgi.py python3 -m flask db upgrade
FLASK_APP=wsgi.py python3 -m flask db downgrade
FLASK_APP=wsgi.py python3 -m flask db upgrade
python3 -m pytest tests/test_ocr_log_model.py -q
```
Expected: upgrade/downgrade/upgrade 皆成功；測試 PASS。

- [ ] **Step 8: 全套回歸 + commit**

```bash
python3 -m pytest -q
git add app/models/ migrations/versions/ tests/test_ocr_log_model.py
git commit -m "feat(ocr): OcrLog model + expenses ocr_failed/ocr_attempts/ocr_last_error + migration"
```

---

### Task 5: storage 加 get()

**Files:**
- Modify: `app/storage/r2.py`（`MockStorage.get`、`R2Storage.get`）
- Test: `tests/test_storage_get.py`

**Interfaces:**
- Produces: `get(key) -> bytes | None`（Mock：無此 key 回 None；R2：回物件 bytes）

- [ ] **Step 1: 寫失敗測試**

`tests/test_storage_get.py`：
```python
from app.storage.r2 import MockStorage


def test_mock_put_get_roundtrip():
    s = MockStorage()
    s.put("k1", b"hello", "image/jpeg")
    assert s.get("k1") == b"hello"


def test_mock_get_missing_returns_none():
    assert MockStorage().get("nope") is None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_storage_get.py -q`
Expected: FAIL（`AttributeError: 'MockStorage' object has no attribute 'get'`）

- [ ] **Step 3: 實作 get**

`app/storage/r2.py`：`MockStorage` 加：
```python
    def get(self, key):
        obj = self.objects.get(key)
        return obj["data"] if obj else None
```
`R2Storage` 加：
```python
    def get(self, key):
        resp = self._client.get_object(Bucket=self.bucket, Key=key)
        return resp["Body"].read()
```

- [ ] **Step 4: 跑測試 + commit**

Run: `python3 -m pytest tests/test_storage_get.py -q`
Expected: PASS
```bash
git add app/storage/r2.py tests/test_storage_get.py
git commit -m "feat(storage): 加 get(key) 供背景重排/重新辨識重抓原圖"
```

---

### Task 6: _run_ocr 改寫（重試結果 → ocr_log + 新狀態機）

**Files:**
- Modify: `app/expenses/tasks.py`（`_run_ocr`，加 `_write_ocr_logs`/`_last_error` helper）
- Test: `tests/test_ocr_run.py`

**Interfaces:**
- Consumes: `app.ocr.retry.recognize_with_retry`、`app.models.OcrLog`、`app.ocr.provider.get_provider/coerce_amount`
- Produces: `_run_ocr(app, expense_id, image_bytes, content_type)`：跑重試、每 attempt 寫 `ocr_log`、依 `final_outcome` 設狀態（success→draft；fatal→draft+ocr_failed；exhausted 未達 `OCR_MAX_ROUNDS`→留 pending_ocr、達上限→draft+ocr_failed）。`schedule_ocr` 不變。

- [ ] **Step 1: 寫失敗測試**

`tests/test_ocr_run.py`（用 monkeypatch 換掉 `recognize_with_retry`，`EXPENSE_OCR_SYNC` 讓 schedule 同步）：
```python
from datetime import datetime, timezone
from app.extensions import db
from app.models import Store, User, Expense, OcrLog
import app.expenses.tasks as tasks


def _mk(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="e", role="employee", store_id=s.id); u.set_password("1234")
        db.session.add(u); db.session.commit()
        e = Expense(store_id=s.id, created_by=u.id, status="pending_ocr",
                    created_at=datetime.now(timezone.utc))
        db.session.add(e); db.session.commit()
        return e.id


def _patch(monkeypatch, result):
    monkeypatch.setattr(tasks, "recognize_with_retry",
                        lambda *a, **k: result)


def test_success_sets_draft_and_logs(app, monkeypatch):
    eid = _mk(app)
    _patch(monkeypatch, {"fields": {"summary": "全家", "amount": 1290, "category_id": None,
                                    "confidence": 0.9, "is_handwritten": False, "raw": {}},
                         "final_outcome": "success",
                         "attempts": [{"attempt": 1, "outcome": "success", "error_type": None,
                                       "http_status": None, "duration_ms": 50}]})
    tasks._run_ocr(app, eid, b"img", "image/jpeg")
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "draft" and e.ocr_failed is False and float(e.amount) == 1290.0
        assert e.ocr_attempts == 1
        assert OcrLog.query.filter_by(expense_id=eid, outcome="success").count() == 1


def test_fatal_sets_draft_failed(app, monkeypatch):
    eid = _mk(app)
    _patch(monkeypatch, {"fields": None, "final_outcome": "fatal",
                         "attempts": [{"attempt": 1, "outcome": "fatal", "error_type": "schema",
                                       "http_status": None, "duration_ms": 30}]})
    tasks._run_ocr(app, eid, b"img", "image/jpeg")
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "draft" and e.ocr_failed is True and e.ocr_last_error == "schema"


def test_exhausted_below_limit_stays_pending(app, monkeypatch):
    eid = _mk(app)
    app.config["OCR_MAX_ROUNDS"] = 3
    _patch(monkeypatch, {"fields": None, "final_outcome": "exhausted",
                         "attempts": [{"attempt": 1, "outcome": "retryable", "error_type": "overloaded",
                                       "http_status": 503, "duration_ms": 40}]})
    tasks._run_ocr(app, eid, b"img", "image/jpeg")
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "pending_ocr" and e.ocr_failed is False  # 留給背景重排
        assert e.ocr_attempts == 1 and e.ocr_last_error == "overloaded"


def test_exhausted_at_limit_marks_failed(app, monkeypatch):
    eid = _mk(app)
    app.config["OCR_MAX_ROUNDS"] = 1   # 第一輪就達上限
    _patch(monkeypatch, {"fields": None, "final_outcome": "exhausted",
                         "attempts": [{"attempt": 1, "outcome": "retryable", "error_type": "rate_limit",
                                       "http_status": 429, "duration_ms": 40}]})
    tasks._run_ocr(app, eid, b"img", "image/jpeg")
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "draft" and e.ocr_failed is True
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_ocr_run.py -q`
Expected: FAIL（舊 `_run_ocr` 無 ocr_log、無 ocr_failed 邏輯）

- [ ] **Step 3: 改寫 _run_ocr**

`app/expenses/tasks.py`：檔頭 import 加：
```python
from app.models import Expense, OcrLog
from app.ocr.retry import recognize_with_retry
```
（`from app.models import Expense` 原本就有，改為含 OcrLog。）加 helper 與改寫 `_run_ocr`：
```python
def _last_error(attempts):
    return attempts[-1]["error_type"] if attempts else None


def _write_ocr_logs(expense, attempts):
    now = datetime.now(timezone.utc)
    for a in attempts:
        db.session.add(OcrLog(
            expense_id=expense.id, store_id=expense.store_id,
            attempt=a["attempt"], outcome=a["outcome"], error_type=a["error_type"],
            http_status=a["http_status"], duration_ms=a["duration_ms"], ts=now))


def _run_ocr(app, expense_id, image_bytes, content_type):
    with app.app_context():
        e = db.session.get(Expense, expense_id)
        if e is None or e.status != "pending_ocr":
            return
        e.ocr_attempts += 1
        result = recognize_with_retry(get_provider(), image_bytes, content_type, current_app.config)
        _write_ocr_logs(e, result["attempts"])
        outcome = result["final_outcome"]
        if outcome == "success":
            f = result["fields"]
            amount, ok = coerce_amount(f.get("amount"))
            e.summary = f.get("summary")
            e.category_id = _valid_category_id(f.get("category_id"))
            e.amount = amount
            e.amount_parse_ok = ok
            e.ocr_confidence = f.get("confidence")
            e.ocr_is_handwritten = f.get("is_handwritten")
            e.ocr_raw = f.get("raw")
            e.status = "draft"
            e.ocr_failed = False
        elif outcome == "fatal":
            e.status = "draft"; e.ocr_failed = True; e.amount_parse_ok = False
            e.ocr_last_error = _last_error(result["attempts"])
        else:  # exhausted
            e.ocr_last_error = _last_error(result["attempts"])
            if e.ocr_attempts >= current_app.config.get("OCR_MAX_ROUNDS", 3):
                e.status = "draft"; e.ocr_failed = True; e.amount_parse_ok = False
            # 未達上限 → 維持 pending_ocr，待 reconcile_stale 重排
        db.session.commit()
```

- [ ] **Step 4: 跑測試 + 回歸**

Run:
```bash
python3 -m pytest tests/test_ocr_run.py -q
python3 -m pytest -q
```
Expected: PASS（既有 capture 測試走 MockProvider → success → draft，行為不變）。若有既有測試斷言舊「失敗→draft」的具體路徑而破，於本 task 調整並記報告。

- [ ] **Step 5: commit**

```bash
git add app/expenses/tasks.py tests/test_ocr_run.py
git commit -m "feat(ocr): _run_ocr 用重試結果寫 ocr_log + 新失敗狀態機"
```

---

### Task 7: reconcile_stale 背景有限次重排（從 R2 重抓）

**Files:**
- Modify: `app/expenses/tasks.py`（`reconcile_stale`）
- Test: `tests/test_ocr_reconcile.py`

**Interfaces:**
- Consumes: `app.storage.r2.get_storage`（`get`）、`schedule_ocr`
- Produces: `reconcile_stale(user_id)`：逾時 pending_ocr 且 `ocr_attempts < OCR_MAX_ROUNDS` 且有 `image_key` → 從 R2 重抓 `schedule_ocr` 重跑；否則收斂成 `draft` + `ocr_failed=True`。

- [ ] **Step 1: 寫失敗測試**

`tests/test_ocr_reconcile.py`：
```python
from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models import Store, User, Expense
from app.storage.r2 import get_storage
import app.expenses.tasks as tasks


def _stale_expense(app, attempts, image_key="k1"):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="e", role="employee", store_id=s.id); u.set_password("1234")
        db.session.add(u); db.session.commit()
        old = datetime.now(timezone.utc) - timedelta(seconds=9999)
        e = Expense(store_id=s.id, created_by=u.id, status="pending_ocr",
                    created_at=old, ocr_attempts=attempts, image_key=image_key)
        db.session.add(e); db.session.commit()
        return u.id, e.id


def test_below_limit_reschedules(app, monkeypatch):
    app.config["OCR_MAX_ROUNDS"] = 3
    uid, eid = _stale_expense(app, attempts=1)
    with app.app_context():
        get_storage().put("k1", b"img", "image/jpeg")
    called = []
    monkeypatch.setattr(tasks, "schedule_ocr", lambda *a, **k: called.append(a))
    with app.app_context():
        tasks.reconcile_stale(uid)
        e = db.session.get(Expense, eid)
        assert e.status == "pending_ocr"    # 重排、不收斂
    assert len(called) == 1


def test_at_limit_converges_failed(app, monkeypatch):
    app.config["OCR_MAX_ROUNDS"] = 3
    uid, eid = _stale_expense(app, attempts=3)
    monkeypatch.setattr(tasks, "schedule_ocr", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不該重排")))
    with app.app_context():
        tasks.reconcile_stale(uid)
        e = db.session.get(Expense, eid)
        assert e.status == "draft" and e.ocr_failed is True


def test_missing_image_converges_failed(app, monkeypatch):
    app.config["OCR_MAX_ROUNDS"] = 3
    uid, eid = _stale_expense(app, attempts=0, image_key="gone")  # R2 沒這 key
    monkeypatch.setattr(tasks, "schedule_ocr", lambda *a, **k: called.append(a))
    called = []
    with app.app_context():
        tasks.reconcile_stale(uid)
        e = db.session.get(Expense, eid)
        assert e.status == "draft" and e.ocr_failed is True
    assert called == []
```
（測試用 MockStorage singleton；`test_missing_image` 的 `get("gone")` 回 None。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_ocr_reconcile.py -q`
Expected: FAIL（舊 reconcile 直接把 pending_ocr → draft，不重排）

- [ ] **Step 3: 改寫 reconcile_stale**

`app/expenses/tasks.py`：檔頭 import 加 `from app.storage.r2 import get_storage`。改寫：
```python
def reconcile_stale(user_id):
    """暫存區列表拉取時就地收斂：逾時仍 pending_ocr 的單，
    未達重排上限且原圖還在 → 從 R2 重抓再跑一輪 OCR；否則收斂成 draft+ocr_failed。"""
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=current_app.config.get("OCR_STALE_SECONDS", 120))
    max_rounds = current_app.config.get("OCR_MAX_ROUNDS", 3)
    stale = (Expense.query
             .filter(Expense.created_by == user_id,
                     Expense.status == "pending_ocr",
                     Expense.created_at < cutoff).all())
    storage = get_storage()
    changed = False
    for e in stale:
        image_bytes = None
        if e.ocr_attempts < max_rounds and e.image_key:
            try:
                image_bytes = storage.get(e.image_key)
            except Exception:
                image_bytes = None
        if image_bytes:
            schedule_ocr(e.id, image_bytes, "image/jpeg")   # 跑新一輪（含重試）
        else:
            e.status = "draft"; e.ocr_failed = True; e.amount_parse_ok = False
            e.ocr_last_error = e.ocr_last_error or "gave_up"
            changed = True
    if changed:
        db.session.commit()
```

- [ ] **Step 4: 跑測試 + 回歸 + commit**

Run:
```bash
python3 -m pytest tests/test_ocr_reconcile.py -q && python3 -m pytest -q
```
Expected: PASS
```bash
git add app/expenses/tasks.py tests/test_ocr_reconcile.py
git commit -m "feat(ocr): reconcile_stale 有限次背景重排(從 R2 重抓)、達上限收斂 failed"
```

---

### Task 8: serialize 回失敗旗標 + POST /expenses/<id>/reocr

**Files:**
- Modify: `app/expenses/serialize.py`
- Modify: `app/expenses/routes.py`（新 `reocr` 端點）
- Test: `tests/test_expense_reocr.py`

**Interfaces:**
- Consumes: `_load_owned`、`get_storage().get`、`schedule_ocr`
- Produces:
  - `serialize_expense` 多回 `ocr_failed`、`ocr_last_error`
  - `POST /expenses/<int:eid>/reocr`：owner-scope；僅 `status=="draft" 且 ocr_failed` 可重辨（否則 409）；無 image_key/抓不到圖 → 400；重置 `ocr_attempts=0/ocr_failed=False/ocr_last_error=None`、`status="pending_ocr"`、`schedule_ocr`；回 `{status:"ok"}` 202

- [ ] **Step 1: 寫失敗測試**

`tests/test_expense_reocr.py`（沿用既有 employee client pattern，參考 `tests/test_expense_edit_submit.py`）：
```python
import time
from datetime import datetime, timezone
from app.extensions import db
from app.models import Store, User, Device, Expense
from app.storage.r2 import get_storage
import app.expenses.tasks as tasks


def _seed(app, ocr_failed=True, image_key="k1"):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="e", role="employee", store_id=s.id); u.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add_all([u, dev]); db.session.commit()
        e = Expense(store_id=s.id, created_by=u.id, status="draft",
                    created_at=datetime.now(timezone.utc), ocr_failed=ocr_failed,
                    image_key=image_key)
        db.session.add(e); db.session.commit()
        return u.id, e.id


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_reocr_resets_and_schedules(app, monkeypatch):
    uid, eid = _seed(app)
    with app.app_context():
        get_storage().put("k1", b"img", "image/jpeg")
    called = []
    monkeypatch.setattr("app.expenses.routes.schedule_ocr", lambda *a, **k: called.append(a))
    r = _client(app, uid).post(f"/expenses/{eid}/reocr")
    assert r.status_code == 202
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "pending_ocr" and e.ocr_failed is False and e.ocr_attempts == 0
    assert len(called) == 1


def test_reocr_non_failed_409(app):
    uid, eid = _seed(app, ocr_failed=False)
    assert _client(app, uid).post(f"/expenses/{eid}/reocr").status_code == 409


def test_reocr_missing_image_400(app):
    uid, eid = _seed(app, image_key="gone")
    assert _client(app, uid).post(f"/expenses/{eid}/reocr").status_code == 400
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_expense_reocr.py -q`
Expected: FAIL（404，端點不存在）

- [ ] **Step 3: serialize 加欄位**

`app/expenses/serialize.py`：在回傳 dict `d` 內（`thumb_url` 那行附近）加：
```python
        "ocr_failed": e.ocr_failed,
        "ocr_last_error": e.ocr_last_error,
```

- [ ] **Step 4: 加 reocr 端點**

`app/expenses/routes.py`：確認檔頭已 import `get_storage`、`schedule_ocr`（capture 已用）。加端點（放 `discard`/`no_receipt` 附近）：
```python
@expense_bp.post("/<int:eid>/reocr")
def reocr(eid):
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    e, err = _load_owned(eid, user)
    if err:
        return err
    if e.status != "draft" or not e.ocr_failed:
        return jsonify(status="error", message="not re-ocr-able"), 409
    if not e.image_key:
        return jsonify(status="error", message="no image"), 400
    try:
        image_bytes = get_storage().get(e.image_key)
    except Exception:
        image_bytes = None
    if not image_bytes:
        return jsonify(status="error", message="image unavailable"), 400
    e.status = "pending_ocr"
    e.ocr_failed = False
    e.ocr_attempts = 0
    e.ocr_last_error = None
    db.session.commit()
    schedule_ocr(e.id, image_bytes, "image/jpeg")
    return jsonify(status="ok"), 202
```

- [ ] **Step 5: 跑測試 + 回歸 + commit**

Run:
```bash
python3 -m pytest tests/test_expense_reocr.py -q && python3 -m pytest -q
```
Expected: PASS
```bash
git add app/expenses/serialize.py app/expenses/routes.py tests/test_expense_reocr.py
git commit -m "feat(ocr): serialize 回 ocr_failed + POST /expenses/<id>/reocr 手動重新辨識"
```

---

### Task 9: 暫存區 UI — OCR 失敗提示 + 重新辨識鈕

**Files:**
- Modify: `app/static/js/expenses_api.js`（加 `reocrExpense`）
- Modify: `app/static/js/pending.js`（失敗列標示 + 重新辨識鈕）
- Modify: `app/static/css/app.css`（`.pd-ocr-failed` 樣式）
- Modify: `app/static/sw.js`（bump CACHE_NAME）
- Test: 手動 e2e（純 DOM 膠合，不寫脆弱 DOM 測試）

**Interfaces:**
- Consumes: 後端 `POST /expenses/<id>/reocr`；serialize 的 `ocr_failed`
- Produces: `reocrExpense(id)`（expenses_api）；`draft` 且 `ocr_failed` 的列顯示紅字提示 + 「重新辨識」鈕

- [ ] **Step 1: expenses_api 加 reocr**

`app/static/js/expenses_api.js`：沿用該檔既有 fetch 包裝（與 `submitExpense` 相同 pattern，回 `{status, data}`），加並 export：
```javascript
export const reocrExpense = (id) => postJson(`/expenses/${id}/reocr`);
```
（`postJson`/實際 helper 名稱以該檔為準；若 `submitExpense` 寫成 `req('POST', ...)` 就照它。）

- [ ] **Step 2: pending.js 失敗列標示 + 重新辨識鈕**

`app/static/js/pending.js`：
- 檔頭 import 加入 `reocrExpense`：
```javascript
import {
  listPending, patchExpense, submitExpense, discardExpense, listCategories, noReceipt, reocrExpense,
} from './expenses_api.js';
```
- 在建立每列的 `tr.innerHTML` 內，`<div class="pd-row-err" data-f="err"></div>` 之後，插入失敗提示區塊（僅失敗時顯示）：把該 `<td>` 的動作欄改為：
```javascript
      <td>
        <button data-act="submit">送出</button><button data-act="del">丟棄</button>
        ${e.ocr_failed ? '<button data-act="reocr">重新辨識</button>' : ''}
        <div class="pd-row-err" data-f="err"></div>
        ${e.ocr_failed ? '<div class="pd-ocr-failed">⚠ OCR 失敗，請手動確認金額/分類</div>' : ''}
      </td>`;
```
- 在既有 submit/del 事件綁定之後，加 reocr 綁定（僅失敗列有此鈕）：
```javascript
    const reBtn = tr.querySelector('[data-act="reocr"]');
    if (reBtn) {
      reBtn.addEventListener('click', async () => {
        setErr('');
        const { status } = await reocrExpense(e.id);
        if (status === 202 || status === 200) {
          setErr('已送出重新辨識，稍後重整暫存區查看');
          reBtn.disabled = true;
        } else {
          setErr('重新辨識失敗，請稍後再試');
        }
      });
    }
```

- [ ] **Step 3: CSS**

`app/static/css/app.css`：加（沿用既有暗色 modal 風格——暫存區是 `#modal-root` 暗色，`.pd-row-err` 已是紅字 `#ff6b6b`）：
```css
.pd-ocr-failed { color: #ff6b6b; font-size: .8rem; margin-top: 4px; white-space: normal; }
```

- [ ] **Step 4: bump sw.js**

`app/static/sw.js`：`CACHE_NAME` 版本 +1（如 `calc-v19` → `calc-v20`）。

- [ ] **Step 5: 前端回歸 + 後端全套**

Run:
```bash
node --test tests/js/*.mjs && python3 -m pytest -q
```
Expected: PASS（本 task 未動純邏輯模組，JS 數不變；後端不變）。

- [ ] **Step 6: 手動 e2e（可選、驗收用）**

啟動：
```bash
set -a; . ./.env; set +a
E2E_LOGIN_BYPASS=1 OCR_PROVIDER=gemini GEMINI_MAX_RETRIES=1 FLASK_APP=wsgi.py python3 -m flask run --port 5001 --no-reload
```
（要模擬失敗可暫設無效 `GEMINI_API_KEY` → 401/400 fatal → 暫存區看到「⚠ OCR 失敗」+ 重新辨識鈕。）

- [ ] **Step 7: commit**

```bash
git add app/static/js/expenses_api.js app/static/js/pending.js app/static/css/app.css app/static/sw.js
git commit -m "feat(ocr-ui): 暫存區 OCR 失敗提示 + 重新辨識鈕"
```

---

### Task 10: .env.example + 設定文件

**Files:**
- Modify: `.env.example`
- Test: 無（文件）

- [ ] **Step 1: 補設定項**

`.env.example`：在 Gemini 相關區塊加（附註解）：
```
# OCR 韌性
GEMINI_MAX_RETRIES=3        # 單輪內對 429/503/5xx/timeout 的重試次數
GEMINI_RETRY_BASE=0.5       # 退避基秒(指數退避 base)
OCR_MAX_ROUNDS=3            # 背景重排輪數上限，達上限收斂成 draft+ocr_failed
```

- [ ] **Step 2: 驗證 + commit**

驗證 `.env.example` 無語法問題（純 KEY=VALUE，工具 `grep -n '=' .env.example` 目視每行含 `=`）。
```bash
git add .env.example
git commit -m "docs(ocr): .env.example 補 OCR 重試/重排設定項"
```

---

## Self-Review 檢核（已於撰寫後執行）

- **Spec coverage**：重試+退避(Task 2,3)、錯誤分類(Task 1)、`ocr_log`(Task 4,6)、失敗旗標欄位(Task 4)、狀態機 success/fatal/exhausted(Task 6)、背景有限次重排(Task 7)、storage.get(Task 5)、手動重新辨識端點+UI(Task 8,9)、設定項(Task 10) 皆有對應 task。
- **關鍵防呆**：Global Constraints 明列「Boolean 欄位 migration 用 `sa.false()` 不可 `sa.text('0')`」——避免重蹈稽核 migration 的 Postgres Critical。
- **型別一致**：`classify_exception`/`recognize_with_retry`(回傳 dict 結構)/`_write_ocr_logs`/`_last_error`/`OcrLog` 欄位/`get`/`reocr` 跨 task 命名一致；`recognize_with_retry` 的 attempts item 欄位（attempt/outcome/error_type/http_status/duration_ms）在 Task 2 定義、Task 6 消費一致。
- **回歸風險已標**：Task 3/6 明列「舊 recognize 回 empty / 舊 _run_ocr `if not result`」的既有測試需掃 `grep -rn recognize tests/` 並調整。
- **無 placeholder**：各 step 附實際程式碼與指令。
- **注意事項**：Task 9 `expenses_api.js` 的實際 fetch helper 名稱以該檔為準（`postJson`/`req`）；Task 4 migration 若 autogenerate 未用 batch 需手動包。
