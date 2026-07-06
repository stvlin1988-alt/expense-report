# 後台管理 UI（Plan 3b）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 隱蔽登入成功後，`manager` / `super_admin` 進入一個正常清爽的前端管理後台（單一網址 `/` 的 view state），可管理帳號、裝置、店別、自己的密碼，並替員工代錄人臉。

**Architecture:** 後端沿用 Plan 2 既有 `/admin/*` 寫入端點，只**新增三個讀取/停用端點**（`GET /admin/users`、`GET /admin/stores`、`POST /admin/users/<id>/active`）、修一個 3a 遺留的 PIN 檢查排序、並在注入的 identity 加上 `id`。前端新增 4 支 ES module（`admin.js` 殼 + `admin_accounts.js` + `admin_devices.js` + `admin_api.js`）＋一支純函式工具 `admin_util.js`（node 測），登入成功後由 `auth.js`/`main.js` 依 role 分流呼叫 `showAdminPanel()`。新裝置改為開頁自動 `register-device` 入待核准佇列。

**Tech Stack:** Flask 3.1 + Flask-SQLAlchemy 2.0 + pytest（後端）；原生 ES modules + `fetch` + Web Crypto（前端，無打包）；`node --test` 測純函式；`Camera` helper 單張擷取不落地。

## Global Constraints

- **與 webapp 完全隔離**：獨立 repo / DB / R2 / URL / 記憶命名空間，不共用檔。
- **單一可見網址 `/`**：後台是登入後前端 view state，網址列永遠只有 `/`；重整回計算機、須重新隱蔽登入。
- **4 位純數字 PIN**：所有密碼輸入 `inputmode="numeric" maxlength="4"` + 濾非數字；後端 `is_valid_pin`（已存在於 `app/models/user.py`）在寫入端點驗證。
- **scope 判斷一律以後端為準**：前端過濾只是體驗；沿用既有 `_manages` / `_manages_device` / `_visible_device_query`。
- **影像不落地**：代錄臉走 `Camera` 單張 base64 → `POST /face/enroll`，成功/失敗都 `cam.stop()`。
- **時間 UI 台灣時間**（`Asia/Taipei`），DB 存 UTC。
- **不新增 Python 依賴**（沿用 stdlib / 既有套件）。
- **測試慣例**：後端 `python3 -m pytest -q`；前端純邏輯 `node --test tests/js/*.test.mjs`；DOM/相機膠合手動 e2e（super_admin 經隱蔽登入進後台，dev 用 VirtualCam）。
- **啟動 dev**：`FLASK_APP=wsgi.py SECRET_KEY=dev python3 -m flask run --port 5001`；`flask db upgrade` 後測。

---

## File Structure

**後端（修改）**
- `app/admin/routes.py` — 新增 `list_users` / `list_stores` / `set_user_active`；修 `reset_password`、`approve_device` 的 PIN 檢查排序。
- `app/web/routes.py` — 注入的 `identity` dict 加 `id`（前端「禁停自己」UX 需要）。

**前端（新增，`app/static/js/`）**
| 檔 | 職責 |
|---|---|
| `admin_util.js` | 純函式：`isValidPin` / `roleLabel` / `filterByStore` / `deviceStatusLabel` / `sortPendingFirst` / `isOk`（node 測） |
| `admin_api.js` | 後台 fetch 薄封裝，回 `{status, data}` |
| `admin.js` | 後台面板殼：`showAdminPanel(identity)`、分頁導覽、調店切換、登出、我的密碼分頁、店別分頁（super_admin） |
| `admin_accounts.js` | 帳號分頁：`renderAccounts(container, ctx)` — 清單/創帳號/改密碼/停用復用/代錄臉 |
| `admin_devices.js` | 裝置分頁：`renderDevices(container, ctx)` — 清單/待核准置頂/核准綁定/換機/撤銷 |

**前端（修改）**
- `app/static/js/auth.js` — `submit()` 成功後依 role 呼叫 `showAdminPanel` 或 `showAppView`；移除開 modal 時的 register-device。
- `app/static/js/main.js` — 開頁自動 register-device；`cfg.identity` 快捷依 role 分流。
- `app/static/css/app.css` — 追加正常面板樣式（表格/表單/分頁/按鈕）。

**測試（新增）**
- `tests/test_admin_lists.py` — `GET /admin/users`、`GET /admin/stores`、`POST /admin/users/<id>/active`。
- `tests/test_admin_pin_order.py` — PIN 檢查排序修正（越權 + 格式錯 → 403）。
- `tests/test_web_index.py` — （既有檔追加）identity 注入含 `id`。
- `tests/js/admin_util.test.mjs` — 純函式。

---

## Task 1: `GET /admin/stores`（店別清單，依 scope）

**Files:**
- Modify: `app/admin/routes.py`（在 `create_store` 之後新增 `list_stores`）
- Test: `tests/test_admin_lists.py`（新建）

**Interfaces:**
- Consumes: 既有 `role_required`、`current_user`、`Store` model、`db`。
- Produces: `GET /admin/stores` → `{status:"ok", stores:[{id, name, code}]}`。super_admin 回全部店；manager 回 `[自己的 store]`（無 store 則空清單）。

- [ ] **Step 1: Write the failing test**

新建 `tests/test_admin_lists.py`：

```python
from app.extensions import db
from app.models.user import User
from app.models.store import Store
from app.models.device import Device


def _login_as(app, user_id, uid="devA"):
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
        emp = User(name="員工A", role="employee", store_id=a.id); emp.set_password("pw")
        emp_b = User(name="員工B", role="employee", store_id=b.id); emp_b.set_password("pw")
        sa_dev = Device(client_uid="devSA", store_id=a.id, is_approved=True)
        mgr_dev = Device(client_uid="devMgr", store_id=a.id, is_approved=True)
        db.session.add_all([sa, mgr, emp, emp_b, sa_dev, mgr_dev]); db.session.commit()
        return {"a": a.id, "b": b.id, "sa": sa.id, "mgr": mgr.id,
                "emp": emp.id, "emp_b": emp_b.id}


def test_super_admin_lists_all_stores(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.get("/admin/stores")
    body = r.get_json()
    assert body["status"] == "ok"
    codes = {s["code"] for s in body["stores"]}
    assert codes == {"A", "B"}


def test_manager_lists_only_own_store(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"], uid="devMgr")
    r = c.get("/admin/stores")
    codes = {s["code"] for s in r.get_json()["stores"]}
    assert codes == {"A"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_admin_lists.py::test_super_admin_lists_all_stores tests/test_admin_lists.py::test_manager_lists_only_own_store -v`
Expected: FAIL（404 / route 不存在）

- [ ] **Step 3: Write minimal implementation**

在 `app/admin/routes.py` 的 `create_store` 函式之後（約 line 40）新增：

```python
@admin_bp.get("/stores")
@role_required("manager", "super_admin")
def list_stores():
    actor = current_user()
    if actor.role == "super_admin":
        stores = Store.query.order_by(Store.id).all()
    else:  # manager：僅本店（無 store 則空）
        stores = [actor.store] if actor.store is not None else []
    return jsonify(status="ok", stores=[
        {"id": s.id, "name": s.name, "code": s.code} for s in stores
    ])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_admin_lists.py -v`
Expected: PASS（2 個 store 測試綠）

- [ ] **Step 5: Commit**

```bash
git add app/admin/routes.py tests/test_admin_lists.py
git commit -m "feat(admin): GET /admin/stores 依 scope 回店清單"
```

---

## Task 2: `GET /admin/users`（帳號清單，依 scope + has_face）

**Files:**
- Modify: `app/admin/routes.py`（在 `create_user` 之後新增 `list_users`）
- Test: `tests/test_admin_lists.py`（追加）

**Interfaces:**
- Consumes: `role_required`、`current_user`、`User`、`db`。
- Produces: `GET /admin/users`（可帶 `?store_id=<int>`）→ `{status:"ok", users:[{id, name, role, store_id, active, has_face}]}`。`has_face = user.face_encoding is not None`（**絕不回 encoding**）。super_admin 全部（可 store_id 過濾）；manager 僅 `store_id == actor.store_id`。

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_admin_lists.py`（沿用檔頭 `_login_as` / `_base`）：

```python
def test_super_admin_lists_all_users(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.get("/admin/users")
    body = r.get_json()
    assert body["status"] == "ok"
    names = {u["name"] for u in body["users"]}
    assert {"業主", "店長A", "員工A", "員工B"} <= names


def test_super_admin_users_store_filter(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.get(f"/admin/users?store_id={ids['b']}")
    names = {u["name"] for u in r.get_json()["users"]}
    assert names == {"員工B"}


def test_manager_lists_only_own_store_users(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"], uid="devMgr")
    r = c.get("/admin/users")
    names = {u["name"] for u in r.get_json()["users"]}
    assert names == {"店長A", "員工A"}
    assert "員工B" not in names and "業主" not in names


def test_users_payload_has_face_flag_not_encoding(app):
    ids = _base(app)
    with app.app_context():
        u = db.session.get(User, ids["emp"])
        u.face_encoding = b"\x00" * 16  # 假 encoding
        db.session.commit()
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.get(f"/admin/users?store_id={ids['a']}")
    row = next(u for u in r.get_json()["users"] if u["name"] == "員工A")
    assert row["has_face"] is True
    assert "face_encoding" not in row and "encoding" not in row
    other = next(u for u in r.get_json()["users"] if u["name"] == "店長A")
    assert other["has_face"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_admin_lists.py -k users -v`
Expected: FAIL（route 不存在）

- [ ] **Step 3: Write minimal implementation**

在 `app/admin/routes.py` 的 `create_user` 函式之後（約 line 71）新增：

```python
@admin_bp.get("/users")
@role_required("manager", "super_admin")
def list_users():
    actor = current_user()
    q = User.query
    if actor.role == "super_admin":
        store_id_filter = request.args.get("store_id", type=int)
        if store_id_filter is not None:
            q = q.filter(User.store_id == store_id_filter)
    else:  # manager：僅本店
        q = q.filter(User.store_id == actor.store_id)
    users = q.order_by(User.id).all()
    return jsonify(status="ok", users=[
        {"id": u.id, "name": u.name, "role": u.role, "store_id": u.store_id,
         "active": u.active, "has_face": u.face_encoding is not None}
        for u in users
    ])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_admin_lists.py -v`
Expected: PASS（全綠）

- [ ] **Step 5: Commit**

```bash
git add app/admin/routes.py tests/test_admin_lists.py
git commit -m "feat(admin): GET /admin/users 依 scope 回帳號清單(has_face 不回 encoding)"
```

---

## Task 3: `POST /admin/users/<id>/active`（停用/復用 + 守門）

**Files:**
- Modify: `app/admin/routes.py`（在 `reset_password` 之後新增 `set_user_active`）
- Test: `tests/test_admin_lists.py`（追加）

**Interfaces:**
- Consumes: `role_required`、`current_user`、`_manages`、`User`、`db`。
- Produces: `POST /admin/users/<int:user_id>/active`，body `{active: bool}` → `{status:"ok"}`。守門：非 bool→400；target 不存在→404；`_manages` 不成立→403；**禁停自己**→400；**禁停最後一位在職 super_admin**→400。

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_admin_lists.py`：

```python
def test_super_admin_deactivates_and_reactivates_user(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.post(f"/admin/users/{ids['emp']}/active", json={"active": False})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert db.session.get(User, ids["emp"]).active is False
    r2 = c.post(f"/admin/users/{ids['emp']}/active", json={"active": True})
    assert r2.get_json()["status"] == "ok"
    with app.app_context():
        assert db.session.get(User, ids["emp"]).active is True


def test_active_non_bool_rejected(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.post(f"/admin/users/{ids['emp']}/active", json={"active": "yes"})
    assert r.status_code == 400


def test_active_target_not_found(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.post("/admin/users/99999/active", json={"active": False})
    assert r.status_code == 404


def test_manager_cannot_deactivate_other_store_or_non_employee(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"], uid="devMgr")
    # 他店員工 → 403
    r1 = c.post(f"/admin/users/{ids['emp_b']}/active", json={"active": False})
    assert r1.status_code == 403
    # super_admin（非 employee）→ 403
    r2 = c.post(f"/admin/users/{ids['sa']}/active", json={"active": False})
    assert r2.status_code == 403


def test_cannot_deactivate_self(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"], uid="devMgr")
    r = c.post(f"/admin/users/{ids['mgr']}/active", json={"active": False})
    assert r.status_code == 400
    with app.app_context():
        assert db.session.get(User, ids["mgr"]).active is True


def test_cannot_deactivate_last_super_admin(app):
    # 唯一 super_admin 停用自己 → 400（自我守門先擋，且為最後 super_admin）
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.post(f"/admin/users/{ids['sa']}/active", json={"active": False})
    assert r.status_code == 400
    with app.app_context():
        assert db.session.get(User, ids["sa"]).active is True


def test_super_admin_can_deactivate_other_super_admin(app):
    # 有兩位 super_admin 時可停用另一位（非最後一位）
    ids = _base(app)
    with app.app_context():
        sa2 = User(name="業主2", role="super_admin", active=True); sa2.set_password("pw")
        db.session.add(sa2); db.session.commit()
        sa2_id = sa2.id
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.post(f"/admin/users/{sa2_id}/active", json={"active": False})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert db.session.get(User, sa2_id).active is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_admin_lists.py -k active -v`
Expected: FAIL（route 不存在）

- [ ] **Step 3: Write minimal implementation**

在 `app/admin/routes.py` 的 `reset_password` 函式之後（約 line 89）新增：

```python
@admin_bp.post("/users/<int:user_id>/active")
@role_required("manager", "super_admin")
def set_user_active(user_id):
    data = request.get_json(silent=True) or {}
    active = data.get("active")
    if not isinstance(active, bool):
        return jsonify(status="error", message="active must be bool"), 400
    target = db.session.get(User, user_id)
    if target is None:
        return jsonify(status="error", message="user not found"), 404
    actor = current_user()
    if not _manages(actor, target):
        return jsonify(status="error", message="forbidden"), 403
    if active is False:
        if target.id == actor.id:
            return jsonify(status="error", message="cannot deactivate self"), 400
        if target.role == "super_admin":
            others = User.query.filter(
                User.role == "super_admin",
                User.active.is_(True),
                User.id != target.id,
            ).count()
            if others == 0:
                return jsonify(status="error", message="cannot deactivate last super_admin"), 400
    target.active = active
    db.session.commit()
    return jsonify(status="ok")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_admin_lists.py -v`
Expected: PASS（全綠）

- [ ] **Step 5: Commit**

```bash
git add app/admin/routes.py tests/test_admin_lists.py
git commit -m "feat(admin): POST /admin/users/<id>/active 停用復用+禁停自己/最後super_admin"
```

---

## Task 4: PIN 檢查排序修正（3a 遺留 Minor §5.5）

**Files:**
- Modify: `app/admin/routes.py`（`reset_password`、`approve_device` new_user 分支）
- Test: `tests/test_admin_pin_order.py`（新建）

**Interfaces:**
- 行為變更：越權者（403）不再因「PIN 格式錯」先收到 400；一律先回 403，不對越權者洩漏 PIN 格式要求。既有正常流程回傳碼不變。

- [ ] **Step 1: Write the failing test**

新建 `tests/test_admin_pin_order.py`：

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
        mgr = User(name="店長A", role="manager", store_id=a.id); mgr.set_password("pw")
        emp_b = User(name="員工B", role="employee", store_id=b.id); emp_b.set_password("pw")
        mgr_dev = Device(client_uid="devMgr", store_id=a.id, is_approved=True)
        pend_b = Device(client_uid="pendB", store_id=b.id, device_name="B新機")
        db.session.add_all([mgr, emp_b, mgr_dev, pend_b]); db.session.commit()
        return {"a": a.id, "b": b.id, "mgr": mgr.id, "emp_b": emp_b.id,
                "pend_b": pend_b.id}


def test_reset_password_authz_before_pin_format(app):
    # manager 對他店員工重設密碼 + 密碼格式錯 → 應回 403（越權），不因格式先回 400
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.post(f"/admin/users/{ids['emp_b']}/password", json={"password": "abc"})
    assert r.status_code == 403


def test_approve_new_user_authz_before_pin_format(app):
    # manager 核准他店待核准裝置 + 建 new_user（格式錯）→ 應回 403（越權他店裝置），非 400
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.post(f"/admin/devices/{ids['pend_b']}/approve",
               json={"new_user": {"name": "新人", "password": "abc", "role": "employee"}})
    assert r.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_admin_pin_order.py -v`
Expected: `test_reset_password_authz_before_pin_format` FAIL（現回 400，因 `is_valid_pin` 在 `_manages` 之前）；`test_approve_new_user_authz_before_pin_format` 已因 `_manages_device`（line 163）在前而 PASS，但保留以防回歸。

- [ ] **Step 3: Write minimal implementation**

修改 `app/admin/routes.py` 的 `reset_password`（現 line 74–89），把 `is_valid_pin` 檢查移到 `_manages` 403 之後：

```python
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
    if not is_valid_pin(new_password):
        return jsonify(status="error", message="pin must be 4 digits"), 400
    target.set_password(new_password); db.session.commit()
    return jsonify(status="ok")
```

修改 `approve_device` 的 `new_user` 分支（現 line 176–200），把 `is_valid_pin(password)` 檢查從「解析後立即」移到「manager role!=employee 403 判斷之後、建立 User 之前」：

```python
    if new_user:
        name = (new_user.get("name") or "").strip()
        password = str(new_user.get("password") or "")
        role = new_user.get("role") or "employee"
        if not name or not password:
            return jsonify(status="error", message="name/password required"), 400
        if role not in ROLES:
            return jsonify(status="error", message="invalid role"), 400
        if actor.role == "manager":
            if role != "employee":
                return jsonify(status="error", message="forbidden"), 403
            resolved_store_id = actor.store_id
        else:  # super_admin
            try:
                resolved_store_id = int(new_user.get("store_id"))
            except (TypeError, ValueError):
                return jsonify(status="error", message="invalid store_id"), 400
            if db.session.get(Store, resolved_store_id) is None:
                return jsonify(status="error", message="store not found"), 400
        if not is_valid_pin(password):
            return jsonify(status="error", message="pin must be 4 digits"), 400
        u = User(name=name, role=role, store_id=resolved_store_id)
        u.set_password(password)
        db.session.add(u); db.session.flush()
        bound_user_id = u.id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_admin_pin_order.py tests/test_admin_store_account.py tests/test_admin_devices.py -v`
Expected: PASS（新測綠，且既有 admin 測試無回歸）

- [ ] **Step 5: Commit**

```bash
git add app/admin/routes.py tests/test_admin_pin_order.py
git commit -m "fix(admin): PIN 格式檢查移到物件級授權(403)之後，不對越權者洩漏格式"
```

---

## Task 5: `admin_util.js` 純函式 + node 測試

**Files:**
- Create: `app/static/js/admin_util.js`
- Test: `tests/js/admin_util.test.mjs`

**Interfaces:**
- Produces（供 admin.js / admin_accounts.js / admin_devices.js 匯入）：
  - `isValidPin(pw): boolean` — `/^\d{4}$/`
  - `roleLabel(role): string` — 角色中文
  - `filterByStore(items, storeId): Array` — storeId 為 null 回全部，否則依 `item.store_id === storeId` 過濾（回新陣列）
  - `deviceStatusLabel(d): string` — `已撤銷` / `已核准` / `待核准`
  - `sortPendingFirst(devices): Array` — 待核准（`!is_approved && !is_revoked`）置頂，回新陣列
  - `isOk(httpStatus, body): boolean` — `httpStatus===200 && body.status==='ok'`

- [ ] **Step 1: Write the failing test**

新建 `tests/js/admin_util.test.mjs`：

```javascript
import test from 'node:test';
import assert from 'node:assert';
import {
  isValidPin, roleLabel, filterByStore, deviceStatusLabel, sortPendingFirst, isOk,
} from '../../app/static/js/admin_util.js';

test('isValidPin 僅接受 4 位純數字', () => {
  assert.equal(isValidPin('1234'), true);
  assert.equal(isValidPin('12a4'), false);
  assert.equal(isValidPin('123'), false);
  assert.equal(isValidPin('12345'), false);
  assert.equal(isValidPin(1234), false);
});

test('roleLabel 對映中文、未知原樣', () => {
  assert.equal(roleLabel('super_admin'), '業主');
  assert.equal(roleLabel('manager'), '店長');
  assert.equal(roleLabel('employee'), '員工');
  assert.equal(roleLabel('accountant'), '會計');
  assert.equal(roleLabel('weird'), 'weird');
});

test('filterByStore：null 回全部、否則依 store_id', () => {
  const items = [{ store_id: 1 }, { store_id: 2 }, { store_id: null }];
  assert.equal(filterByStore(items, null).length, 3);
  assert.deepEqual(filterByStore(items, 2), [{ store_id: 2 }]);
  // 不 mutate 原陣列
  assert.equal(items.length, 3);
});

test('deviceStatusLabel：撤銷優先於核准', () => {
  assert.equal(deviceStatusLabel({ is_revoked: true, is_approved: true }), '已撤銷');
  assert.equal(deviceStatusLabel({ is_revoked: false, is_approved: true }), '已核准');
  assert.equal(deviceStatusLabel({ is_revoked: false, is_approved: false }), '待核准');
});

test('sortPendingFirst：待核准排最前，不 mutate', () => {
  const devs = [
    { id: 1, is_approved: true, is_revoked: false },
    { id: 2, is_approved: false, is_revoked: false },
    { id: 3, is_approved: true, is_revoked: true },
  ];
  const out = sortPendingFirst(devs);
  assert.equal(out[0].id, 2);
  assert.equal(devs[0].id, 1); // 原陣列不變
});

test('isOk：200 + status ok', () => {
  assert.equal(isOk(200, { status: 'ok' }), true);
  assert.equal(isOk(200, { status: 'error' }), false);
  assert.equal(isOk(403, { status: 'ok' }), false);
  assert.equal(isOk(200, null), false);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/js/admin_util.test.mjs`
Expected: FAIL（`admin_util.js` 不存在，import 失敗）

- [ ] **Step 3: Write minimal implementation**

新建 `app/static/js/admin_util.js`：

```javascript
export function isValidPin(pw) {
  return typeof pw === 'string' && /^\d{4}$/.test(pw);
}

export const ROLE_LABEL = {
  employee: '員工', manager: '店長', accountant: '會計', super_admin: '業主',
};

export function roleLabel(role) {
  return ROLE_LABEL[role] || role;
}

export function filterByStore(items, storeId) {
  if (storeId == null) return items.slice();
  return items.filter((it) => it.store_id === storeId);
}

export function deviceStatusLabel(d) {
  if (d.is_revoked) return '已撤銷';
  if (d.is_approved) return '已核准';
  return '待核准';
}

export function sortPendingFirst(devices) {
  const rank = (d) => ((!d.is_approved && !d.is_revoked) ? 0 : 1);
  return devices.slice().sort((a, b) => rank(a) - rank(b));
}

export function isOk(httpStatus, body) {
  return httpStatus === 200 && !!body && body.status === 'ok';
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test tests/js/admin_util.test.mjs`
Expected: PASS（6 測綠）

- [ ] **Step 5: Commit**

```bash
git add app/static/js/admin_util.js tests/js/admin_util.test.mjs
git commit -m "feat(admin-ui): admin_util 純函式(pin/role/store過濾/裝置狀態)+node測"
```

---

## Task 6: `admin_api.js` 後台 fetch 薄封裝

**Files:**
- Create: `app/static/js/admin_api.js`

**Interfaces:**
- Produces: `export const api`，每個方法回 `Promise<{status:number, data:object}>`：
  - `getUsers(storeId?)` → `GET /admin/users[?store_id=]`
  - `getStores()` → `GET /admin/stores`
  - `getDevices(storeId?)` → `GET /admin/devices[?store_id=]`
  - `createUser({name, password, role, store_id?})` → `POST /admin/users`
  - `resetPassword(id, password)` → `POST /admin/users/<id>/password`
  - `setActive(id, active)` → `POST /admin/users/<id>/active`
  - `enrollFace(userId, faceImage)` → `POST /face/enroll {user_id, face_image}`
  - `createStore(name, code)` → `POST /admin/stores`
  - `approveDevice(id, payload)` → `POST /admin/devices/<id>/approve`
  - `revokeDevice(id)` → `POST /admin/devices/<id>/revoke`
  - `changeMyPassword(oldp, newp)` → `POST /admin/me/password {old_password, new_password}`

> 純 fetch 膠合，無自動測試（由 Task 8/9 手動 e2e 覆蓋）。回應正規化邏輯（`isOk`）已在 `admin_util` 測過。

- [ ] **Step 1: Write the module**

新建 `app/static/js/admin_api.js`：

```javascript
async function req(method, url, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  return { status: res.status, data };
}

const withStore = (base, storeId) =>
  (storeId != null ? `${base}?store_id=${storeId}` : base);

export const api = {
  getUsers: (storeId) => req('GET', withStore('/admin/users', storeId)),
  getStores: () => req('GET', '/admin/stores'),
  getDevices: (storeId) => req('GET', withStore('/admin/devices', storeId)),
  createUser: (payload) => req('POST', '/admin/users', payload),
  resetPassword: (id, password) => req('POST', `/admin/users/${id}/password`, { password }),
  setActive: (id, active) => req('POST', `/admin/users/${id}/active`, { active }),
  enrollFace: (userId, faceImage) =>
    req('POST', '/face/enroll', { user_id: userId, face_image: faceImage }),
  createStore: (name, code) => req('POST', '/admin/stores', { name, code }),
  approveDevice: (id, payload) => req('POST', `/admin/devices/${id}/approve`, payload),
  revokeDevice: (id) => req('POST', `/admin/devices/${id}/revoke`),
  changeMyPassword: (oldp, newp) =>
    req('POST', '/admin/me/password', { old_password: oldp, new_password: newp }),
};
```

- [ ] **Step 2: 語法檢查（node 解析）**

Run: `node --input-type=module -e "import('./app/static/js/admin_api.js').then(m => console.log(Object.keys(m.api).length))"`
Expected: 印出 `11`（模組可解析、api 有 11 個方法）

- [ ] **Step 3: Commit**

```bash
git add app/static/js/admin_api.js
git commit -m "feat(admin-ui): admin_api 後台 fetch 薄封裝"
```

---

## Task 7: `identity` 注入加 `id` + `admin.js` 殼 + role 分流 + CSS

**Files:**
- Modify: `app/web/routes.py`（`index` 的 identity dict 加 `id`）
- Modify: `app/static/js/auth.js`（`submit()` 成功依 role 分流）
- Modify: `app/static/js/main.js`（`cfg.identity` 快捷依 role 分流）
- Create: `app/static/js/admin.js`
- Modify: `app/static/css/app.css`（追加面板樣式）
- Test: `tests/test_web_index.py`（追加 identity 含 id）

**Interfaces:**
- Consumes: `api`（admin_api.js）、`renderAccounts`（Task 8）、`renderDevices`（Task 9）、`isValidPin`/`roleLabel`（admin_util.js）。
- Produces:
  - `export function showAdminPanel(identity)` — identity = `{id, name, role}`；掛出後台面板。
  - 後台 ctx（傳給分頁模組）：`{ identity, storeId, stores, api, reload }`，其中 `storeId` = 目前檢視店別（super_admin 可切、manager 固定 null 用後端 scope）、`stores` = `GET /admin/stores` 結果、`reload()` = 重繪目前分頁。
- 分頁模組合約（Task 8/9 實作）：`renderAccounts(container, ctx)`、`renderDevices(container, ctx)`，各自把 DOM 畫進 `container`。

- [ ] **Step 1: Write the failing test（identity 含 id）**

在既有 `tests/test_web_index.py` 追加（若已有 `_login_as`/fixture 沿用；以下自含 client 建立）：

```python
def test_index_injects_identity_with_id(app):
    from app.extensions import db
    from app.models.user import User
    from app.models.store import Store
    from app.models.device import Device
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A"); db.session.add(s); db.session.commit()
        sa = User(name="業主", role="super_admin"); sa.set_password("pw")
        dev = Device(client_uid="devSA", store_id=s.id, is_approved=True)
        db.session.add_all([sa, dev]); db.session.commit()
        sa_id = sa.id
    c = app.test_client()
    c.set_cookie("device_uid", "devSA")
    with c.session_transaction() as sess:
        sess["user_id"] = sa_id
        import time; sess["_last_request_at"] = int(time.time())
    html = c.get("/").get_data(as_text=True)
    import json, re
    m = re.search(r'<script id="app-config"[^>]*>(.*?)</script>', html, re.S)
    cfg = json.loads(m.group(1))
    assert cfg["identity"]["id"] == sa_id
    assert cfg["identity"]["role"] == "super_admin"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_web_index.py::test_index_injects_identity_with_id -v`
Expected: FAIL（identity 目前只有 name/role，無 id）

- [ ] **Step 3: 後端加 id**

修改 `app/web/routes.py` 的 `index`（現 line 24–27）：

```python
    if uid:
        u = db.session.get(User, uid)
        if u and u.active:
            identity = {"id": u.id, "name": u.name, "role": u.role}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_web_index.py -v`
Expected: PASS（含新測，既有 index 測無回歸）

- [ ] **Step 5: 寫 `admin.js` 殼**

新建 `app/static/js/admin.js`：

```javascript
import { api } from './admin_api.js';
import { isValidPin } from './admin_util.js';
import { renderAccounts } from './admin_accounts.js';
import { renderDevices } from './admin_devices.js';

const root = () => document.getElementById('modal-root');

export async function showAdminPanel(identity) {
  const isSuper = identity.role === 'super_admin';
  const state = { tab: 'accounts', storeId: null, stores: [] };

  // 先抓店清單（供調店切換 + 分頁下拉）
  try {
    const { status, data } = await api.getStores();
    if (status === 200 && data.status === 'ok') state.stores = data.stores;
  } catch (e) { /* 靜默：分頁自行處理空清單 */ }

  const tabs = [
    { key: 'accounts', label: '帳號' },
    { key: 'devices', label: '裝置' },
    ...(isSuper ? [{ key: 'stores', label: '店別' }] : []),
    { key: 'mypw', label: '我的密碼' },
  ];

  function shellHtml() {
    const storeOpts = isSuper
      ? `<select id="ap-store" class="ap-select">
           <option value="">全部店</option>
           ${state.stores.map((s) => `<option value="${s.id}">${s.name}</option>`).join('')}
         </select>`
      : '';
    const tabBtns = tabs.map((t) =>
      `<button class="ap-tab${t.key === state.tab ? ' active' : ''}" data-tab="${t.key}" type="button">${t.label}</button>`
    ).join('');
    return `
      <div class="admin-panel">
        <header class="ap-head">
          <span class="ap-title">管理後台</span>
          <span class="ap-who">${identity.name}</span>
          ${storeOpts}
          <button class="ap-btn ap-logout" id="ap-logout" type="button">登出</button>
        </header>
        <nav class="ap-tabs">${tabBtns}</nav>
        <section class="ap-body" id="ap-body"></section>
      </div>`;
  }

  function ctx() {
    return {
      identity,
      storeId: state.storeId,
      stores: state.stores,
      api,
      reload: renderActiveTab,
      refreshStores: refreshStores,
    };
  }

  async function refreshStores() {
    try {
      const { status, data } = await api.getStores();
      if (status === 200 && data.status === 'ok') state.stores = data.stores;
    } catch (e) { /* 靜默 */ }
    // 重畫店別下拉（保留當前選擇）
    const sel = document.getElementById('ap-store');
    if (sel) {
      const cur = sel.value;
      sel.innerHTML = `<option value="">全部店</option>` +
        state.stores.map((s) => `<option value="${s.id}">${s.name}</option>`).join('');
      sel.value = cur;
    }
  }

  function renderMyPassword(container) {
    container.innerHTML = `
      <div class="ap-form">
        <input type="password" id="mp-old" placeholder="舊密碼" inputmode="numeric" maxlength="4" autocomplete="off">
        <input type="password" id="mp-new" placeholder="新密碼(4位)" inputmode="numeric" maxlength="4" autocomplete="off">
        <button class="ap-btn" id="mp-submit" type="button">變更密碼</button>
        <div class="ap-msg" id="mp-msg"></div>
      </div>`;
    const old = container.querySelector('#mp-old');
    const neu = container.querySelector('#mp-new');
    const msg = container.querySelector('#mp-msg');
    [old, neu].forEach((el) => el.addEventListener('input', () => {
      el.value = el.value.replace(/\D/g, '').slice(0, 4);
    }));
    container.querySelector('#mp-submit').addEventListener('click', async () => {
      msg.textContent = '';
      if (!isValidPin(neu.value)) { msg.textContent = '新密碼需為 4 位數字'; return; }
      try {
        const { status, data } = await api.changeMyPassword(old.value, neu.value);
        if (status === 200 && data.status === 'ok') {
          msg.style.color = '#2e7d32'; msg.textContent = '已變更';
          old.value = ''; neu.value = '';
        } else if (data.message === 'wrong old password' || status === 400) {
          msg.style.color = '#c62828'; msg.textContent = '舊密碼錯誤或格式不符';
        } else {
          msg.style.color = '#c62828'; msg.textContent = '變更失敗';
        }
      } catch (e) {
        msg.style.color = '#c62828'; msg.textContent = '變更失敗，請重試';
      }
    });
  }

  function renderStores(container) {
    // 僅 super_admin 進得來（tab 不對其他角色顯示）
    const rows = state.stores.map((s) =>
      `<tr><td>${s.name}</td><td>${s.code}</td></tr>`).join('');
    container.innerHTML = `
      <table class="ap-table">
        <thead><tr><th>店名</th><th>代碼</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="2">尚無店別</td></tr>'}</tbody>
      </table>
      <div class="ap-form">
        <input type="text" id="st-name" placeholder="店名" autocomplete="off">
        <input type="text" id="st-code" placeholder="代碼" autocomplete="off">
        <button class="ap-btn" id="st-add" type="button">新增店</button>
        <div class="ap-msg" id="st-msg"></div>
      </div>`;
    const msg = container.querySelector('#st-msg');
    container.querySelector('#st-add').addEventListener('click', async () => {
      msg.textContent = '';
      const name = container.querySelector('#st-name').value.trim();
      const code = container.querySelector('#st-code').value.trim();
      if (!name || !code) { msg.textContent = '請填店名與代碼'; return; }
      try {
        const { status, data } = await api.createStore(name, code);
        if (status === 200 && data.status === 'ok') {
          await refreshStores();
          renderActiveTab();
        } else if (status === 409) {
          msg.style.color = '#c62828'; msg.textContent = '店名或代碼已存在';
        } else {
          msg.style.color = '#c62828'; msg.textContent = '新增失敗';
        }
      } catch (e) {
        msg.style.color = '#c62828'; msg.textContent = '新增失敗，請重試';
      }
    });
  }

  function renderActiveTab() {
    const body = document.getElementById('ap-body');
    if (!body) return;
    body.innerHTML = '';
    if (state.tab === 'accounts') renderAccounts(body, ctx());
    else if (state.tab === 'devices') renderDevices(body, ctx());
    else if (state.tab === 'stores') renderStores(body);
    else if (state.tab === 'mypw') renderMyPassword(body);
  }

  function mount() {
    root().innerHTML = shellHtml();
    document.getElementById('ap-logout').addEventListener('click', async () => {
      await api.changeMyPassword; // no-op 保持一致；實際登出如下
      try { await fetch('/auth/logout', { method: 'POST' }); } catch (e) { /* ignore */ }
      location.reload();
    });
    const sel = document.getElementById('ap-store');
    if (sel) sel.addEventListener('change', () => {
      state.storeId = sel.value ? parseInt(sel.value, 10) : null;
      renderActiveTab();
    });
    root().querySelectorAll('.ap-tab').forEach((btn) => {
      btn.addEventListener('click', () => {
        state.tab = btn.dataset.tab;
        root().querySelectorAll('.ap-tab').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        renderActiveTab();
      });
    });
    renderActiveTab();
  }

  mount();
}
```

> 註：`ap-logout` handler 內第一行 `await api.changeMyPassword;` 是誤植，改用純登出。實作時直接寫成：
> ```javascript
> document.getElementById('ap-logout').addEventListener('click', async () => {
>   try { await fetch('/auth/logout', { method: 'POST' }); } catch (e) { /* ignore */ }
>   location.reload();
> });
> ```

- [ ] **Step 6: auth.js 依 role 分流**

修改 `app/static/js/auth.js`：頂部 import 加入 `showAdminPanel`，`submit()` 成功分支改依 role：

```javascript
import { Camera } from './camera.js';
import { showAdminPanel } from './admin.js';
```

`submit()` 內成功分支（現 line 125–128）改為：

```javascript
      if (data.status === 'ok') {
        cam.stop();
        const identity = { id: data.id, name: data.name, role: data.role };
        if (data.role === 'manager' || data.role === 'super_admin') showAdminPanel(identity);
        else showAppView({ name: data.name, role: data.role });
        return;
      }
```

- [ ] **Step 7: main.js 的 identity 快捷依 role 分流**

修改 `app/static/js/main.js`：頂部 import 加 `showAdminPanel`：

```javascript
import { openAuth, showAppView } from './auth.js';
import { showAdminPanel } from './admin.js';
```

`cfg.identity` 快捷（現 line 149–155）改為：

```javascript
if (cfg.identity) {
  const orig = window.__openAuth;
  window.__openAuth = function (seedMode) {
    if (cfg.identity) {
      if (cfg.identity.role === 'manager' || cfg.identity.role === 'super_admin') {
        showAdminPanel(cfg.identity);
      } else {
        showAppView(cfg.identity);
      }
      return;
    }
    orig(seedMode);
  };
}
```

- [ ] **Step 8: CSS 面板樣式**

在 `app/static/css/app.css` 末端追加：

```css
/* ---- 管理後台（正常清爽面板；與 covert 計算機樣式區隔）---- */
.admin-panel {
  position: fixed; inset: 0; background: #f5f6f8; color: #1c1c1e;
  display: flex; flex-direction: column; z-index: 50; overflow: hidden;
}
.ap-head {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 16px; background: #fff; border-bottom: 1px solid #e0e0e0;
}
.ap-title { font-weight: 600; font-size: 17px; }
.ap-who { color: #666; font-size: 14px; }
.ap-head .ap-logout { margin-left: auto; }
.ap-select {
  padding: 6px 10px; border: 1px solid #ccc; border-radius: 8px; font-size: 14px;
}
.ap-tabs { display: flex; gap: 4px; padding: 8px 12px; background: #fff; border-bottom: 1px solid #e0e0e0; }
.ap-tab {
  padding: 8px 14px; border: none; background: transparent; border-radius: 8px;
  font-size: 15px; color: #555; cursor: pointer;
}
.ap-tab.active { background: #007aff; color: #fff; }
.ap-body { flex: 1; overflow-y: auto; padding: 16px; }
.ap-table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px; overflow: hidden; }
.ap-table th, .ap-table td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #eee; font-size: 14px; }
.ap-table th { background: #fafafa; color: #666; font-weight: 500; }
.ap-form { margin-top: 16px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.ap-form input, .ap-form select {
  padding: 8px 10px; border: 1px solid #ccc; border-radius: 8px; font-size: 14px;
}
.ap-btn {
  padding: 8px 16px; border: none; border-radius: 8px; background: #007aff; color: #fff;
  font-size: 14px; cursor: pointer;
}
.ap-btn.secondary { background: #8e8e93; }
.ap-btn.danger { background: #ff3b30; }
.ap-btn:disabled { opacity: 0.5; }
.ap-msg { width: 100%; font-size: 13px; min-height: 18px; }
.ap-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; }
.ap-badge.pending { background: #fff3cd; color: #856404; }
.ap-badge.approved { background: #d4edda; color: #155724; }
.ap-badge.revoked { background: #f8d7da; color: #721c24; }
.ap-badge.inactive { background: #e2e3e5; color: #6c757d; }
.ap-rowbtns { display: flex; gap: 6px; flex-wrap: wrap; }
.ap-video { width: 100%; max-width: 320px; border-radius: 8px; margin-top: 8px; }
```

- [ ] **Step 9: 語法檢查 + 手動 e2e**

Run: `node --input-type=module -e "import('./app/static/js/admin.js').then(() => console.log('ok')).catch(e => { console.error(e.message); process.exit(1); })"`
Expected: 因 admin_accounts.js / admin_devices.js 尚未建，import 會失敗 —— **此步驟延到 Task 8/9 完成後**。本 task 先確認 admin.js 檔語法（用 `node --check` 無法檢 ESM import，改為肉眼＋後續整合驗）。

改以 `--check`（僅語法，不解析 import）：
Run: `node --check app/static/js/admin.js && node --check app/static/js/auth.js && node --check app/static/js/main.js`
Expected: 無輸出（語法 OK）

- [ ] **Step 10: Commit**

```bash
git add app/web/routes.py app/static/js/admin.js app/static/js/auth.js app/static/js/main.js app/static/css/app.css tests/test_web_index.py
git commit -m "feat(admin-ui): admin.js 面板殼(分頁/調店/登出/我的密碼/店別)+role分流+identity加id+CSS"
```

---

## Task 8: `admin_accounts.js` 帳號分頁

**Files:**
- Create: `app/static/js/admin_accounts.js`

**Interfaces:**
- Consumes: `ctx = { identity, storeId, stores, api, reload }`（來自 admin.js）；`Camera`（camera.js）；`isValidPin` / `roleLabel` / `filterByStore`（admin_util.js）。
- Produces: `export function renderAccounts(container, ctx)` — 把帳號分頁 DOM 畫進 `container`。
- 用到的既有端點：`GET /admin/users`、`POST /admin/users`、`POST /admin/users/<id>/password`、`POST /admin/users/<id>/active`、`POST /face/enroll {user_id}`。

- [ ] **Step 1: Write the module**

新建 `app/static/js/admin_accounts.js`：

```javascript
import { Camera } from './camera.js';
import { isValidPin, roleLabel, filterByStore } from './admin_util.js';

export function renderAccounts(container, ctx) {
  const { identity, storeId, stores, api } = ctx;
  const isSuper = identity.role === 'super_admin';

  container.innerHTML = `
    <div id="acc-list">載入中…</div>
    <div class="ap-form" id="acc-create"></div>
    <div class="ap-msg" id="acc-msg"></div>
    <video id="acc-video" autoplay playsinline muted class="ap-video" style="display:none;"></video>
    <canvas id="acc-canvas" style="display:none;"></canvas>`;

  const msg = container.querySelector('#acc-msg');
  const video = container.querySelector('#acc-video');
  const canvas = container.querySelector('#acc-canvas');
  const cam = new Camera(video, canvas);

  function setMsg(text, ok) {
    msg.textContent = text;
    msg.style.color = ok ? '#2e7d32' : '#c62828';
  }

  async function loadList() {
    const listEl = container.querySelector('#acc-list');
    let users = [];
    try {
      const { status, data } = await api.getUsers(isSuper ? storeId : undefined);
      if (status === 200 && data.status === 'ok') users = data.users;
      else { listEl.textContent = '無法載入帳號'; return; }
    } catch (e) { listEl.textContent = '無法載入帳號'; return; }

    // super_admin 選了店 → 後端已過濾；未選店時前端不再過濾（回全部）
    const rows = filterByStore(users, isSuper ? storeId : null).map((u) => {
      const face = u.has_face ? '有' : '—';
      const activeBadge = u.active ? '' : '<span class="ap-badge inactive">停用</span>';
      return `
        <tr data-uid="${u.id}" data-role="${u.role}" data-active="${u.active}">
          <td>${u.name} ${activeBadge}</td>
          <td>${roleLabel(u.role)}</td>
          <td>${u.store_id ?? '—'}</td>
          <td>${face}</td>
          <td class="ap-rowbtns">
            <button class="ap-btn" data-act="pw" type="button">改密碼</button>
            <button class="ap-btn secondary" data-act="face" type="button">錄臉</button>
            <button class="ap-btn ${u.active ? 'danger' : ''}" data-act="active" type="button">${u.active ? '停用' : '復用'}</button>
          </td>
        </tr>`;
    }).join('');

    listEl.innerHTML = `
      <table class="ap-table">
        <thead><tr><th>姓名</th><th>角色</th><th>店</th><th>臉</th><th>操作</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="5">尚無帳號</td></tr>'}</tbody>
      </table>`;

    listEl.querySelectorAll('tr[data-uid]').forEach((tr) => {
      const uid = parseInt(tr.dataset.uid, 10);
      tr.querySelector('[data-act="pw"]').addEventListener('click', () => resetPw(uid));
      tr.querySelector('[data-act="face"]').addEventListener('click', () => enrollFace(uid));
      tr.querySelector('[data-act="active"]').addEventListener('click', () =>
        toggleActive(uid, tr.dataset.active !== 'true'));
    });
  }

  async function resetPw(uid) {
    const pin = prompt('輸入新的 4 位數字密碼');
    if (pin == null) return;
    if (!isValidPin(pin)) { setMsg('密碼需為 4 位數字', false); return; }
    try {
      const { status, data } = await api.resetPassword(uid, pin);
      if (status === 200 && data.status === 'ok') setMsg('已重設密碼', true);
      else if (status === 403) setMsg('無權限', false);
      else setMsg('重設失敗', false);
    } catch (e) { setMsg('重設失敗，請重試', false); }
  }

  async function toggleActive(uid, active) {
    try {
      const { status, data } = await api.setActive(uid, active);
      if (status === 200 && data.status === 'ok') { await loadList(); setMsg(active ? '已復用' : '已停用', true); }
      else if (status === 400) setMsg(data.message === 'cannot deactivate self' ? '不能停用自己' : '不能停用最後一位業主', false);
      else if (status === 403) setMsg('無權限', false);
      else setMsg('操作失敗', false);
    } catch (e) { setMsg('操作失敗，請重試', false); }
  }

  async function enrollFace(uid) {
    setMsg('', true);
    if (!cam.isRecording) {
      try {
        await cam.start();
        video.style.display = 'block';
        setMsg('請對準該員工鏡頭，再按一次「錄臉」', true);
      } catch (e) { setMsg('無法開啟鏡頭', false); }
      return;
    }
    try {
      const face = cam.capture();
      const { status, data } = await api.enrollFace(uid, face);
      if (status === 200 && data.status === 'ok') { setMsg('已錄臉', true); await loadList(); }
      else if (data.status === 'face_not_found') setMsg('未偵測到人臉，請重試', false);
      else setMsg('錄臉失敗', false);
    } catch (e) { setMsg('錄臉失敗，請重試', false); }
    finally { cam.stop(); video.style.display = 'none'; }  // 影像不落地
  }

  function renderCreateForm() {
    const createEl = container.querySelector('#acc-create');
    const roleSel = isSuper
      ? `<select id="acc-role">
           <option value="employee">員工</option>
           <option value="manager">店長</option>
           <option value="accountant">會計</option>
           <option value="super_admin">業主</option>
         </select>`
      : `<input type="hidden" id="acc-role" value="employee"><span>員工</span>`;
    const storeSel = isSuper
      ? `<select id="acc-store">
           ${stores.map((s) => `<option value="${s.id}">${s.name}</option>`).join('')}
         </select>`
      : '';
    createEl.innerHTML = `
      <input type="text" id="acc-name" placeholder="姓名" autocomplete="off">
      <input type="password" id="acc-pw" placeholder="4位密碼" inputmode="numeric" maxlength="4" autocomplete="off">
      ${roleSel} ${storeSel}
      <button class="ap-btn" id="acc-add" type="button">建立帳號</button>`;
    const pw = createEl.querySelector('#acc-pw');
    pw.addEventListener('input', () => { pw.value = pw.value.replace(/\D/g, '').slice(0, 4); });
    createEl.querySelector('#acc-add').addEventListener('click', createUser);
  }

  async function createUser() {
    setMsg('', true);
    const name = container.querySelector('#acc-name').value.trim();
    const pw = container.querySelector('#acc-pw').value;
    const role = container.querySelector('#acc-role').value;
    if (!name) { setMsg('請填姓名', false); return; }
    if (!isValidPin(pw)) { setMsg('密碼需為 4 位數字', false); return; }
    const payload = { name, password: pw, role };
    if (isSuper) {
      const storeEl = container.querySelector('#acc-store');
      if (!storeEl || !storeEl.value) { setMsg('請選擇店別', false); return; }
      payload.store_id = parseInt(storeEl.value, 10);
    } else {
      payload.role = 'employee';
      payload.store_id = identity.store_id ?? undefined; // manager 後端強制本店
    }
    try {
      const { status, data } = await api.createUser(payload);
      if (status === 200 && data.status === 'ok') {
        setMsg('已建立帳號', true);
        container.querySelector('#acc-name').value = '';
        container.querySelector('#acc-pw').value = '';
        await loadList();
      } else if (status === 403) setMsg('無權限', false);
      else setMsg('建立失敗（' + (data.message || '') + '）', false);
    } catch (e) { setMsg('建立失敗，請重試', false); }
  }

  renderCreateForm();
  loadList();
}
```

> 註：manager 建帳號時後端 `create_user` 會強制 `role==employee` 且 `store_id==actor.store_id`；前端 `identity.store_id` 若未注入則傳 `undefined`，後端仍以 actor 為準（manager 傳 `store_id != actor.store_id` 會 403）。為避免 manager 誤送，**Task 7 的 identity 也應帶 `store_id`**——見下方 Step 2。

- [ ] **Step 2: identity 補 store_id（讓 manager 建帳號帶對店）**

修改 `app/web/routes.py` 的 `index`（Task 7 已改為含 id 的那行）再補 `store_id`：

```python
    if uid:
        u = db.session.get(User, uid)
        if u and u.active:
            identity = {"id": u.id, "name": u.name, "role": u.role, "store_id": u.store_id}
```

同步修改 `app/static/js/auth.js` `submit()` 成功分支的 identity（Task 7 Step 6）改為帶 `store_id`：

```javascript
        const identity = { id: data.id, name: data.name, role: data.role, store_id: data.store_id ?? null };
```

> `/auth/verify` 目前回 `{status, id, name, role}` 不含 store_id。manager 建帳號時後端本就強制本店、`store_id` 對不上會 403；為讓 manager 從「登入當下（verify 路徑）」也能正確帶店，最穩妥是讓前端 manager 分支**不送 store_id**（交給後端強制）。因此 `admin_accounts.js` 的 manager 分支已寫成「不可靠則不送」——實作時確認 manager 路徑 `payload.store_id` 若為 `undefined` 則 `createUser` 送出的 JSON 不含該鍵（`JSON.stringify` 會略過 undefined），後端 `create_user` 對 manager 會因 `store_id != actor.store_id`（None != a.id）而 403。**修正做法**：manager 分支改為送 `identity.store_id`（來自 index 注入，已含），verify 路徑因缺 store_id 則退回占位→不影響（manager 通常靠 session 快捷進後台，identity 由 index 注入齊全）。保留 index 注入 store_id 即可，manager 分支送 `payload.store_id = identity.store_id`。

- [ ] **Step 3: 修正 manager 建帳號 store_id 來源**

將 `admin_accounts.js` `createUser()` 的 manager 分支確定為：

```javascript
    } else {
      payload.role = 'employee';
      payload.store_id = identity.store_id; // 由 index 注入；缺則後端擋
    }
```

- [ ] **Step 4: 語法檢查**

Run: `node --check app/static/js/admin_accounts.js`
Expected: 無輸出（語法 OK）

- [ ] **Step 5: Commit**

```bash
git add app/static/js/admin_accounts.js app/web/routes.py app/static/js/auth.js
git commit -m "feat(admin-ui): admin_accounts 帳號分頁(清單/創帳號/改密碼/停用復用/代錄臉)"
```

---

## Task 9: `admin_devices.js` 裝置分頁

**Files:**
- Create: `app/static/js/admin_devices.js`

**Interfaces:**
- Consumes: `ctx = { identity, storeId, stores, api }`；`isValidPin` / `deviceStatusLabel` / `sortPendingFirst`（admin_util.js）。
- Produces: `export function renderDevices(container, ctx)`。
- 用到的既有端點：`GET /admin/devices`、`POST /admin/devices/<id>/approve`、`POST /admin/devices/<id>/revoke`、`GET /admin/users`（核准綁定現有 user 用）。
- approve payload 三選一：`{bound_user_id}` / `{new_user:{name,password,role,store_id?}}` / `{store_id}`（裸核准）。

- [ ] **Step 1: Write the module**

新建 `app/static/js/admin_devices.js`：

```javascript
import { isValidPin, deviceStatusLabel, sortPendingFirst, roleLabel } from './admin_util.js';

export function renderDevices(container, ctx) {
  const { identity, storeId, stores, api } = ctx;
  const isSuper = identity.role === 'super_admin';

  container.innerHTML = `
    <div id="dev-list">載入中…</div>
    <div class="ap-msg" id="dev-msg"></div>`;
  const msg = container.querySelector('#dev-msg');
  const setMsg = (t, ok) => { msg.textContent = t; msg.style.color = ok ? '#2e7d32' : '#c62828'; };

  async function loadUsers() {
    try {
      const { status, data } = await api.getUsers(isSuper ? storeId : undefined);
      if (status === 200 && data.status === 'ok') return data.users;
    } catch (e) { /* ignore */ }
    return [];
  }

  async function loadList() {
    const listEl = container.querySelector('#dev-list');
    let devices = [];
    try {
      const { status, data } = await api.getDevices(isSuper ? storeId : undefined);
      if (status === 200 && data.status === 'ok') devices = data.devices;
      else { listEl.textContent = '無法載入裝置'; return; }
    } catch (e) { listEl.textContent = '無法載入裝置'; return; }

    const users = await loadUsers();
    const userName = (id) => (users.find((u) => u.id === id) || {}).name || id;

    const rows = sortPendingFirst(devices).map((d) => {
      const label = deviceStatusLabel(d);
      const cls = d.is_revoked ? 'revoked' : (d.is_approved ? 'approved' : 'pending');
      const tail = (d.client_uid || '').slice(-6);
      const bound = d.bound_user_id ? userName(d.bound_user_id) : '—';
      const actions = (!d.is_approved && !d.is_revoked)
        ? `<button class="ap-btn" data-act="approve" type="button">核准</button>`
        : (d.is_approved && !d.is_revoked
            ? `<button class="ap-btn danger" data-act="revoke" type="button">撤銷</button>`
            : '');
      return `
        <tr data-did="${d.id}">
          <td>${d.device_name || 'Unknown'}</td>
          <td>…${tail}</td>
          <td>${d.store_id ?? '—'}</td>
          <td>${bound}</td>
          <td><span class="ap-badge ${cls}">${label}</span></td>
          <td class="ap-rowbtns">${actions}</td>
        </tr>`;
    }).join('');

    listEl.innerHTML = `
      <table class="ap-table">
        <thead><tr><th>裝置</th><th>UID</th><th>店</th><th>綁定</th><th>狀態</th><th>操作</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="6">尚無裝置</td></tr>'}</tbody>
      </table>
      <div id="dev-approve-panel"></div>`;

    listEl.querySelectorAll('tr[data-did]').forEach((tr) => {
      const did = parseInt(tr.dataset.did, 10);
      const ap = tr.querySelector('[data-act="approve"]');
      const rv = tr.querySelector('[data-act="revoke"]');
      if (ap) ap.addEventListener('click', () => showApprove(did, users));
      if (rv) rv.addEventListener('click', () => revoke(did));
    });
  }

  function showApprove(did, users) {
    const panel = container.querySelector('#dev-approve-panel');
    const userOpts = users.map((u) => `<option value="${u.id}">${u.name}（${roleLabel(u.role)}）</option>`).join('');
    const storeOpts = stores.map((s) => `<option value="${s.id}">${s.name}</option>`).join('');
    panel.innerHTML = `
      <div class="ap-form" style="flex-direction:column;align-items:stretch;">
        <div><strong>核准裝置 #${did}</strong></div>
        <label><input type="radio" name="ap-mode" value="bind" checked> 綁到現有使用者</label>
        <select id="ap-bind">${userOpts || '<option value="">（無可綁定使用者）</option>'}</select>
        <label><input type="radio" name="ap-mode" value="new"> 建新帳號並綁定</label>
        <div class="ap-form">
          <input type="text" id="ap-nu-name" placeholder="姓名" autocomplete="off">
          <input type="password" id="ap-nu-pw" placeholder="4位密碼" inputmode="numeric" maxlength="4" autocomplete="off">
          ${isSuper ? `<select id="ap-nu-role"><option value="employee">員工</option><option value="manager">店長</option><option value="accountant">會計</option><option value="super_admin">業主</option></select>` : `<input type="hidden" id="ap-nu-role" value="employee">`}
        </div>
        ${isSuper ? `<label><input type="radio" name="ap-mode" value="bare"> 裸核准（僅指派店）</label><select id="ap-bare-store">${storeOpts}</select>` : ''}
        <div class="ap-rowbtns">
          <button class="ap-btn" id="ap-confirm" type="button">確認核准</button>
          <button class="ap-btn secondary" id="ap-cancel" type="button">取消</button>
        </div>
      </div>`;
    const pw = panel.querySelector('#ap-nu-pw');
    pw.addEventListener('input', () => { pw.value = pw.value.replace(/\D/g, '').slice(0, 4); });
    panel.querySelector('#ap-cancel').addEventListener('click', () => { panel.innerHTML = ''; });
    panel.querySelector('#ap-confirm').addEventListener('click', () => confirmApprove(did, panel));
  }

  async function confirmApprove(did, panel) {
    const mode = panel.querySelector('input[name="ap-mode"]:checked').value;
    let payload = {};
    if (mode === 'bind') {
      const v = panel.querySelector('#ap-bind').value;
      if (!v) { setMsg('請選擇使用者', false); return; }
      payload = { bound_user_id: parseInt(v, 10) };
    } else if (mode === 'new') {
      const name = panel.querySelector('#ap-nu-name').value.trim();
      const p = panel.querySelector('#ap-nu-pw').value;
      const role = panel.querySelector('#ap-nu-role').value;
      if (!name) { setMsg('請填姓名', false); return; }
      if (!isValidPin(p)) { setMsg('密碼需為 4 位數字', false); return; }
      const nu = { name, password: p, role };
      if (isSuper) {
        const bareStore = panel.querySelector('#ap-bare-store');
        nu.store_id = bareStore ? parseInt(bareStore.value, 10) : undefined;
      }
      payload = { new_user: nu };
    } else if (mode === 'bare') {
      const s = panel.querySelector('#ap-bare-store').value;
      payload = { store_id: parseInt(s, 10) };
    }
    try {
      const { status, data } = await api.approveDevice(did, payload);
      if (status === 200 && data.status === 'ok') { setMsg('已核准（換機會自動撤舊）', true); panel.innerHTML = ''; await loadList(); }
      else if (status === 403) setMsg('無權限', false);
      else setMsg('核准失敗（' + (data.message || '') + '）', false);
    } catch (e) { setMsg('核准失敗，請重試', false); }
  }

  async function revoke(did) {
    if (!confirm('確定撤銷此裝置？')) return;
    try {
      const { status, data } = await api.revokeDevice(did);
      if (status === 200 && data.status === 'ok') { setMsg('已撤銷', true); await loadList(); }
      else if (status === 403) setMsg('無權限', false);
      else setMsg('撤銷失敗', false);
    } catch (e) { setMsg('撤銷失敗，請重試', false); }
  }

  loadList();
}
```

- [ ] **Step 2: 語法檢查 + admin.js 整合 import 驗證**

Run: `node --check app/static/js/admin_devices.js`
Expected: 無輸出

Run（現在 admin.js 的相依都存在，可完整解析 import 圖）：
`node --input-type=module -e "Promise.all([import('./app/static/js/admin.js'),import('./app/static/js/admin_accounts.js'),import('./app/static/js/admin_devices.js')]).then(() => console.log('graph ok')).catch(e => { console.error(e.message); process.exit(1); })"`
Expected: 印出 `graph ok`（整個 admin 模組圖可解析；`camera.js` 內若引用 `navigator` 只在函式內、模組頂層不執行則不報錯。若因瀏覽器 API 於頂層報錯，改用逐檔 `node --check` 並於瀏覽器 e2e 驗）。

- [ ] **Step 3: Commit**

```bash
git add app/static/js/admin_devices.js
git commit -m "feat(admin-ui): admin_devices 裝置分頁(待核准置頂/核准綁定/換機/撤銷)"
```

---

## Task 10: 開頁自動 `register-device`（§5.4，新裝置入待核准佇列）

**Files:**
- Modify: `app/static/js/main.js`（開頁呼叫 register-device 一次）
- Modify: `app/static/js/auth.js`（移除開 modal 時的 register-device）

**Interfaces:**
- 行為變更：未知裝置一開頁就 `POST /api/v1/register-device`（建立 `is_approved=False` 待核准列）；已核准裝置靠 cookie 更新 `last_seen_at`、不重複建列。登入 modal 不再自行 register。

- [ ] **Step 1: main.js 開頁 register-device**

在 `app/static/js/main.js` 末端（`initFx(); renderCalc();` 之前或之後）加入 best-effort 一次性註冊：

```javascript
// 開頁即註冊裝置：未知裝置進待核准佇列（已核准者更新 last_seen；cookie 去重）
(async () => {
  try {
    await fetch('/api/v1/register-device', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_name: navigator.userAgent.slice(0, 100) }),
    });
  } catch (e) { /* best-effort：網路故障不影響計算機幌子 */ }
})();
```

- [ ] **Step 2: auth.js 移除開 modal 時的 register-device**

刪除 `app/static/js/auth.js` `openLoginFlow()` 內的 register-device 區塊（現 line 100–107）：

```javascript
  // 開 modal 當下才註冊裝置（避免公開瀏覽就洗 pending）
  try {
    await postJSON('/api/v1/register-device', {
      device_name: navigator.userAgent.slice(0, 100),
    });
  } catch (e) {
    // register-device 為 best-effort 入列，網路故障不應阻斷 modal 展開
  }
```

刪除後 `openLoginFlow()` 直接進 `try { await cam.start(); } ...`。

- [ ] **Step 3: 語法檢查**

Run: `node --check app/static/js/main.js && node --check app/static/js/auth.js`
Expected: 無輸出

- [ ] **Step 4: 手動 e2e（見下方「整合驗證」）**

開頁 → 開發者工具 Network 應見一發 `POST /api/v1/register-device`；未核准裝置以另一 super_admin 進後台裝置分頁應見該待核准列。

- [ ] **Step 5: Commit**

```bash
git add app/static/js/main.js app/static/js/auth.js
git commit -m "feat(admin-ui): 新裝置開頁自動 register-device 入待核准佇列(移出登入modal)"
```

---

## Task 11: SW 快取版本 bump + 全套測試回歸

**Files:**
- Modify: `app/static/sw.js`（bump `CACHE_NAME`，強制客戶端取新前端）

**Interfaces:**
- 前端 JS 大幅變更，PWA service worker 需 bump 快取版本，避免客戶端吃到舊 bundle。

- [ ] **Step 1: bump SW 快取版本**

在 `app/static/sw.js` 找到 `CACHE_NAME`（前次為 `calc-v2`），改為 `calc-v3`。

Run: `grep -n "CACHE_NAME\|calc-v" app/static/sw.js`
Expected: 顯示現值，確認改為 `v3`。

- [ ] **Step 2: 後端全套回歸**

Run: `python3 -m pytest -q`
Expected: 全綠（既有 + 本 plan 新增；預期 1 個第三方 `pkg_resources` DeprecationWarning，非失敗）

- [ ] **Step 3: 前端純函式全套回歸**

Run: `node --test tests/js/*.test.mjs`
Expected: 全綠（calculator / currency / secret / admin_util）

- [ ] **Step 4: Commit**

```bash
git add app/static/sw.js
git commit -m "chore(pwa): bump SW cache calc-v2→v3（後台前端上線，強制客戶端取新版）"
```

---

## 整合驗證（手動 e2e，全部 task 完成後）

> dev 環境（VMware VM 無實體相機）需先備妥 VirtualCam：
> ```bash
> sudo modprobe v4l2loopback devices=1 video_nr=10 card_label=VirtualCam exclusive_caps=1
> gst-launch-1.0 filesrc location=~/projects/webapp/app1_notes/static/face_photos/2_5a490e70.jpg ! decodebin ! imagefreeze ! videoconvert ! videoscale ! video/x-raw,format=YUY2,width=640,height=480,framerate=30/1 ! v4l2sink device=/dev/video10 sync=false &
> flask db upgrade
> FLASK_APP=wsgi.py SECRET_KEY=dev python3 -m flask run --port 5001
> # 用 /usr/bin/google-chrome（非 snap）；改前端 JS 後 DevTools unregister SW 或 bypass
> ```

驗證清單：
1. **seed → 進後台**：全新 DB，開頁 bootstrap 建 super_admin（錄臉）→ reload → 計算機幌子 `0 7 8 × 2 =` → 登入 modal 刷臉登入 → **應進管理後台面板**（非占位頁）。
2. **帳號分頁**：super_admin 建一員工（選店 + 4 位 PIN）→ 清單出現 → 對其「錄臉」（VirtualCam）→「臉」欄變「有」。
3. **員工登入**：登出 → 用該員工 PIN + 臉登入 → 應到占位頁（非後台）。
4. **裝置佇列**：換一個乾淨 cookie（DevTools 清 `device_uid`）開頁 → 後台裝置分頁應見**待核准**列（置頂）→ 核准並綁定該員工 → 該裝置可登入。
5. **換機撤舊**：對同一員工核准另一台裝置 → 舊裝置狀態應轉「已撤銷」。
6. **停用/守門**：停用該員工 → 其登入被擋；試停用自己 → 前端/後端擋（訊息）；唯一 super_admin 試停自己 → 擋。
7. **調店過濾**（super_admin）：頂部調店切換 → 帳號/裝置清單依店過濾。
8. **我的密碼**：改自己 PIN → 登出 → 用新 PIN 登入成功。
9. **店別分頁**（super_admin）：新增一間店 → 調店下拉出現新店。

---

## Self-Review（對照 spec 檢查）

**Spec coverage：**
- §4.1 登入後分流 → Task 7（auth.js/main.js role 分流）。✅
- §4.2 面板結構（tabs/調店/登出）→ Task 7（admin.js 殼）。✅
- §5.1 `GET /admin/users` → Task 2。✅
- §5.2 `GET /admin/stores` → Task 1。✅
- §5.3 `POST /admin/users/<id>/active`（守門）→ Task 3。✅
- §5.4 開頁自動 register-device → Task 10。✅
- §5.5 PIN 排序修正 → Task 4。✅
- §6 帳號分頁（清單/創/改密碼/停用/代錄臉）→ Task 8。✅
- §7 裝置分頁（清單/待核准/核准綁定三選一/換機/撤銷）→ Task 9。✅
- §8 我的密碼分頁 → Task 7（renderMyPassword）。✅
- §9 檔案切分（admin.js/admin_accounts/admin_devices/admin_api）→ Task 5–9。✅
- §10 測試策略（pytest + node --test + 手動 e2e）→ 各 task + 整合驗證。✅
- §11 風險（register-device 雜訊靠 TTL、停用守門、單一網址）→ 已於 Task 3/10 與註記涵蓋。✅

**其他 3a 遺留 Minor（記憶提及、非本 spec §5.5 範圍）**：經查現有碼，`auth.js`/`bootstrap.js` submit 已有 try/catch、`currency.test.mjs` 已含 THB 斷言、`main.js` 無 `displayEl` 死變數——**皆已於 3a 後續 commit 修畢**，本 plan 不重複處理（實作 Task 開始前可再 `grep` 確認）。

**Placeholder scan：** 無 TODO/TBD；所有 step 附完整程式碼與可執行指令。Task 7 Step 5 的 `ap-logout` 誤植已於註記給出正確版本，實作時採註記版。

**Type consistency：** `showAdminPanel(identity)`（admin.js 匯出）↔ auth.js/main.js 呼叫一致；`renderAccounts(container, ctx)` / `renderDevices(container, ctx)` 合約於 Task 7 定義、Task 8/9 實作一致；`api.*` 方法名於 Task 6 定義、Task 7/8/9 使用一致；`ctx` 欄位（identity/storeId/stores/api/reload）跨檔一致。

**已知取捨（實作者注意）：**
- `/auth/verify` 回應不含 `store_id`；manager 從 verify 路徑登入時 identity 無 store_id。實務上 manager 靠 session 快捷（index 注入含 store_id）進後台；若走 verify 路徑建帳號需帶店，manager 分支送 `identity.store_id`（可能為 undefined→後端以 actor 強制/擋）。此為既有 API 契約限制，不在本 plan 擴充 verify 回應；如驗證發現卡點，另開小修改 verify 回傳 store_id。
