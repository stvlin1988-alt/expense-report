# Phase 1 Auth & Device Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建好 expense-report 的認證子系統：裝置綁定 + 免帳號「密碼＋人臉 best-match」登入 + 30 分鐘 idle session + 後台管理（店/帳號/密碼/裝置），dlib 走預編 wheel 零編譯 build。

**Architecture:** 沿用 Plan 1 的 Flask app-factory + SQLAlchemy 2.x + Flask-Migrate。認證兩層：`device_uid`（持久 cookie，認證唯一依據，`before_request` 裝置閘）+ session（30 分 idle，`before_request` idle 閘）。人臉比對在伺服器端用 `face_recognition`(dlib)：登入/錄臉的單張畫面僅在記憶體、算完 128 維 encoding 即丟，DB 只存向量。`fingerprint` 僅存供稽核、永不參與認證。

**Tech Stack:** Python 3.12, Flask 3.1.x, Flask-SQLAlchemy 3.1.x, SQLAlchemy 2.0.x, Flask-Migrate 4.x, `face_recognition`, `dlib`(預編 wheel), `face_recognition_models`(預編 wheel), `numpy`, `Pillow`, `Flask-Limiter`, pytest 8.x。部署 Zeabur（Dockerfile，2CPU/8GB 無 GPU）。

設計來源：`docs/superpowers/specs/2026-07-02-auth-device-design.md`。

## Global Constraints

- 與 webapp **完全隔離**：參考其做法**重寫**，不 import、不連其 DB/R2。
- 依賴**鎖版**（鬆 pin）列於 `requirements.txt`；`dlib`/`face_recognition_models` 由 `wheels/` 預編 wheel 提供，**不列 pip 版本解析**。
- **fingerprint 永不作認證判斷**：只寫入 `Device.fingerprint` 供稽核；認證一律用 `client_uid`。
- **影像不落地**：登入/錄臉單張畫面僅記憶體、算完 encoding 即丟；DB 只存 128 維 `float64` bytes，無任何照片。
- **前端不輪詢**：idle 逾時純伺服器端判定（`before_request`）。
- **狀態全進 DB / session cookie**：不用 module-level dict 存跨 request 狀態（workers>1）。
- 時間存 **UTC**（`datetime.now(timezone.utc)`）。
- 角色 enum 固定：`employee | manager | accountant | super_admin`。**manager = 本店 scope 後台管理者**；**super_admin = 全域（含開店、調店切換）**；accountant 專責帳務無後台；employee 無後台。
- best-match 參數：`threshold=0.45`、`ambiguous_margin=0.05`。
- session：`SESSION_COOKIE_HTTPONLY=True`、`SESSION_COOKIE_SAMESITE="Lax"`、`SESSION_COOKIE_SECURE` 由 env 控、`PERMANENT_SESSION_LIFETIME=timedelta(minutes=35)`、idle 上限 **30 分鐘（1800 秒）滑動**。
- `device_uid` cookie：httpOnly、Secure、SameSite=Lax、max_age 10 年。
- config 檔（Dockerfile / zbpack.json / requirements）commit 前驗證可用（`docker build` 或至少 `pip install` 成功、`python -c import`）。
- 每個 task 結束都 commit。
- **範圍外（後續前端 plan）**：登入頁 UI（Apple 計算機＋幣別換算落地頁）、相機擷取 JS、後台 HTML 模板。本 plan 只做後端 API + models + gates，全程以 test client + mock `face_recognition` 驗證。

---

### Task 1: Build 基礎 — 預編 wheel + Dockerfile + 依賴 + pkg_resources shim

**Files:**
- Create: `wheels/dlib-20.0.1-cp312-cp312-linux_x86_64.whl`（自 webapp 複製）
- Create: `wheels/face_recognition_models-0.3.0-py2.py3-none-any.whl`（自 webapp 複製）
- Modify: `requirements.txt`
- Create: `Dockerfile`
- Create: `zbpack.json`
- Modify: `wsgi.py`（加 pkg_resources shim）
- Create: `tests/test_face_runtime.py`

**Interfaces:**
- Produces: 可 `import dlib`、`import face_recognition`、`import face_recognition_models` 的 runtime；`Dockerfile` build 時 dlib 零編譯。

- [ ] **Step 1: 複製預編 wheel**

```bash
mkdir -p wheels
cp /home/hirain0126/projects/webapp/app_unified/wheels/dlib-20.0.1-cp312-cp312-linux_x86_64.whl wheels/
cp /home/hirain0126/projects/webapp/app_unified/wheels/face_recognition_models-0.3.0-py2.py3-none-any.whl wheels/
ls -lh wheels/
```
Expected: 兩個 .whl（約 3.9M + 96M）。

- [ ] **Step 2: 本機安裝 wheel + 依賴（供 dev/測試 import）**

```bash
python3 -m pip install --no-deps wheels/dlib-20.0.1-cp312-cp312-linux_x86_64.whl wheels/face_recognition_models-0.3.0-py2.py3-none-any.whl
python3 -m pip install "face_recognition==1.3.*" "numpy==2.*" "Pillow==11.*" "Flask-Limiter==3.*"
```
說明：`--no-deps` 裝 wheel 避免 pip 解析去編譯 dlib；`face_recognition` 純 Python，dlib/models 已由 wheel 滿足。若 `numpy==2.*` 與既有相依衝突，改裝 `numpy==1.26.*` 並在報告註明。

- [ ] **Step 3: 更新 requirements.txt**

在 `requirements.txt` 末尾加（保持�byte-for-byte 鬆 pin 風格）：
```
face_recognition==1.3.*
numpy==2.*
Pillow==11.*
Flask-Limiter==3.*
```
（`dlib` 與 `face_recognition_models` 不列此檔，改由 `wheels/` 提供。若 Step 2 改用 numpy 1.26，此處同步改 `numpy==1.26.*`。）

- [ ] **Step 4: 寫 pkg_resources shim（wsgi.py）**

在 `wsgi.py` 頂端（`from app import create_app` 之前）插入：
```python
# face_recognition_models 需要 pkg_resources.resource_filename；新版 setuptools 移除了 pkg_resources
import sys
import types

try:
    import pkg_resources  # noqa: F401
except Exception:
    import importlib.util as _ilu

    def _resource_filename(package_or_requirement, resource_name):
        spec = _ilu.find_spec(package_or_requirement)
        if spec and spec.submodule_search_locations:
            import os
            return os.path.join(list(spec.submodule_search_locations)[0], resource_name)
        raise FileNotFoundError(resource_name)

    _shim = types.ModuleType("pkg_resources")
    _shim.resource_filename = _resource_filename
    sys.modules["pkg_resources"] = _shim
```

- [ ] **Step 5: 寫 Dockerfile**

`Dockerfile`:
```dockerfile
FROM python:3.12-slim

LABEL "language"="python"
LABEL "framework"="flask"

# dlib runtime 相依
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    libopenblas0 \
    liblapack3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# 預編 wheel — 零編譯、排在 app code 之前吃 layer cache
COPY wheels/ /tmp/wheels/
RUN pip install --no-cache-dir --no-deps /tmp/wheels/*.whl && rm -rf /tmp/wheels

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 驗證 dlib 已裝好（零編譯）
RUN python -c "import dlib; print('dlib OK')"

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app && \
    chown -R appuser:appuser /usr/local/lib/python3.12/site-packages
USER appuser

EXPOSE 8080
ENV PYTHONUNBUFFERED=1
ENV SESSION_COOKIE_SECURE=true

CMD ["gunicorn", "-b", "0.0.0.0:8080", "wsgi:app"]
```
注意：`gunicorn` 需在 requirements.txt（若尚未有則加 `gunicorn==23.*` 並本機 `pip install`）。

- [ ] **Step 6: 寫 zbpack.json**

`zbpack.json`:
```json
{
  "use_dockerfile": true
}
```
驗證 JSON 合法：`python3 -c "import json; json.load(open('zbpack.json'))"` → 無錯。

- [ ] **Step 7: 寫 runtime import 測試**

`tests/test_face_runtime.py`:
```python
def test_face_libs_importable():
    import dlib          # noqa: F401
    import face_recognition  # noqa: F401
    import face_recognition_models  # noqa: F401


def test_pkg_resources_available_after_wsgi_shim():
    import wsgi  # noqa: F401  匯入 wsgi 觸發 shim
    import pkg_resources
    assert hasattr(pkg_resources, "resource_filename")
```

- [ ] **Step 8: 跑測試確認 PASS**

Run: `python3 -m pytest tests/test_face_runtime.py -v`
Expected: PASS（若本機無法裝 dlib wheel，於報告 BLOCKED 並附錯誤；否則綠燈）。

- [ ] **Step 9: Commit**

```bash
git add wheels/ requirements.txt Dockerfile zbpack.json wsgi.py tests/test_face_runtime.py
git commit -m "build: 預編 dlib/face_recognition wheel + Dockerfile (零編譯 build)"
```

---

### Task 2: 認證資料模型 — Device 新表 + User.face_encoding + 遷移

**Files:**
- Create: `app/models/device.py`
- Modify: `app/models/user.py`（加 `face_encoding` 欄位）
- Modify: `app/models/__init__.py`（掛 `Device`）
- Create: `tests/test_models_device.py`

**Interfaces:**
- Consumes: `db`（`app/extensions.py`）、`create_app(TestConfig)`。
- Produces: `Device(id, store_id, bound_user_id, client_uid, fingerprint, device_name, is_approved, is_revoked, last_seen_at, created_at)`；`User.face_encoding`（`LargeBinary`, nullable）。

- [ ] **Step 1: 寫失敗測試**

`tests/test_models_device.py`:
```python
import numpy as np
from app.extensions import db
from app.models.device import Device
from app.models.user import User


def test_create_device_defaults(app):
    with app.app_context():
        db.create_all()
        d = Device(client_uid="uid-123", fingerprint="fp-abc", device_name="門市iPad")
        db.session.add(d)
        db.session.commit()
        assert d.id is not None
        assert d.is_approved is False
        assert d.is_revoked is False
        assert d.created_at is not None
        assert d.last_seen_at is not None


def test_client_uid_unique(app):
    with app.app_context():
        db.create_all()
        db.session.add(Device(client_uid="dup"))
        db.session.commit()
        db.session.add(Device(client_uid="dup"))
        import pytest, sqlalchemy
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_user_face_encoding_roundtrip(app):
    with app.app_context():
        db.create_all()
        enc = np.arange(128, dtype=np.float64)
        u = User(name="小明", role="employee")
        u.face_encoding = enc.tobytes()
        db.session.add(u)
        db.session.commit()
        back = np.frombuffer(u.face_encoding, dtype=np.float64)
        assert back.shape == (128,)
        assert np.allclose(back, enc)
```

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python3 -m pytest tests/test_models_device.py -v`
Expected: FAIL（`app.models.device` 不存在 / `face_encoding` 無此欄位）。

- [ ] **Step 3: 寫 Device model**

`app/models/device.py`:
```python
from datetime import datetime, timezone
from app.extensions import db


class Device(db.Model):
    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey("stores.id"), nullable=True)
    bound_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    client_uid = db.Column(db.String(64), unique=True, nullable=False)
    fingerprint = db.Column(db.Text, nullable=True)  # 僅稽核，永不作認證判斷
    device_name = db.Column(db.String(100), nullable=False, default="Unknown")
    is_approved = db.Column(db.Boolean, nullable=False, default=False)
    is_revoked = db.Column(db.Boolean, nullable=False, default=False)
    last_seen_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    store = db.relationship("Store")
    bound_user = db.relationship("User", foreign_keys=[bound_user_id])
```

- [ ] **Step 4: 加 User.face_encoding**

在 `app/models/user.py` 的 `User` class 內（欄位區，例如 `password_hash` 之後）加：
```python
    face_encoding = db.Column(db.LargeBinary, nullable=True)  # 128-d float64 bytes；不存影像
```

- [ ] **Step 5: 掛進 models __init__**

在 `app/models/__init__.py` 加 `from app.models.device import Device` 並補進 `__all__`。

- [ ] **Step 6: 跑測試確認 PASS**

Run: `python3 -m pytest tests/test_models_device.py -v`
Expected: PASS

- [ ] **Step 7: 產遷移 + Commit**

```bash
export FLASK_APP=wsgi.py
flask db migrate -m "devices + user face_encoding"
flask db upgrade
```
開啟 `migrations/versions/*_devices_user_face_encoding.py` 確認 `create_table('devices')`（含 client_uid unique、self/FK）與 `add_column('users', 'face_encoding')` 都在、非空。
```bash
git add app/ tests/ migrations/
git commit -m "feat: Device model + User.face_encoding + migration"
```

---

### Task 3: 人臉引擎 — best-match 純函式 + encode wrapper（可 mock）

**Files:**
- Create: `app/face/__init__.py`
- Create: `app/face/engine.py`
- Create: `tests/test_face_engine.py`

**Interfaces:**
- Consumes: `face_recognition`、`numpy`。
- Produces:
  - `best_match_among(candidates, submitted_encoding, threshold=0.45, ambiguous_margin=0.05) -> tuple[object | None, dict]`：`candidates` 為有 `.face_encoding`(bytes) 屬性的物件序列；回 `(matched_or_None, info)`，`info` 含 `best_dist`/`second_dist`/`ambiguous`/`reason`。
  - `encode_face(image_bytes: bytes) -> "numpy.ndarray | None"`：解碼單張圖算 128 維 encoding；無臉回 None。
  - `encode_face_async(image_bytes: bytes, timeout: float = 15.0) -> "numpy.ndarray | None"`：在 thread executor 跑 `encode_face`，逾時回 None。
  - `FACE_AVAILABLE: bool`。

- [ ] **Step 1: 寫失敗測試（best-match 純函式，用假 encoding）**

`tests/test_face_engine.py`:
```python
import numpy as np
from app.face.engine import best_match_among


class _Cand:
    def __init__(self, name, vec):
        self.name = name
        self.face_encoding = np.asarray(vec, dtype=np.float64).tobytes()


def _vec(fill):
    return np.full(128, float(fill), dtype=np.float64)


def test_best_match_picks_closest_within_threshold():
    submitted = _vec(0.0)
    cands = [_Cand("a", _vec(0.0)), _Cand("b", _vec(5.0))]
    matched, info = best_match_among(cands, submitted)
    assert matched.name == "a"
    assert info["best_dist"] < 0.45


def test_no_match_when_all_beyond_threshold():
    submitted = _vec(0.0)
    cands = [_Cand("a", _vec(9.0))]
    matched, info = best_match_among(cands, submitted)
    assert matched is None
    assert info["best_dist"] > 0.45


def test_ambiguous_close_call_rejected():
    # 兩個候選與 submitted 距離幾乎相同 → 撞臉整批拒
    submitted = _vec(0.0)
    v = np.zeros(128); v[0] = 0.30
    v2 = np.zeros(128); v2[0] = 0.31
    cands = [_Cand("a", v), _Cand("b", v2)]
    matched, info = best_match_among(cands, submitted)
    assert matched is None
    assert info.get("ambiguous") is True


def test_empty_candidates():
    matched, info = best_match_among([], _vec(0.0))
    assert matched is None
    assert info.get("reason") == "no enrolled users"
```

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python3 -m pytest tests/test_face_engine.py -v`
Expected: FAIL（模組不存在）。

- [ ] **Step 3: 寫 engine**

`app/face/__init__.py`:
```python
```
（空檔，套件標記）

`app/face/engine.py`:
```python
import io
import logging
from concurrent.futures import ThreadPoolExecutor

import numpy as np

logger = logging.getLogger(__name__)

try:
    import face_recognition_models  # noqa: F401  觸發 pkg_resources shim 使用
    import face_recognition
    FACE_AVAILABLE = True
except Exception as _e:  # pragma: no cover - 環境相依
    logger.warning("face_recognition unavailable: %s", _e)
    FACE_AVAILABLE = False

_executor = ThreadPoolExecutor(max_workers=2)


def best_match_among(candidates, submitted_encoding,
                     threshold: float = 0.45,
                     ambiguous_margin: float = 0.05):
    """從 candidates 選 face_distance 最低且 < threshold 者；前兩名距離差
    < ambiguous_margin 視為撞臉、整批拒。candidates 需有 .face_encoding(bytes)。"""
    submitted = np.asarray(submitted_encoding, dtype=np.float64)
    scored = []
    for c in candidates:
        enc = getattr(c, "face_encoding", None)
        if not enc:
            continue
        known = np.frombuffer(enc, dtype=np.float64)
        scored.append((float(np.linalg.norm(known - submitted)), c))
    if not scored:
        return None, {"reason": "no enrolled users"}
    scored.sort(key=lambda x: x[0])
    best_dist, best = scored[0]
    info = {"best_dist": best_dist}
    if best_dist > threshold:
        return None, info
    if len(scored) >= 2:
        info["second_dist"] = scored[1][0]
        if scored[1][0] - best_dist < ambiguous_margin:
            info["ambiguous"] = True
            return None, info
    return best, info


def encode_face(image_bytes: bytes):
    """單張圖 → 128 維 encoding；無臉回 None。CPU heavy（dlib）。"""
    if not FACE_AVAILABLE:
        return None
    img = face_recognition.load_image_file(io.BytesIO(image_bytes))
    locations = face_recognition.face_locations(img, number_of_times_to_upsample=1)
    encodings = face_recognition.face_encodings(img, locations)
    return encodings[0] if encodings else None


def encode_face_async(image_bytes: bytes, timeout: float = 15.0):
    """在 thread executor 跑 encode_face，逾時/失敗回 None（不卡 worker）。"""
    try:
        return _executor.submit(encode_face, image_bytes).result(timeout=timeout)
    except Exception as e:
        logger.warning("encode_face_async failed: %s", e)
        return None
```

- [ ] **Step 4: 跑測試確認 PASS**

Run: `python3 -m pytest tests/test_face_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/face/ tests/test_face_engine.py
git commit -m "feat: face engine — best-match 純函式 + encode wrapper"
```

---

### Task 4: 裝置註冊端點 `/api/v1/register-device` + 授權判斷 + 待核准清理

**Files:**
- Create: `app/devices/__init__.py`
- Create: `app/devices/routes.py`
- Modify: `app/__init__.py`（註冊 `device_bp`）
- Create: `tests/test_register_device.py`

**Interfaces:**
- Consumes: `db`、`Device`。
- Produces: blueprint `device_bp`(url_prefix `/api/v1`)；`POST /api/v1/register-device`；helper `is_device_authorized(client_uid: str | None) -> bool`（**只用 client_uid，永不用 fingerprint**）；`_cleanup_pending_devices() -> int`；cookie 名 `device_uid`。

- [ ] **Step 1: 寫失敗測試**

`tests/test_register_device.py`:
```python
from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models.device import Device
from app.devices.routes import is_device_authorized, _cleanup_pending_devices


def test_register_new_device_creates_pending_and_sets_cookie(app, client):
    with app.app_context():
        db.create_all()
    resp = client.post("/api/v1/register-device",
                       json={"fingerprint": "fp1", "device_name": "iPad"})
    assert resp.status_code == 200
    assert "device_uid" in resp.headers.get("Set-Cookie", "")
    with app.app_context():
        d = Device.query.one()
        assert d.is_approved is False
        assert d.fingerprint == "fp1"
        assert d.client_uid


def test_register_existing_uid_is_seen_not_duplicated(app, client):
    with app.app_context():
        db.create_all()
        db.session.add(Device(client_uid="known", fingerprint="fp"))
        db.session.commit()
    resp = client.post("/api/v1/register-device",
                       json={"client_uid": "known", "fingerprint": "fp"})
    assert resp.status_code == 200
    with app.app_context():
        assert Device.query.count() == 1


def test_is_device_authorized_uid_only(app):
    with app.app_context():
        db.create_all()
        db.session.add(Device(client_uid="ok", fingerprint="shared",
                              is_approved=True, is_revoked=False))
        db.session.add(Device(client_uid="revoked", fingerprint="shared",
                              is_approved=True, is_revoked=True))
        db.session.commit()
        assert is_device_authorized("ok") is True
        assert is_device_authorized("revoked") is False
        assert is_device_authorized("nonexistent") is False
        assert is_device_authorized(None) is False
        # fingerprint 永不作認證：就算 fingerprint 相同，未核准仍不通過
        db.session.add(Device(client_uid="pending", fingerprint="shared"))
        db.session.commit()
        assert is_device_authorized("pending") is False


def test_cleanup_removes_stale_pending(app):
    with app.app_context():
        db.create_all()
        old = Device(client_uid="old", is_approved=False)
        old.created_at = datetime.now(timezone.utc) - timedelta(minutes=31)
        fresh = Device(client_uid="fresh", is_approved=False)
        approved_old = Device(client_uid="appr", is_approved=True)
        approved_old.created_at = datetime.now(timezone.utc) - timedelta(minutes=31)
        db.session.add_all([old, fresh, approved_old])
        db.session.commit()
        removed = _cleanup_pending_devices()
        assert removed == 1
        assert {d.client_uid for d in Device.query.all()} == {"fresh", "appr"}
```

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python3 -m pytest tests/test_register_device.py -v`
Expected: FAIL（模組不存在）。

- [ ] **Step 3: 寫 devices blueprint**

`app/devices/__init__.py`:
```python
from app.devices.routes import device_bp

__all__ = ["device_bp"]
```

`app/devices/routes.py`:
```python
import uuid
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, jsonify

from app.extensions import db
from app.models.device import Device

device_bp = Blueprint("device", __name__, url_prefix="/api/v1")

UID_COOKIE_NAME = "device_uid"
UID_COOKIE_MAX_AGE = 60 * 60 * 24 * 365 * 10  # 10 年
PENDING_DEVICE_TTL_MINUTES = 30


def _get_cookie_uid():
    return (request.cookies.get(UID_COOKIE_NAME) or "").strip() or None


def _set_uid_cookie(resp, uid):
    resp.set_cookie(
        UID_COOKIE_NAME, uid,
        max_age=UID_COOKIE_MAX_AGE,
        httponly=True, secure=True, samesite="Lax",
    )


def _cleanup_pending_devices():
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=PENDING_DEVICE_TTL_MINUTES)
    stale = Device.query.filter(
        Device.is_approved.is_(False), Device.created_at < cutoff
    ).all()
    for d in stale:
        db.session.delete(d)
    if stale:
        db.session.commit()
    return len(stale)


def is_device_authorized(client_uid):
    """僅用 client_uid 判斷；fingerprint 永不參與。"""
    if not client_uid:
        return False
    d = Device.query.filter_by(client_uid=client_uid).first()
    if not d or not d.is_approved or d.is_revoked:
        return False
    if d.bound_user_id and d.bound_user and not d.bound_user.active:
        return False
    return True


@device_bp.post("/register-device")
def register_device():
    try:
        _cleanup_pending_devices()
    except Exception:
        db.session.rollback()

    data = request.get_json(silent=True) or {}
    fp = (data.get("fingerprint") or "").strip() or None
    body_uid = (data.get("client_uid") or "").strip() or None
    device_name = data.get("device_name") or "Unknown"

    uid = _get_cookie_uid() or body_uid
    device = Device.query.filter_by(client_uid=uid).first() if uid else None

    if device is None:
        uid = uid or uuid.uuid4().hex
        device = Device(client_uid=uid, fingerprint=fp, device_name=device_name)
        db.session.add(device)
    else:
        device.last_seen_at = datetime.now(timezone.utc)
        if fp:
            device.fingerprint = fp
    db.session.commit()

    resp = jsonify(status="ok",
                   approved=device.is_approved,
                   revoked=device.is_revoked)
    _set_uid_cookie(resp, uid)
    return resp
```

- [ ] **Step 4: 註冊 blueprint**

在 `app/__init__.py` 的 `create_app` 內、`return app` 前加：
```python
    from app.devices import device_bp
    app.register_blueprint(device_bp)
```

- [ ] **Step 5: 跑測試確認 PASS**

Run: `python3 -m pytest tests/test_register_device.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/devices/ app/__init__.py tests/test_register_device.py
git commit -m "feat: register-device 端點 + client_uid 授權判斷 + 待核准清理"
```

---

### Task 5: seed mode + 裝置閘 + idle 逾時（before_request）+ session config

**Files:**
- Create: `app/auth/gates.py`
- Modify: `app/config.py`（session cookie + lifetime）
- Modify: `app/__init__.py`（註冊 before_request）
- Create: `tests/test_gates.py`

**Interfaces:**
- Consumes: `Device`、`User`、`is_device_authorized`、`session`。
- Produces:
  - `is_seed_mode() -> bool`。
  - `register_gates(app)`：掛 `before_request` 兩閘（裝置閘 + idle 逾時），並提供 `IDLE_MAX_SECONDS = 1800`。
  - config：`SESSION_COOKIE_HTTPONLY/SAMESITE/SECURE`、`PERMANENT_SESSION_LIFETIME`。

- [ ] **Step 1: 寫 config 改動**

在 `app/config.py` 的 `Config` 內加（沿用既有 import os；頂部若無則加 `from datetime import timedelta`）：
```python
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=35)
```

- [ ] **Step 2: 寫失敗測試**

`tests/test_gates.py`:
```python
import time
from app.extensions import db
from app.models.user import User
from app.models.device import Device
from app.auth.gates import is_seed_mode, IDLE_MAX_SECONDS


def _mk_super_admin_with_face():
    u = User(name="業主", role="super_admin")
    u.set_password("pw")
    u.face_encoding = b"\x00" * 1024
    return u


def test_seed_mode_true_when_no_super_admin(app):
    with app.app_context():
        db.create_all()
        assert is_seed_mode() is True


def test_seed_mode_true_when_no_approved_device(app):
    with app.app_context():
        db.create_all()
        db.session.add(_mk_super_admin_with_face())
        db.session.commit()
        assert is_seed_mode() is True  # 無已核准裝置


def test_seed_mode_false_when_admin_face_and_approved_device(app):
    with app.app_context():
        db.create_all()
        db.session.add(_mk_super_admin_with_face())
        db.session.add(Device(client_uid="d1", is_approved=True))
        db.session.commit()
        assert is_seed_mode() is False


def test_seed_mode_true_when_admin_has_no_face(app):
    with app.app_context():
        db.create_all()
        u = User(name="業主", role="super_admin"); u.set_password("pw")
        db.session.add(u)
        db.session.add(Device(client_uid="d1", is_approved=True))
        db.session.commit()
        assert is_seed_mode() is True


def test_idle_max_is_30_minutes():
    assert IDLE_MAX_SECONDS == 1800
```

- [ ] **Step 3: 跑測試確認 FAIL**

Run: `python3 -m pytest tests/test_gates.py -v`
Expected: FAIL（模組不存在）。

- [ ] **Step 4: 寫 gates**

`app/auth/gates.py`:
```python
import time

from flask import request, session, jsonify

from app.models.user import User
from app.models.device import Device
from app.devices.routes import is_device_authorized, UID_COOKIE_NAME

IDLE_MAX_SECONDS = 30 * 60

_EXEMPT_PREFIXES = ("/static/", "/api/v1/")
_EXEMPT_PATHS = ("/health", "/sw.js", "/auth/logout")


def is_seed_mode():
    """任一成立即 seed mode：無 super_admin / 無已核准裝置 / 所有 super_admin 無臉。"""
    admins = User.query.filter_by(role="super_admin").all()
    if not admins:
        return True
    if Device.query.filter_by(is_approved=True).count() == 0:
        return True
    if all(a.face_encoding is None for a in admins):
        return True
    return False


def _is_exempt(path):
    return path in _EXEMPT_PATHS or path.startswith(_EXEMPT_PREFIXES)


def register_gates(app):
    @app.before_request
    def _device_gate():
        path = request.path or ""
        if _is_exempt(path):
            return None
        if is_seed_mode():
            return None  # 首次啟用：放行以完成 bootstrap
        uid = (request.cookies.get(UID_COOKIE_NAME) or "").strip() or None
        if not is_device_authorized(uid):
            return jsonify(status="device_not_approved"), 403
        return None

    @app.before_request
    def _idle_gate():
        path = request.path or ""
        if _is_exempt(path):
            return None
        if not session.get("user_id"):
            return None
        now = int(time.time())
        last = session.get("_last_request_at")
        if last is not None and now - last > IDLE_MAX_SECONDS:
            session.clear()
            return jsonify(status="session_expired"), 401
        session["_last_request_at"] = now  # 滑動續命
        return None
```

- [ ] **Step 5: 註冊 gates**

在 `app/__init__.py` 的 `create_app` 內、`return app` 前（在 blueprint 註冊之後）加：
```python
    from app.auth.gates import register_gates
    register_gates(app)
```

- [ ] **Step 6: 跑全部測試確認 PASS**

Run: `python3 -m pytest tests/test_gates.py tests/test_register_device.py -v`
Expected: PASS（注意 gates 掛上後，其他既有測試若打受保護路由可能開始被裝置閘擋 → 下一步驗證全套）。

- [ ] **Step 7: 跑全套確認未破壞既有**

Run: `python3 -m pytest -v`
Expected: 全 PASS。若既有 Task 5 的 `/auth/login` 測試因閘被擋而失敗，屬預期（Task 6 會移除該路由與測試）；於報告列出受影響測試名稱，暫不修改其他 task 的測試。

- [ ] **Step 8: Commit**

```bash
git add app/auth/gates.py app/config.py app/__init__.py tests/test_gates.py
git commit -m "feat: seed mode + 裝置閘 + 30 分 idle 逾時 before_request"
```

---

### Task 6: `/auth/verify` 免帳號 best-match 登入（取代 name+password）+ rate limit + current_user active 重查

**Files:**
- Modify: `app/extensions.py`（加 `limiter`）
- Modify: `app/auth/routes.py`（移除舊 `/auth/login`；加 `/auth/verify`；`login()` helper）
- Modify: `app/auth/decorators.py`（`current_user` 加 active 重查、改用 `db.session.get`）
- Modify: `app/__init__.py`（init limiter）
- Delete/Modify: `tests/test_auth.py`（移除 name+password login 測試，保留 password/seed 測試）
- Create: `tests/test_verify_login.py`

**Interfaces:**
- Consumes: `User`、`Device`、`best_match_among`、`encode_face_async`、`is_device_authorized`。
- Produces: `POST /auth/verify`（body `{password, face_image}`，回 JSON `status`）；`login(user)` 寫 `session['user_id']` + `session.permanent=True` + `session['_last_request_at']`；`limiter`（`app/extensions.py`）。
- 候選 scope：該裝置 `store_id` 的在職 user + 全域角色（`accountant`/`super_admin`）。

- [ ] **Step 1: 加 limiter 到 extensions**

在 `app/extensions.py` 加：
```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=[])
```
在 `app/__init__.py` 的 `create_app` 內（db.init_app 附近）加：
```python
    from app.extensions import limiter
    limiter.init_app(app)
```

- [ ] **Step 2: 寫失敗測試**

`tests/test_verify_login.py`:
```python
import numpy as np
import pytest
from app.extensions import db
from app.models.user import User
from app.models.store import Store
from app.models.device import Device


def _enc(fill):
    return np.full(128, float(fill), dtype=np.float64)


@pytest.fixture
def seeded(app):
    with app.app_context():
        db.create_all()
        store = Store(name="A店", code="A")
        db.session.add(store); db.session.commit()
        emp = User(name="小明", role="employee", store_id=store.id)
        emp.set_password("1234"); emp.face_encoding = _enc(0.0).tobytes()
        dev = Device(client_uid="devA", store_id=store.id, is_approved=True)
        db.session.add_all([emp, dev]); db.session.commit()
        return {"store_id": store.id}


def _client_with_device(app, uid="devA"):
    c = app.test_client()
    c.set_cookie("device_uid", uid)
    return c


def test_verify_ok(monkeypatch, app, seeded):
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: _enc(0.0))
    c = _client_with_device(app)
    r = c.post("/auth/verify", json={"password": "1234", "face_image": "data:x"})
    assert r.get_json()["status"] == "ok"


def test_verify_wrong_password(app, seeded):
    c = _client_with_device(app)
    r = c.post("/auth/verify", json={"password": "bad", "face_image": "data:x"})
    assert r.get_json()["status"] == "wrong_password"


def test_verify_face_mismatch(monkeypatch, app, seeded):
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: _enc(9.0))
    c = _client_with_device(app)
    r = c.post("/auth/verify", json={"password": "1234", "face_image": "data:x"})
    assert r.get_json()["status"] == "face_mismatch"


def test_verify_need_face_enroll(app, seeded):
    with app.app_context():
        u = User.query.filter_by(name="小明").one()
        u.face_encoding = None
        db.session.commit()
    c = _client_with_device(app)
    r = c.post("/auth/verify", json={"password": "1234", "face_image": "data:x"})
    assert r.get_json()["status"] == "need_face_enroll"


def test_verify_face_not_found(monkeypatch, app, seeded):
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: None)
    c = _client_with_device(app)
    r = c.post("/auth/verify", json={"password": "1234", "face_image": "data:x"})
    assert r.get_json()["status"] == "face_not_found"


def test_verify_candidate_scoped_to_store(monkeypatch, app, seeded):
    # 另一店員工同密碼同臉，不應被 A 店裝置比中
    with app.app_context():
        other = Store(name="B店", code="B"); db.session.add(other); db.session.commit()
        u = User(name="B小華", role="employee", store_id=other.id)
        u.set_password("1234"); u.face_encoding = _enc(0.0).tobytes()
        db.session.add(u); db.session.commit()
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: _enc(0.0))
    c = _client_with_device(app)
    r = c.post("/auth/verify", json={"password": "1234", "face_image": "data:x"})
    # 仍應登入 A 店小明（B 店員工不在候選內），驗證未撞臉整批拒
    assert r.get_json()["status"] == "ok"
```

- [ ] **Step 3: 跑測試確認 FAIL**

Run: `python3 -m pytest tests/test_verify_login.py -v`
Expected: FAIL（`/auth/verify` 不存在）。

- [ ] **Step 4: 改寫 auth/routes.py**

把 `app/auth/routes.py` 全檔改為：
```python
from flask import Blueprint, request, session, jsonify

from app.extensions import db, limiter
from app.models.user import User
from app.models.device import Device
from app.devices.routes import UID_COOKIE_NAME
from app.face.engine import best_match_among, encode_face_async

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def login(user):
    session["user_id"] = user.id
    session.permanent = True
    import time
    session["_last_request_at"] = int(time.time())


def _candidate_users():
    """該裝置所屬店的在職 user + 全域角色（accountant/super_admin）。"""
    uid = (request.cookies.get(UID_COOKIE_NAME) or "").strip() or None
    device = Device.query.filter_by(client_uid=uid).first() if uid else None
    store_id = device.store_id if device else None
    q = User.query.filter_by(active=True)
    from sqlalchemy import or_
    conds = [User.role.in_(("accountant", "super_admin"))]
    if store_id is not None:
        conds.append(User.store_id == store_id)
    return q.filter(or_(*conds)).all()


@auth_bp.post("/verify")
@limiter.limit("20 per minute", exempt_when=lambda: __import__("flask").current_app.config.get("TESTING"))
def verify():
    data = request.get_json(silent=True) or {}
    password = str(data.get("password") or "")
    face_image = data.get("face_image")

    pin_users = [u for u in _candidate_users() if u.check_password(password)]
    if not pin_users:
        return jsonify(status="wrong_password")

    face_enrolled = [u for u in pin_users if u.face_encoding is not None]
    if not face_enrolled:
        return jsonify(status="need_face_enroll")
    if not face_image:
        return jsonify(status="face_mismatch")

    import base64
    try:
        img_bytes = base64.b64decode(str(face_image).split(",")[-1])
    except Exception:
        img_bytes = b""
    submitted = encode_face_async(img_bytes)
    if submitted is None:
        return jsonify(status="face_not_found")

    matched, info = best_match_among(face_enrolled, submitted)
    if matched is None:
        return jsonify(status="ambiguous" if info.get("ambiguous") else "face_mismatch")

    if matched.store_id and matched.store and not matched.store.active:
        return jsonify(status="store_disabled")

    login(matched)
    return jsonify(status="ok", id=matched.id, name=matched.name, role=matched.role)


@auth_bp.post("/logout")
def logout():
    session.clear()
    return jsonify(status="ok")
```
注意：`face_image` 解碼後的 `img_bytes` 僅傳入 encode 後即由 GC 回收，**不落地**。

- [ ] **Step 5: current_user 加 active 重查 + 現代化 API**

把 `app/auth/decorators.py` 的 `current_user` 改為：
```python
def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return User.query.filter_by(id=uid, active=True).first()
```
（移除舊的 `User.query.get(uid)`；`role_required` 其餘不變。）

- [ ] **Step 6: 清理 Task 5 舊登入測試**

編輯 `tests/test_auth.py`：**移除** `test_login_and_session`（name+password 登入已由 `/auth/verify` 取代）。**保留** `test_password_hash_roundtrip`、`test_seed_admin_idempotent`。若這兩個測試打了受保護路由被閘擋，改為只在 `app.app_context()` 內操作 model（不經 HTTP）。

- [ ] **Step 7: 跑測試確認 PASS**

Run: `python3 -m pytest tests/test_verify_login.py tests/test_auth.py -v`
Expected: PASS

- [ ] **Step 8: 跑全套 + Commit**

Run: `python3 -m pytest -v`（全 PASS）
```bash
git add app/extensions.py app/auth/ app/__init__.py tests/
git commit -m "feat: /auth/verify best-match 登入取代舊 login + rate limit + current_user active 重查"
```

---

### Task 7: 人臉錄入端點 `/face/enroll`

**Files:**
- Create: `app/face/routes.py`
- Modify: `app/__init__.py`（註冊 `face_bp`）
- Create: `tests/test_face_enroll.py`

**Interfaces:**
- Consumes: `User`、`encode_face_async`、`role_required`/`current_user`、`db`。
- Produces: blueprint `face_bp`(url_prefix `/face`)；`POST /face/enroll`（body `{user_id?, face_image}`；未帶 user_id 則錄自己）。權限：seed mode 放行本人；否則需 manager/super_admin，且 manager 限本店員工。

- [ ] **Step 1: 寫失敗測試**

`tests/test_face_enroll.py`:
```python
import numpy as np
from app.extensions import db
from app.models.user import User
from app.models.store import Store
from app.models.device import Device


def _enc(fill):
    return np.full(128, float(fill), dtype=np.float64)


def _login_as(app, user_id):
    c = app.test_client()
    c.set_cookie("device_uid", "devA")
    with c.session_transaction() as s:
        s["user_id"] = user_id
        import time; s["_last_request_at"] = int(time.time())
    return c


def test_admin_enrolls_user_face(monkeypatch, app):
    monkeypatch.setattr("app.face.routes.encode_face_async", lambda *_a, **_k: _enc(1.0))
    with app.app_context():
        db.create_all()
        store = Store(name="A店", code="A"); db.session.add(store); db.session.commit()
        admin = User(name="店長", role="manager", store_id=store.id); admin.set_password("pw")
        emp = User(name="小明", role="employee", store_id=store.id); emp.set_password("pw")
        dev = Device(client_uid="devA", store_id=store.id, is_approved=True)
        db.session.add_all([admin, emp, dev]); db.session.commit()
        admin_id, emp_id = admin.id, emp.id
    c = _login_as(app, admin_id)
    r = c.post("/face/enroll", json={"user_id": emp_id, "face_image": "data:x"})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert User.query.get(emp_id).face_encoding is not None


def test_enroll_no_face_detected(monkeypatch, app):
    monkeypatch.setattr("app.face.routes.encode_face_async", lambda *_a, **_k: None)
    with app.app_context():
        db.create_all()
        store = Store(name="A店", code="A"); db.session.add(store); db.session.commit()
        admin = User(name="店長", role="manager", store_id=store.id); admin.set_password("pw")
        dev = Device(client_uid="devA", store_id=store.id, is_approved=True)
        db.session.add_all([admin, dev]); db.session.commit()
        admin_id = admin.id
    c = _login_as(app, admin_id)
    r = c.post("/face/enroll", json={"user_id": admin_id, "face_image": "data:x"})
    assert r.get_json()["status"] == "face_not_found"


def test_employee_cannot_enroll_others(monkeypatch, app):
    with app.app_context():
        db.create_all()
        store = Store(name="A店", code="A"); db.session.add(store); db.session.commit()
        emp = User(name="小明", role="employee", store_id=store.id); emp.set_password("pw")
        other = User(name="小華", role="employee", store_id=store.id); other.set_password("pw")
        dev = Device(client_uid="devA", store_id=store.id, is_approved=True)
        db.session.add_all([emp, other, dev]); db.session.commit()
        emp_id, other_id = emp.id, other.id
    c = _login_as(app, emp_id)
    r = c.post("/face/enroll", json={"user_id": other_id, "face_image": "data:x"})
    assert r.status_code == 403
```

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python3 -m pytest tests/test_face_enroll.py -v`
Expected: FAIL。

- [ ] **Step 3: 寫 face/routes.py**

`app/face/routes.py`:
```python
import base64

from flask import Blueprint, request, jsonify

from app.extensions import db
from app.models.user import User
from app.auth.decorators import current_user
from app.auth.gates import is_seed_mode
from app.face.engine import encode_face_async

face_bp = Blueprint("face", __name__, url_prefix="/face")


def _can_enroll(actor, target):
    if actor is None:
        return False
    if actor.id == target.id:
        return True
    if actor.role == "super_admin":
        return True
    if actor.role == "manager":
        return target.store_id == actor.store_id
    return False


@face_bp.post("/enroll")
def enroll():
    data = request.get_json(silent=True) or {}
    face_image = data.get("face_image")
    target_id = data.get("user_id")

    actor = current_user()
    if target_id is None:
        target = actor
    else:
        target = db.session.get(User, target_id)
    if target is None:
        return jsonify(status="error", message="user not found"), 404

    # seed mode：允許本人自錄（bootstrap）；否則需管理權限
    if is_seed_mode():
        if actor is not None and not _can_enroll(actor, target):
            return jsonify(status="error", message="forbidden"), 403
    elif not _can_enroll(actor, target):
        return jsonify(status="error", message="forbidden"), 403

    if not face_image:
        return jsonify(status="face_not_found")
    try:
        img_bytes = base64.b64decode(str(face_image).split(",")[-1])
    except Exception:
        img_bytes = b""
    encoding = encode_face_async(img_bytes)
    if encoding is None:
        return jsonify(status="face_not_found")

    import numpy as np
    target.face_encoding = np.asarray(encoding, dtype=np.float64).tobytes()
    db.session.commit()
    return jsonify(status="ok")
```
注意：`img_bytes` 算完 encoding 即由 GC 回收，只存向量、**不落地**。

- [ ] **Step 4: 註冊 blueprint**

在 `app/__init__.py` 的 `create_app` 內、`return app` 前加：
```python
    from app.face.routes import face_bp
    app.register_blueprint(face_bp)
```

- [ ] **Step 5: 跑測試確認 PASS**

Run: `python3 -m pytest tests/test_face_enroll.py -v`
Expected: PASS

- [ ] **Step 6: 跑全套 + Commit**

Run: `python3 -m pytest -v`（全 PASS）
```bash
git add app/face/routes.py app/__init__.py tests/test_face_enroll.py
git commit -m "feat: /face/enroll 人臉錄入（原圖即丟只存向量）"
```

---

### Task 8: 後台 — 店別管理 + 直接創帳號 + 密碼管理

**Files:**
- Create: `app/admin/__init__.py`
- Create: `app/admin/routes.py`
- Modify: `app/__init__.py`（註冊 `admin_bp`）
- Create: `tests/test_admin_store_account.py`

**Interfaces:**
- Consumes: `User`、`Store`、`current_user`、`role_required`、`db`。
- Produces: blueprint `admin_bp`(url_prefix `/admin`)；
  - `POST /admin/stores`（super_admin 建店：`{name, code}`）
  - `POST /admin/users`（建帳號：`{name, password, role, store_id}`；manager 限本店）
  - `POST /admin/users/<id>/password`（重設他人密碼；manager 限本店）
  - `POST /admin/me/password`（改自己密碼：`{old_password, new_password}`）
- 權限 helper：`_manages(actor, target_user) -> bool`（super_admin 全域；manager 同店）。

- [ ] **Step 1: 寫失敗測試**

`tests/test_admin_store_account.py`:
```python
from app.extensions import db
from app.models.user import User
from app.models.store import Store
from app.models.device import Device


def _login_as(app, user_id):
    c = app.test_client()
    c.set_cookie("device_uid", "devA")
    with c.session_transaction() as s:
        s["user_id"] = user_id
        import time; s["_last_request_at"] = int(time.time())
    return c


def _base(app):
    with app.app_context():
        db.create_all()
        a = Store(name="A店", code="A"); db.session.add(a); db.session.commit()
        sa = User(name="業主", role="super_admin"); sa.set_password("pw")
        mgr = User(name="店長", role="manager", store_id=a.id); mgr.set_password("pw")
        dev = Device(client_uid="devA", store_id=a.id, is_approved=True)
        db.session.add_all([sa, mgr, dev]); db.session.commit()
        return {"a": a.id, "sa": sa.id, "mgr": mgr.id}


def test_super_admin_creates_store(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"])
    r = c.post("/admin/stores", json={"name": "B店", "code": "B"})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert Store.query.filter_by(code="B").one().name == "B店"


def test_manager_cannot_create_store(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.post("/admin/stores", json={"name": "B店", "code": "B"})
    assert r.status_code == 403


def test_manager_creates_own_store_employee(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.post("/admin/users", json={"name": "小明", "password": "1234",
                                     "role": "employee", "store_id": ids["a"]})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert User.query.filter_by(name="小明").one().check_password("1234")


def test_manager_cannot_create_other_store_user(app):
    ids = _base(app)
    with app.app_context():
        b = Store(name="B店", code="B"); db.session.add(b); db.session.commit()
        b_id = b.id
    c = _login_as(app, ids["mgr"])
    r = c.post("/admin/users", json={"name": "外店", "password": "1234",
                                     "role": "employee", "store_id": b_id})
    assert r.status_code == 403


def test_manager_resets_own_store_user_password(app):
    ids = _base(app)
    with app.app_context():
        emp = User(name="小明", role="employee", store_id=ids["a"]); emp.set_password("old")
        db.session.add(emp); db.session.commit()
        emp_id = emp.id
    c = _login_as(app, ids["mgr"])
    r = c.post(f"/admin/users/{emp_id}/password", json={"password": "new"})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert User.query.get(emp_id).check_password("new")


def test_self_change_password_requires_old(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    bad = c.post("/admin/me/password", json={"old_password": "wrong", "new_password": "x"})
    assert bad.status_code == 400
    ok = c.post("/admin/me/password", json={"old_password": "pw", "new_password": "new"})
    assert ok.get_json()["status"] == "ok"
    with app.app_context():
        assert User.query.get(ids["mgr"]).check_password("new")
```

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python3 -m pytest tests/test_admin_store_account.py -v`
Expected: FAIL。

- [ ] **Step 3: 寫 admin blueprint**

`app/admin/__init__.py`:
```python
from app.admin.routes import admin_bp

__all__ = ["admin_bp"]
```

`app/admin/routes.py`:
```python
from flask import Blueprint, request, jsonify

from app.extensions import db
from app.models.user import User
from app.models.store import Store
from app.auth.decorators import current_user, role_required

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

ROLES = ("employee", "manager", "accountant", "super_admin")


def _manages(actor, target):
    if actor is None:
        return False
    if actor.role == "super_admin":
        return True
    if actor.role == "manager":
        return target.store_id is not None and target.store_id == actor.store_id
    return False


@admin_bp.post("/stores")
@role_required("super_admin")
def create_store():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    code = (data.get("code") or "").strip()
    if not name or not code:
        return jsonify(status="error", message="name/code required"), 400
    if Store.query.filter_by(code=code).first() or Store.query.filter_by(name=name).first():
        return jsonify(status="error", message="store exists"), 409
    store = Store(name=name, code=code)
    db.session.add(store); db.session.commit()
    return jsonify(status="ok", id=store.id)


@admin_bp.post("/users")
@role_required("manager", "super_admin")
def create_user():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    password = str(data.get("password") or "")
    role = data.get("role") or "employee"
    store_id = data.get("store_id")
    if not name or not password or role not in ROLES:
        return jsonify(status="error", message="invalid input"), 400

    actor = current_user()
    if actor.role == "manager" and store_id != actor.store_id:
        return jsonify(status="error", message="forbidden"), 403

    user = User(name=name, role=role, store_id=store_id)
    user.set_password(password)
    db.session.add(user); db.session.commit()
    return jsonify(status="ok", id=user.id)


@admin_bp.post("/users/<int:user_id>/password")
@role_required("manager", "super_admin")
def reset_password(user_id):
    data = request.get_json(silent=True) or {}
    new_password = str(data.get("password") or "")
    if not new_password:
        return jsonify(status="error", message="password required"), 400
    target = db.session.get(User, user_id)
    if target is None:
        return jsonify(status="error", message="user not found"), 404
    if not _manages(current_user(), target):
        return jsonify(status="error", message="forbidden"), 403
    target.set_password(new_password); db.session.commit()
    return jsonify(status="ok")


@admin_bp.post("/me/password")
def change_own_password():
    actor = current_user()
    if actor is None:
        return jsonify(status="error", message="unauthenticated"), 401
    data = request.get_json(silent=True) or {}
    if not actor.check_password(str(data.get("old_password") or "")):
        return jsonify(status="error", message="wrong old password"), 400
    new_password = str(data.get("new_password") or "")
    if not new_password:
        return jsonify(status="error", message="new password required"), 400
    actor.set_password(new_password); db.session.commit()
    return jsonify(status="ok")
```

- [ ] **Step 4: 註冊 blueprint**

在 `app/__init__.py` 的 `create_app` 內、`return app` 前加：
```python
    from app.admin import admin_bp
    app.register_blueprint(admin_bp)
```

- [ ] **Step 5: 跑測試確認 PASS**

Run: `python3 -m pytest tests/test_admin_store_account.py -v`
Expected: PASS

- [ ] **Step 6: 跑全套 + Commit**

Run: `python3 -m pytest -v`（全 PASS）
```bash
git add app/admin/ app/__init__.py tests/test_admin_store_account.py
git commit -m "feat: 後台 店別管理 + 直接創帳號 + 密碼管理（含權限 scope）"
```

---

### Task 9: 後台 — 裝置核准 / 換機 / 撤銷 + 調店檢視過濾

**Files:**
- Modify: `app/admin/routes.py`（加裝置管理 + 清單過濾）
- Create: `tests/test_admin_devices.py`

**Interfaces:**
- Consumes: `Device`、`User`、`current_user`、`db`。
- Produces:
  - `GET /admin/devices?store_id=`（列裝置；super_admin 可選店過濾、預設全部；manager 限本店）
  - `POST /admin/devices/<id>/approve`（核准；可帶 `{bound_user_id}` 綁既有帳號＝換機，會撤該 user 其他已核准裝置；或帶 `{new_user: {...}}` 建新帳號並綁）
  - `POST /admin/devices/<id>/revoke`
- 權限 helper：`_manages_device(actor, device) -> bool`（super_admin 全域；manager 同店：`device.store_id == actor.store_id`）。

- [ ] **Step 1: 寫失敗測試**

`tests/test_admin_devices.py`:
```python
from app.extensions import db
from app.models.user import User
from app.models.store import Store
from app.models.device import Device


def _login_as(app, user_id, uid="devMgr"):
    c = app.test_client()
    c.set_cookie("device_uid", uid)
    with c.session_transaction() as s:
        s["user_id"] = user_id
        import time; s["_last_request_at"] = int(time.time())
    return c


def _base(app):
    with app.app_context():
        db.create_all()
        a = Store(name="A店", code="A"); b = Store(name="B店", code="B")
        db.session.add_all([a, b]); db.session.commit()
        sa = User(name="業主", role="super_admin"); sa.set_password("pw")
        mgr = User(name="店長A", role="manager", store_id=a.id); mgr.set_password("pw")
        # 管理者自己的已核准裝置（供登入用）
        mgr_dev = Device(client_uid="devMgr", store_id=a.id, is_approved=True)
        sa_dev = Device(client_uid="devSA", is_approved=True)
        # 待核准裝置
        pend_a = Device(client_uid="pendA", store_id=a.id, device_name="A新機")
        pend_b = Device(client_uid="pendB", store_id=b.id, device_name="B新機")
        db.session.add_all([sa, mgr, mgr_dev, sa_dev, pend_a, pend_b]); db.session.commit()
        return {"a": a.id, "b": b.id, "sa": sa.id, "mgr": mgr.id,
                "pend_a": pend_a.id, "pend_b": pend_b.id}


def test_manager_lists_only_own_store_devices(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.get("/admin/devices")
    uids = {d["client_uid"] for d in r.get_json()["devices"]}
    assert "pendA" in uids and "devMgr" in uids
    assert "pendB" not in uids and "devSA" not in uids


def test_super_admin_store_filter(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    all_r = c.get("/admin/devices")
    assert {d["client_uid"] for d in all_r.get_json()["devices"]} >= {"pendA", "pendB"}
    filtered = c.get(f"/admin/devices?store_id={ids['b']}")
    uids = {d["client_uid"] for d in filtered.get_json()["devices"]}
    assert "pendB" in uids and "pendA" not in uids


def test_manager_cannot_approve_other_store_device(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.post(f"/admin/devices/{ids['pend_b']}/approve", json={})
    assert r.status_code == 403


def test_approve_with_new_account_binds_user(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.post(f"/admin/devices/{ids['pend_a']}/approve",
               json={"new_user": {"name": "小明", "password": "1234", "role": "employee"}})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        d = Device.query.get(ids["pend_a"])
        assert d.is_approved is True and d.bound_user_id is not None
        assert User.query.get(d.bound_user_id).name == "小明"


def test_approve_rebind_existing_revokes_old(app):
    ids = _base(app)
    with app.app_context():
        emp = User(name="小明", role="employee", store_id=ids["a"]); emp.set_password("1234")
        db.session.add(emp); db.session.commit()
        old = Device(client_uid="oldPhone", store_id=ids["a"],
                     is_approved=True, bound_user_id=emp.id)
        db.session.add(old); db.session.commit()
        emp_id, old_id = emp.id, old.id
    c = _login_as(app, ids["mgr"])
    r = c.post(f"/admin/devices/{ids['pend_a']}/approve",
               json={"bound_user_id": emp_id})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert Device.query.get(old_id).is_revoked is True   # 舊機撤銷
        assert Device.query.get(ids["pend_a"]).is_approved is True


def test_revoke_device(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.post(f"/admin/devices/{ids['pend_a']}/revoke", json={})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert Device.query.get(ids["pend_a"]).is_revoked is True
```

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python3 -m pytest tests/test_admin_devices.py -v`
Expected: FAIL。

- [ ] **Step 3: 加裝置管理到 admin/routes.py**

在 `app/admin/routes.py` 末尾加（沿用檔頭既有 import，另補 `from app.models.device import Device`）：
```python
from app.models.device import Device


def _visible_device_query(actor, store_id_filter=None):
    q = Device.query
    if actor.role == "manager":
        return q.filter(Device.store_id == actor.store_id)
    # super_admin
    if store_id_filter is not None:
        return q.filter(Device.store_id == store_id_filter)
    return q


def _manages_device(actor, device):
    if actor.role == "super_admin":
        return True
    if actor.role == "manager":
        return device.store_id == actor.store_id
    return False


@admin_bp.get("/devices")
@role_required("manager", "super_admin")
def list_devices():
    actor = current_user()
    store_id_filter = request.args.get("store_id", type=int)
    devices = _visible_device_query(actor, store_id_filter).order_by(
        Device.created_at.desc()
    ).all()
    return jsonify(status="ok", devices=[
        {"id": d.id, "client_uid": d.client_uid, "device_name": d.device_name,
         "store_id": d.store_id, "bound_user_id": d.bound_user_id,
         "is_approved": d.is_approved, "is_revoked": d.is_revoked}
        for d in devices
    ])


@admin_bp.post("/devices/<int:device_id>/approve")
@role_required("manager", "super_admin")
def approve_device(device_id):
    actor = current_user()
    device = db.session.get(Device, device_id)
    if device is None:
        return jsonify(status="error", message="device not found"), 404
    if not _manages_device(actor, device):
        return jsonify(status="error", message="forbidden"), 403

    data = request.get_json(silent=True) or {}
    bound_user_id = data.get("bound_user_id")
    new_user = data.get("new_user")

    if new_user:
        u = User(name=(new_user.get("name") or "").strip(),
                 role=new_user.get("role") or "employee",
                 store_id=device.store_id)
        u.set_password(str(new_user.get("password") or ""))
        db.session.add(u); db.session.flush()
        bound_user_id = u.id

    if bound_user_id is not None:
        # 換機：撤該 user 其他已核准裝置（撤舊發新）
        for old in Device.query.filter(
            Device.bound_user_id == bound_user_id,
            Device.id != device.id,
            Device.is_approved.is_(True),
        ).all():
            old.is_revoked = True
        device.bound_user_id = bound_user_id

    device.is_approved = True
    device.is_revoked = False
    db.session.commit()
    return jsonify(status="ok", bound_user_id=device.bound_user_id)


@admin_bp.post("/devices/<int:device_id>/revoke")
@role_required("manager", "super_admin")
def revoke_device(device_id):
    actor = current_user()
    device = db.session.get(Device, device_id)
    if device is None:
        return jsonify(status="error", message="device not found"), 404
    if not _manages_device(actor, device):
        return jsonify(status="error", message="forbidden"), 403
    device.is_revoked = True
    db.session.commit()
    return jsonify(status="ok")
```

- [ ] **Step 4: 跑測試確認 PASS**

Run: `python3 -m pytest tests/test_admin_devices.py -v`
Expected: PASS

- [ ] **Step 5: 跑全套 + Commit**

Run: `python3 -m pytest -v`（全 PASS）
```bash
git add app/admin/routes.py tests/test_admin_devices.py
git commit -m "feat: 後台 裝置核准/換機/撤銷 + 調店檢視過濾"
```

---

## Self-Review

**Spec coverage（對 `2026-07-02-auth-device-design.md`）：**
- §1 雙 cookie / 裝置閘 / idle 閘 → Task 5 ✅
- §2 seed mode → Task 5 `is_seed_mode` ✅
- §3 資料模型（User.face_encoding / Device）→ Task 2 ✅
- §4 `/auth/verify` best-match（候選 scope 到店＋全域、threshold/ambiguous、rate limit、store_disabled）→ Task 3（引擎）+ Task 6（端點）✅
- §5 register-device + cleanup + client_uid 授權（fingerprint 僅稽核）→ Task 4 ✅
- §6.1 調店過濾 → Task 9；§6.2 新增店 → Task 8；§6.3 直接創帳號 → Task 8；§6.4 密碼管理 → Task 8；§6.5 裝置核准/換機/撤銷 → Task 9 ✅
- §7 人臉錄入（原圖即丟）→ Task 7 ✅
- §8 idle 30 分（滑動、不輪詢）→ Task 5 ✅
- §9 取代 Task 5 name+password 登入 + current_user active 重查 → Task 6 ✅
- §10 build（預編 wheel、Dockerfile layer cache、pkg_resources shim、依賴鎖版）→ Task 1 ✅
- §11 測試（face_recognition mock）→ 各 task 測試以 monkeypatch mock `encode_face_async` ✅
- §12 鐵律：fingerprint 僅稽核（Task 4 測試明確斷言）、影像不落地（Task 6/7 註明）、不輪詢（Task 5）、UTC（Task 2）✅

**Placeholder scan：** 無 TBD/TODO；每個 code step 均含完整程式碼與指令。

**Type consistency：** `is_device_authorized(client_uid)`、`best_match_among(candidates, submitted, threshold, ambiguous_margin)`、`encode_face_async(image_bytes, timeout)`、`login(user)`、`current_user()`、`is_seed_mode()`、`register_gates(app)`、`IDLE_MAX_SECONDS`、`UID_COOKIE_NAME`、cookie 名 `device_uid`、狀態字串（`ok/wrong_password/need_face_enroll/face_mismatch/face_not_found/ambiguous/store_disabled/device_not_approved/session_expired`）跨 task 命名一致。

**已知延後項（記錄，非本 plan）：** rate-limit 用 Flask-Limiter 預設 in-memory 儲存（per-worker，非跨 worker 共享）— Phase 1 可接受，未來要跨 worker 精確限流需接共享後端（如 Redis），列入後續加固。

## 後續（各自 JIT plan）
- 登入頁 UI（Apple 計算機 + 幣別換算落地頁）+ 相機擷取 JS + 後台 HTML 模板。
- 上傳 + OCR、暫存區、店管理者稽核、會計核銷。
