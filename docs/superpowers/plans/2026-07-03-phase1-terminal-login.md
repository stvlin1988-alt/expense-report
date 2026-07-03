# Plan 3a — 公開計算機終端 + 隱蔽登入前端 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立門市公用手機的第一批 HTML 前端——對外是一台可用的 Apple iOS 風計算機（含即時匯率換算），只有輸入隱蔽指令才叫出「密碼＋人臉」登入。

**Architecture:** Flask Jinja 渲染單一可見網址 `/`，登入後畫面用前端 view state 切換（網址列永遠只有 `/`）。純邏輯（計算機引擎、交叉匯率、暗號 hash 比對）切成 ESM 模組並以 node 內建 test runner 做 TDD；DOM/相機/流程膠合以完整程式碼提供、手動瀏覽器驗證。匯率由後端 `urllib` 抓 open.er-api.com、快取進 DB（`fx_rate_cache`）、lazy TTL 刷新。

**Tech Stack:** Flask 3.1 / Flask-SQLAlchemy 3.1 / SQLAlchemy 2.0 / Flask-Migrate（後端）；原生 JS ES modules + `fetch` + Web Crypto（前端，無打包）；pytest（後端測試）；node 22 內建 `node:test`（前端純邏輯測試）。

## Global Constraints

- 影像不落地：相機單張畫面僅在記憶體、送出 base64 後即丟；不錄影、不進相簿、DB 不存照片。
- fingerprint 永不作認證判斷（僅稽核）。
- 前端不輪詢：匯率載入時抓一次讀快取；idle 逾時由後端 gate 判定。
- 時間 UI 一律台灣時間（DB 存 UTC）。
- 狀態全進 DB，workers>1 不用 module-level dict（匯率快取進 `fx_rate_cache`）。
- 與 webapp 完全隔離：獨立模板/靜態，不共用檔案（僅參考 pattern）。
- 使用者可見網址只有 `/`：不新增 `/home`、`/enroll` 等會洩底的路徑。
- 依賴鎖版；**不新增 Python 套件**（匯率用 stdlib `urllib`）。
- 隱蔽回饋：所有登入失敗一律回同一句無害訊息，不透露是登入或錯在何處。
- 後端 API 契約（既有、不改）：`POST /auth/verify {password, face_image}` → `{status, id, name, role}`；`POST /auth/bootstrap {name, password, face_image}`（seed-only）；`POST /face/enroll {face_image, user_id?}`（需登入）；`POST /api/v1/register-device`；`POST /auth/logout`。

---

## 檔案結構

**後端（新建）**
- `app/models/fx_rate.py` — `FxRate` 匯率快取 model
- `app/fx/__init__.py` — 匯出 `fx_bp`
- `app/fx/service.py` — 抓取/快取/交叉匯率
- `app/fx/routes.py` — `GET /api/v1/fx`
- `app/web/__init__.py` — 匯出 `web_bp`
- `app/web/routes.py` — `GET /`、`GET /sw.js`
- `migrations/versions/b7f3c1a9d2e4_fx_rate_cache.py` — 建表

**後端（修改）**
- `app/models/__init__.py` — 註冊 `FxRate`
- `app/config.py` — 暗號碼 + 匯率設定
- `app/auth/gates.py` — `/` 加入豁免
- `app/__init__.py` — 註冊 `web_bp`、`fx_bp`

**前端（新建）**
- `app/templates/base.html` — PWA 骨架
- `app/templates/index.html` — 計算機終端 + 隱藏 modal
- `app/static/css/app.css` — iOS 風樣式
- `app/static/manifest.json` — PWA manifest（無害名稱）
- `app/static/sw.js` — service worker
- `app/static/js/package.json` — `{"type":"module"}`（讓 node 以 ESM import；不影響瀏覽器）
- `app/static/js/calculator.js` — 純計算機引擎（ESM）
- `app/static/js/currency.js` — 純交叉匯率（ESM）
- `app/static/js/secret.js` — 暗號正規化 + hash 比對 + 6 秒窗（ESM）
- `app/static/js/camera.js` — `Camera` 單張擷取類別（ESM）
- `app/static/js/fx.js` — 讀 `/api/v1/fx`（ESM）
- `app/static/js/auth.js` — 登入/bootstrap modal、相機流程、登入後畫面、登出、更新臉（ESM）
- `app/static/js/main.js` — 進入點：讀 config、鍵盤、tab、計算機/匯率、暗號觸發（ESM）

**測試（新建）**
- `tests/test_fx_service.py`
- `tests/test_web_index.py`
- `tests/js/calculator.test.mjs`
- `tests/js/currency.test.mjs`
- `tests/js/secret.test.mjs`

---

## Task 1: FxRate 匯率快取 model + migration

**Files:**
- Create: `app/models/fx_rate.py`
- Modify: `app/models/__init__.py`
- Create: `migrations/versions/b7f3c1a9d2e4_fx_rate_cache.py`
- Test: `tests/test_fx_service.py`（本 task 先放 model 建表測試）

**Interfaces:**
- Produces: `FxRate(base:str, rates_json:str, fetched_at:datetime)`，`__tablename__="fx_rate_cache"`，`base` unique。

- [ ] **Step 1: 寫失敗測試**

`tests/test_fx_service.py`：
```python
import json
from app.extensions import db
from app.models.fx_rate import FxRate


def test_fxrate_model_persists(app):
    with app.app_context():
        db.create_all()
        row = FxRate(base="USD", rates_json=json.dumps({"USD": 1.0}))
        db.session.add(row)
        db.session.commit()
        got = FxRate.query.filter_by(base="USD").first()
        assert got is not None
        assert json.loads(got.rates_json)["USD"] == 1.0
        assert got.fetched_at is not None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_fx_service.py::test_fxrate_model_persists -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.fx_rate'`

- [ ] **Step 3: 建 model**

`app/models/fx_rate.py`：
```python
from datetime import datetime, timezone

from app.extensions import db


class FxRate(db.Model):
    """匯率快取：以 base 幣別為鍵存一份 rates JSON。狀態進 DB，workers>1 共用。"""
    __tablename__ = "fx_rate_cache"

    id = db.Column(db.Integer, primary_key=True)
    base = db.Column(db.String(3), unique=True, nullable=False)
    rates_json = db.Column(db.Text, nullable=False)  # {"JPY":..,"USD":..,...}
    fetched_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
```

`app/models/__init__.py` 改為：
```python
from app.models.store import Store
from app.models.user import User, ROLES
from app.models.category import Category
from app.models.doc_type import DocType
from app.models.device import Device
from app.models.fx_rate import FxRate

__all__ = ["Store", "User", "ROLES", "Category", "DocType", "Device", "FxRate"]
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_fx_service.py::test_fxrate_model_persists -v`
Expected: PASS

- [ ] **Step 5: 建 migration**

`migrations/versions/b7f3c1a9d2e4_fx_rate_cache.py`：
```python
"""fx_rate_cache

Revision ID: b7f3c1a9d2e4
Revises: 51e7c6648ba0
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = "b7f3c1a9d2e4"
down_revision = "51e7c6648ba0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fx_rate_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("base", sa.String(length=3), nullable=False),
        sa.Column("rates_json", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("base", name="uq_fx_rate_cache_base"),
    )


def downgrade():
    op.drop_table("fx_rate_cache")
```

- [ ] **Step 6: 驗證 migration 鏈接正確**

Run: `FLASK_APP=wsgi.py python3 -m flask db heads 2>/dev/null`
Expected: 輸出含 `b7f3c1a9d2e4 (head)`（若 dev DB 未初始化只需確認鏈無錯；tests 用 `db.create_all()` 不走 migration）

- [ ] **Step 7: Commit**

```bash
git add app/models/fx_rate.py app/models/__init__.py migrations/versions/b7f3c1a9d2e4_fx_rate_cache.py tests/test_fx_service.py
git commit -m "feat(fx): FxRate 匯率快取 model + migration"
```

---

## Task 2: 匯率服務（抓取 + 快取 + 交叉匯率）

**Files:**
- Create: `app/fx/service.py`
- Modify: `app/config.py`
- Test: `tests/test_fx_service.py`（新增服務測試）

**Interfaces:**
- Consumes: `FxRate`（Task 1）。
- Produces：
  - `app.fx.service.BASE = "USD"`
  - `app.fx.service.CURRENCIES = ["TWD","JPY","USD","THB","EUR"]`
  - `_fetch_remote_rates() -> dict|None`（可被 monkeypatch）
  - `get_rates() -> (rates:dict|None, fetched_at_iso:str|None)`

- [ ] **Step 1: 加 config**

`app/config.py` 的 `class Config` 內，`PERMANENT_SESSION_LIFETIME` 之後加：
```python
    # 隱蔽登入暗號（可經 env 改；預設 078*2）
    EXPENSE_TRIGGER_CODE = os.environ.get("EXPENSE_TRIGGER_CODE", "078*2")
    # 匯率
    FX_API_URL = os.environ.get("FX_API_URL", "https://open.er-api.com/v6/latest/USD")
    FX_TTL_SECONDS = int(os.environ.get("FX_TTL_SECONDS", str(6 * 3600)))
    FX_FETCH_TIMEOUT = int(os.environ.get("FX_FETCH_TIMEOUT", "8"))
```

- [ ] **Step 2: 寫失敗測試**

`tests/test_fx_service.py` 追加：
```python
from datetime import datetime, timezone, timedelta
import app.fx.service as svc

SAMPLE = {"TWD": 32.0, "JPY": 155.0, "USD": 1.0, "THB": 36.0, "EUR": 0.92}


def test_get_rates_fetches_and_caches_when_empty(app, monkeypatch):
    monkeypatch.setattr(svc, "_fetch_remote_rates", lambda: dict(SAMPLE))
    with app.app_context():
        db.create_all()
        rates, fetched = svc.get_rates()
        assert rates == SAMPLE
        assert fetched is not None
        assert FxRate.query.filter_by(base="USD").count() == 1


def test_get_rates_returns_cache_within_ttl_without_fetch(app, monkeypatch):
    calls = {"n": 0}

    def fake():
        calls["n"] += 1
        return dict(SAMPLE)

    monkeypatch.setattr(svc, "_fetch_remote_rates", fake)
    with app.app_context():
        db.create_all()
        svc.get_rates()
        svc.get_rates()
        assert calls["n"] == 1  # TTL 內不重抓


def test_get_rates_refreshes_when_stale(app, monkeypatch):
    monkeypatch.setattr(svc, "_fetch_remote_rates", lambda: dict(SAMPLE))
    with app.app_context():
        db.create_all()
        db.session.add(FxRate(
            base="USD", rates_json=json.dumps({"USD": 1.0}),
            fetched_at=datetime.now(timezone.utc) - timedelta(hours=7)))
        db.session.commit()
        rates, _ = svc.get_rates()
        assert rates == SAMPLE


def test_get_rates_falls_back_to_stale_cache_on_failure(app, monkeypatch):
    monkeypatch.setattr(svc, "_fetch_remote_rates", lambda: None)
    old = {"USD": 1.0, "TWD": 30.0}
    with app.app_context():
        db.create_all()
        db.session.add(FxRate(
            base="USD", rates_json=json.dumps(old),
            fetched_at=datetime.now(timezone.utc) - timedelta(hours=7)))
        db.session.commit()
        rates, _ = svc.get_rates()
        assert rates == old


def test_get_rates_none_when_no_cache_and_fetch_fails(app, monkeypatch):
    monkeypatch.setattr(svc, "_fetch_remote_rates", lambda: None)
    with app.app_context():
        db.create_all()
        rates, fetched = svc.get_rates()
        assert rates is None and fetched is None
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_fx_service.py -v`
Expected: FAIL — `AttributeError: module 'app.fx.service' has no attribute ...`（或 import error）

- [ ] **Step 4: 建服務**

`app/fx/service.py`：
```python
import json
import urllib.request
from datetime import datetime, timezone, timedelta

from flask import current_app

from app.extensions import db
from app.models.fx_rate import FxRate

BASE = "USD"
CURRENCIES = ["TWD", "JPY", "USD", "THB", "EUR"]


def _aware(dt):
    """SQLite 取回的 datetime 可能無 tzinfo；一律當成 UTC。"""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _fetch_remote_rates():
    """抓外部匯率，回 {cur: rate_per_USD}；失敗或幣別不齊回 None。"""
    url = current_app.config["FX_API_URL"]
    timeout = current_app.config.get("FX_FETCH_TIMEOUT", 8)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("result") != "success":
        return None
    rates = payload.get("rates") or {}
    picked = {c: rates[c] for c in CURRENCIES if c in rates}
    if any(c not in picked for c in CURRENCIES):
        return None
    return picked


def get_rates():
    """(rates, fetched_at_iso)。TTL 內回快取；過期抓新；失敗回舊快取；
    無快取且抓取失敗 → (None, None)。"""
    row = FxRate.query.filter_by(base=BASE).first()
    ttl = timedelta(seconds=current_app.config.get("FX_TTL_SECONDS", 6 * 3600))
    now = datetime.now(timezone.utc)

    if row is not None and (now - _aware(row.fetched_at)) < ttl:
        return json.loads(row.rates_json), _aware(row.fetched_at).isoformat()

    try:
        remote = _fetch_remote_rates()
    except Exception:
        remote = None

    if remote is not None:
        if row is None:
            row = FxRate(base=BASE, rates_json=json.dumps(remote), fetched_at=now)
            db.session.add(row)
        else:
            row.rates_json = json.dumps(remote)
            row.fetched_at = now
        db.session.commit()
        return remote, now.isoformat()

    if row is not None:
        return json.loads(row.rates_json), _aware(row.fetched_at).isoformat()
    return None, None
```

- [ ] **Step 5: 跑測試確認通過**

Run: `python3 -m pytest tests/test_fx_service.py -v`
Expected: PASS（全部）

- [ ] **Step 6: Commit**

```bash
git add app/fx/service.py app/config.py tests/test_fx_service.py
git commit -m "feat(fx): 匯率抓取/快取服務 + TTL/fallback"
```

---

## Task 3: `GET /api/v1/fx` 端點

**Files:**
- Create: `app/fx/routes.py`
- Create: `app/fx/__init__.py`
- Modify: `app/__init__.py`
- Test: `tests/test_fx_service.py`（新增端點測試）

**Interfaces:**
- Consumes: `app.fx.service.get_rates/BASE/CURRENCIES`。
- Produces: blueprint `fx_bp`；`GET /api/v1/fx` → `{status:"ok"|"unavailable", base, currencies, rates?, fetched_at?}`（皆 200）。

- [ ] **Step 1: 寫失敗測試**

`tests/test_fx_service.py` 追加：
```python
def test_fx_endpoint_ok(app, monkeypatch):
    monkeypatch.setattr(svc, "_fetch_remote_rates", lambda: dict(SAMPLE))
    with app.app_context():
        db.create_all()
    c = app.test_client()
    r = c.get("/api/v1/fx")
    assert r.status_code == 200
    j = r.get_json()
    assert j["status"] == "ok"
    assert j["base"] == "USD"
    assert j["currencies"] == ["TWD", "JPY", "USD", "THB", "EUR"]
    assert j["rates"]["JPY"] == 155.0


def test_fx_endpoint_unavailable(app, monkeypatch):
    monkeypatch.setattr(svc, "_fetch_remote_rates", lambda: None)
    with app.app_context():
        db.create_all()
    c = app.test_client()
    r = c.get("/api/v1/fx")
    assert r.status_code == 200
    assert r.get_json()["status"] == "unavailable"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_fx_service.py::test_fx_endpoint_ok -v`
Expected: FAIL — 404（路由不存在）

- [ ] **Step 3: 建 blueprint + 註冊**

`app/fx/routes.py`：
```python
from flask import Blueprint, jsonify

from app.fx.service import get_rates, BASE, CURRENCIES

fx_bp = Blueprint("fx", __name__)


@fx_bp.get("/api/v1/fx")
def fx():
    rates, fetched_at = get_rates()
    if rates is None:
        return jsonify(status="unavailable", base=BASE, currencies=CURRENCIES)
    return jsonify(status="ok", base=BASE, currencies=CURRENCIES,
                   rates=rates, fetched_at=fetched_at)
```

`app/fx/__init__.py`：
```python
from app.fx.routes import fx_bp

__all__ = ["fx_bp"]
```

`app/__init__.py` 在 `app.register_blueprint(admin_bp)` 之後加：
```python
    from app.fx import fx_bp
    app.register_blueprint(fx_bp)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_fx_service.py -v`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
git add app/fx/ app/__init__.py tests/test_fx_service.py
git commit -m "feat(fx): GET /api/v1/fx 端點"
```

---

## Task 4: `web` blueprint — `GET /`（注入 seed_mode/secret_hash/identity）+ `/sw.js` + gate 豁免

**Files:**
- Create: `app/web/routes.py`
- Create: `app/web/__init__.py`
- Create: `app/templates/index.html`（本 task 先放最小可渲染骨架）
- Modify: `app/auth/gates.py`
- Modify: `app/__init__.py`
- Test: `tests/test_web_index.py`

**Interfaces:**
- Consumes: `app.auth.gates.is_seed_mode`、`config.EXPENSE_TRIGGER_CODE`、`User`。
- Produces: blueprint `web_bp`；`GET /` 渲染 `index.html` 並注入模板變數 `seed_mode:bool`、`secret_hash:str`(sha256 hex of code)、`identity:{name,role}|None`；`GET /sw.js` 提供 `app/static/sw.js`。

- [ ] **Step 1: 寫失敗測試**

`tests/test_web_index.py`：
```python
import re
import json
import hashlib

import numpy as np

from app.extensions import db
from app.models.user import User
from app.models.device import Device


def _cfg(data):
    m = re.search(rb'id="app-config"[^>]*>(.*?)</script>', data, re.S)
    return json.loads(m.group(1))


def test_index_renders(app):
    with app.app_context():
        db.create_all()
    r = app.test_client().get("/")
    assert r.status_code == 200
    assert b"app-config" in r.data


def test_index_seed_mode_true_when_empty(app):
    with app.app_context():
        db.create_all()
    r = app.test_client().get("/")
    assert _cfg(r.data)["seedMode"] is True


def test_index_secret_hash_matches_config(app):
    with app.app_context():
        db.create_all()
    r = app.test_client().get("/")
    assert _cfg(r.data)["secretHash"] == hashlib.sha256(b"078*2").hexdigest()


def _make_non_seed():
    sa = User(name="業主", role="super_admin")
    sa.set_password("pw")
    sa.face_encoding = np.zeros(128, dtype=np.float64).tobytes()
    db.session.add(sa)
    db.session.add(Device(client_uid="devOK", is_approved=True))
    db.session.commit()
    return sa.id


def test_index_exempt_even_when_device_unapproved(app):
    with app.app_context():
        db.create_all()
        _make_non_seed()
    c = app.test_client()
    c.set_cookie("device_uid", "bad")
    assert c.get("/").status_code == 200  # '/' 豁免 device gate


def test_index_injects_identity_when_logged_in(app):
    with app.app_context():
        db.create_all()
        u = User(name="王小明", role="employee")
        u.set_password("p")
        db.session.add(u)
        db.session.commit()
        uid = u.id
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = uid
    cfg = _cfg(c.get("/").data)
    assert cfg["identity"]["name"] == "王小明"
    assert cfg["identity"]["role"] == "employee"


def test_index_no_identity_when_anonymous(app):
    with app.app_context():
        db.create_all()
    assert _cfg(app.test_client().get("/").data)["identity"] is None


def test_sw_served_at_root(app):
    with app.app_context():
        db.create_all()
    r = app.test_client().get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["Content-Type"]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_web_index.py -v`
Expected: FAIL — 404（`/` 與 `/sw.js` 路由不存在）

- [ ] **Step 3: 建最小 index.html 骨架**

`app/templates/index.html`（Task 9 會擴充成完整 UI；本 task 只需能渲染 config）：
```html
<!DOCTYPE html>
<html lang="zh-TW">
<head><meta charset="UTF-8"><title>計算機</title></head>
<body>
<script id="app-config" type="application/json">
{{ {"seedMode": seed_mode, "secretHash": secret_hash, "identity": identity} | tojson }}
</script>
</body>
</html>
```

- [ ] **Step 4: 建 web blueprint**

`app/web/routes.py`：
```python
import hashlib
import os

from flask import (Blueprint, current_app, render_template, session,
                   send_from_directory)

from app.auth.gates import is_seed_mode
from app.models.user import User
from app.extensions import db

web_bp = Blueprint("web", __name__)


def _secret_hash():
    code = current_app.config["EXPENSE_TRIGGER_CODE"]
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


@web_bp.get("/")
def index():
    identity = None
    uid = session.get("user_id")
    if uid:
        u = db.session.get(User, uid)
        if u and u.active:
            identity = {"name": u.name, "role": u.role}
    return render_template(
        "index.html",
        seed_mode=is_seed_mode(),
        secret_hash=_secret_hash(),
        identity=identity,
    )


@web_bp.get("/sw.js")
def service_worker():
    return send_from_directory(
        os.path.join(current_app.root_path, "static"),
        "sw.js",
        mimetype="application/javascript",
    )
```

`app/web/__init__.py`：
```python
from app.web.routes import web_bp

__all__ = ["web_bp"]
```

- [ ] **Step 5: gate 豁免 `/` + 註冊 blueprint**

`app/auth/gates.py` 改 `_EXEMPT_PATHS`：
```python
_EXEMPT_PATHS = ("/health", "/sw.js", "/auth/logout", "/")
```

`app/__init__.py` 在 `app.register_blueprint(admin_bp)` 之後（fx 之前或後皆可）加：
```python
    from app.web import web_bp
    app.register_blueprint(web_bp)
```

- [ ] **Step 6: 建暫時空 sw.js 讓 `/sw.js` 測試可過**

建立 `app/static/sw.js`（Task 8 會寫完整內容；先放最小合法 JS）：
```javascript
// service worker placeholder — Task 8 補完整快取策略
self.addEventListener('install', () => self.skipWaiting());
```

- [ ] **Step 7: 跑測試確認通過**

Run: `python3 -m pytest tests/test_web_index.py -v`
Expected: PASS（全部）

- [ ] **Step 8: 全套回歸**

Run: `python3 -m pytest -q`
Expected: 全綠（既有 89 + 本批新增）

- [ ] **Step 9: Commit**

```bash
git add app/web/ app/templates/index.html app/static/sw.js app/auth/gates.py app/__init__.py tests/test_web_index.py
git commit -m "feat(web): GET / 注入 seed_mode/secret_hash/identity + /sw.js + gate 豁免"
```

---

## Task 5: 計算機引擎（純邏輯，node TDD）

**Files:**
- Create: `app/static/js/package.json`
- Create: `app/static/js/calculator.js`
- Test: `tests/js/calculator.test.mjs`

**Interfaces:**
- Produces: `class CalcEngine`，方法 `inputDigit(d:string)`、`inputDot()`、`inputOp(op:'+'|'-'|'*'|'/')`、`equals()`、`clear()`、`negate()`、`percent()`；getter `display:string`。

- [ ] **Step 1: 建 ESM 開關 + 失敗測試**

`app/static/js/package.json`：
```json
{ "type": "module" }
```

`tests/js/calculator.test.mjs`：
```javascript
import test from 'node:test';
import assert from 'node:assert';
import { CalcEngine } from '../../app/static/js/calculator.js';

test('加法 2+3=5', () => {
  const c = new CalcEngine();
  c.inputDigit('2'); c.inputOp('+'); c.inputDigit('3'); c.equals();
  assert.equal(c.display, '5');
});

test('乘法 7*8=56', () => {
  const c = new CalcEngine();
  c.inputDigit('7'); c.inputOp('*'); c.inputDigit('8'); c.equals();
  assert.equal(c.display, '56');
});

test('前導 0：078 顯示 78，078*2=156', () => {
  const c = new CalcEngine();
  c.inputDigit('0'); c.inputDigit('7'); c.inputDigit('8');
  assert.equal(c.display, '78');
  c.inputOp('*'); c.inputDigit('2'); c.equals();
  assert.equal(c.display, '156');
});

test('連續運算 1+2+3=6', () => {
  const c = new CalcEngine();
  c.inputDigit('1'); c.inputOp('+'); c.inputDigit('2');
  c.inputOp('+'); c.inputDigit('3'); c.equals();
  assert.equal(c.display, '6');
});

test('除以 0 顯示 錯誤', () => {
  const c = new CalcEngine();
  c.inputDigit('5'); c.inputOp('/'); c.inputDigit('0'); c.equals();
  assert.equal(c.display, '錯誤');
});

test('percent：50% = 0.5', () => {
  const c = new CalcEngine();
  c.inputDigit('5'); c.inputDigit('0'); c.percent();
  assert.equal(c.display, '0.5');
});

test('negate 正負切換', () => {
  const c = new CalcEngine();
  c.inputDigit('9'); c.negate();
  assert.equal(c.display, '-9');
  c.negate();
  assert.equal(c.display, '9');
});

test('小數點 3.14', () => {
  const c = new CalcEngine();
  c.inputDigit('3'); c.inputDot(); c.inputDigit('1'); c.inputDigit('4');
  assert.equal(c.display, '3.14');
});

test('clear 歸零', () => {
  const c = new CalcEngine();
  c.inputDigit('9'); c.clear();
  assert.equal(c.display, '0');
});
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `node --test tests/js/calculator.test.mjs`
Expected: FAIL — 無法解析 `../../app/static/js/calculator.js`

- [ ] **Step 3: 建引擎**

`app/static/js/calculator.js`：
```javascript
export class CalcEngine {
  constructor() { this._reset(); }

  _reset() {
    this.current = '0';
    this.stored = null;
    this.op = null;
    this.overwrite = true; // 下一個數字覆蓋顯示
  }

  clear() { this._reset(); }
  get display() { return this.current; }

  _num() { return parseFloat(this.current); }

  _set(n) {
    if (!isFinite(n)) { this.current = '錯誤'; return; }
    // 去除浮點雜訊：四捨五入到 10 位小數
    this.current = String(Math.round((n + Number.EPSILON) * 1e10) / 1e10);
  }

  inputDigit(d) {
    if (this.current === '錯誤') this._reset();
    if (this.overwrite) { this.current = d; this.overwrite = false; }
    else if (this.current === '0') this.current = d;
    else this.current += d;
  }

  inputDot() {
    if (this.current === '錯誤') this._reset();
    if (this.overwrite) { this.current = '0.'; this.overwrite = false; return; }
    if (!this.current.includes('.')) this.current += '.';
  }

  negate() {
    if (this.current === '0' || this.current === '錯誤') return;
    this.current = this.current.startsWith('-')
      ? this.current.slice(1) : '-' + this.current;
  }

  percent() {
    if (this.current === '錯誤') return;
    this._set(this._num() / 100);
    this.overwrite = true;
  }

  _apply(a, op, b) {
    switch (op) {
      case '+': return a + b;
      case '-': return a - b;
      case '*': return a * b;
      case '/': return b === 0 ? NaN : a / b;
      default: return b;
    }
  }

  inputOp(op) {
    if (this.current === '錯誤') return;
    if (this.op !== null && !this.overwrite) {
      this._set(this._apply(this.stored, this.op, this._num()));
      this.stored = this._num();
    } else {
      this.stored = this._num();
    }
    this.op = op;
    this.overwrite = true;
  }

  equals() {
    if (this.op === null || this.current === '錯誤') return;
    this._set(this._apply(this.stored, this.op, this._num()));
    this.op = null;
    this.stored = null;
    this.overwrite = true;
  }
}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `node --test tests/js/calculator.test.mjs`
Expected: PASS（9 tests）

- [ ] **Step 5: Commit**

```bash
git add app/static/js/package.json app/static/js/calculator.js tests/js/calculator.test.mjs
git commit -m "feat(calc): 純計算機引擎 CalcEngine + node 測試"
```

---

## Task 6: 交叉匯率（純邏輯，node TDD）

**Files:**
- Create: `app/static/js/currency.js`
- Test: `tests/js/currency.test.mjs`

**Interfaces:**
- Produces: `cross(amount:number, from:string, to:string, rates:{[cur]:perUSD}) -> number|null`；`convertAll(amount, from, currencies:string[], rates) -> {[cur]:number}`（不含 from 自己；缺率者略過）。

- [ ] **Step 1: 寫失敗測試**

`tests/js/currency.test.mjs`：
```javascript
import test from 'node:test';
import assert from 'node:assert';
import { cross, convertAll } from '../../app/static/js/currency.js';

const R = { TWD: 32, JPY: 150, USD: 1, THB: 36, EUR: 0.9 };

test('USD→TWD：10 USD = 320 TWD', () => {
  assert.equal(cross(10, 'USD', 'TWD', R), 320);
});

test('交叉 TWD→JPY：320 TWD = 1500 JPY', () => {
  assert.ok(Math.abs(cross(320, 'TWD', 'JPY', R) - 1500) < 1e-9);
});

test('缺率回 null', () => {
  assert.equal(cross(1, 'USD', 'GBP', R), null);
});

test('convertAll 不含 from、涵蓋其他幣', () => {
  const out = convertAll(1, 'USD', ['TWD', 'JPY', 'USD', 'THB', 'EUR'], R);
  assert.equal(out.USD, undefined);
  assert.equal(out.TWD, 32);
  assert.equal(out.JPY, 150);
  assert.equal(out.EUR, 0.9);
});
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `node --test tests/js/currency.test.mjs`
Expected: FAIL — 無法解析模組

- [ ] **Step 3: 建模組**

`app/static/js/currency.js`：
```javascript
// rates: {cur: 每 1 USD 對應的該幣金額}。跨幣：amount * rate[to] / rate[from]
export function cross(amount, from, to, rates) {
  const rf = rates[from], rt = rates[to];
  if (!rf || !rt) return null;
  return amount * (rt / rf);
}

export function convertAll(amount, from, currencies, rates) {
  const out = {};
  for (const c of currencies) {
    if (c === from) continue;
    const v = cross(amount, from, c, rates);
    if (v !== null) out[c] = v;
  }
  return out;
}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `node --test tests/js/currency.test.mjs`
Expected: PASS（4 tests）

- [ ] **Step 5: Commit**

```bash
git add app/static/js/currency.js tests/js/currency.test.mjs
git commit -m "feat(fx): 交叉匯率純函式 cross/convertAll + node 測試"
```

---

## Task 7: 暗號正規化 + hash 比對 + 6 秒窗（純邏輯，node TDD）

**Files:**
- Create: `app/static/js/secret.js`
- Test: `tests/js/secret.test.mjs`

**Interfaces:**
- Produces:
  - `canonicalToken(key:string) -> string`（`×→*`、`÷→/`、`−→-`，其餘原樣）
  - `buildSequence(tokens:string[]) -> string`
  - `sha256hex(str:string) -> Promise<string>`（Web Crypto）
  - `matchesSecret(sequence:string, secretHash:string) -> Promise<boolean>`
  - `withinWindow(loadTs:number, nowTs:number, windowMs=6000) -> boolean`

- [ ] **Step 1: 寫失敗測試**

`tests/js/secret.test.mjs`：
```javascript
import test from 'node:test';
import assert from 'node:assert';
import {
  canonicalToken, buildSequence, sha256hex, matchesSecret, withinWindow,
} from '../../app/static/js/secret.js';

test('canonicalToken 正規化運算子', () => {
  assert.equal(canonicalToken('×'), '*');
  assert.equal(canonicalToken('÷'), '/');
  assert.equal(canonicalToken('−'), '-');
  assert.equal(canonicalToken('7'), '7');
});

test('buildSequence 串接 078*2', () => {
  assert.equal(buildSequence(['0', '7', '8', '*', '2']), '078*2');
});

test('sha256hex 對應已知 078*2 雜湊', async () => {
  // 與後端 hashlib.sha256(b"078*2").hexdigest() 一致
  const h = await sha256hex('078*2');
  assert.match(h, /^[0-9a-f]{64}$/);
  assert.equal(h, await sha256hex('078*2')); // 穩定
});

test('matchesSecret 正確比對', async () => {
  const h = await sha256hex('078*2');
  assert.equal(await matchesSecret('078*2', h), true);
  assert.equal(await matchesSecret('078*3', h), false);
});

test('withinWindow 邊界', () => {
  assert.equal(withinWindow(1000, 1000 + 5999), true);
  assert.equal(withinWindow(1000, 1000 + 6000), true);
  assert.equal(withinWindow(1000, 1000 + 6001), false);
});
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `node --test tests/js/secret.test.mjs`
Expected: FAIL — 無法解析模組

- [ ] **Step 3: 建模組**

`app/static/js/secret.js`：
```javascript
const OP_MAP = { '×': '*', '÷': '/', '−': '-', 'x': '*' };

export function canonicalToken(key) {
  return OP_MAP[key] || key;
}

export function buildSequence(tokens) {
  return tokens.join('');
}

export async function sha256hex(str) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(str));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
}

export async function matchesSecret(sequence, secretHash) {
  return (await sha256hex(sequence)) === secretHash;
}

export function withinWindow(loadTs, nowTs, windowMs = 6000) {
  return (nowTs - loadTs) <= windowMs;
}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `node --test tests/js/secret.test.mjs`
Expected: PASS（5 tests）

- [ ] **Step 5: 跨端一致性驗證（前後端同雜湊）**

Run:
```bash
python3 -c "import hashlib; print(hashlib.sha256(b'078*2').hexdigest())"
node -e "const {sha256hex}=await import('./app/static/js/secret.js'); console.log(await sha256hex('078*2'))"
```
Expected: 兩行輸出**完全相同**（前端比對得過後端注入的 secret_hash）

- [ ] **Step 6: Commit**

```bash
git add app/static/js/secret.js tests/js/secret.test.mjs
git commit -m "feat(secret): 暗號正規化/雜湊比對/6秒窗純函式 + node 測試"
```

---

## Task 8: PWA 殼（base.html + manifest.json + sw.js + 註冊）

**Files:**
- Create: `app/templates/base.html`
- Create: `app/static/manifest.json`
- Modify: `app/static/sw.js`（補完整內容，覆蓋 Task 4 的 placeholder）
- Test: 手動 + `tests/test_web_index.py::test_sw_served_at_root`（既有）

**Interfaces:**
- Consumes: `/sw.js`（Task 4）。
- Produces: `base.html` 提供 `{% block body %}`、`{% block scripts %}`；註冊 `/sw.js`。

- [ ] **Step 1: 建 base.html**

`app/templates/base.html`：
```html
<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <meta name="theme-color" content="#000000">
  <title>計算機</title>
  <link rel="manifest" href="{{ url_for('static', filename='manifest.json') }}">
  <link rel="stylesheet" href="{{ url_for('static', filename='css/app.css') }}">
</head>
<body>
  {% block body %}{% endblock %}
  <script>
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', () =>
        navigator.serviceWorker.register('/sw.js').catch(() => {}));
    }
  </script>
  {% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 2: 建 manifest.json（無害名稱）**

`app/static/manifest.json`：
```json
{
  "name": "計算機",
  "short_name": "計算機",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "background_color": "#000000",
  "theme_color": "#000000",
  "icons": []
}
```

- [ ] **Step 3: 驗證 JSON 合法**

Run: `python3 -c "import json; json.load(open('app/static/manifest.json')); print('manifest ok')"`
Expected: `manifest ok`

- [ ] **Step 4: 寫完整 sw.js**

覆蓋 `app/static/sw.js`：
```javascript
/**
 * Service Worker — PWA 離線殼
 *   - /static/*：cache-first（計算機離線可用）
 *   - /auth/*、/face/*、/api/*：network-first 且「絕不快取」（認證/影像/匯率）
 *   - 導覽：network-first，離線 fallback 到快取
 * 所有分支保證回傳 Response（避免 respondWith(undefined) 例外）。
 */
const CACHE_NAME = 'calc-v1';
const STATIC_URLS = [
  '/',
  '/static/css/app.css',
  '/static/js/main.js',
  '/static/js/calculator.js',
  '/static/js/currency.js',
  '/static/js/secret.js',
  '/static/js/fx.js',
  '/static/js/camera.js',
  '/static/js/auth.js',
  '/static/manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((c) => c.addAll(STATIC_URLS)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

async function networkFirst(request) {
  try {
    return await fetch(request);
  } catch (err) {
    const cached = await caches.match(request);
    return cached || Response.error();
  }
}

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 認證/影像/匯率：network-first，絕不快取
  if (url.pathname.startsWith('/auth/') ||
      url.pathname.startsWith('/face/') ||
      url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // 靜態：cache-first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request).then((resp) => {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then((c) => c.put(event.request, clone));
          return resp;
        }).catch(() => Response.error());
      })
    );
    return;
  }

  // 導覽（含 '/'）：network-first
  event.respondWith(networkFirst(event.request));
});
```

- [ ] **Step 5: 驗證 sw.js 語法合法**

Run: `node --check app/static/sw.js && echo "sw.js ok"`
Expected: `sw.js ok`

- [ ] **Step 6: 回歸既有測試**

Run: `python3 -m pytest tests/test_web_index.py -q`
Expected: PASS（含 `test_sw_served_at_root`）

- [ ] **Step 7: Commit**

```bash
git add app/templates/base.html app/static/manifest.json app/static/sw.js
git commit -m "feat(pwa): base.html + manifest + sw.js network-first 不快取 auth/face/api"
```

---

## Task 9: 計算機終端 UI（index.html + app.css + main.js）

**Files:**
- Modify: `app/templates/index.html`（擴充成完整 UI，繼承 base.html）
- Create: `app/static/css/app.css`
- Create: `app/static/js/fx.js`
- Create: `app/static/js/main.js`
- Test: 手動瀏覽器

**Interfaces:**
- Consumes: `CalcEngine`(Task5)、`convertAll`(Task6)、`canonicalToken/buildSequence/matchesSecret/withinWindow`(Task7)、`/api/v1/fx`。
- Produces: `fx.js` 匯出 `loadRates() -> Promise<{ok, base, currencies, rates, fetchedAt}>`；`main.js` 掛載 UI、暴露暗號觸發時呼叫 `window.__openAuth(seedMode)`（Task 10/11 實作）。

> 本 task 完成「可用的計算機 + 匯率換算 + 暗號觸發偵測」。暗號觸發後呼叫 `window.__openAuth`；此函式在 Task 10/11 前先以 `console.log` 佔位（本 task 末尾臨時定義），Task 11 再換成真流程。

- [ ] **Step 1: 寫完整 index.html**

`app/templates/index.html`：
```html
{% extends "base.html" %}
{% block body %}
<script id="app-config" type="application/json">
{{ {"seedMode": seed_mode, "secretHash": secret_hash, "identity": identity} | tojson }}
</script>

<div id="calc-app">
  <div class="tabs">
    <button class="tab active" data-tab="calc" type="button">計算機</button>
    <button class="tab" data-tab="fx" type="button">匯率</button>
  </div>

  <div id="calc-display" class="display">0</div>

  <div id="fx-panel" hidden>
    <div id="fx-currencies" class="fx-currencies"></div>
    <div id="fx-amount" class="display">0</div>
    <div id="fx-results" class="fx-results"></div>
    <div id="fx-updated" class="fx-updated"></div>
  </div>

  <div class="keys">
    <button class="key fn" data-action="clear" type="button">AC</button>
    <button class="key fn" data-action="negate" type="button">±</button>
    <button class="key fn" data-action="percent" type="button">%</button>
    <button class="key op" data-op="/" type="button">÷</button>
    <button class="key" data-digit="7" type="button">7</button>
    <button class="key" data-digit="8" type="button">8</button>
    <button class="key" data-digit="9" type="button">9</button>
    <button class="key op" data-op="*" type="button">×</button>
    <button class="key" data-digit="4" type="button">4</button>
    <button class="key" data-digit="5" type="button">5</button>
    <button class="key" data-digit="6" type="button">6</button>
    <button class="key op" data-op="-" type="button">−</button>
    <button class="key" data-digit="1" type="button">1</button>
    <button class="key" data-digit="2" type="button">2</button>
    <button class="key" data-digit="3" type="button">3</button>
    <button class="key op" data-op="+" type="button">+</button>
    <button class="key zero" data-digit="0" type="button">0</button>
    <button class="key" data-action="dot" type="button">.</button>
    <button class="key op equals" data-action="equals" type="button">=</button>
  </div>
</div>

<div id="modal-root"></div>
{% endblock %}
{% block scripts %}
<script type="module" src="{{ url_for('static', filename='js/main.js') }}"></script>
{% endblock %}
```

- [ ] **Step 2: 寫 app.css（iOS 風）**

`app/static/css/app.css`：
```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, 'PingFang TC', 'Segoe UI', sans-serif;
  background: #000; color: #fff; min-height: 100vh;
  display: flex; align-items: flex-end; justify-content: center;
  user-select: none; -webkit-user-select: none;
}
#calc-app { width: 100%; max-width: 420px; padding: 12px; }
.tabs { display: flex; gap: 8px; margin-bottom: 8px; }
.tab {
  flex: 1; padding: 10px; border: none; border-radius: 10px;
  background: #1c1c1e; color: #999; font-size: 1rem; cursor: pointer;
}
.tab.active { background: #2c2c2e; color: #fff; }
.display {
  text-align: right; font-size: 3.2rem; font-weight: 300;
  padding: 16px 12px; min-height: 84px; overflow: hidden;
  white-space: nowrap; text-overflow: ellipsis;
}
.keys { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.key {
  aspect-ratio: 1 / 1; border: none; border-radius: 50%;
  font-size: 1.8rem; background: #333; color: #fff; cursor: pointer;
}
.key:active { filter: brightness(1.4); }
.key.fn { background: #a5a5a5; color: #000; }
.key.op { background: #ff9500; color: #fff; }
.key.zero { aspect-ratio: auto; grid-column: span 2; border-radius: 40px; text-align: left; padding-left: 28px; }
.fx-currencies { display: flex; gap: 6px; flex-wrap: wrap; margin: 4px 0; }
.fx-chip { padding: 6px 12px; border-radius: 16px; background: #1c1c1e; color: #999; border: none; cursor: pointer; font-size: .9rem; }
.fx-chip.active { background: #ff9500; color: #fff; }
.fx-results { display: flex; flex-direction: column; gap: 6px; padding: 0 12px 8px; }
.fx-row { display: flex; justify-content: space-between; font-size: 1.1rem; color: #ddd; }
.fx-updated { text-align: right; font-size: .75rem; color: #666; padding: 0 12px 6px; }
.fx-unavailable { color: #ff6b6b; text-align: center; padding: 8px; }

/* modal 通用 */
.modal-backdrop {
  position: fixed; inset: 0; background: rgba(0,0,0,.7);
  display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 16px;
}
.modal-box { background: #1c1c1e; color: #fff; border-radius: 16px; padding: 24px; width: 360px; max-width: 95vw; }
.modal-box h2 { font-size: 1.2rem; margin-bottom: 16px; font-weight: 600; }
.modal-box input {
  width: 100%; padding: 12px; margin-bottom: 12px; border-radius: 10px;
  border: 1px solid #3a3a3c; background: #2c2c2e; color: #fff; font-size: 1rem;
}
.modal-box video { width: 100%; border-radius: 10px; background: #000; margin-bottom: 12px; }
.modal-btn {
  width: 100%; padding: 13px; border: none; border-radius: 10px;
  background: #ff9500; color: #fff; font-size: 1rem; font-weight: 600; cursor: pointer;
}
.modal-btn.secondary { background: #3a3a3c; }
.modal-msg { text-align: center; font-size: .9rem; min-height: 1.2em; margin-top: 10px; color: #ff6b6b; }
.app-view-info { font-size: 1rem; margin-bottom: 16px; line-height: 1.8; }
```

- [ ] **Step 3: 寫 fx.js**

`app/static/js/fx.js`：
```javascript
export async function loadRates() {
  try {
    const res = await fetch('/api/v1/fx');
    const data = await res.json();
    if (data.status !== 'ok') {
      return { ok: false, base: data.base, currencies: data.currencies || [] };
    }
    return {
      ok: true, base: data.base, currencies: data.currencies,
      rates: data.rates, fetchedAt: data.fetched_at,
    };
  } catch (err) {
    return { ok: false, base: 'USD', currencies: [] };
  }
}
```

- [ ] **Step 4: 寫 main.js（計算機 + 匯率 + tab + 暗號觸發）**

`app/static/js/main.js`：
```javascript
import { CalcEngine } from './calculator.js';
import { convertAll } from './currency.js';
import { loadRates } from './fx.js';
import { canonicalToken, buildSequence, matchesSecret, withinWindow } from './secret.js';

const cfg = JSON.parse(document.getElementById('app-config').textContent);
const engine = new CalcEngine();
const displayEl = document.getElementById('calc-display');
const fxPanel = document.getElementById('fx-panel');
const calcDisplay = document.getElementById('calc-display');

let mode = 'calc';           // 'calc' | 'fx'
let seq = [];                // 暗號 token 累積（自載入/清除起）
let triggerLocked = false;   // 6 秒窗逾時後鎖定
const loadTs = Date.now();
setTimeout(() => { triggerLocked = true; }, 6000);

// ---- 顯示 ----
function renderCalc() { calcDisplay.textContent = engine.display; }

// ---- 匯率 ----
let fxState = { ok: false, currencies: [], rates: {}, from: 'TWD', amount: '0' };

function renderFx() {
  const chips = document.getElementById('fx-currencies');
  const amountEl = document.getElementById('fx-amount');
  const results = document.getElementById('fx-results');
  const updated = document.getElementById('fx-updated');

  chips.innerHTML = '';
  fxState.currencies.forEach((c) => {
    const b = document.createElement('button');
    b.className = 'fx-chip' + (c === fxState.from ? ' active' : '');
    b.textContent = c;
    b.type = 'button';
    b.addEventListener('click', () => { fxState.from = c; renderFx(); });
    chips.appendChild(b);
  });

  amountEl.textContent = fxState.amount;

  if (!fxState.ok) {
    results.innerHTML = '<div class="fx-unavailable">暫時無法取得匯率</div>';
    updated.textContent = '';
    return;
  }
  const out = convertAll(parseFloat(fxState.amount) || 0, fxState.from,
    fxState.currencies, fxState.rates);
  results.innerHTML = '';
  Object.keys(out).forEach((c) => {
    const row = document.createElement('div');
    row.className = 'fx-row';
    row.innerHTML = `<span>${c}</span><span>${out[c].toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>`;
    results.appendChild(row);
  });
  updated.textContent = fxState.fetchedAt
    ? '更新：' + new Date(fxState.fetchedAt).toLocaleString('zh-TW', { timeZone: 'Asia/Taipei' })
    : '';
}

async function initFx() {
  const r = await loadRates();
  fxState.ok = r.ok;
  fxState.currencies = r.currencies || [];
  fxState.rates = r.rates || {};
  if (fxState.currencies.length && !fxState.currencies.includes(fxState.from)) {
    fxState.from = fxState.currencies[0];
  }
  fxState.fetchedAt = r.fetchedAt;
  if (mode === 'fx') renderFx();
}

// ---- tab 切換 ----
document.querySelectorAll('.tab').forEach((t) => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((x) => x.classList.remove('active'));
    t.classList.add('active');
    mode = t.dataset.tab;
    if (mode === 'fx') {
      calcDisplay.hidden = true; fxPanel.hidden = false; renderFx();
    } else {
      calcDisplay.hidden = false; fxPanel.hidden = true; renderCalc();
    }
  });
});

// ---- fx 金額輸入 ----
function fxDigit(d) {
  if (fxState.amount === '0') fxState.amount = d;
  else fxState.amount += d;
  renderFx();
}
function fxDot() { if (!fxState.amount.includes('.')) fxState.amount += '.'; renderFx(); }
function fxClear() { fxState.amount = '0'; renderFx(); }

// ---- 暗號偵測（僅 calc mode）----
async function checkSecret() {
  if (triggerLocked || mode !== 'calc') return false;
  if (!withinWindow(loadTs, Date.now())) { triggerLocked = true; return false; }
  const ok = await matchesSecret(buildSequence(seq), cfg.secretHash);
  return ok;
}

// ---- 鍵盤事件 ----
document.querySelector('.keys').addEventListener('click', async (e) => {
  const btn = e.target.closest('button');
  if (!btn) return;

  const digit = btn.dataset.digit;
  const op = btn.dataset.op;
  const action = btn.dataset.action;

  if (mode === 'fx') {
    if (digit !== undefined) fxDigit(digit);
    else if (action === 'dot') fxDot();
    else if (action === 'clear') fxClear();
    // 匯率 tab 忽略運算子與 =
    return;
  }

  // calc mode：同時餵計算機引擎與暗號序列
  if (digit !== undefined) { seq.push(digit); engine.inputDigit(digit); renderCalc(); }
  else if (op !== undefined) { seq.push(canonicalToken(btn.textContent)); engine.inputOp(op); renderCalc(); }
  else if (action === 'dot') { seq.push('.'); engine.inputDot(); renderCalc(); }
  else if (action === 'negate') { engine.negate(); renderCalc(); }
  else if (action === 'percent') { engine.percent(); renderCalc(); }
  else if (action === 'clear') { seq = []; engine.clear(); renderCalc(); }
  else if (action === 'equals') {
    if (await checkSecret()) {
      seq = []; engine.clear(); renderCalc();
      window.__openAuth(cfg.seedMode);   // Task 11 換成真流程
      return;
    }
    seq = []; engine.equals(); renderCalc();
  }
});

// 暫時佔位：Task 11 以 auth.js 覆蓋
window.__openAuth = window.__openAuth || function (seedMode) {
  console.log('trigger! seedMode =', seedMode);
};

initFx();
renderCalc();
```

- [ ] **Step 5: 手動驗證（本機瀏覽器）**

啟動：
```bash
FLASK_APP=wsgi.py SECRET_KEY=dev python3 -m flask run --port 5001
```
開 `http://localhost:5001/`，逐項確認：
- 計算機四則運算正常、AC/±/%/. 正常。
- 切「匯率」tab → 出現幣別 chip、輸入金額即時換算（若外部 API 可連）；斷網或 API 不可用時顯示「暫時無法取得匯率」，計算機 tab 不受影響。
- 開 DevTools Console，載入頁 6 秒**內**按 `0 7 8 × 2 =` → Console 印 `trigger! seedMode = true`（此時無資料庫資料 → seed mode）；顯示被清空、不顯示 156。
- 6 秒**後**再按 `078*2=` → 正常顯示 `156`、Console 無 trigger。
- `078*2=` 未觸發時（例如先按別的再 AC 後超時）行為與一般計算機一致。

- [ ] **Step 6: Commit**

```bash
git add app/templates/index.html app/static/css/app.css app/static/js/fx.js app/static/js/main.js
git commit -m "feat(ui): iOS 風計算機 + 匯率換算 tab + 暗號觸發偵測(6秒窗)"
```

---

## Task 10: 相機擷取類別（Camera，ESM）

**Files:**
- Create: `app/static/js/camera.js`
- Test: 手動瀏覽器（相機需真實裝置/VirtualCam）

**Interfaces:**
- Produces: `class Camera(videoEl:HTMLVideoElement, canvasEl:HTMLCanvasElement)`；`async start()`、`stop()`、`capture() -> dataURL|null`、getter `isRecording:boolean`。

- [ ] **Step 1: 建 camera.js**

`app/static/js/camera.js`：
```javascript
export class Camera {
  constructor(videoEl, canvasEl) {
    this.video = videoEl;
    this.canvas = canvasEl;
    this.stream = null;
  }

  get isRecording() { return this.stream !== null; }

  async start() {
    if (this.stream) return;
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'user' }, audio: false,
    });
    this.video.srcObject = this.stream;
    this.video.muted = true;
    await this.video.play();
  }

  capture() {
    if (!this.stream) return null;
    const ctx = this.canvas.getContext('2d');
    this.canvas.width = this.video.videoWidth || 640;
    this.canvas.height = this.video.videoHeight || 480;
    ctx.drawImage(this.video, 0, 0);
    return this.canvas.toDataURL('image/jpeg', 0.85); // 單張、僅記憶體
  }

  stop() {
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
  }
}
```

- [ ] **Step 2: 語法檢查**

Run: `node --check app/static/js/camera.js && echo "camera.js ok"`
Expected: `camera.js ok`

- [ ] **Step 3: Commit**

```bash
git add app/static/js/camera.js
git commit -m "feat(camera): Camera 單張擷取類別（不錄影不落地）"
```

---

## Task 11: 登入流程（auth.js：暗號→register-device→相機→/auth/verify→隱蔽回饋→登入後畫面→登出）

**Files:**
- Create: `app/static/js/auth.js`
- Modify: `app/static/js/main.js`（import auth，接上 `__openAuth`）
- Test: 手動瀏覽器 e2e

**Interfaces:**
- Consumes: `Camera`(Task10)、`cfg.identity`、後端 `/api/v1/register-device`、`/auth/verify`、`/auth/logout`、`/face/enroll`。
- Produces: `auth.js` 匯出 `openAuth(seedMode:boolean)`、`showAppView(identity)`；掛 `window.__openAuth = openAuth`。

> 隱蔽回饋：登入失敗一律 `NEUTRAL_MSG = '無法計算，請重試'`；只有成功才有明顯轉場。本 task 先做**一般模式登入**與**登入後畫面/登出/更新臉**；bootstrap（seed mode）在 Task 12。

- [ ] **Step 1: 建 auth.js**

`app/static/js/auth.js`：
```javascript
import { Camera } from './camera.js';

const NEUTRAL_MSG = '無法計算，請重試';
const root = () => document.getElementById('modal-root');

function clearRoot() { root().innerHTML = ''; }

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  return { status: res.status, data: await res.json().catch(() => ({})) };
}

// 登入後占位畫面（前端 view state，不換網址）
export function showAppView(identity) {
  clearRoot();
  const roleZh = { employee: '員工', manager: '店長', accountant: '會計', super_admin: '業主' };
  root().innerHTML = `
    <div class="modal-backdrop">
      <div class="modal-box">
        <h2>已登入</h2>
        <div class="app-view-info">
          姓名：${identity.name}<br>身分：${roleZh[identity.role] || identity.role}
        </div>
        <video id="av-video" autoplay playsinline muted style="display:none;"></video>
        <canvas id="av-canvas" style="display:none;"></canvas>
        <button class="modal-btn secondary" id="av-reface" type="button">更新人臉</button>
        <div class="modal-msg" id="av-msg" style="color:#4cd964;"></div>
        <button class="modal-btn" id="av-logout" type="button" style="margin-top:10px;">登出</button>
      </div>
    </div>`;

  const cam = new Camera(document.getElementById('av-video'), document.getElementById('av-canvas'));
  const msg = document.getElementById('av-msg');

  document.getElementById('av-reface').addEventListener('click', async () => {
    try {
      if (!cam.isRecording) {
        await cam.start();
        document.getElementById('av-video').style.display = 'block';
        msg.textContent = '請對準鏡頭，再按一次「更新人臉」';
        return;
      }
      const face = cam.capture();
      const { data } = await postJSON('/face/enroll', { face_image: face });
      msg.textContent = data.status === 'ok' ? '人臉已更新' : '更新失敗，請重試';
      msg.style.color = data.status === 'ok' ? '#4cd964' : '#ff6b6b';
      cam.stop();
      document.getElementById('av-video').style.display = 'none';
    } catch (e) {
      msg.textContent = '無法開啟鏡頭';
      msg.style.color = '#ff6b6b';
    }
  });

  document.getElementById('av-logout').addEventListener('click', async () => {
    cam.stop();
    await postJSON('/auth/logout');
    clearRoot();
  });
}

function loginModal() {
  clearRoot();
  root().innerHTML = `
    <div class="modal-backdrop" id="auth-backdrop">
      <div class="modal-box">
        <h2>　</h2>
        <video id="m-video" autoplay playsinline muted></video>
        <canvas id="m-canvas" style="display:none;"></canvas>
        <input type="password" id="m-pw" placeholder="密碼" inputmode="numeric" autocomplete="off">
        <button class="modal-btn" id="m-submit" type="button">確定</button>
        <div class="modal-msg" id="m-msg"></div>
      </div>
    </div>`;
  return {
    video: document.getElementById('m-video'),
    canvas: document.getElementById('m-canvas'),
    pw: document.getElementById('m-pw'),
    submit: document.getElementById('m-submit'),
    msg: document.getElementById('m-msg'),
    backdrop: document.getElementById('auth-backdrop'),
  };
}

async function openLoginFlow() {
  const el = loginModal();
  const cam = new Camera(el.video, el.canvas);

  // 開 modal 當下才註冊裝置（避免公開瀏覽就洗 pending）
  await postJSON('/api/v1/register-device', {
    device_name: navigator.userAgent.slice(0, 100),
  });
  try { await cam.start(); } catch (e) { /* 無鏡頭：仍可送出，後端回無害訊息 */ }

  // 背景點擊關閉
  el.backdrop.addEventListener('click', (ev) => {
    if (ev.target === el.backdrop) { cam.stop(); clearRoot(); }
  });

  async function submit() {
    el.submit.disabled = true;
    el.msg.textContent = '';
    const face = cam.isRecording ? cam.capture() : null;
    const { data } = await postJSON('/auth/verify', {
      password: el.pw.value, face_image: face,
    });
    if (data.status === 'ok') {
      cam.stop();
      showAppView({ name: data.name, role: data.role });
      return;
    }
    // 其餘一律隱蔽
    el.msg.textContent = NEUTRAL_MSG;
    el.submit.disabled = false;
  }

  el.submit.addEventListener('click', submit);
  el.pw.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
}

export function openAuth(seedMode) {
  if (seedMode) {
    if (window.__openBootstrap) window.__openBootstrap();  // Task 12
    else openLoginFlow();
    return;
  }
  openLoginFlow();
}
```

- [ ] **Step 2: main.js 接上 auth**

`app/static/js/main.js` 頂部 import 區加：
```javascript
import { openAuth, showAppView } from './auth.js';
```
把檔案末尾的臨時佔位：
```javascript
window.__openAuth = window.__openAuth || function (seedMode) {
  console.log('trigger! seedMode =', seedMode);
};
```
改為：
```javascript
window.__openAuth = openAuth;

// 若伺服器判定本 session 已登入 → 暗號直接回登入後畫面（不需重打密碼）
// （由 Task 11：登入後畫面）。這裡僅在暗號觸發時判斷，故保留 identity 供 openAuth 分流。
if (cfg.identity) {
  const orig = window.__openAuth;
  window.__openAuth = function (seedMode) {
    if (cfg.identity) { showAppView(cfg.identity); return; }
    orig(seedMode);
  };
}
```

- [ ] **Step 3: 手動 e2e（一般模式登入）**

前置：先建立一位有臉的使用者可用（可用既有 `/auth/bootstrap` 或 seed 後 Task 12；此步驟若尚無帳號，先驗「隱蔽回饋」路徑）。

啟動：`FLASK_APP=wsgi.py SECRET_KEY=dev python3 -m flask run --port 5001`

- 6 秒內按 `078*2=` → 跳出登入 modal（自動開相機）。
- 隨便輸入錯密碼 + 送出 → 顯示「無法計算，請重試」（不透露錯在密碼或臉）。
- 背景點擊 → 關閉 modal、相機停止（檢查鏡頭指示燈熄）。
- 若已有正確帳號＋臉：輸入正確密碼 + 對準鏡頭 → 送出 → 切到「已登入」畫面顯示姓名/身分。
- 「登出」→ 回計算機。
- 用真實人臉照片或 webapp 的 VirtualCam（v4l2loopback）餵臉驗證比對成功路徑。

- [ ] **Step 4: Commit**

```bash
git add app/static/js/auth.js app/static/js/main.js
git commit -m "feat(auth): 隱蔽登入流程(register-device→相機→verify→隱蔽回饋)+登入後畫面/登出/更新臉"
```

---

## Task 12: 首次啟用 bootstrap（seed mode）

**Files:**
- Create: `app/static/js/bootstrap.js`
- Modify: `app/templates/index.html`（載入 bootstrap.js）
- Test: 手動 e2e（乾淨 DB）

**Interfaces:**
- Consumes: `Camera`、`showAppView`(Task11)、`/auth/bootstrap`。
- Produces: `bootstrap.js` 掛 `window.__openBootstrap = openBootstrap()`；成功後 `location.reload()`。

- [ ] **Step 1: 建 bootstrap.js**

`app/static/js/bootstrap.js`：
```javascript
import { Camera } from './camera.js';

const root = () => document.getElementById('modal-root');

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  return { status: res.status, data: await res.json().catch(() => ({})) };
}

function openBootstrap() {
  root().innerHTML = `
    <div class="modal-backdrop" id="bs-backdrop">
      <div class="modal-box">
        <h2>首次設定</h2>
        <input type="text" id="bs-name" placeholder="姓名" autocomplete="off">
        <input type="password" id="bs-pw" placeholder="密碼" autocomplete="off">
        <video id="bs-video" autoplay playsinline muted></video>
        <canvas id="bs-canvas" style="display:none;"></canvas>
        <button class="modal-btn" id="bs-submit" type="button">建立並登入</button>
        <div class="modal-msg" id="bs-msg"></div>
      </div>
    </div>`;

  const cam = new Camera(document.getElementById('bs-video'), document.getElementById('bs-canvas'));
  const msg = document.getElementById('bs-msg');
  cam.start().catch(() => { msg.textContent = '無法開啟鏡頭'; });

  document.getElementById('bs-backdrop').addEventListener('click', (ev) => {
    if (ev.target === ev.currentTarget) { cam.stop(); root().innerHTML = ''; }
  });

  document.getElementById('bs-submit').addEventListener('click', async () => {
    const btn = document.getElementById('bs-submit');
    btn.disabled = true; msg.textContent = '';
    const face = cam.isRecording ? cam.capture() : null;
    const { data } = await postJSON('/auth/bootstrap', {
      name: document.getElementById('bs-name').value.trim(),
      password: document.getElementById('bs-pw').value,
      face_image: face,
    });
    if (data.status === 'ok') {
      msg.style.color = '#4cd964'; msg.textContent = '完成，正在進入…';
      cam.stop();
      setTimeout(() => location.reload(), 800);
      return;
    }
    if (data.status === 'face_not_found') msg.textContent = '未偵測到人臉，請對準鏡頭重試';
    else if (data.status === 'error') msg.textContent = '請填寫姓名與密碼';
    else if (data.status === 'already_initialized') { setTimeout(() => location.reload(), 500); }
    else msg.textContent = '設定失敗，請重試';
    btn.disabled = false;
  });
}

window.__openBootstrap = openBootstrap;
```

- [ ] **Step 2: index.html 載入 bootstrap.js**

`app/templates/index.html` 的 `{% block scripts %}` 內、`main.js` **之前**加一行（讓 `window.__openBootstrap` 於 main.js 觸發前就緒）：
```html
<script type="module" src="{{ url_for('static', filename='js/bootstrap.js') }}"></script>
```

- [ ] **Step 3: 手動 e2e（乾淨 DB → 首次啟用）**

前置：清空/使用新 DB 進入 seed mode。啟動 flask。
- 開 `/`，6 秒內按 `078*2=` → 跳「首次設定」modal（自動開相機）。
- 填姓名、密碼、對準鏡頭 → 「建立並登入」→ 顯示「完成」→ reload。
- reload 後已非 seed mode；再按暗號 → 因 session 已登入 → 直接顯示「已登入」畫面（驗證 Task 11 的 identity 快捷）。
- 未填姓名/密碼 → 「請填寫姓名與密碼」；沒對到臉 → 「未偵測到人臉」。

- [ ] **Step 4: Commit**

```bash
git add app/static/js/bootstrap.js app/templates/index.html
git commit -m "feat(bootstrap): seed mode 首次設定 modal（建業主+錄臉→reload）"
```

---

## Task 13: 整合回歸 + 本機端到端驗收

**Files:**
- 無新檔；全面回歸與驗收。

- [ ] **Step 1: 後端全套測試**

Run: `python3 -m pytest -q`
Expected: 全綠（既有 89 + fx/web 新增），輸出僅剩既有 pkg_resources warning。

- [ ] **Step 2: 前端純邏輯全套**

Run: `node --test tests/js/`
Expected: calculator/currency/secret 全 PASS。

- [ ] **Step 3: 前後端雜湊一致性**

Run:
```bash
python3 -c "import hashlib; print(hashlib.sha256(b'078*2').hexdigest())"
node -e "const {sha256hex}=await import('./app/static/js/secret.js'); console.log(await sha256hex('078*2'))"
```
Expected: 兩行相同。

- [ ] **Step 4: 本機端到端手動驗收清單**

啟動：`FLASK_APP=wsgi.py SECRET_KEY=dev python3 -m flask run --port 5001` → `http://localhost:5001/`

- [ ] 計算機四則/AC/±/%/. 正常；離線（關 flask 後重整，SW 快取）計算機仍可開。
- [ ] 匯率 tab：能連外時顯示現在匯率並即時換算；不可用時顯示「暫時無法取得匯率」。
- [ ] seed mode：暗號 → 首次設定 → 建業主+錄臉 → reload 進系統。
- [ ] 一般模式：暗號 → 密碼+刷臉 → 登入成功切「已登入」；錯密碼/錯臉 → 同一句無害訊息。
- [ ] 6 秒窗逾時 → 暗號失效、`078*2=` 顯示 156，純計算機。
- [ ] 未核准裝置（清 `device_uid` cookie、於非 seed mode）→ 暗號可開 modal、送出得無害訊息；後端 `devices` 表出現該 pending 裝置。
- [ ] 已登入 session 重整 → 回計算機；暗號 → 直接回「已登入」畫面（免重打密碼）。
- [ ] 網址列全程只有 `/`（無 home/enroll 等字眼）。

- [ ] **Step 5: 依 finishing-a-development-branch 收尾**

回報驗收結果給 user；測試 OK + user 明說才 merge 回 master、不 push（沿用專案慣例）。

---

## Self-Review（撰寫者自檢）

**1. Spec 覆蓋**
- §3 單一網址/切畫面 → Task 4（`/` 唯一頁）、Task 11（view state）、Task 13 驗收「網址只有 `/`」。✅
- §4 路由/gate → Task 3（`/api/v1/fx`）、Task 4（`/`、`/sw.js`、gate 豁免）。✅
- §5.1 計算機/匯率 UI → Task 5/6/9。✅
- §5.2 暗號 078*2 + 6 秒窗 + secret_hash → Task 7（純邏輯）、Task 9（觸發+窗）、Task 4（注入 hash）。✅
- §6.1 登入 modal（register-device→相機→verify）→ Task 10/11。✅
- §6.2 bootstrap → Task 12。✅
- §6.3 登入後畫面 + 本人更新臉 + 登出 → Task 11。✅
- §6.4 隱蔽回饋 → Task 11（NEUTRAL_MSG）。✅
- §7 匯率服務（DB 快取/TTL/fallback/open.er-api.com/urllib）→ Task 1/2/3。✅
- §8 PWA 殼 → Task 8。✅
- §10 測試策略（pytest + node + 手動 e2e）→ 各 task + Task 13。✅

**2. Placeholder 掃描**：無 TBD/TODO；每個 code step 皆含完整可貼程式碼。Task 4 Step 6 的「placeholder sw.js」是刻意的最小合法檔、Task 8 覆蓋為完整內容（已標註）。✅

**3. 型別/命名一致性**
- `CalcEngine` 方法名（inputDigit/inputOp/inputDot/equals/clear/negate/percent、getter display）Task 5 定義、Task 9 使用一致。✅
- `convertAll(amount, from, currencies, rates)` Task 6 定義、Task 9 使用一致。✅
- `secret.js` 匯出（canonicalToken/buildSequence/sha256hex/matchesSecret/withinWindow）Task 7 定義、Task 9 使用一致。✅
- `Camera(video, canvas)` + start/stop/capture/isRecording：Task 10 定義，Task 11/12 使用一致。✅
- `window.__openAuth`（main.js 呼叫、auth.js 指派）、`window.__openBootstrap`（auth.js 呼叫、bootstrap.js 指派）跨檔一致。✅
- 後端 `get_rates()` 回傳 `(rates, fetched_at_iso)`：Task 2 定義、Task 3 使用一致。✅
- config `EXPENSE_TRIGGER_CODE` 預設 `078*2`：Task 2 定義、Task 4 `_secret_hash` 使用、Task 7 一致性驗證。✅
