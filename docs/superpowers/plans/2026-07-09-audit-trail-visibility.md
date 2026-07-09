# 稽核軌跡可視化 + 操作記錄查詢頁 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓「誰建立、誰最後修改+時間、完整改動軌跡」在單子上看得到，並提供主管/經理一個獨立頁籤依日期+員工查全店操作記錄。

**Architecture:** 資料層在 `expenses` 加兩冗餘欄 `last_modified_by`/`last_modified_at`，在既有 `log_edit_if_changed` 有寫 edit 時同步蓋值（員工/主管兩處 PATCH 自然涵蓋）。序列化補建立者/最後修改者姓名（批次 name map 避免 N+1）。新增兩端點：`GET /expenses/<id>/logs`（每單軌跡，本人/同店主管可看）與 `GET /audit/logs`（集中操作記錄，manager/super_admin scope）。前端把建立者/最後修改/軌跡展開接進確認區與稽核頁，並新增「操作記錄」後台頁籤。動作中文對映（edit→修改/check→簽核）一律在前端純函式做（DRY），端點回原始 action。

**Tech Stack:** Flask + SQLAlchemy 2.0 + Flask-Migrate(alembic) + pytest；前端 ESM（`app/static/js/`）+ `node --test`。

## Global Constraints

- 時間 UI 一律台灣時間（Asia/Taipei）顯示，DB 存 UTC；後端時間欄一律用 `iso_utc()` 補 UTC 標記；前端格式化用 `formatDateTimeTW`（`audit_util.js`，可 node 測）。
- per-store scope 沿用 `app/audit/routes.py` 的 `_scope_store_id()`：manager→本店；super_admin→需帶 `store_id`（GET 讀 query）；缺→400、跨店→403。
- 前端不輪詢：軌跡展開、操作記錄查詢皆按需（點擊/選日期）呼叫。
- 不新增 Python 依賴（純 stdlib）。
- 回傳慣例 `jsonify(status="ok", ...)`；沿用既有 `serialize_expense` / `serialize_audit_item`。
- migration 兩新欄 nullable（FK + timestamp），**無 Boolean server_default**。
- 每次改前端 JS/CSS 必 bump `app/static/sw.js` 的 `CACHE_NAME`（現 `calc-v30`）——本計畫在最後一個前端 task（Task 8）統一 bump 到 `calc-v31`。
- alembic 現 head=`c1a2b3d4e5f6`（新 migration 的 `down_revision` 必須是它）。
- 測試 fixture pattern：`db.create_all()` in `app.app_context()`；直接建 model；`_client(app, uid)` 設 `device_uid` cookie + session（見既有 `tests/test_audit_edit.py`）。

---

### Task 1: `expenses` 加冗餘欄 + migration + log helper 同步蓋值

**Files:**
- Modify: `app/models/expense.py`（加兩欄）
- Create: `migrations/versions/e7d9f1b3a5c2_expenses_last_modified.py`
- Modify: `app/audit/log.py`（`log_edit_if_changed` 蓋 last_modified）
- Test: `tests/test_last_modified_stamp.py`

**Interfaces:**
- Produces: `Expense.last_modified_by`(int|None, FK users.id)、`Expense.last_modified_at`(datetime tz|None)；`log_edit_if_changed(expense, actor_user_id, before)` 在回 `True` 時，會把 `expense.last_modified_by=actor_user_id`、`expense.last_modified_at=<與該筆 AuditLog.ts 同一時戳>`。回 `False`（無變動）時完全不動。`record_check` 不動 last_modified。

- [ ] **Step 1: 寫失敗測試**

`tests/test_last_modified_stamp.py`：
```python
from datetime import datetime, timezone
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Expense, AuditLog
from app.audit.log import snapshot, log_edit_if_changed, record_check


def _mk(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="u", role="employee", store_id=s.id); u.set_password("1234")
        db.session.add(u); db.session.commit()
        e = Expense(store_id=s.id, created_by=u.id, status="draft",
                    created_at=datetime.now(timezone.utc), amount=Decimal("100"))
        db.session.add(e); db.session.commit()
        return u.id, e.id


def test_stamp_on_change(app):
    uid, eid = _mk(app)
    with app.app_context():
        e = db.session.get(Expense, eid)
        before = snapshot(e)
        e.amount = Decimal("250")
        assert log_edit_if_changed(e, uid, before) is True
        db.session.commit()
        e = db.session.get(Expense, eid)
        assert e.last_modified_by == uid
        assert e.last_modified_at is not None
        row = AuditLog.query.filter_by(action="edit").one()
        assert e.last_modified_at == row.ts   # 同一時戳


def test_no_stamp_when_unchanged(app):
    uid, eid = _mk(app)
    with app.app_context():
        e = db.session.get(Expense, eid)
        before = snapshot(e)
        assert log_edit_if_changed(e, uid, before) is False
        db.session.commit()
        e = db.session.get(Expense, eid)
        assert e.last_modified_by is None and e.last_modified_at is None


def test_check_does_not_stamp(app):
    uid, eid = _mk(app)
    with app.app_context():
        e = db.session.get(Expense, eid)
        record_check(e, uid); db.session.commit()
        e = db.session.get(Expense, eid)
        assert e.last_modified_by is None and e.last_modified_at is None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_last_modified_stamp.py -q`
Expected: FAIL（`Expense` 無 `last_modified_by` 屬性 / AttributeError）

- [ ] **Step 3: model 加兩欄**

`app/models/expense.py`，在 `handover_id` 那行（約 line 43）之後加：
```python
    last_modified_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    last_modified_at = db.Column(db.DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: 建 migration**

`migrations/versions/e7d9f1b3a5c2_expenses_last_modified.py`：
```python
"""expenses: last_modified_by / last_modified_at

Revision ID: e7d9f1b3a5c2
Revises: c1a2b3d4e5f6
Create Date: 2026-07-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e7d9f1b3a5c2'
down_revision = 'c1a2b3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_modified_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('last_modified_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.drop_column('last_modified_at')
        batch_op.drop_column('last_modified_by')
```

- [ ] **Step 5: log helper 蓋值**

`app/audit/log.py` 把 `log_edit_if_changed` 改成（用單一 ts 同時給 AuditLog 與 expense）：
```python
def log_edit_if_changed(expense, actor_user_id, before):
    """before 為改動前 snapshot；與現值不同才寫一筆 edit。回是否有寫。"""
    after = _amt_cat(expense)
    if after == before:
        return False
    ts = datetime.now(timezone.utc)
    db.session.add(AuditLog(
        expense_id=expense.id, actor_user_id=actor_user_id, action="edit",
        before_json=before, after_json=after, ts=ts,
    ))
    expense.last_modified_by = actor_user_id
    expense.last_modified_at = ts
    return True
```

- [ ] **Step 6: 跑測試確認通過**

Run: `python3 -m pytest tests/test_last_modified_stamp.py tests/test_audit_log_helper.py -q`
Expected: PASS（新 3 測 + 既有 helper 測都綠）

- [ ] **Step 7: 全套回歸**

Run: `python3 -m pytest -q`
Expected: PASS（不得因加欄破壞既有測）

- [ ] **Step 8: Commit**

```bash
git add app/models/expense.py migrations/versions/e7d9f1b3a5c2_expenses_last_modified.py app/audit/log.py tests/test_last_modified_stamp.py
git commit -m "feat(audit): expenses.last_modified_by/at 冗餘欄 + log helper 同步蓋值 + migration"
```

---

### Task 2: `serialize_expense` 補建立者/最後修改者 + 呼叫端 name map

**Files:**
- Modify: `app/expenses/serialize.py`（加 `name_by_id` 參數 + 三欄）
- Modify: `app/audit/serialize.py`（傳 `name_by_id` 給 `serialize_expense`）
- Modify: `app/audit/routes.py`（`_audit_maps` 併入 created_by/last_modified_by）
- Modify: `app/expenses/routes.py`（pending / detail 建 name map 傳入）
- Test: `tests/test_serialize_names.py`

**Interfaces:**
- Consumes: Task 1 的 `Expense.last_modified_by`/`last_modified_at`。
- Produces: `serialize_expense(e, storage, with_main=False, name_by_id=None)` 多回 `created_by_name`、`last_modified_by_name`、`last_modified_at`(iso)。`name_by_id` 為 `{user_id: name}` dict（None→三欄皆 None/iso）。`serialize_audit_item` 內部把收到的 `actor_name_by_id` 當 `name_by_id` 傳下去；`_audit_maps` 回的 names dict 現含 audited_by + created_by + last_modified_by 三種 id。

- [ ] **Step 1: 寫失敗測試**

`tests/test_serialize_names.py`：
```python
from datetime import datetime, timezone
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Expense
from app.expenses.serialize import serialize_expense
from app.storage.r2 import get_storage


def _mk(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="小明", role="employee", store_id=s.id); u.set_password("1234")
        m = User(name="主管", role="manager", store_id=s.id); m.set_password("1234")
        db.session.add_all([u, m]); db.session.commit()
        e = Expense(store_id=s.id, created_by=u.id, status="draft",
                    created_at=datetime.now(timezone.utc), amount=Decimal("100"),
                    last_modified_by=m.id, last_modified_at=datetime.now(timezone.utc))
        db.session.add(e); db.session.commit()
        return u.id, m.id, e.id


def test_serialize_with_name_map(app):
    uid, mid, eid = _mk(app)
    with app.app_context():
        e = db.session.get(Expense, eid)
        names = {uid: "小明", mid: "主管"}
        d = serialize_expense(e, get_storage(), name_by_id=names)
        assert d["created_by_name"] == "小明"
        assert d["last_modified_by_name"] == "主管"
        assert d["last_modified_at"] is not None


def test_serialize_without_name_map_is_none(app):
    uid, mid, eid = _mk(app)
    with app.app_context():
        e = db.session.get(Expense, eid)
        d = serialize_expense(e, get_storage())
        assert d["created_by_name"] is None
        assert d["last_modified_by_name"] is None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_serialize_names.py -q`
Expected: FAIL（`serialize_expense` 無 `name_by_id` 參數 / KeyError `created_by_name`）

- [ ] **Step 3: 改 `serialize_expense`**

`app/expenses/serialize.py` 改簽名與 dict：
```python
def serialize_expense(e, storage, with_main=False, name_by_id=None):
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
        "created_at": iso_utc(e.created_at),
        "created_by_name": name_by_id.get(e.created_by) if name_by_id else None,
        "last_modified_by_name": name_by_id.get(e.last_modified_by) if name_by_id else None,
        "last_modified_at": iso_utc(e.last_modified_at),
        "thumb_url": storage.presigned_url(e.thumb_key) if e.thumb_key else None,
        "ocr_failed": e.ocr_failed,
        "ocr_last_error": e.ocr_last_error,
    }
    if with_main:
        d["image_url"] = storage.presigned_url(e.image_key) if e.image_key else None
    return d
```

- [ ] **Step 4: `serialize_audit_item` 傳 name_by_id**

`app/audit/serialize.py` 第一行序列化改成：
```python
    d = serialize_expense(e, storage, with_main=True, name_by_id=actor_name_by_id)
```
（其餘不動；`actor_name_by_id` 現會含 created_by/last_modified_by 姓名，見 Step 5。）

- [ ] **Step 5: `_audit_maps` 併入 created_by / last_modified_by**

`app/audit/routes.py` 的 `_audit_maps`：
```python
def _audit_maps(expenses):
    uids = {e.audited_by for e in expenses if e.audited_by}
    uids |= {e.created_by for e in expenses}
    uids |= {e.last_modified_by for e in expenses if e.last_modified_by}
    cids = {e.category_id for e in expenses if e.category_id}
    names = {u.id: u.name for u in User.query.filter(User.id.in_(uids)).all()} if uids else {}
    cats = {c.id: c.name for c in Category.query.filter(Category.id.in_(cids)).all()} if cids else {}
    return names, cats
```

- [ ] **Step 6: 員工 pending / detail 建 name map**

`app/expenses/routes.py` 頂部 import 加 `User`：
```python
from app.models import Expense, Category, User
```
`pending()` 序列化前建 map（在 `rows = ...` 之後、`storage = ...` 之後）：
```python
    storage = get_storage()
    uids = {e.created_by for e in rows} | {e.last_modified_by for e in rows if e.last_modified_by}
    names = {u.id: u.name for u in User.query.filter(User.id.in_(uids)).all()} if uids else {}
    return jsonify(status="ok",
                    expenses=[serialize_expense(e, storage, with_main=True, name_by_id=names) for e in rows])
```
`detail()` 同樣傳 map：
```python
    e, err = _load_owned(eid, user)
    if err:
        return err
    uids = {e.created_by} | ({e.last_modified_by} if e.last_modified_by else set())
    names = {u.id: u.name for u in User.query.filter(User.id.in_(uids)).all()} if uids else {}
    return jsonify(status="ok",
                   expense=serialize_expense(e, get_storage(), with_main=True, name_by_id=names))
```
（`edit()` 回傳的 `serialize_expense(e, get_storage())` 不需 name_by_id，維持原樣——前端 edit 後不靠回傳顯示姓名。）

- [ ] **Step 7: 跑測試 + 既有 audit 序列化回歸**

Run: `python3 -m pytest tests/test_serialize_names.py tests/test_audit_pending.py tests/test_audit_items.py tests/test_expense_pending.py -q`
Expected: PASS

- [ ] **Step 8: 全套回歸**

Run: `python3 -m pytest -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add app/expenses/serialize.py app/audit/serialize.py app/audit/routes.py app/expenses/routes.py tests/test_serialize_names.py
git commit -m "feat(audit): serialize 補 created_by_name/last_modified_by_name/last_modified_at + 呼叫端 name map"
```

---

### Task 3: `GET /expenses/<id>/logs`（每單軌跡端點）

**Files:**
- Modify: `app/expenses/routes.py`（新端點 + import AuditLog）
- Test: `tests/test_expense_logs.py`

**Interfaces:**
- Consumes: `AuditLog`(expense_id, actor_user_id, action, ts)、`iso_utc`。
- Produces: `GET /expenses/<int:eid>/logs` → `{status:"ok", logs:[{actor_name, ts, action}]}`。`action` 為**原始值** `"edit"|"check"`（中文對映在前端）。依 `ts` 升冪。權限：未登入 401；找不到 404；放行條件＝`e.created_by==user.id`（本人）或 `user.role=="super_admin"`（全域）或（`user.role=="manager"` 且 `e.store_id==user.store_id`）；否則 403。

- [ ] **Step 1: 寫失敗測試**

`tests/test_expense_logs.py`：
```python
import time
from datetime import datetime, timezone
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense, AuditLog


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        emp = User(name="emp", role="employee", store_id=s.id); emp.set_password("1234")
        other_emp = User(name="emp2", role="employee", store_id=s.id); other_emp.set_password("1234")
        mgr = User(name="mgr", role="manager", store_id=s.id); mgr.set_password("1234")
        sup = User(name="sup", role="super_admin", store_id=s.id); sup.set_password("1234")
        db.session.add_all([emp, other_emp, mgr, sup]); db.session.commit()
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add(dev); db.session.commit()
        now = datetime.now(timezone.utc)
        e = Expense(store_id=s.id, created_by=emp.id, status="draft",
                    created_at=now, amount=Decimal("100"))
        db.session.add(e); db.session.commit()
        db.session.add_all([
            AuditLog(expense_id=e.id, actor_user_id=emp.id, action="edit",
                     before_json={"amount": 100.0, "category_id": None},
                     after_json={"amount": 120.0, "category_id": None}, ts=now),
            AuditLog(expense_id=e.id, actor_user_id=mgr.id, action="check",
                     before_json=None, after_json={"status": "audited"}, ts=now),
        ])
        db.session.commit()
        return {"store": s.id, "emp": emp.id, "other": other_emp.id,
                "mgr": mgr.id, "sup": sup.id, "eid": e.id}


def _client(app, uid, uid_cookie="dev1"):
    c = app.test_client(); c.set_cookie("device_uid", uid_cookie)
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_owner_sees_logs(app):
    ids = _seed(app)
    c = _client(app, ids["emp"])
    r = c.get(f"/expenses/{ids['eid']}/logs")
    assert r.status_code == 200
    logs = r.get_json()["logs"]
    assert [l["action"] for l in logs] == ["edit", "check"]     # ts 升冪
    assert logs[0]["actor_name"] == "emp" and logs[1]["actor_name"] == "mgr"


def test_same_store_manager_sees_logs(app):
    ids = _seed(app)
    assert _client(app, ids["mgr"]).get(f"/expenses/{ids['eid']}/logs").status_code == 200


def test_super_admin_sees_logs(app):
    ids = _seed(app)
    assert _client(app, ids["sup"]).get(f"/expenses/{ids['eid']}/logs").status_code == 200


def test_other_employee_forbidden(app):
    ids = _seed(app)
    assert _client(app, ids["other"]).get(f"/expenses/{ids['eid']}/logs").status_code == 403


def test_cross_store_manager_forbidden(app):
    ids = _seed(app)
    with app.app_context():
        s2 = Store(name="B", code="B"); db.session.add(s2); db.session.commit()
        m2 = User(name="m2", role="manager", store_id=s2.id); m2.set_password("1234")
        db.session.add(m2); db.session.commit()
        d2 = Device(client_uid="dev2", store_id=s2.id, is_approved=True)
        db.session.add(d2); db.session.commit()
        m2_id = m2.id
    c = _client(app, m2_id, uid_cookie="dev2")
    assert c.get(f"/expenses/{ids['eid']}/logs").status_code == 403


def test_missing_404(app):
    ids = _seed(app)
    assert _client(app, ids["emp"]).get("/expenses/999999/logs").status_code == 404
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_expense_logs.py -q`
Expected: FAIL（404/route 不存在）

- [ ] **Step 3: 端點實作**

`app/expenses/routes.py` import 補 `AuditLog`：
```python
from app.models import Expense, Category, User, AuditLog
```
新端點（放在 `detail()` 之後）：
```python
@expense_bp.get("/<int:eid>/logs")
def logs(eid):
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    e = db.session.get(Expense, eid)
    if e is None:
        return jsonify(status="error", message="not found"), 404
    allowed = (e.created_by == user.id
               or user.role == "super_admin"
               or (user.role == "manager" and e.store_id == user.store_id))
    if not allowed:
        return jsonify(status="error", message="forbidden"), 403
    rows = (AuditLog.query.filter_by(expense_id=eid)
            .order_by(AuditLog.ts.asc(), AuditLog.id.asc()).all())
    uids = {r.actor_user_id for r in rows}
    names = {u.id: u.name for u in User.query.filter(User.id.in_(uids)).all()} if uids else {}
    from app.expenses.logic import iso_utc
    return jsonify(status="ok", logs=[
        {"actor_name": names.get(r.actor_user_id), "ts": iso_utc(r.ts), "action": r.action}
        for r in rows
    ])
```
（`iso_utc` 已在檔頂 import：`from app.expenses.logic import compute_business_date`——改成 `from app.expenses.logic import compute_business_date, iso_utc` 並移除函式內的區域 import。）

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_expense_logs.py -q`
Expected: PASS（6 測全綠）

- [ ] **Step 5: 全套回歸**

Run: `python3 -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/expenses/routes.py tests/test_expense_logs.py
git commit -m "feat(audit): GET /expenses/<id>/logs 每單軌跡端點(本人/同店主管/super_admin)"
```

---

### Task 4: `GET /audit/logs`（集中操作記錄端點）

**Files:**
- Modify: `app/audit/routes.py`（新端點 + import AuditLog/timedelta + TW 常數）
- Test: `tests/test_audit_logs.py`

**Interfaces:**
- Consumes: `_scope_store_id()`、`AuditLog`、`Expense`、`User`、`iso_utc`。
- Produces: `GET /audit/logs?date=YYYY-MM-DD&actor_id=<opt>` → `{status:"ok", items:[{expense_id, summary, actor_name, ts, action}], actors:[{id,name}]}`。`date` 為台灣日曆日（00:00–24:00 TW 轉 UTC 範圍篩 `AuditLog.ts`）；join `Expense` 篩 scope store；`actor_id` 選填再篩 actor；`items` 依 ts 降冪。`actors`＝該 scope 店的在職 users。缺 date→400；super_admin 缺 store_id→400；跨店因 store 篩自然為空。

- [ ] **Step 1: 寫失敗測試**

`tests/test_audit_logs.py`：
```python
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense, AuditLog

_TW = timezone(timedelta(hours=8))


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        emp = User(name="emp", role="employee", store_id=s.id); emp.set_password("1234")
        mgr = User(name="mgr", role="manager", store_id=s.id); mgr.set_password("1234")
        db.session.add_all([emp, mgr]); db.session.commit()
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add(dev); db.session.commit()
        e = Expense(store_id=s.id, created_by=emp.id, status="draft",
                    created_at=datetime.now(timezone.utc), amount=Decimal("100"), summary="午餐")
        db.session.add(e); db.session.commit()
        # 台灣 2026-07-09 之內的兩筆（一 emp edit、一 mgr check）
        t1 = datetime(2026, 7, 9, 10, 0, tzinfo=_TW).astimezone(timezone.utc)  # 09 TW
        t2 = datetime(2026, 7, 9, 23, 30, tzinfo=_TW).astimezone(timezone.utc) # 09 TW（UTC 已跨到 07-09 15:30）
        # 台灣 2026-07-10 的一筆（不應出現在 07-09 查詢）
        t3 = datetime(2026, 7, 10, 0, 30, tzinfo=_TW).astimezone(timezone.utc)
        db.session.add_all([
            AuditLog(expense_id=e.id, actor_user_id=emp.id, action="edit",
                     before_json={}, after_json={}, ts=t1),
            AuditLog(expense_id=e.id, actor_user_id=mgr.id, action="check",
                     before_json=None, after_json={}, ts=t2),
            AuditLog(expense_id=e.id, actor_user_id=emp.id, action="edit",
                     before_json={}, after_json={}, ts=t3),
        ])
        db.session.commit()
        return {"store": s.id, "emp": emp.id, "mgr": mgr.id}


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_manager_logs_by_date(app):
    ids = _seed(app)
    c = _client(app, ids["mgr"])
    r = c.get("/audit/logs?date=2026-07-09")
    assert r.status_code == 200
    body = r.get_json()
    # 07-09 兩筆、依 ts 降冪（check 在前）
    assert [i["action"] for i in body["items"]] == ["check", "edit"]
    assert body["items"][0]["summary"] == "午餐"
    assert {a["name"] for a in body["actors"]} == {"emp", "mgr"}


def test_date_excludes_other_day(app):
    ids = _seed(app)
    r = _client(app, ids["mgr"]).get("/audit/logs?date=2026-07-10")
    assert [i["action"] for i in r.get_json()["items"]] == ["edit"]   # 只剩 t3 那筆


def test_actor_filter(app):
    ids = _seed(app)
    r = _client(app, ids["mgr"]).get(f"/audit/logs?date=2026-07-09&actor_id={ids['emp']}")
    items = r.get_json()["items"]
    assert len(items) == 1 and items[0]["action"] == "edit"


def test_bad_date_400(app):
    ids = _seed(app)
    assert _client(app, ids["mgr"]).get("/audit/logs?date=nope").status_code == 400


def test_super_admin_needs_store_id(app):
    ids = _seed(app)
    with app.app_context():
        sup = User(name="sup", role="super_admin", store_id=ids["store"]); sup.set_password("1234")
        db.session.add(sup); db.session.commit(); sup_id = sup.id
    c = _client(app, sup_id)
    assert c.get("/audit/logs?date=2026-07-09").status_code == 400
    assert c.get(f"/audit/logs?date=2026-07-09&store_id={ids['store']}").status_code == 200


def test_cross_store_isolation(app):
    ids = _seed(app)
    with app.app_context():
        s2 = Store(name="B", code="B"); db.session.add(s2); db.session.commit()
        m2 = User(name="m2", role="manager", store_id=s2.id); m2.set_password("1234")
        db.session.add(m2); db.session.commit(); m2_id = m2.id
    # m2 是 B 店 manager；查不到 A 店的 log
    c = app.test_client()
    d2 = None
    with app.app_context():
        d2 = Device(client_uid="dev2", store_id=s2_id if (s2_id := m2_and_store(app)) else None)  # noqa
    # 簡化：直接用 A 店裝置查不到 B——改測 m2 查自己店為空
    cc = _client(app, m2_id)
    # m2 的 device_uid=dev1 屬 A 店，會 mismatch；改建 B 店裝置
```
> 註：`test_cross_store_isolation` 上面示意過度；實作時請比照 `tests/test_audit_edit.py::test_manager_edit_cross_store_forbidden` 的乾淨寫法——為 B 店建 `Device(client_uid="dev2", store_id=s2.id, is_approved=True)`，用 `c.set_cookie("device_uid","dev2")` 登入 m2，`GET /audit/logs?date=2026-07-09` 應 200 但 `items == []`（A 店的 log 不外洩）。**Task 實作者請直接寫成這個乾淨版本，不要照抄示意碼。**

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_audit_logs.py -q`
Expected: FAIL（route 不存在 / 404）

- [ ] **Step 3: 端點實作**

`app/audit/routes.py`：import 補 `AuditLog`、`timedelta`：
```python
from datetime import datetime, timezone, timedelta
from app.models import Expense, Store, Handover, User, Category, AuditLog
```
檔案上方（`_scope_store_id` 之前）加 TW 常數：
```python
_TW = timezone(timedelta(hours=8))
```
新端點（放在 `days()` 之後）：
```python
@audit_bp.get("/logs")
@role_required("manager", "super_admin")
def audit_logs():
    from datetime import date as _date
    store_id, err = _scope_store_id()
    if err:
        return err
    try:
        d = _date.fromisoformat(request.args.get("date", ""))
    except (TypeError, ValueError):
        return jsonify(status="error", message="bad date"), 400
    start = datetime(d.year, d.month, d.day, tzinfo=_TW).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    q = (db.session.query(AuditLog, Expense)
         .join(Expense, AuditLog.expense_id == Expense.id)
         .filter(Expense.store_id == store_id,
                 AuditLog.ts >= start, AuditLog.ts < end))
    actor_id = request.args.get("actor_id", type=int)
    if actor_id is not None:
        q = q.filter(AuditLog.actor_user_id == actor_id)
    rows = q.order_by(AuditLog.ts.desc(), AuditLog.id.desc()).all()
    uids = {lg.actor_user_id for lg, _ in rows}
    names = {u.id: u.name for u in User.query.filter(User.id.in_(uids)).all()} if uids else {}
    items = [{"expense_id": lg.expense_id, "summary": exp.summary,
              "actor_name": names.get(lg.actor_user_id),
              "ts": iso_utc(lg.ts), "action": lg.action}
             for lg, exp in rows]
    actors = [{"id": u.id, "name": u.name}
              for u in User.query.filter_by(store_id=store_id, active=True)
              .order_by(User.name).all()]
    return jsonify(status="ok", items=items, actors=actors)
```
> 註：`iso_utc` 已在檔頂 import（`from app.expenses.logic import iso_utc`）。若無，補上。

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_audit_logs.py -q`
Expected: PASS

- [ ] **Step 5: 全套回歸**

Run: `python3 -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/audit/routes.py tests/test_audit_logs.py
git commit -m "feat(audit): GET /audit/logs 集中操作記錄(依台灣日+員工篩, scope 本店)"
```

---

### Task 5: 前端純函式 `action_label` + `renderTrailRows`（node 測）

**Files:**
- Modify: `app/static/js/audit_util.js`（加兩純函式）
- Test: `tests/js/audit_trail.mjs`

**Interfaces:**
- Consumes: `formatDateTimeTW`(同檔)、`escapeHtml`(from `admin_util.js`，純函式)。
- Produces: `action_label(action)`→`'修改'|'簽核'|原字串`；`renderTrailRows(logs)`→HTML 字串（空陣列回 `'<div class="au-trail-empty">無修改記錄</div>'`；每筆 `actor_name・時間・動作`，順序保留）。

- [ ] **Step 1: 寫失敗測試**

`tests/js/audit_trail.mjs`：
```javascript
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { action_label, renderTrailRows } from '../../app/static/js/audit_util.js';

test('action_label 對映', () => {
  assert.equal(action_label('edit'), '修改');
  assert.equal(action_label('check'), '簽核');
  assert.equal(action_label('weird'), 'weird');
  assert.equal(action_label(''), '');
});

test('renderTrailRows 空陣列', () => {
  assert.match(renderTrailRows([]), /無修改記錄/);
  assert.match(renderTrailRows(null), /無修改記錄/);
});

test('renderTrailRows 多筆保留順序 + 含動作中文', () => {
  const html = renderTrailRows([
    { actor_name: '小明', ts: '2026-07-09T02:00:00+00:00', action: 'edit' },
    { actor_name: '主管', ts: '2026-07-09T03:00:00+00:00', action: 'check' },
  ]);
  assert.ok(html.indexOf('小明') < html.indexOf('主管'));  // 順序保留
  assert.match(html, /修改/);
  assert.match(html, /簽核/);
});
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `node --test tests/js/audit_trail.mjs`
Expected: FAIL（`action_label` / `renderTrailRows` 未匯出）

- [ ] **Step 3: 實作純函式**

`app/static/js/audit_util.js` 頂部加 import，檔尾加兩函式：
```javascript
import { escapeHtml } from './admin_util.js';
```
```javascript
export function action_label(action) {
  if (action === 'edit') return '修改';
  if (action === 'check') return '簽核';
  return action || '';
}

export function renderTrailRows(logs) {
  if (!logs || !logs.length) return '<div class="au-trail-empty">無修改記錄</div>';
  return logs.map((l) =>
    `<div class="au-trail-row">${escapeHtml(l.actor_name || '—')}・${formatDateTimeTW(l.ts)}・${action_label(l.action)}</div>`
  ).join('');
}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `node --test tests/js/audit_trail.mjs`
Expected: PASS

- [ ] **Step 5: JS 全套回歸**

Run: `node --test tests/js/*.mjs`
Expected: PASS（不破壞既有 JS 測）

- [ ] **Step 6: Commit**

```bash
git add app/static/js/audit_util.js tests/js/audit_trail.mjs
git commit -m "feat(audit-ui): action_label + renderTrailRows 純函式(共用軌跡渲染)"
```

---

### Task 6: 員工確認區顯示建立者/最後修改/軌跡展開（`pending.js`）

**Files:**
- Modify: `app/static/js/expenses_api.js`（加 `getExpenseLogs`）
- Modify: `app/static/js/pending.js`（建立者欄 + 最後修改 + 軌跡展開）
- Test: 手動 e2e（純 DOM 膠合；渲染邏輯已由 Task 5 測）

**Interfaces:**
- Consumes: Task 3 `/expenses/<id>/logs`；Task 5 `renderTrailRows`、`formatDateTimeTW`；serialize 的 `created_by_name`/`last_modified_by_name`/`last_modified_at`。
- Produces: `getExpenseLogs(id)`→`{status,data}`。

- [ ] **Step 1: api 方法**

`app/static/js/expenses_api.js` 檔尾加：
```javascript
export const getExpenseLogs = (id) => jsonFetch(`/expenses/${id}/logs`);
```

- [ ] **Step 2: import 調整**

`app/static/js/pending.js` 上方：
```javascript
import { formatDateTimeTW, renderTrailRows } from './audit_util.js';
```
```javascript
import {
  listPending, patchExpense, submitExpense, discardExpense, listCategories, noReceipt, reocrExpense, getExpenseLogs,
} from './expenses_api.js';
```

- [ ] **Step 3: 表頭加「建立者」**

`pending.js` 表頭改（加一欄）：
```javascript
        <table id="pd-table"><thead><tr>
          <th>圖</th><th>建立</th><th>建立者</th><th>摘要</th><th>分類</th><th>金額</th><th>燈</th><th></th>
        </tr></thead><tbody></tbody></table>
```

- [ ] **Step 4: 列渲染加建立者 + 最後修改 + 軌跡鈕**

`pending.js` 的 `tr.innerHTML` 改為（在 `建立` 後插 `建立者` cell、動作 cell 內加最後修改行 + 軌跡鈕 + 容器）：
```javascript
    tr.innerHTML = `
      <td>${thumb}</td>
      <td class="au-time">${formatDateTimeTW(e.created_at)}</td>
      <td>${escapeHtml(e.created_by_name || '')}</td>
      <td>${e.status === 'pending_ocr'
        ? '<span class="pd-ocring">🕓 辨識中…（稍後按重整）</span>'
        : `<input value="${escapeHtml(e.summary || '')}" data-f="summary">`}</td>
      <td><select data-f="category"></select></td>
      <td><input value="${e.amount ?? ''}" inputmode="decimal" data-f="amount" style="width:80px"></td>
      <td>${lightLabel(e.light)}</td>
      <td>
        ${e.status === 'pending_ocr' ? '' : '<button data-act="submit">送出</button>'}<button data-act="del">丟棄</button>
        ${e.ocr_failed ? '<button data-act="reocr">重新辨識</button>' : ''}
        <button data-act="trail" type="button">軌跡</button>
        ${e.last_modified_at
          ? `<div class="pd-lastmod">最後修改：${escapeHtml(e.last_modified_by_name || '')}（${formatDateTimeTW(e.last_modified_at)}）</div>`
          : ''}
        <div class="pd-trail" data-f="trail" hidden></div>
        <div class="pd-row-err" data-f="err"></div>
        ${e.ocr_failed ? '<div class="pd-ocr-failed">⚠ OCR 失敗，請手動確認金額/分類</div>' : ''}
      </td>`;
```

- [ ] **Step 5: 軌跡鈕事件（放在既有 `del` handler 附近）**

`pending.js` 每列事件綁定區加：
```javascript
    const trailBox = tr.querySelector('[data-f="trail"]');
    tr.querySelector('[data-act="trail"]').addEventListener('click', async () => {
      if (!trailBox.hidden) { trailBox.hidden = true; return; }
      trailBox.hidden = false;
      trailBox.innerHTML = '載入中…';
      try {
        const { data } = await getExpenseLogs(e.id);
        trailBox.innerHTML = renderTrailRows(data.logs);
      } catch {
        trailBox.innerHTML = '<div class="au-trail-empty">軌跡載入失敗</div>';
      }
    });
```

- [ ] **Step 6: 手動 e2e（見 Task 8 統一啟動後一起測）**

本 task 不獨立起 server（sw 尚未 bump）。程式碼審查 + Task 8 後一起 e2e。確認：確認區列有「建立者」欄、改過的單顯示「最後修改」、點「軌跡」展開看到 `誰・時間・動作`。

- [ ] **Step 7: Commit**

```bash
git add app/static/js/expenses_api.js app/static/js/pending.js
git commit -m "feat(audit-ui): 員工確認區顯示建立者/最後修改/軌跡展開"
```

---

### Task 7: 主管稽核頁顯示建立者/最後修改/軌跡展開（`admin_audit.js`）

**Files:**
- Modify: `app/static/js/admin_api.js`（加 `expenseLogs`）
- Modify: `app/static/js/admin_audit.js`（總表/待稽核列加建立者 + 最後修改 + 軌跡展開）
- Test: 手動 e2e

**Interfaces:**
- Consumes: Task 3 `/expenses/<id>/logs`；Task 5 `renderTrailRows`；serialize_audit_item 的 `created_by_name`/`last_modified_by_name`/`last_modified_at`（Task 2 已補）。
- Produces: `api.expenseLogs(id)`→`{status,data}`。

- [ ] **Step 1: api 方法**

`app/static/js/admin_api.js` 的 `api` 物件加一行（放 `auditByDate` 附近）：
```javascript
  expenseLogs: (id) => req('GET', `/expenses/${id}/logs`),
```

- [ ] **Step 2: import renderTrailRows**

`app/static/js/admin_audit.js` 上方：
```javascript
import { formatMoney, formatDateTimeTW, renderTrailRows } from './audit_util.js';
```

- [ ] **Step 3: 總表列加「建立者」欄 + 最後修改 + 軌跡**

`admin_audit.js` 的 `summaryRowHtml(e)` 改（加建立者 cell、稽核者後加軌跡鈕；金額 cell 下加最後修改小字）：
```javascript
function summaryRowHtml(e) {
  return `
    <tr data-eid="${e.id}">
      <td class="au-time">${formatDateTimeTW(e.created_at)}</td>
      <td>${escapeHtml(e.created_by_name || '')}</td>
      <td>${e.thumb_url ? `<img src="${e.thumb_url}" width="40" class="au-thumb" data-zoom="${e.image_url || ''}">` : '—'}</td>
      <td>${escapeHtml(e.summary || '')}${e.is_no_receipt ? ' <span class="au-mod">無單據</span>' : ''}</td>
      <td>${escapeHtml(e.category_name || '')}</td>
      <td>${e.amount ?? ''}${e.is_modified_by_manager ? ' <span class="au-mod">主管改</span>' : ''}
        ${e.last_modified_at ? `<div class="au-lastmod">改：${escapeHtml(e.last_modified_by_name || '')}（${formatDateTimeTW(e.last_modified_at)}）</div>` : ''}</td>
      <td>${lightLabel(e.light)}</td>
      <td>${e.status === 'audited' ? '已稽核' : '待稽核'}</td>
      <td>${escapeHtml(e.audited_by_name || '')}</td>
      <td><button class="ap-btn" data-trail="${e.id}" type="button">軌跡</button></td>
    </tr>`;
}
```

- [ ] **Step 4: 總表表頭補「建立者」「軌跡」欄**

`admin_audit.js` `renderSummary` 的 `<thead>`（約 line 66-67）改：
```javascript
      <table class="pd-table"><thead><tr>
        <th>建立</th><th>建立者</th><th>圖</th><th>摘要</th><th>分類</th><th>金額</th><th>燈</th><th>狀態</th><th>稽核者</th><th>軌跡</th>
      </tr></thead><tbody>${sh.items.map(summaryRowHtml).join('')}</tbody></table>
```

- [ ] **Step 5: 軌跡展開（總表 render 後綁定）**

`admin_audit.js` `renderSummary` 於 `body.innerHTML = ...` 之後、既有 `.au-thumb` 綁定附近，加委派綁定：
```javascript
  body.querySelectorAll('[data-trail]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const tr = btn.closest('tr');
      let box = tr.nextElementSibling;
      if (box && box.classList.contains('au-trail-tr')) { box.remove(); return; }
      box = document.createElement('tr');
      box.className = 'au-trail-tr';
      box.innerHTML = `<td colspan="10">載入中…</td>`;
      tr.after(box);
      try {
        const { data } = await api.expenseLogs(btn.dataset.trail);
        box.innerHTML = `<td colspan="10">${renderTrailRows(data.logs)}</td>`;
      } catch {
        box.innerHTML = `<td colspan="10">軌跡載入失敗</td>`;
      }
    });
  });
```

- [ ] **Step 6: 待稽核清單列同樣加建立者 + 軌跡（`renderPending`）**

`admin_audit.js` 的 `renderPending` 待稽核列（找該函式中組列 HTML 處）比照：加 `建立者`（`created_by_name`）顯示、`last_modified_at` 存在時顯示「改：X（時間）」、加 `data-trail` 軌跡鈕，並在 render 後套用 Step 5 同款 `[data-trail]` 綁定（可抽成本檔區域函式 `wireTrails(body)` 供總表與待稽核共用，避免重複）。

> 實作提示：把 Step 5 的綁定邏輯抽成 `function wireTrails(scope) {...}`（`colspan` 用該表欄數；待稽核表與總表欄數不同時各自傳對的 colspan，或用固定大值如 `10` 亦可接受），總表與待稽核 render 後各呼叫一次。

- [ ] **Step 7: 手動 e2e（Task 8 後一起）**

確認：主管稽核「總表查詢」與「待稽核」列有「建立者」、改過的單顯示「改：X（時間）」、點「軌跡」inline 展開看 `誰・時間・動作`（含員工在確認區改的那筆 + 主管簽核那筆）。

- [ ] **Step 8: Commit**

```bash
git add app/static/js/admin_api.js app/static/js/admin_audit.js
git commit -m "feat(audit-ui): 主管稽核總表/待稽核 顯示建立者/最後修改/軌跡展開"
```

---

### Task 8: 「操作記錄」後台頁籤（`admin_logs.js`）+ sw bump

**Files:**
- Modify: `app/static/js/admin_api.js`（加 `auditLogs`）
- Create: `app/static/js/admin_logs.js`
- Modify: `app/static/js/admin.js`（加頁籤 + 導覽分支）
- Modify: `app/static/sw.js`（`calc-v30`→`calc-v31`）
- Test: 手動 e2e

**Interfaces:**
- Consumes: Task 4 `/audit/logs`；`action_label`/`formatDateTimeTW`。
- Produces: `renderLogs(container, identity, storeId)`（export，供 admin.js 呼叫）；`api.auditLogs(storeId, date, actorId)`。

- [ ] **Step 1: api 方法**

`app/static/js/admin_api.js` `api` 物件加：
```javascript
  auditLogs: (storeId, date, actorId) => {
    const p = new URLSearchParams();
    if (storeId != null) p.set('store_id', storeId);
    p.set('date', date);
    if (actorId != null) p.set('actor_id', actorId);
    return req('GET', `/audit/logs?${p.toString()}`);
  },
```

- [ ] **Step 2: 建 `admin_logs.js`**

`app/static/js/admin_logs.js`：
```javascript
import { api } from './admin_api.js';
import { escapeHtml } from './admin_util.js';
import { formatDateTimeTW, action_label } from './audit_util.js';

// 台灣今日（YYYY-MM-DD）
function todayTW() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date());
  return parts; // en-CA 產出 2026-07-09 格式
}

export async function renderLogs(container, identity, storeId) {
  const isSuper = identity.role === 'super_admin';
  if (isSuper && !storeId) {
    container.innerHTML = '<div class="ap-empty">請先於上方選擇一家店</div>';
    return;
  }
  const sid = isSuper ? storeId : null;
  const date = todayTW();
  container.innerHTML = `
    <div class="au-day-nav">
      日期：<input type="date" id="lg-date" value="${date}" max="${date}">
      員工：<select id="lg-actor"><option value="">全部</option></select>
    </div>
    <div class="pd-table-wrap"><table class="pd-table"><thead><tr>
      <th>時間</th><th>員工</th><th>單號</th><th>摘要</th><th>動作</th>
    </tr></thead><tbody id="lg-body"></tbody></table></div>`;
  const dinp = container.querySelector('#lg-date');
  const asel = container.querySelector('#lg-actor');

  async function load() {
    const body = container.querySelector('#lg-body');
    body.innerHTML = '<tr><td colspan="5">載入中…</td></tr>';
    const actorId = asel.value ? Number(asel.value) : null;
    const { data } = await api.auditLogs(sid, dinp.value, actorId);
    const actors = data.actors || [];
    // 只在第一次填員工下拉（保留當前選擇）
    if (asel.options.length <= 1 && actors.length) {
      asel.innerHTML = '<option value="">全部</option>' +
        actors.map((a) => `<option value="${a.id}">${escapeHtml(a.name)}</option>`).join('');
      asel.value = actorId != null ? String(actorId) : '';
    }
    const items = data.items || [];
    body.innerHTML = items.length
      ? items.map((i) => `<tr>
          <td class="au-time">${formatDateTimeTW(i.ts)}</td>
          <td>${escapeHtml(i.actor_name || '')}</td>
          <td>#${i.expense_id}</td>
          <td>${escapeHtml(i.summary || '')}</td>
          <td>${action_label(i.action)}</td>
        </tr>`).join('')
      : '<tr><td colspan="5">當天沒有操作記錄</td></tr>';
  }

  dinp.addEventListener('change', () => { if (dinp.value) load(); });
  asel.addEventListener('change', load);
  load();
}
```

- [ ] **Step 3: `admin.js` 加頁籤 + 分支**

`app/static/js/admin.js`：import 加：
```javascript
import { renderLogs } from './admin_logs.js';
```
`tabs` 陣列加一項（放稽核之後）：
```javascript
  const tabs = [
    { key: 'audit', label: '稽核' },
    { key: 'logs', label: '操作記錄' },
    { key: 'accounts', label: '帳號' },
    { key: 'devices', label: '裝置' },
    ...(isSuper ? [{ key: 'stores', label: '店別' }] : []),
    { key: 'mypw', label: '我的密碼' },
  ];
```
`renderActiveTab()` 分支加（在 `audit` 分支後）：
```javascript
    else if (state.tab === 'logs') renderLogs(body, identity, state.storeId);
```

- [ ] **Step 4: bump sw.js**

`app/static/sw.js` 第 10 行：
```javascript
const CACHE_NAME = 'calc-v31';
```

- [ ] **Step 5: JS 全套回歸**

Run: `node --test tests/js/*.mjs`
Expected: PASS

- [ ] **Step 6: 後端全套回歸**

Run: `python3 -m pytest -q`
Expected: PASS（全綠）

- [ ] **Step 7: 本機 e2e（統一驗收）**

啟動：
```bash
cd ~/projects/expense-report
set -a; . ./.env; set +a
E2E_LOGIN_BYPASS=1 FLASK_APP=wsgi.py python3 -m flask db upgrade
E2E_LOGIN_BYPASS=1 FLASK_APP=wsgi.py python3 -m flask run --port 5001 --no-reload
```
驗收清單：
1. `/dev/login-test`（員工）→ 拍單（`/dev/sample-receipt` 免相機）→ 確認區改金額/分類 → 列上「建立者」有值、改後「最後修改」出現、點「軌跡」看到「小明・時間・修改」。送出。
2. `/dev/login-manager`（主管）→ 稽核「待稽核」改金額 → 打勾簽核 → 「總表查詢」該單有「建立者」「改：X」、點「軌跡」看到員工改 + 主管改 + 簽核多筆。
3. 後台「操作記錄」頁籤 → 日期預設今日、選員工下拉 → 列出當天 `時間・員工・單號・摘要・動作`；換日期/員工即時刷新。
4. super_admin 需先上方選店才看得到稽核/操作記錄。

- [ ] **Step 8: Commit**

```bash
git add app/static/js/admin_api.js app/static/js/admin_logs.js app/static/js/admin.js app/static/sw.js
git commit -m "feat(audit-ui): 操作記錄查詢頁籤(依日期+員工) + sw calc-v31"
```

---

## Self-Review

**Spec coverage：**
- 建立者上單 → Task 2（serialize `created_by_name`）+ Task 6/7（前端列）。✓
- 最後修改者+時間（只最後一次、有改才顯示）→ Task 1（冗餘欄）+ Task 2（serialize）+ Task 6/7（列 `last_modified_at` 條件顯示）。✓
- 每單展開軌跡（誰/時間/動作、不顯示改前後值）→ Task 3（端點回 actor_name/ts/action）+ Task 5（renderTrailRows）+ Task 6/7（展開）。✓
- 獨立操作記錄頁籤（manager/super_admin，依日期+員工）→ Task 4（端點）+ Task 8（頁籤）。✓
- 動作對映 edit→修改/check→簽核 → Task 5（`action_label`，前端 DRY；端點回原始 action）。✓
- scope/跨店 403、super_admin 選店 → Task 3/4 權限測試。✓
- 台灣時間、iso_utc、不輪詢、不新增依賴、sw bump → Global Constraints + 各 task。✓
- YAGNI（不追蹤 summary 改動、不顯示 before→after、不分兩行、不做依單號/動作篩選）→ 計畫未實作，符合。✓

**Placeholder scan：** Task 4 Step 1 的 `test_cross_store_isolation` 是**示意**並已明確標註「請照 test_audit_edit 乾淨版本重寫、不要照抄」——這是唯一刻意留白處，已附完整替代描述，非隱性 placeholder。其餘步驟皆含實際 code。

**Type consistency：**
- `serialize_expense(e, storage, with_main=False, name_by_id=None)` 全 task 一致；`created_by_name`/`last_modified_by_name`/`last_modified_at` 命名一致。
- 端點 `action` 一律回原始 `"edit"/"check"`；中文對映只在前端 `action_label`。
- `renderTrailRows(logs)` 消費 `{actor_name, ts, action}`，與 Task 3 端點回傳鍵一致。
- `/audit/logs` 回 `{items:[{expense_id,summary,actor_name,ts,action}], actors:[{id,name}]}`，與 Task 8 `admin_logs.js` 消費鍵一致。
- migration `down_revision='c1a2b3d4e5f6'`（現 head）。

## Execution Handoff

見主流程：從 master 開 branch `feat/audit-trail-visibility` → SDD subagent-driven 逐 task → 最終 opus 全 branch review → 本機 e2e → user 明說才 fast-forward merge master、不 push。
