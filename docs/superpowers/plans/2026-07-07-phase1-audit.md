# Phase 1 稽核（店管理者交接班打勾）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓店管理者在交接班時逐筆核對員工送出的雜支單、可微調金額/分類、打勾稽核（`submitted → audited`），並以交班/結班分區間、產當日總表；全程寫 `audit_log`。

**Architecture:** 新 `audit` blueprint（`/audit/*`）與既有 `admin`/`expenses` 分離；新增 `handovers`、`audit_log` 表與 `expenses` 稽核欄位；`audit_log` 寫入做共用 helper 供員工端與稽核端呼叫；前端在既有後台面板加「稽核」分頁。

**Tech Stack:** Flask / Flask-SQLAlchemy 2.0 / Flask-Migrate(alembic) / pytest；前端 ESM + `node --test`。系統 python3.12，無 venv。

依據 spec：`docs/superpowers/specs/2026-07-07-phase1-audit-design.md`。

## Global Constraints

- 時間 UI 一律台灣時間顯示，DB 存 UTC（`datetime.now(timezone.utc)`）。
- 前端不輪詢；狀態全進 DB。
- 不新增 Python 依賴（用既有 stdlib / SQLAlchemy）。
- 影像不落地（本 task 不碰上傳；稽核只讀 thumb presigned url）。
- 每次改前端 JS/CSS 必 bump `app/static/sw.js` 的 `CACHE_NAME`。
- 測試：後端 `python3 -m pytest -q`；前端純邏輯 `node --test tests/js/*.mjs`。
- 沿用既有回傳慣例 `jsonify(status="ok"/"error", ...)` 與 `@role_required` / `current_user()`。
- 從 master 開 branch `feat/phase1-audit`。

---

### Task 1: 資料模型 + migration

**Files:**
- Create: `app/models/handover.py`
- Create: `app/models/audit_log.py`
- Modify: `app/models/expense.py`（加欄位 + STATUSES）
- Modify: `app/models/__init__.py`（export）
- Create: migration（autogenerate 產生於 `migrations/versions/`）
- Test: `tests/test_audit_model.py`

**Interfaces:**
- Produces:
  - `Handover(id, store_id, closed_at, closed_by, type)`，`Handover.TYPES = ("shift", "day")`
  - `AuditLog(id, expense_id, actor_user_id, action, before_json, after_json, ts)`
  - `Expense.audited_by / audited_at / is_modified_by_manager / handover_id`；`Expense.STATUSES` 含 `"audited"`

- [ ] **Step 1: 寫失敗測試**

`tests/test_audit_model.py`：
```python
from datetime import datetime, timezone
from app.extensions import db
from app.models import Store, User, Category, Expense, Handover, AuditLog


def test_models_and_expense_fields(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="mgr", role="manager", store_id=s.id); u.set_password("1234")
        db.session.add(u); db.session.commit()
        now = datetime.now(timezone.utc)
        e = Expense(store_id=s.id, created_by=u.id, status="submitted", created_at=now)
        db.session.add(e); db.session.commit()

        # 稽核欄位可寫
        e.audited_by = u.id; e.audited_at = now; e.is_modified_by_manager = True
        h = Handover(store_id=s.id, closed_at=now, closed_by=u.id, type="shift")
        db.session.add(h); db.session.commit()
        e.handover_id = h.id; db.session.commit()

        log = AuditLog(expense_id=e.id, actor_user_id=u.id, action="edit",
                       before_json={"amount": None, "category_id": None},
                       after_json={"amount": 100.0, "category_id": None}, ts=now)
        db.session.add(log); db.session.commit()

        assert "audited" in Expense.STATUSES
        assert Handover.query.count() == 1
        assert AuditLog.query.filter_by(action="edit").count() == 1
        assert db.session.get(Expense, e.id).handover_id == h.id
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_audit_model.py -q`
Expected: FAIL（`ImportError: cannot import name 'Handover'`）

- [ ] **Step 3: 建 model 檔**

`app/models/handover.py`：
```python
from app.extensions import db


class Handover(db.Model):
    __tablename__ = "handovers"
    TYPES = ("shift", "day")

    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey("stores.id"), nullable=False, index=True)
    closed_at = db.Column(db.DateTime(timezone=True), nullable=False)
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    type = db.Column(db.String(8), nullable=False)  # shift | day
```

`app/models/audit_log.py`：
```python
from app.extensions import db


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    expense_id = db.Column(db.Integer, db.ForeignKey("expenses.id"), nullable=False, index=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    action = db.Column(db.String(16), nullable=False)  # edit | check
    before_json = db.Column(db.JSON, nullable=True)
    after_json = db.Column(db.JSON, nullable=True)
    ts = db.Column(db.DateTime(timezone=True), nullable=False)
```

- [ ] **Step 4: 改 Expense 加欄位 + STATUSES**

`app/models/expense.py`：`STATUSES` 改為：
```python
    STATUSES = ("pending_ocr", "draft", "submitted", "audited")
```
在 `no_receipt_reason` / `doc_type_id` 附近加：
```python
    audited_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    audited_at = db.Column(db.DateTime(timezone=True), nullable=True)
    is_modified_by_manager = db.Column(db.Boolean, nullable=False, default=False)
    handover_id = db.Column(db.Integer, db.ForeignKey("handovers.id"), nullable=True, index=True)
```

- [ ] **Step 5: export models**

`app/models/__init__.py`：於 `from app.models.expense import Expense` 之後加兩行 import，並把兩個名稱加入 `__all__`：
```python
from app.models.expense import Expense
from app.models.handover import Handover
from app.models.audit_log import AuditLog

__all__ = [
    "Store", "User", "ROLES", "is_valid_pin", "Category", "DocType",
    "Device", "FxRate", "Expense", "Handover", "AuditLog",
]
```

- [ ] **Step 6: 產 migration**

Run:
```bash
FLASK_APP=wsgi.py python3 -m flask db migrate -m "audit: handovers + audit_log + expense audit fields"
```
打開新產生的 `migrations/versions/*_audit_*.py`，確認 `upgrade()` 含（順序：先建 handovers，再 add expenses.handover_id 的 FK）：
- `op.create_table("handovers", ...)`
- `op.create_table("audit_log", ...)`
- `op.add_column("expenses", sa.Column("audited_by", ...))` 等 4 欄
- `op.create_index(...)`（handover_id）

若 autogenerate 對 SQLite 的 add FK column 有 batch 問題，確認檔案使用 `with op.batch_alter_table("expenses") as batch_op:` 包住 add_column。手動補上即可。

- [ ] **Step 7: upgrade + 跑測試**

Run:
```bash
FLASK_APP=wsgi.py python3 -m flask db upgrade
python3 -m pytest tests/test_audit_model.py -q
```
Expected: PASS

- [ ] **Step 8: 全套回歸 + commit**

```bash
python3 -m pytest -q
git add app/models/ migrations/versions/ tests/test_audit_model.py
git commit -m "feat(audit): Handover/AuditLog model + expenses 稽核欄位 + migration"
```

---

### Task 2: audit_log 寫入 helper（共用）

**Files:**
- Create: `app/audit/__init__.py`（空 package 起手，blueprint 於 Task 4 加）
- Create: `app/audit/log.py`
- Test: `tests/test_audit_log_helper.py`

**Interfaces:**
- Produces:
  - `snapshot(expense) -> dict`：回 `{"amount": float|None, "category_id": int|None}`
  - `log_edit_if_changed(expense, actor_user_id, before) -> bool`：before≠現值才寫 `action="edit"` 一筆並回 True
  - `record_check(expense, actor_user_id) -> None`：寫 `action="check"`（before=None, after={"status":"audited"}）
  - 皆只 `db.session.add(...)`，不 commit（由呼叫端 commit）

- [ ] **Step 1: 寫失敗測試**

`tests/test_audit_log_helper.py`：
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
        return s.id, u.id, e.id


def test_log_edit_only_when_changed(app):
    _, uid, eid = _mk(app)
    with app.app_context():
        e = db.session.get(Expense, eid)
        before = snapshot(e)
        # 無變動 → 不寫
        assert log_edit_if_changed(e, uid, before) is False
        # 改金額 → 寫一筆 edit，before/after 正確
        from decimal import Decimal
        e.amount = Decimal("250")
        assert log_edit_if_changed(e, uid, before) is True
        db.session.commit()
        rows = AuditLog.query.filter_by(action="edit").all()
        assert len(rows) == 1
        assert rows[0].before_json == {"amount": 100.0, "category_id": None}
        assert rows[0].after_json == {"amount": 250.0, "category_id": None}


def test_record_check(app):
    _, uid, eid = _mk(app)
    with app.app_context():
        e = db.session.get(Expense, eid)
        record_check(e, uid); db.session.commit()
        row = AuditLog.query.filter_by(action="check").one()
        assert row.before_json is None
        assert row.after_json == {"status": "audited"}
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_audit_log_helper.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.audit'`）

- [ ] **Step 3: 建 package + helper**

`app/audit/__init__.py`：
```python
```
（先留空檔；blueprint 於 Task 4 加入。）

`app/audit/log.py`：
```python
from datetime import datetime, timezone
from app.extensions import db
from app.models import AuditLog


def _amt_cat(expense):
    return {
        "amount": float(expense.amount) if expense.amount is not None else None,
        "category_id": expense.category_id,
    }


def snapshot(expense):
    """在改動前呼叫，取金額/分類快照。"""
    return _amt_cat(expense)


def log_edit_if_changed(expense, actor_user_id, before):
    """before 為改動前 snapshot；與現值不同才寫一筆 edit。回是否有寫。"""
    after = _amt_cat(expense)
    if after == before:
        return False
    db.session.add(AuditLog(
        expense_id=expense.id, actor_user_id=actor_user_id, action="edit",
        before_json=before, after_json=after, ts=datetime.now(timezone.utc),
    ))
    return True


def record_check(expense, actor_user_id):
    db.session.add(AuditLog(
        expense_id=expense.id, actor_user_id=actor_user_id, action="check",
        before_json=None, after_json={"status": "audited"},
        ts=datetime.now(timezone.utc),
    ))
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_audit_log_helper.py -q`
Expected: PASS

- [ ] **Step 5: commit**

```bash
git add app/audit/ tests/test_audit_log_helper.py
git commit -m "feat(audit): audit_log 寫入 helper(snapshot/log_edit_if_changed/record_check)"
```

---

### Task 3: 員工暫存區 PATCH 加寫 edit log（§5.5）

**Files:**
- Modify: `app/expenses/routes.py`（`edit()` 函式）
- Test: `tests/test_expense_audit_log.py`

**Interfaces:**
- Consumes: `app.audit.log.snapshot`, `log_edit_if_changed`
- Produces: 員工 PATCH 改到 amount/category_id 時，多寫一筆 `AuditLog(action="edit")`；回傳與行為不變。

- [ ] **Step 1: 寫失敗測試**

`tests/test_expense_audit_log.py`（沿用既有 test client 建 employee session 的 pattern，參考 `tests/test_expense_categories.py`）：
```python
import time
from datetime import datetime, timezone
from app.extensions import db
from app.models import Store, User, Device, Expense, AuditLog


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="emp", role="employee", store_id=s.id); u.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        e = Expense(store_id=s.id, created_by=None, status="draft",
                    created_at=datetime.now(timezone.utc))
        db.session.add_all([u, dev]); db.session.commit()
        e.created_by = u.id; db.session.add(e); db.session.commit()
        return u.id, e.id


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_employee_patch_amount_writes_edit_log(app):
    uid, eid = _seed(app)
    c = _client(app, uid)
    r = c.patch(f"/expenses/{eid}", json={"amount": "300"})
    assert r.status_code == 200
    with app.app_context():
        logs = AuditLog.query.filter_by(expense_id=eid, action="edit").all()
        assert len(logs) == 1
        assert logs[0].actor_user_id == uid
        assert logs[0].after_json["amount"] == 300.0


def test_employee_patch_summary_only_no_log(app):
    uid, eid = _seed(app)
    c = _client(app, uid)
    c.patch(f"/expenses/{eid}", json={"summary": "改摘要"})
    with app.app_context():
        assert AuditLog.query.filter_by(expense_id=eid).count() == 0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_expense_audit_log.py -q`
Expected: FAIL（log 為 0 筆）

- [ ] **Step 3: 改 edit() 加 snapshot + log**

`app/expenses/routes.py`：檔頭加 import：
```python
from app.audit.log import snapshot, log_edit_if_changed
```
在 `edit()` 內，`data = request.get_json(...)` 之後、改動之前，取快照；所有欄位改完、`db.session.commit()` 之前，補記 log。改成：
```python
    data = request.get_json(silent=True) or {}
    before = snapshot(e)
    if "summary" in data:
        e.summary = data["summary"]
    if "category_id" in data:
        e.category_id = _valid_category_id(data["category_id"])
        e.is_modified_by_user = True
    if "amount" in data:
        try:
            e.amount = None if data["amount"] is None else Decimal(str(data["amount"]))
            e.amount_parse_ok = e.amount is not None
        except (InvalidOperation, ValueError):
            e.amount = None; e.amount_parse_ok = False
        e.is_modified_by_user = True
    log_edit_if_changed(e, user.id, before)
    db.session.commit()
```

- [ ] **Step 4: 跑測試 + 回歸**

Run:
```bash
python3 -m pytest tests/test_expense_audit_log.py tests/test_expenses.py -q
```
Expected: PASS（既有 expenses 測試不受影響）

- [ ] **Step 5: commit**

```bash
git add app/expenses/routes.py tests/test_expense_audit_log.py
git commit -m "feat(audit): 員工暫存區 PATCH 改金額/分類寫 audit_log(edit)"
```

---

### Task 4: audit blueprint + scope helper + GET /audit/pending

**Files:**
- Modify: `app/audit/__init__.py`（建 blueprint）
- Create: `app/audit/routes.py`
- Modify: `app/__init__.py`（註冊 `audit_bp`）
- Test: `tests/test_audit_pending.py`

**Interfaces:**
- Produces:
  - blueprint `audit_bp`（`url_prefix="/audit"`）
  - `_scope_store_id(from_body=False) -> (store_id|None, error_response|None)`：manager 用本店；super_admin 需帶 `store_id`（GET 讀 query、POST 讀 body）；缺/無效 → 400
  - `GET /audit/pending`：回 `{status:"ok", groups:[{business_date, subtotal, items:[serialized]}]}`

- [ ] **Step 1: 寫失敗測試**

`tests/test_audit_pending.py`：
```python
import time
from datetime import datetime, timezone, date
from app.extensions import db
from app.models import Store, User, Device, Expense


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); s2 = Store(name="B", code="B")
        db.session.add_all([s, s2]); db.session.commit()
        mgr = User(name="mgr", role="manager", store_id=s.id); mgr.set_password("1234")
        emp = User(name="emp", role="employee", store_id=s.id); emp.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add_all([mgr, emp, dev]); db.session.commit()
        now = datetime.now(timezone.utc)
        from decimal import Decimal
        e1 = Expense(store_id=s.id, created_by=emp.id, status="submitted", created_at=now,
                     business_date=date(2026, 7, 7), amount=Decimal("100"), submitted_at=now)
        e2 = Expense(store_id=s.id, created_by=emp.id, status="submitted", created_at=now,
                     business_date=date(2026, 7, 7), amount=Decimal("50"), submitted_at=now)
        other = Expense(store_id=s2.id, created_by=emp.id, status="submitted", created_at=now,
                        business_date=date(2026, 7, 7), amount=Decimal("999"), submitted_at=now)
        db.session.add_all([e1, e2, other]); db.session.commit()
        return mgr.id, s.id


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_pending_groups_by_business_date_with_subtotal(app):
    mgr_id, sid = _seed(app)
    c = _client(app, mgr_id)
    body = c.get("/audit/pending").get_json()
    assert body["status"] == "ok"
    assert len(body["groups"]) == 1
    g = body["groups"][0]
    assert g["business_date"] == "2026-07-07"
    assert g["subtotal"] == 150.0            # 只含本店（100+50），不含他店 999
    assert len(g["items"]) == 2


def test_pending_requires_manager(app):
    _seed(app)
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    assert c.get("/audit/pending").status_code == 401
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_audit_pending.py -q`
Expected: FAIL（404 / blueprint 未註冊）

- [ ] **Step 3: 建 blueprint**

`app/audit/__init__.py`：
```python
from flask import Blueprint

audit_bp = Blueprint("audit", __name__, url_prefix="/audit")

from app.audit import routes  # noqa: E402,F401
```

- [ ] **Step 4: 寫 routes（scope helper + pending）**

`app/audit/routes.py`：
```python
from flask import request, jsonify
from app.extensions import db
from app.models import Expense, Store
from app.auth.decorators import current_user, role_required
from app.expenses.serialize import serialize_expense
from app.storage.r2 import get_storage
from app.audit import audit_bp


def _scope_store_id(from_body=False):
    """回 (store_id, error)。manager→本店；super_admin→需帶 store_id（GET 讀 query、POST 讀 body）。"""
    actor = current_user()
    if actor.role == "manager":
        return actor.store_id, None
    # super_admin
    if from_body:
        raw = (request.get_json(silent=True) or {}).get("store_id")
    else:
        raw = request.args.get("store_id")
    try:
        sid = int(raw)
    except (TypeError, ValueError):
        return None, (jsonify(status="error", message="store_id required"), 400)
    if db.session.get(Store, sid) is None:
        return None, (jsonify(status="error", message="store not found"), 400)
    return sid, None


@audit_bp.get("/pending")
@role_required("manager", "super_admin")
def pending():
    store_id, err = _scope_store_id()
    if err:
        return err
    rows = (Expense.query
            .filter(Expense.store_id == store_id, Expense.status == "submitted")
            .order_by(Expense.business_date.asc(), Expense.submitted_at.asc())
            .all())
    storage = get_storage()
    groups = {}
    for e in rows:
        key = e.business_date.isoformat() if e.business_date else "none"
        groups.setdefault(key, []).append(e)
    out = []
    for bd in sorted(groups):
        items = groups[bd]
        subtotal = sum(float(x.amount) for x in items if x.amount is not None)
        out.append({
            "business_date": bd, "subtotal": subtotal,
            "items": [serialize_expense(x, storage) for x in items],
        })
    return jsonify(status="ok", groups=out)
```

- [ ] **Step 5: 註冊 blueprint**

`app/__init__.py`：在 `expense_bp` 註冊之後加：
```python
    from app.audit import audit_bp
    app.register_blueprint(audit_bp)
```

- [ ] **Step 6: 跑測試 + 回歸 + commit**

Run:
```bash
python3 -m pytest tests/test_audit_pending.py -q && python3 -m pytest -q
```
Expected: PASS
```bash
git add app/audit/ app/__init__.py tests/test_audit_pending.py
git commit -m "feat(audit): audit blueprint + scope helper + GET /audit/pending"
```

---

### Task 5: PATCH /audit/<eid>（主管稽核改金額/分類）

**Files:**
- Modify: `app/audit/routes.py`
- Test: `tests/test_audit_edit.py`

**Interfaces:**
- Consumes: `_scope_store_id`, `app.audit.log.snapshot/log_edit_if_changed`, `app.expenses.tasks._valid_category_id`
- Produces: `PATCH /audit/<eid>`；僅 `status=submitted` 可改（否則 409）；跨店 403；設 `is_modified_by_manager=True`；寫 `audit_log(edit)`；回 `{status:"ok"}`

- [ ] **Step 1: 寫失敗測試**

`tests/test_audit_edit.py`（沿用 Task 4 的 `_seed`/`_client` 結構，可 copy）：
```python
import time
from datetime import datetime, timezone, date
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense, AuditLog


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        mgr = User(name="mgr", role="manager", store_id=s.id); mgr.set_password("1234")
        emp = User(name="emp", role="employee", store_id=s.id); emp.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add_all([mgr, emp, dev]); db.session.commit()
        now = datetime.now(timezone.utc)
        sub = Expense(store_id=s.id, created_by=emp.id, status="submitted", created_at=now,
                      business_date=date(2026, 7, 7), amount=Decimal("100"), submitted_at=now)
        aud = Expense(store_id=s.id, created_by=emp.id, status="audited", created_at=now,
                      amount=Decimal("80"))
        db.session.add_all([sub, aud]); db.session.commit()
        return mgr.id, sub.id, aud.id


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_manager_edit_submitted(app):
    mgr_id, sub_id, _ = _seed(app)
    c = _client(app, mgr_id)
    r = c.patch(f"/audit/{sub_id}", json={"amount": "120"})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, sub_id)
        assert float(e.amount) == 120.0 and e.is_modified_by_manager is True
        assert AuditLog.query.filter_by(expense_id=sub_id, action="edit").count() == 1


def test_manager_edit_audited_locked_409(app):
    mgr_id, _, aud_id = _seed(app)
    c = _client(app, mgr_id)
    assert c.patch(f"/audit/{aud_id}", json={"amount": "1"}).status_code == 409
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_audit_edit.py -q`
Expected: FAIL（404）

- [ ] **Step 3: 實作 PATCH**

`app/audit/routes.py` 加 import 與端點：
```python
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from app.expenses.tasks import _valid_category_id
from app.audit.log import snapshot, log_edit_if_changed, record_check


def _load_in_scope(eid, store_id):
    e = db.session.get(Expense, eid)
    if e is None:
        return None, (jsonify(status="error", message="not found"), 404)
    if e.store_id != store_id:
        return None, (jsonify(status="error", message="forbidden"), 403)
    return e, None


@audit_bp.patch("/<int:eid>")
@role_required("manager", "super_admin")
def edit(eid):
    store_id, err = _scope_store_id()
    if err:
        return err
    e, err = _load_in_scope(eid, store_id)
    if err:
        return err
    if e.status != "submitted":
        return jsonify(status="error", message="not editable"), 409
    data = request.get_json(silent=True) or {}
    before = snapshot(e)
    if "category_id" in data:
        e.category_id = _valid_category_id(data["category_id"])
    if "amount" in data:
        try:
            e.amount = None if data["amount"] is None else Decimal(str(data["amount"]))
            e.amount_parse_ok = e.amount is not None
        except (InvalidOperation, ValueError):
            e.amount = None; e.amount_parse_ok = False
    if log_edit_if_changed(e, current_user().id, before):
        e.is_modified_by_manager = True
    db.session.commit()
    return jsonify(status="ok")
```
註：`_scope_store_id` 讀 query，但 PATCH 的 super_admin 需帶 store_id — 由前端放 querystring（`/audit/<id>?store_id=<n>`）。manager 不受影響。

- [ ] **Step 4: 跑測試 + commit**

Run: `python3 -m pytest tests/test_audit_edit.py -q`
Expected: PASS
```bash
git add app/audit/routes.py tests/test_audit_edit.py
git commit -m "feat(audit): PATCH /audit/<id> 主管稽核改金額/分類(僅 submitted、寫 log)"
```

---

### Task 6: POST /audit/<eid>/check（打勾）

**Files:**
- Modify: `app/audit/routes.py`
- Test: `tests/test_audit_check.py`

**Interfaces:**
- Consumes: `_scope_store_id`, `_load_in_scope`, `record_check`
- Produces: `POST /audit/<eid>/check`；`submitted→audited`，設 `audited_by/at`，`handover_id` 保持 null，寫 `audit_log(check)`；非 submitted → 409

- [ ] **Step 1: 寫失敗測試**

`tests/test_audit_check.py`（沿用 Task 5 `_seed`/`_client`）：
```python
# ... 同 Task 5 的 _seed / _client（copy）...

def test_check_submitted_to_audited(app):
    mgr_id, sub_id, _ = _seed(app)
    c = _client(app, mgr_id)
    r = c.post(f"/audit/{sub_id}/check")
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, sub_id)
        assert e.status == "audited" and e.audited_by == mgr_id
        assert e.audited_at is not None and e.handover_id is None
        from app.models import AuditLog
        assert AuditLog.query.filter_by(expense_id=sub_id, action="check").count() == 1


def test_check_non_submitted_409(app):
    mgr_id, _, aud_id = _seed(app)
    c = _client(app, mgr_id)
    assert c.post(f"/audit/{aud_id}/check").status_code == 409
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_audit_check.py -q`
Expected: FAIL（404）

- [ ] **Step 3: 實作 check**

`app/audit/routes.py` 加：
```python
@audit_bp.post("/<int:eid>/check")
@role_required("manager", "super_admin")
def check(eid):
    store_id, err = _scope_store_id()
    if err:
        return err
    e, err = _load_in_scope(eid, store_id)
    if err:
        return err
    if e.status != "submitted":
        return jsonify(status="error", message="not checkable"), 409
    e.status = "audited"
    e.audited_by = current_user().id
    e.audited_at = datetime.now(timezone.utc)
    record_check(e, current_user().id)
    db.session.commit()
    return jsonify(status="ok")
```

- [ ] **Step 4: 跑測試 + commit**

Run: `python3 -m pytest tests/test_audit_check.py -q`
Expected: PASS
```bash
git add app/audit/routes.py tests/test_audit_check.py
git commit -m "feat(audit): POST /audit/<id>/check 打勾 submitted→audited(寫 log)"
```

---

### Task 7: 交班/結班 + 取消（POST /audit/handover, /audit/handover/undo）

**Files:**
- Modify: `app/audit/routes.py`
- Test: `tests/test_audit_handover.py`

**Interfaces:**
- Consumes: `_scope_store_id(from_body=True)`, `Handover`
- Produces:
  - `POST /audit/handover {type, store_id?}`：建 Handover(type)，把該店 `audited 且 handover_id IS NULL` 的單原子蓋章；無可歸班 → 400；回 `{status:"ok", handover_id, type, count}`
  - `POST /audit/handover/undo {store_id?}`：刪該店最近 Handover、其單 handover_id 退回 null；無 → 400；回 `{status:"ok", reopened}`

- [ ] **Step 1: 寫失敗測試**

`tests/test_audit_handover.py`：
```python
import time
from datetime import datetime, timezone
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense, Handover


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        mgr = User(name="mgr", role="manager", store_id=s.id); mgr.set_password("1234")
        emp = User(name="emp", role="employee", store_id=s.id); emp.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add_all([mgr, emp, dev]); db.session.commit()
        now = datetime.now(timezone.utc)

        def mk(status, amt):
            return Expense(store_id=s.id, created_by=emp.id, status=status,
                           created_at=now, amount=Decimal(str(amt)))
        a1 = mk("audited", 100); a2 = mk("audited", 50); sub = mk("submitted", 999)
        db.session.add_all([a1, a2, sub]); db.session.commit()
        return mgr.id, s.id, a1.id, a2.id, sub.id


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_handover_stamps_audited_open_only(app):
    mgr_id, sid, a1, a2, sub = _seed(app)
    c = _client(app, mgr_id)
    r = c.post("/audit/handover", json={"type": "shift"}).get_json()
    assert r["status"] == "ok" and r["count"] == 2 and r["type"] == "shift"
    with app.app_context():
        h = Handover.query.one()
        assert db.session.get(Expense, a1).handover_id == h.id
        assert db.session.get(Expense, a2).handover_id == h.id
        assert db.session.get(Expense, sub).handover_id is None  # submitted 不歸班


def test_empty_handover_400(app):
    mgr_id, sid, a1, a2, sub = _seed(app)
    c = _client(app, mgr_id)
    c.post("/audit/handover", json={"type": "shift"})       # 先歸掉 a1/a2
    assert c.post("/audit/handover", json={"type": "shift"}).status_code == 400


def test_undo_reopens_last(app):
    mgr_id, sid, a1, a2, sub = _seed(app)
    c = _client(app, mgr_id)
    c.post("/audit/handover", json={"type": "shift"})
    r = c.post("/audit/handover/undo", json={}).get_json()
    assert r["status"] == "ok" and r["reopened"] == 2
    with app.app_context():
        assert Handover.query.count() == 0
        assert db.session.get(Expense, a1).handover_id is None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_audit_handover.py -q`
Expected: FAIL（404）

- [ ] **Step 3: 實作 handover + undo**

`app/audit/routes.py` 加 import `from app.models import Handover` 與端點：
```python
@audit_bp.post("/handover")
@role_required("manager", "super_admin")
def handover():
    data = request.get_json(silent=True) or {}
    htype = data.get("type")
    if htype not in ("shift", "day"):
        return jsonify(status="error", message="bad type"), 400
    store_id, err = _scope_store_id(from_body=True)
    if err:
        return err
    h = Handover(store_id=store_id, closed_at=datetime.now(timezone.utc),
                 closed_by=current_user().id, type=htype)
    db.session.add(h); db.session.flush()
    count = (Expense.query
             .filter(Expense.store_id == store_id, Expense.status == "audited",
                     Expense.handover_id.is_(None))
             .update({Expense.handover_id: h.id}, synchronize_session=False))
    if count == 0:
        db.session.rollback()
        return jsonify(status="error", message="no audited entries to close"), 400
    db.session.commit()
    return jsonify(status="ok", handover_id=h.id, type=htype, count=count)


@audit_bp.post("/handover/undo")
@role_required("manager", "super_admin")
def handover_undo():
    store_id, err = _scope_store_id(from_body=True)
    if err:
        return err
    last = (Handover.query.filter_by(store_id=store_id)
            .order_by(Handover.closed_at.desc(), Handover.id.desc()).first())
    if last is None:
        return jsonify(status="error", message="no handover"), 400
    reopened = (Expense.query.filter_by(handover_id=last.id)
                .update({Expense.handover_id: None}, synchronize_session=False))
    db.session.delete(last)
    db.session.commit()
    return jsonify(status="ok", reopened=reopened)
```
註：super_admin 呼叫需在 body 帶 `store_id`；manager 忽略。

- [ ] **Step 4: 跑測試 + commit**

Run: `python3 -m pytest tests/test_audit_handover.py -q`
Expected: PASS
```bash
git add app/audit/routes.py tests/test_audit_handover.py
git commit -m "feat(audit): 交班/結班 POST /audit/handover + 取消 undo(原子蓋章)"
```

---

### Task 8: GET /audit/summary（當日總表）

**Files:**
- Create: `app/audit/service.py`（`compute_summary` 純邏輯）
- Modify: `app/audit/routes.py`（端點）
- Test: `tests/test_audit_summary.py`

**Interfaces:**
- Produces:
  - `app.audit.service.compute_summary(store_id, before_id=None) -> dict`：回 `{intervals:[{handover_id, type, seq, closed_at, subtotal, count}], open:{subtotal, count}, day_total}`
  - `GET /audit/summary {store_id?, before?}`：包 `compute_summary`

**當前稽核日定義**：該店最近一筆 `type="day"`（結班）之 `closed_at` **之後**的 handover（皆 shift），加上「當前未歸班」(`audited 且 handover_id IS NULL`)。`before=<handover_id>`（須為某 `type="day"`）時回上一個稽核日（該 day-close 及其之前、上一個 day-close 之後的 handover，`open` 為空）。

- [ ] **Step 1: 寫失敗測試**

`tests/test_audit_summary.py`：
```python
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense, Handover


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        mgr = User(name="mgr", role="manager", store_id=s.id); mgr.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add_all([mgr, dev]); db.session.commit()
        return mgr.id, s.id


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def _audited(store_id, mgr_id, amt, handover_id=None):
    return Expense(store_id=store_id, created_by=mgr_id, status="audited",
                   created_at=datetime.now(timezone.utc), amount=Decimal(str(amt)),
                   audited_by=mgr_id, audited_at=datetime.now(timezone.utc),
                   handover_id=handover_id)


def test_summary_current_day(app):
    mgr_id, sid = _seed(app)
    with app.app_context():
        # 一個已交班區間(100+50) + 當前未歸班(30)
        base = datetime(2026, 7, 7, 10, tzinfo=timezone.utc)
        h = Handover(store_id=sid, closed_at=base, closed_by=mgr_id, type="shift")
        db.session.add(h); db.session.flush()
        db.session.add_all([_audited(sid, mgr_id, 100, h.id), _audited(sid, mgr_id, 50, h.id),
                            _audited(sid, mgr_id, 30, None)])
        db.session.commit()
    c = _client(app, mgr_id)
    body = c.get("/audit/summary").get_json()
    assert body["status"] == "ok"
    assert len(body["intervals"]) == 1
    assert body["intervals"][0]["subtotal"] == 150.0 and body["intervals"][0]["seq"] == 1
    assert body["open"]["subtotal"] == 30.0
    assert body["day_total"] == 180.0


def test_summary_excludes_before_day_close(app):
    mgr_id, sid = _seed(app)
    with app.app_context():
        t0 = datetime(2026, 7, 6, 10, tzinfo=timezone.utc)
        # 昨天結班(type=day) 含 200
        d = Handover(store_id=sid, closed_at=t0, closed_by=mgr_id, type="day")
        db.session.add(d); db.session.flush()
        db.session.add(_audited(sid, mgr_id, 200, d.id))
        # 今天當前未歸班 40
        db.session.add(_audited(sid, mgr_id, 40, None))
        db.session.commit()
    c = _client(app, mgr_id)
    body = c.get("/audit/summary").get_json()
    assert body["intervals"] == []            # 昨天已結班，不算今天
    assert body["open"]["subtotal"] == 40.0
    assert body["day_total"] == 40.0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_audit_summary.py -q`
Expected: FAIL（404）

- [ ] **Step 3: 寫 compute_summary 純邏輯**

`app/audit/service.py`：
```python
from app.extensions import db
from app.models import Expense, Handover


def _sum(store_id, handover_id):
    rows = Expense.query.filter_by(store_id=store_id, handover_id=handover_id).all()
    subtotal = sum(float(x.amount) for x in rows if x.amount is not None)
    return subtotal, len(rows)


def compute_summary(store_id, before_id=None):
    """當前稽核日（before_id=None）或指定結班日的分區間彙整。"""
    if before_id is None:
        last_day = (Handover.query
                    .filter_by(store_id=store_id, type="day")
                    .order_by(Handover.closed_at.desc(), Handover.id.desc()).first())
        lower = last_day.closed_at if last_day else None
        q = Handover.query.filter_by(store_id=store_id)
        if lower is not None:
            q = q.filter(Handover.closed_at > lower)
        handovers = q.order_by(Handover.closed_at.asc(), Handover.id.asc()).all()
        include_open = True
    else:
        end = db.session.get(Handover, before_id)
        prev = (Handover.query
                .filter(Handover.store_id == store_id, Handover.type == "day",
                        Handover.closed_at < end.closed_at)
                .order_by(Handover.closed_at.desc(), Handover.id.desc()).first())
        q = Handover.query.filter(Handover.store_id == store_id,
                                  Handover.closed_at <= end.closed_at)
        if prev is not None:
            q = q.filter(Handover.closed_at > prev.closed_at)
        handovers = q.order_by(Handover.closed_at.asc(), Handover.id.asc()).all()
        include_open = False

    intervals = []
    day_total = 0.0
    for i, h in enumerate(handovers, start=1):
        subtotal, count = _sum(store_id, h.id)
        intervals.append({"handover_id": h.id, "type": h.type, "seq": i,
                          "closed_at": h.closed_at.isoformat(), "subtotal": subtotal,
                          "count": count})
        day_total += subtotal

    open_block = {"subtotal": 0.0, "count": 0}
    if include_open:
        s, c = _sum(store_id, None)
        open_block = {"subtotal": s, "count": c}
        day_total += s
    return {"intervals": intervals, "open": open_block, "day_total": day_total}
```

- [ ] **Step 4: 端點包一層**

`app/audit/routes.py` 加：
```python
from app.audit.service import compute_summary


@audit_bp.get("/summary")
@role_required("manager", "super_admin")
def summary():
    store_id, err = _scope_store_id()
    if err:
        return err
    before_id = request.args.get("before", type=int)
    data = compute_summary(store_id, before_id)
    return jsonify(status="ok", **data)
```

- [ ] **Step 5: 跑測試 + 回歸 + commit**

Run:
```bash
python3 -m pytest tests/test_audit_summary.py -q && python3 -m pytest -q
```
Expected: PASS
```bash
git add app/audit/ tests/test_audit_summary.py
git commit -m "feat(audit): GET /audit/summary 當日總表(compute_summary 純邏輯)"
```

---

### Task 9: 前端稽核分頁 — 待稽核子區（清單/改/打勾）+ dev manager 登入

**Files:**
- Modify: `app/static/js/admin_api.js`（audit 方法）
- Modify: `app/static/js/admin.js`（加「稽核」tab）
- Create: `app/static/js/admin_audit.js`
- Create: `app/static/js/audit_util.js`（純邏輯：分組小計格式化）
- Modify: `app/dev/routes.py`（加 `/dev/login-manager` 供手動 e2e）
- Modify: `app/static/sw.js`（bump CACHE_NAME）
- Test: `tests/js/audit.mjs`

**Interfaces:**
- Consumes: 後端 `/audit/pending`, `/audit/<id>`(PATCH), `/audit/<id>/check`；`expenses_util.js` 的 `categoryOptionsHtml`
- Produces: `admin_audit.js` 匯出 `renderAudit(container, identity, storeId)`；`audit_util.js` 匯出 `formatMoney(n)`（純函式，供 JS 測試）

- [ ] **Step 1: 寫純邏輯失敗測試**

`tests/js/audit.mjs`：
```javascript
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatMoney } from '../../app/static/js/audit_util.js';

test('formatMoney thousands', () => {
  assert.equal(formatMoney(1290), '1,290');
  assert.equal(formatMoney(0), '0');
  assert.equal(formatMoney(180.5), '180.5');
});
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `node --test tests/js/audit.mjs`
Expected: FAIL（找不到模組）

- [ ] **Step 3: 建 audit_util.js**

`app/static/js/audit_util.js`：
```javascript
export function formatMoney(n) {
  const num = Number(n) || 0;
  return num.toLocaleString('en-US');
}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `node --test tests/js/audit.mjs`
Expected: PASS

- [ ] **Step 5: admin_api 加 audit 方法**

`app/static/js/admin_api.js`：沿用該檔既有 `req(method, url, body)` 與 `withStore(base, storeId)` helper，在 `api` 物件加（`storeId` 為 super_admin 選定店，manager 傳 null/undefined）：
```javascript
  auditPending: (storeId) => req('GET', withStore('/audit/pending', storeId)),
  auditEdit: (id, patch, storeId) => req('PATCH', withStore(`/audit/${id}`, storeId), patch),
  auditCheck: (id, storeId) => req('POST', withStore(`/audit/${id}/check`, storeId)),
  auditSummary: (storeId, before) => {
    const p = new URLSearchParams();
    if (storeId != null) p.set('store_id', storeId);
    if (before) p.set('before', before);
    const qs = p.toString();
    return req('GET', `/audit/summary${qs ? `?${qs}` : ''}`);
  },
  auditHandover: (type, storeId) => req('POST', '/audit/handover', { type, store_id: storeId }),
  auditUndo: (storeId) => req('POST', '/audit/handover/undo', { store_id: storeId }),
```
（`req` 回 `{status, data}`；`withStore` 於 storeId 非 null 時附 `?store_id=`。）

- [ ] **Step 6: admin.js 加「稽核」tab**

`app/static/js/admin.js`：`import { renderAudit } from './admin_audit.js';`；在 `tabs` 陣列**最前面**加 `{ key: 'audit', label: '稽核' }`（manager + super_admin 皆見）；在分頁 render 分派處（既有 `renderAccounts`/`renderDevices` 的 switch/if）加：
```javascript
      } else if (state.tab === 'audit') {
        renderAudit(body, identity, state.storeId);
```
（`state.storeId` 為 super_admin 調店選定值，manager 為 null。）

- [ ] **Step 7: 建 admin_audit.js（待稽核子區）**

`app/static/js/admin_audit.js`：
```javascript
import { api } from './admin_api.js';
import { escapeHtml } from './admin_util.js';
import { categoryOptionsHtml, lightLabel, parseAmountInput } from './expenses_util.js';
import { formatMoney } from './audit_util.js';

// storeId：super_admin 選定的店；manager 傳 null（後端用本店）
export async function renderAudit(container, identity, storeId) {
  const isSuper = identity.role === 'super_admin';
  if (isSuper && !storeId) {
    container.innerHTML = '<div class="ap-empty">請先於上方選擇一家店</div>';
    return;
  }
  const sid = isSuper ? storeId : undefined;
  container.innerHTML = `
    <div class="audit-sub">
      <button class="ap-tab active" id="au-tab-pending" type="button">待稽核</button>
      <button class="ap-tab" id="au-tab-summary" type="button">當日總表</button>
    </div>
    <div id="au-body"></div>`;
  const body = container.querySelector('#au-body');
  const showPending = () => renderPending(body, sid);
  container.querySelector('#au-tab-pending').addEventListener('click', showPending);
  container.querySelector('#au-tab-summary').addEventListener('click',
    () => renderSummary(body, sid));   // renderSummary 於 Task 10 實作
  showPending();
}

async function renderPending(body, sid) {
  body.innerHTML = '載入中…';
  const { data } = await api.auditPending(sid);
  // 分類清單（供下拉）——沿用員工端 /expenses/categories
  const catResp = await fetch('/expenses/categories').then((r) => r.json()).catch(() => ({}));
  const tree = (catResp && catResp.categories) || [];
  const groups = (data && data.groups) || [];
  if (!groups.length) { body.innerHTML = '<div class="ap-empty">沒有待稽核單據</div>'; return; }
  body.innerHTML = groups.map((g) => `
    <div class="au-group">
      <div class="au-group-head">${g.business_date}　日小計 ${formatMoney(g.subtotal)}</div>
      <table class="pd-table"><thead><tr>
        <th>圖</th><th>摘要</th><th>分類</th><th>金額</th><th>燈</th><th></th>
      </tr></thead><tbody>
      ${g.items.map((e) => rowHtml(e, tree)).join('')}
      </tbody></table>
    </div>`).join('');
  wireRows(body, sid);
  // 交班/結班列（Task 10 補上按鈕邏輯）
}

function rowHtml(e, tree) {
  const thumb = e.thumb_url ? `<img src="${e.thumb_url}" loading="lazy" width="48">` : '—';
  return `<tr data-id="${e.id}">
    <td>${thumb}</td>
    <td>${escapeHtml(e.summary || '')}</td>
    <td><select data-f="category">${categoryOptionsHtml(tree, e.category_id)}</select></td>
    <td><input value="${e.amount ?? ''}" inputmode="decimal" data-f="amount" style="width:80px"></td>
    <td>${lightLabel(e.light)}</td>
    <td><button data-act="check">打勾</button><div class="pd-row-err" data-f="err"></div></td>
  </tr>`;
}

function wireRows(body, sid) {
  body.querySelectorAll('tr[data-id]').forEach((tr) => {
    const id = Number(tr.dataset.id);
    const err = tr.querySelector('[data-f="err"]');
    const cat = tr.querySelector('[data-f="category"]');
    cat.addEventListener('change', async () => {
      err.textContent = '';
      const categoryId = cat.value === '' ? null : Number(cat.value);
      try {
        const { status } = await api.auditEdit(id, { category_id: categoryId }, sid);
        if (status !== 200) err.textContent = '分類儲存失敗';
      } catch { err.textContent = '分類儲存失敗'; }
    });
    tr.querySelector('[data-act="check"]').addEventListener('click', async () => {
      err.textContent = '';
      const parsed = parseAmountInput(tr.querySelector('[data-f="amount"]').value);
      if (!parsed.valid) { err.textContent = '金額格式不正確'; return; }
      const categoryId = cat.value === '' ? null : Number(cat.value);
      await api.auditEdit(id, { amount: parsed.value, category_id: categoryId }, sid);
      const { status } = await api.auditCheck(id, sid);
      if (status === 200) tr.remove(); else err.textContent = '打勾失敗';
    });
  });
}
```

- [ ] **Step 8: dev manager 登入（手動 e2e 用）**

`app/dev/routes.py`：加一個 manager 捷徑（沿用既有 `_blocked()`）：
```python
@dev_bp.get("/login-manager")
def login_manager():
    if _blocked():
        return jsonify(status="not_found"), 404
    store = Store.query.filter_by(code="E2E").first()
    if store is None:
        store = Store(name="測試門市", code="E2E"); db.session.add(store); db.session.commit()
    mgr = User.query.filter_by(name="測試主管").first()
    if mgr is None:
        mgr = User(name="測試主管", role="manager", store_id=store.id)
        mgr.set_password("1234"); db.session.add(mgr); db.session.commit()
    session["user_id"] = mgr.id
    session.permanent = True
    session["_last_request_at"] = int(time.time())
    return redirect("/")
```

- [ ] **Step 9: bump sw.js + 跑前端測試 + 後端回歸**

`app/static/sw.js`：`CACHE_NAME` 版本 +1（如 `calc-v15` → `calc-v16`）。
Run:
```bash
node --test tests/js/*.mjs && python3 -m pytest -q
```
Expected: PASS

- [ ] **Step 10: commit**

```bash
git add app/static/js/ app/dev/routes.py app/static/sw.js tests/js/audit.mjs
git commit -m "feat(audit-ui): 後台稽核分頁-待稽核子區(清單/改/打勾) + dev manager 登入"
```

---

### Task 10: 前端稽核分頁 — 當日總表子區 + 交班/結班/取消

**Files:**
- Modify: `app/static/js/admin_audit.js`（`renderSummary` + 交班/結班/取消按鈕）
- Modify: `app/static/sw.js`（bump CACHE_NAME）
- Test: 手動 e2e（`/dev/login-manager` → 稽核分頁）

**Interfaces:**
- Consumes: `api.auditSummary/auditHandover/auditUndo`
- Produces: `renderSummary(body, sid)`；待稽核子區底部交班/結班/取消按鈕

- [ ] **Step 1: 實作 renderSummary**

`app/static/js/admin_audit.js` 加：
```javascript
async function renderSummary(body, sid) {
  body.innerHTML = '載入中…';
  const { data } = await api.auditSummary(sid);
  const rows = (data.intervals || []).map((it) =>
    `<tr><td>第 ${it.seq} 班${it.type === 'day' ? '（結班）' : ''}</td>
         <td>${new Date(it.closed_at).toLocaleString('zh-TW', { timeZone: 'Asia/Taipei' })}</td>
         <td>${it.count} 筆</td><td>${formatMoney(it.subtotal)}</td></tr>`).join('');
  const open = data.open || { subtotal: 0, count: 0 };
  body.innerHTML = `
    <table class="pd-table"><thead><tr><th>區間</th><th>交班時間</th><th>筆數</th><th>小計</th></tr></thead>
    <tbody>
      ${rows}
      <tr class="au-open"><td>當前未歸班</td><td>—</td><td>${open.count} 筆</td><td>${formatMoney(open.subtotal)}</td></tr>
    </tbody>
    <tfoot><tr><td colspan="3"><b>當日總額</b></td><td><b>${formatMoney(data.day_total)}</b></td></tr></tfoot>
    </table>`;
}
```

- [ ] **Step 2: 待稽核子區加交班/結班/取消按鈕**

`renderPending` 結尾（表格之後）補上按鈕列與 handler：
```javascript
  const bar = document.createElement('div');
  bar.className = 'au-actionbar';
  bar.innerHTML = `
    <button class="modal-btn" id="au-shift" type="button">交班</button>
    <button class="modal-btn" id="au-day" type="button">結班</button>
    <button class="modal-btn secondary" id="au-undo" type="button">取消上一次</button>
    <span class="pd-row-err" id="au-bar-err"></span>`;
  body.appendChild(bar);
  const barErr = bar.querySelector('#au-bar-err');
  const doClose = async (type) => {
    barErr.textContent = '';
    const { status, data } = await api.auditHandover(type, sid);
    barErr.textContent = status === 200
      ? `已${type === 'day' ? '結班' : '交班'}（${data.count} 筆）` : '沒有可歸班的單據';
  };
  bar.querySelector('#au-shift').addEventListener('click', () => doClose('shift'));
  bar.querySelector('#au-day').addEventListener('click', () => doClose('day'));
  bar.querySelector('#au-undo').addEventListener('click', async () => {
    barErr.textContent = '';
    const { status, data } = await api.auditUndo(sid);
    barErr.textContent = status === 200 ? `已取消，退回 ${data.reopened} 筆` : '沒有可取消的交班';
  });
```

- [ ] **Step 3: bump sw.js**

`app/static/sw.js`：`CACHE_NAME` 版本 +1。

- [ ] **Step 4: 手動 e2e 驗證**

啟動：
```bash
set -a; . ./.env; set +a
FLASK_APP=wsgi.py python3 -m flask run --port 5001 --no-reload
```
瀏覽器開 `http://127.0.0.1:5001/dev/login-manager` → 後台「稽核」分頁：
- 待稽核清單顯示（需先有 submitted 單：可用 `/dev/login-test` 拍幾張送出，或直接 seed）
- 改金額/分類、打勾 → 該列消失
- 交班 → 提示 N 筆；當日總表出現該區間
- 結班 → 封當日；取消上一次 → 退回
Expected：流程順、數字正確。

- [ ] **Step 5: 全套回歸 + commit**

Run:
```bash
node --test tests/js/*.mjs && python3 -m pytest -q
```
Expected: PASS
```bash
git add app/static/js/admin_audit.js app/static/sw.js
git commit -m "feat(audit-ui): 當日總表子區 + 交班/結班/取消按鈕"
```

---

## Self-Review 檢核（已於撰寫後執行）

- **Spec coverage**：狀態機(Task1,6)、audit_log 全程(Task2,3,5,6)、稽核改+打勾(Task5,6)、交班/結班/取消(Task7)、當日總表(Task8)、待稽核分組小計(Task4)、UI 兩子區(Task9,10)、per-store scope(Task4 helper 貫穿)、員工端連動(Task3) 皆有對應 task。
- **範圍外**（reject/void/核銷/月結）未納入，符合 spec。
- **型別一致**：`_scope_store_id`/`_load_in_scope`/`snapshot`/`log_edit_if_changed`/`record_check`/`compute_summary`/`renderAudit`/`formatMoney` 跨 task 命名一致。
- **無 placeholder**：各 step 附實際程式碼與指令。
- **注意事項**：Task1 migration 若 SQLite batch FK 需手動包 `batch_alter_table`；Task9 `admin_api.js` 的 `jsonFetch` 命名以該檔實際為準；Task6/8 測試 `_seed`/`_client` 可自 Task5 copy（各測試檔自帶，避免跨檔相依）。
