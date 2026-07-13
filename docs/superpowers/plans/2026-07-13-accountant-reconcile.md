# 會計核銷 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓會計以獨立角色跨店逐筆核銷主管稽核過的雜支單，支援退回／改金額科目／批次核銷／自己新增單，並補上員工備註欄與負數金額。

**Architecture:** 沿用現有 `expenses.status` 狀態機（往前接 `reconciled` / `rejected`）與 `audit_log` 軌跡表，不另開核銷表。會計端是一個新的 Flask blueprint `app/reconcile/`（跨店，不吃 `_scope_store_id`）＋前端一個新面板 `reconcile.js`。備註欄 `note` 是門市內部欄位，**會計端序列化白名單一律不含它**。

**Tech Stack:** Python 3 / Flask / SQLAlchemy / Alembic / SQLite(dev) / 原生 ES module 前端 / pytest / node --test

設計來源：`docs/superpowers/specs/2026-07-13-accountant-reconcile-monthly-design.md`

## Global Constraints

- 時間：DB 存 UTC，UI 一律台灣時間（UTC+8）。既有 pattern：`_TW = timezone(timedelta(hours=8))`（`app/audit/routes.py:15`）。
- 營業日 08:00 分界，`compute_business_date()`（`app/expenses/logic.py:20`）。
- 燈號不新增第三套：會計端沿用 `audit_light()`（`app/expenses/logic.py:53`），唯讀。
- **會計端任何回傳都不得含 `note`**（安全需求，要有測試守住）。
- **負數金額全端合法、金額 0 一律拒絕**；負數在 UI 以紅字顯示。
- 前端不輪詢；狀態全進 DB（不得用 module-level dict）。
- 本計畫**不含**期間／挪下期／封月／月報表——那些在第二份計畫（依賴 `accounting_periods` 表）。核銷清單先不出現「挪下期」按鈕。
- 每個 task 跑 `python3 -m pytest -q` 全綠才 commit。

---

### Task 1: Expense 模型欄位與狀態值

**Files:**
- Modify: `app/models/expense.py:7`（`STATUSES`）、`app/models/expense.py:41-47`（欄位區）
- Create: `migrations/versions/<hash>_expenses_reconcile_fields.py`（由 alembic 產生）
- Test: `tests/test_reconcile_model.py`

**Interfaces:**
- Produces: `Expense.STATUSES` 含 `"reconciled"` / `"rejected"`；欄位 `Expense.reconciled_by:int|None`、`Expense.reconciled_at:datetime|None`、`Expense.reject_reason:str|None`、`Expense.note:str|None`。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_reconcile_model.py
from datetime import datetime, timezone
from app.extensions import db
from app.models import Expense, Store, User


def _seed(app):
    with app.app_context():
        s = Store(name="A店", code="A")
        db.session.add(s); db.session.commit()
        u = User(name="員工", role="employee", store_id=s.id)
        db.session.add(u); db.session.commit()
        return s.id, u.id


def test_expense_has_reconcile_fields(app):
    sid, uid = _seed(app)
    with app.app_context():
        e = Expense(
            store_id=sid, created_by=uid, status="reconciled",
            created_at=datetime.now(timezone.utc),
            reconciled_by=uid, reconciled_at=datetime.now(timezone.utc),
            reject_reason=None, note="老闆交代的",
        )
        db.session.add(e); db.session.commit()
        got = db.session.get(Expense, e.id)
        assert got.status == "reconciled"
        assert got.reconciled_by == uid
        assert got.note == "老闆交代的"


def test_statuses_include_reconciled_and_rejected():
    assert "reconciled" in Expense.STATUSES
    assert "rejected" in Expense.STATUSES
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_reconcile_model.py -q`
Expected: FAIL — `TypeError: 'reconciled_by' is an invalid keyword argument for Expense`

- [ ] **Step 3: 改 model**

`app/models/expense.py` — `STATUSES` 改成：

```python
    STATUSES = ("pending_ocr", "draft", "submitted", "audited", "reconciled", "rejected")
```

在 `last_modified_fields` 那一行之後加欄位：

```python
    # 會計核銷
    reconciled_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reconciled_at = db.Column(db.DateTime(timezone=True), nullable=True)
    reject_reason = db.Column(db.String(200), nullable=True)  # 會計退回原因
    note = db.Column(db.String(200), nullable=True)  # 員工備註；門市內部欄位，會計看不到
```

- [ ] **Step 4: 產生 migration**

Run: `FLASK_APP=wsgi.py SECRET_KEY=dev python3 -m flask db migrate -m "expenses reconcile fields"`
接著**打開產生的檔案確認**只有 `add_column` 四欄（`reconciled_by`, `reconciled_at`, `reject_reason`, `note`），沒有誤刪其他欄位；有多餘 drop 就手動移掉。
Run: `FLASK_APP=wsgi.py SECRET_KEY=dev python3 -m flask db upgrade`

- [ ] **Step 5: 跑測試確認通過**

Run: `python3 -m pytest -q`
Expected: 全綠

- [ ] **Step 6: Commit**

```bash
git add app/models/expense.py migrations/versions tests/test_reconcile_model.py
git commit -m "feat(expense): 新增核銷欄位(reconciled_by/at, reject_reason)與員工備註 note"
```

---

### Task 2: 金額規則——允許負數、拒絕 0

**Files:**
- Create: `app/expenses/amount.py`
- Modify: `app/expenses/routes.py:164-172`（PATCH）、`app/expenses/routes.py:263-270`（no-receipt）、`app/audit/routes.py:98-103`（主管 edit）
- Test: `tests/test_amount_rules.py`

**Interfaces:**
- Produces: `parse_amount(raw) -> tuple[Decimal|None, str|None]`——回 `(金額, 錯誤碼)`。合法回 `(Decimal, None)`；`0` 回 `(None, "amount_zero")`；不能轉數字回 `(None, "amount_invalid")`；`None` 回 `(None, None)`（代表「沒帶這個欄位／清空」，由呼叫端決定要不要擋）。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_amount_rules.py
from decimal import Decimal
from app.expenses.amount import parse_amount


def test_positive():
    assert parse_amount(120) == (Decimal("120"), None)


def test_negative_allowed():
    assert parse_amount(-50) == (Decimal("-50"), None)


def test_negative_string_allowed():
    assert parse_amount("-50.25") == (Decimal("-50.25"), None)


def test_zero_rejected():
    assert parse_amount(0) == (None, "amount_zero")
    assert parse_amount("0.00") == (None, "amount_zero")


def test_garbage_rejected():
    assert parse_amount("abc") == (None, "amount_invalid")


def test_none_is_passthrough():
    assert parse_amount(None) == (None, None)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_amount_rules.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.expenses.amount'`

- [ ] **Step 3: 實作**

```python
# app/expenses/amount.py
"""金額解析：負數合法（無單據建帳、會計沖銷可能是負的），0 一律不合法。"""
from decimal import Decimal, InvalidOperation


def parse_amount(raw):
    """回 (Decimal|None, error_code|None)。error_code: amount_zero / amount_invalid。"""
    if raw is None:
        return None, None
    try:
        val = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None, "amount_invalid"
    if val == 0:
        return None, "amount_zero"
    return val, None
```

- [ ] **Step 4: 三個呼叫端改用它**

`app/expenses/routes.py` PATCH（原本 164-172 那段）改成：

```python
    if "amount" in data:
        new_amount, err = parse_amount(data["amount"])
        if err:
            return jsonify(status="error", message=err), 400
        new_parse_ok = new_amount is not None
        if new_amount != e.amount or new_parse_ok != e.amount_parse_ok:
            e.amount = new_amount
            e.amount_parse_ok = new_parse_ok
            changed = True
```
（`changed` 沿用原本那段的變數名；若原碼用別的名字，照原碼改，不要新增變數。）

`app/expenses/routes.py` no-receipt（原本 263-270）改成：

```python
    amount, err = parse_amount(data.get("amount"))
    if err or amount is None:
        return jsonify(status="error", message=err or "amount required"), 400
```

`app/audit/routes.py` 主管 edit（原本 98-103）改成：

```python
    if "amount" in data:
        new_amount, err = parse_amount(data["amount"])
        if err:
            return jsonify(status="error", message=err), 400
        e.amount = new_amount
        e.amount_parse_ok = new_amount is not None
```

兩個檔案頂部各加 `from app.expenses.amount import parse_amount`。

- [ ] **Step 5: 補 API 層測試**

```python
# 追加到 tests/test_amount_rules.py
def test_no_receipt_rejects_zero(client, app):
    # 依 tests/test_expenses_no_receipt.py 既有的登入 helper 建立員工 session
    # （照該檔案現成的 fixture / login 流程；不要另創一套）
    r = client.post("/expenses/no-receipt", json={"amount": 0, "summary": "x"})
    assert r.status_code == 400
    assert r.get_json()["message"] == "amount_zero"


def test_no_receipt_accepts_negative(client, app):
    r = client.post("/expenses/no-receipt", json={"amount": -300, "summary": "退款"})
    assert r.status_code == 200
```

先打開 `tests/test_expenses_no_receipt.py`（或現有無單據測試檔）看它怎麼登入，照抄那個流程再填進上面兩個測試。

- [ ] **Step 6: 跑測試**

Run: `python3 -m pytest -q`
Expected: 全綠

- [ ] **Step 7: Commit**

```bash
git add app/expenses/amount.py app/expenses/routes.py app/audit/routes.py tests/test_amount_rules.py
git commit -m "feat(expense): 金額允許負數、拒絕 0（集中到 parse_amount）"
```

---

### Task 3: 備註欄後端——員工寫入、送出後鎖

**Files:**
- Modify: `app/expenses/routes.py`（PATCH 加 `note`；`no-receipt` 加 `note`；submit 後拒改）
- Modify: `app/expenses/serialize.py`（回傳 `note`）
- Test: `tests/test_expense_note.py`

**Interfaces:**
- Consumes: Task 1 的 `Expense.note`。
- Produces: 員工端 `PATCH /expenses/<id>` 接受 `{"note": str}`，只在 `status == "draft"` 可寫；`GET /expenses/pending`、`/expenses/<id>` 的回傳含 `note`。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_expense_note.py
# 登入/建單 helper 照 tests/test_expenses_patch.py（或現有 expenses 測試檔）的既有寫法


def test_employee_can_set_note_on_draft(client, app, draft_expense_id):
    r = client.patch(f"/expenses/{draft_expense_id}", json={"note": "老闆請客"})
    assert r.status_code == 200
    r2 = client.get(f"/expenses/{draft_expense_id}")
    assert r2.get_json()["expense"]["note"] == "老闆請客"


def test_note_locked_after_submit(client, app, draft_expense_id):
    client.patch(f"/expenses/{draft_expense_id}", json={"note": "原始說法"})
    client.post(f"/expenses/{draft_expense_id}/submit")
    r = client.patch(f"/expenses/{draft_expense_id}", json={"note": "改口"})
    assert r.status_code == 409
    r2 = client.get(f"/expenses/{draft_expense_id}")
    assert r2.get_json()["expense"]["note"] == "原始說法"


def test_note_max_200(client, app, draft_expense_id):
    r = client.patch(f"/expenses/{draft_expense_id}", json={"note": "x" * 201})
    assert r.status_code == 400
```

`draft_expense_id` fixture 自己在檔案裡寫：建店＋員工＋登入＋建一張 draft（照現有 expenses 測試的做法）。

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_expense_note.py -q`
Expected: FAIL（`note` 不被接受 / 回傳沒有 note 欄位）

- [ ] **Step 3: 實作**

`app/expenses/routes.py` 的 PATCH handler，在既有欄位處理之後加：

```python
    if "note" in data:
        if e.status != "draft":
            return jsonify(status="error", message="note_locked"), 409
        note = (data["note"] or "").strip()
        if len(note) > 200:
            return jsonify(status="error", message="note_too_long"), 400
        e.note = note or None
```

`no-receipt` 建單時帶入（在 `Expense(...)` 的參數裡加）：

```python
        note=((data.get("note") or "").strip() or None),
```

`app/expenses/serialize.py` 的 `d` dict 加一行：

```python
        "note": e.note,
```

- [ ] **Step 4: 跑測試**

Run: `python3 -m pytest -q`
Expected: 全綠

- [ ] **Step 5: Commit**

```bash
git add app/expenses/routes.py app/expenses/serialize.py tests/test_expense_note.py
git commit -m "feat(expense): 員工備註欄（draft 可寫、送出後鎖）"
```

---

### Task 4: 主管／經理可改備註（留 log）

**Files:**
- Modify: `app/audit/routes.py:83-107`（`edit`）、`app/audit/log.py`（快照納入 note）、`app/audit/serialize.py`（回傳 note）
- Test: `tests/test_audit_note.py`

**Interfaces:**
- Consumes: Task 3 的 `Expense.note`。
- Produces: `PATCH /audit/<id>` 接受 `{"note": str}`；`app/audit/log.py` 的 `snapshot()` / `log_edit_if_changed()` 快照多一個 `note` key。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_audit_note.py
# 登入 helper 照 tests/test_audit_edit.py 現成寫法


def test_manager_can_edit_note(client, app, submitted_expense_id):
    r = client.patch(f"/audit/{submitted_expense_id}", json={"note": "主管補充"})
    assert r.status_code == 200
    r2 = client.get("/audit/pending")
    item = r2.get_json()["groups"][0]["items"][0]
    assert item["note"] == "主管補充"


def test_note_edit_writes_audit_log(client, app, submitted_expense_id):
    client.patch(f"/audit/{submitted_expense_id}", json={"note": "主管補充"})
    r = client.get(f"/expenses/{submitted_expense_id}/logs")
    actions = [x["action"] for x in r.get_json()["logs"]]
    assert "edit" in actions
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_audit_note.py -q`
Expected: FAIL（`note` 被忽略；回傳沒有 note）

- [ ] **Step 3: log 快照納入 note**

`app/audit/log.py` 的 `_amt_cat` 改成：

```python
def _amt_cat(expense):
    return {
        "amount": float(expense.amount) if expense.amount is not None else None,
        "category_id": expense.category_id,
        "note": expense.note,
    }
```

`log_edit_if_changed` 的 `changed` 判斷維持只看 amount / category（`last_modified_fields` 語意不變，備註改動不算「改過金額分類」，不該把主管端燈號弄紅），但 before/after JSON 會自動含 note——軌跡看得到。

- [ ] **Step 4: audit edit 接受 note**

`app/audit/routes.py` 的 `edit()`，在 amount 處理之後加：

```python
    if "note" in data:
        note = (data["note"] or "").strip()
        if len(note) > 200:
            return jsonify(status="error", message="note_too_long"), 400
        e.note = note or None
```

`app/audit/serialize.py` 的 `serialize_audit_item` 加：

```python
    d["note"] = e.note
```

- [ ] **Step 5: 跑測試**

Run: `python3 -m pytest -q`
Expected: 全綠

- [ ] **Step 6: Commit**

```bash
git add app/audit/routes.py app/audit/log.py app/audit/serialize.py tests/test_audit_note.py
git commit -m "feat(audit): 主管/經理可改備註並留軌跡"
```

---

### Task 5: 稽核清單納入被退回的單

**Files:**
- Modify: `app/audit/routes.py:37-61`（`pending`）、`app/audit/routes.py:83-93`（`edit` 的可編輯狀態）、`app/audit/routes.py:110-126`（`check`）
- Test: `tests/test_audit_rejected.py`

**Interfaces:**
- Produces: `GET /audit/pending` 同時回 `submitted` 與 `rejected`；每筆多兩個欄位 `is_rejected:bool`、`reject_reason:str|None`。`POST /audit/<id>/check` 允許 `submitted` 或 `rejected` → `audited`（重送後 `reject_reason` 清空）。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_audit_rejected.py
def test_rejected_shows_in_pending(client, app, rejected_expense_id):
    r = client.get("/audit/pending")
    items = [i for g in r.get_json()["groups"] for i in g["items"]]
    hit = [i for i in items if i["id"] == rejected_expense_id]
    assert hit and hit[0]["is_rejected"] is True
    assert hit[0]["reject_reason"] == "金額與照片不符"


def test_manager_recheck_clears_reject(client, app, rejected_expense_id):
    r = client.post(f"/audit/{rejected_expense_id}/check")
    assert r.status_code == 200
    from app.models import Expense
    from app.extensions import db
    with app.app_context():
        e = db.session.get(Expense, rejected_expense_id)
        assert e.status == "audited"
        assert e.reject_reason is None
```

`rejected_expense_id` fixture：直接在 app_context 裡把一張單的 `status` 設成 `"rejected"`、`reject_reason` 設成 `"金額與照片不符"`（這個階段還沒有會計端 API，直接寫 DB 就好）。

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_audit_rejected.py -q`
Expected: FAIL — pending 撈不到 rejected 的單

- [ ] **Step 3: 實作**

`app/audit/routes.py` 的 `pending()` 過濾條件改成：

```python
            .filter(Expense.store_id == store_id,
                    Expense.status.in_(["submitted", "rejected"]))
```

`edit()` 的可編輯判斷改成：

```python
    if e.status not in ("submitted", "rejected"):
        return jsonify(status="error", message="not editable"), 409
```

`check()` 改成：

```python
    if e.status not in ("submitted", "rejected"):
        return jsonify(status="error", message="not checkable"), 409
    e.status = "audited"
    e.reject_reason = None          # 重送後清掉退回原因
    e.audited_by = current_user().id
    e.audited_at = datetime.now(timezone.utc)
```

`app/audit/serialize.py` 加兩行：

```python
    d["is_rejected"] = (e.status == "rejected")
    d["reject_reason"] = e.reject_reason
```

- [ ] **Step 4: 跑測試**

Run: `python3 -m pytest -q`
Expected: 全綠（注意既有 `tests/test_audit_*.py` 不能被打壞）

- [ ] **Step 5: Commit**

```bash
git add app/audit/routes.py app/audit/serialize.py tests/test_audit_rejected.py
git commit -m "feat(audit): 被會計退回的單回到稽核清單，重送即回 audited"
```

---

### Task 6: 會計 blueprint ＋ 待核銷清單

**Files:**
- Create: `app/reconcile/__init__.py`、`app/reconcile/routes.py`、`app/reconcile/serialize.py`
- Modify: `app/__init__.py:51`（註冊 blueprint）
- Test: `tests/test_reconcile_list.py`

**Interfaces:**
- Produces: blueprint `reconcile_bp`（`url_prefix="/reconcile"`）。
  `GET /reconcile/pending?status=&store_id=&category_id=&date_from=&date_to=` → `{"status":"ok","groups":[{"business_date":"2026-07-01","subtotal":1234.0,"items":[...]}],"total":{"reconciled":0.0,"pending":1234.0,"count":3}}`
  `serialize_reconcile_item(e, storage, names, cats) -> dict`——**白名單**，欄位固定為：`id, doc_no, business_date, store_id, store_name, light, summary, category_id, category_name, amount, thumb_url, image_url, status, reject_reason, is_no_receipt, created_by_name`。**不含 `note`、不含 `last_modified_*`、不含 `is_modified_by_manager`。**

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_reconcile_list.py
def test_accountant_sees_audited_across_stores(client, app, two_store_audited):
    login_accountant(client, app)
    r = client.get("/reconcile/pending")
    assert r.status_code == 200
    items = [i for g in r.get_json()["groups"] for i in g["items"]]
    assert {i["store_id"] for i in items} == set(two_store_audited["store_ids"])


def test_submitted_not_visible_to_accountant(client, app, two_store_audited):
    login_accountant(client, app)
    r = client.get("/reconcile/pending")
    items = [i for g in r.get_json()["groups"] for i in g["items"]]
    assert two_store_audited["submitted_id"] not in [i["id"] for i in items]


def test_note_never_leaks_to_accountant(client, app, two_store_audited):
    login_accountant(client, app)
    r = client.get("/reconcile/pending")
    items = [i for g in r.get_json()["groups"] for i in g["items"]]
    assert items
    for i in items:
        assert "note" not in i


def test_manager_forbidden(client, app, two_store_audited):
    login_manager(client, app)
    r = client.get("/reconcile/pending")
    assert r.status_code == 403


def test_totals_signed(client, app, two_store_audited):
    # fixture 內含一張 -100 的單
    login_accountant(client, app)
    t = client.get("/reconcile/pending").get_json()["total"]
    assert t["pending"] == two_store_audited["expected_pending_sum"]  # 有負數扣掉
```

fixture `two_store_audited`：建兩間店、各一張 `audited` 單（其中一張金額 -100）、外加一張 `submitted` 單；`login_accountant` / `login_manager` 用 session transaction 直接塞 `user_id`（照 `tests/test_audit_*.py` 現成的登入 helper）。

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_reconcile_list.py -q`
Expected: FAIL — 404（路由不存在）

- [ ] **Step 3: 建 blueprint**

```python
# app/reconcile/__init__.py
from flask import Blueprint

reconcile_bp = Blueprint("reconcile", __name__, url_prefix="/reconcile")

from app.reconcile import routes  # noqa: E402,F401
```

```python
# app/reconcile/serialize.py
"""會計端序列化：白名單。務必不含 note（門市內部備註，會計看不到）。"""
from flask import current_app
from app.expenses.logic import audit_light, format_doc_no


def serialize_reconcile_item(e, storage, store_name_by_id, cat_name_by_id, user_name_by_id):
    return {
        "id": e.id,
        "doc_no": format_doc_no(e.business_date, e.day_seq),
        "business_date": e.business_date.isoformat() if e.business_date else None,
        "store_id": e.store_id,
        "store_name": store_name_by_id.get(e.store_id),
        "light": audit_light(
            e.amount_parse_ok, e.is_modified_by_user, e.is_no_receipt,
            e.ocr_is_handwritten, e.ocr_confidence,
            green_threshold=current_app.config.get("GREEN_THRESHOLD", 0.85),
        ),
        "summary": e.summary,
        "category_id": e.category_id,
        "category_name": cat_name_by_id.get(e.category_id),
        "amount": float(e.amount) if e.amount is not None else None,
        "thumb_url": storage.presigned_url(e.thumb_key) if e.thumb_key else None,
        "image_url": storage.presigned_url(e.image_key) if e.image_key else None,
        "status": e.status,
        "reject_reason": e.reject_reason,
        "is_no_receipt": e.is_no_receipt,
        "created_by_name": user_name_by_id.get(e.created_by),
    }
```

```python
# app/reconcile/routes.py
from datetime import date

from flask import request, jsonify

from app.extensions import db
from app.models import Expense, Store, Category, User
from app.auth.decorators import role_required
from app.storage.r2 import get_storage
from app.reconcile import reconcile_bp
from app.reconcile.serialize import serialize_reconcile_item

VISIBLE = ("audited", "reconciled", "rejected")   # 會計看得到的狀態（submitted 不給看）


def _maps(rows):
    sids = {e.store_id for e in rows}
    cids = {e.category_id for e in rows if e.category_id}
    uids = {e.created_by for e in rows}
    stores = {s.id: s.name for s in Store.query.filter(Store.id.in_(sids)).all()} if sids else {}
    cats = {c.id: c.name for c in Category.query.filter(Category.id.in_(cids)).all()} if cids else {}
    users = {u.id: u.name for u in User.query.filter(User.id.in_(uids)).all()} if uids else {}
    return stores, cats, users


def _parse_date(raw):
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


@reconcile_bp.get("/pending")
@role_required("accountant")
def pending():
    q = Expense.query.filter(Expense.status.in_(VISIBLE))

    st = request.args.get("status")
    if st in VISIBLE:
        q = q.filter(Expense.status == st)

    sid = request.args.get("store_id")
    if sid:
        q = q.filter(Expense.store_id == int(sid))

    cid = request.args.get("category_id")
    if cid:
        q = q.filter(Expense.category_id == int(cid))

    d_from = _parse_date(request.args.get("date_from"))
    if d_from:
        q = q.filter(Expense.business_date >= d_from)
    d_to = _parse_date(request.args.get("date_to"))
    if d_to:
        q = q.filter(Expense.business_date <= d_to)

    rows = q.order_by(Expense.business_date.asc(), Expense.store_id.asc(),
                      Expense.day_seq.asc()).all()

    storage = get_storage()
    stores, cats, users = _maps(rows)

    groups, by_date = [], {}
    for e in rows:
        key = e.business_date.isoformat() if e.business_date else "none"
        by_date.setdefault(key, []).append(e)
    for bd in sorted(by_date):
        items = by_date[bd]
        groups.append({
            "business_date": bd,
            "subtotal": sum(float(x.amount) for x in items if x.amount is not None),
            "items": [serialize_reconcile_item(x, storage, stores, cats, users) for x in items],
        })

    total = {
        "reconciled": sum(float(e.amount) for e in rows
                          if e.status == "reconciled" and e.amount is not None),
        "pending": sum(float(e.amount) for e in rows
                       if e.status in ("audited", "rejected") and e.amount is not None),
        "count": len(rows),
    }
    return jsonify(status="ok", groups=groups, total=total)
```

`app/__init__.py`，在 audit blueprint 之後加：

```python
    from app.reconcile import reconcile_bp
    app.register_blueprint(reconcile_bp)
```

- [ ] **Step 4: 跑測試**

Run: `python3 -m pytest -q`
Expected: 全綠

- [ ] **Step 5: Commit**

```bash
git add app/reconcile app/__init__.py tests/test_reconcile_list.py
git commit -m "feat(reconcile): 會計待核銷清單(跨店/篩選/日小計/合計，白名單不含 note)"
```

---

### Task 7: 核銷（含批次）

**Files:**
- Modify: `app/reconcile/routes.py`、`app/audit/log.py`（加 `record_reconcile`）
- Test: `tests/test_reconcile_approve.py`

**Interfaces:**
- Consumes: Task 6 的 `reconcile_bp`。
- Produces:
  `POST /reconcile/<int:eid>/approve` → 200 `{"status":"ok"}`；單不是 `audited` 回 409 `{"message":"not_reconcilable"}`。
  `POST /reconcile/approve-batch` body `{"ids":[1,2,3]}` → 200 `{"status":"ok","approved":[1,2],"skipped":[3]}`（`skipped`＝狀態不對的）。
  `app/audit/log.py::record_reconcile(expense, actor_user_id)`。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_reconcile_approve.py
def test_approve_audited(client, app, audited_id):
    login_accountant(client, app)
    r = client.post(f"/reconcile/{audited_id}/approve")
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, audited_id)
        assert e.status == "reconciled"
        assert e.reconciled_by is not None
        assert e.reconciled_at is not None


def test_approve_twice_is_conflict(client, app, audited_id):
    login_accountant(client, app)
    client.post(f"/reconcile/{audited_id}/approve")
    r = client.post(f"/reconcile/{audited_id}/approve")
    assert r.status_code == 409
    assert r.get_json()["message"] == "not_reconcilable"


def test_cannot_approve_submitted(client, app, submitted_id):
    login_accountant(client, app)
    r = client.post(f"/reconcile/{submitted_id}/approve")
    assert r.status_code == 409


def test_approve_writes_log(client, app, audited_id):
    login_accountant(client, app)
    client.post(f"/reconcile/{audited_id}/approve")
    with app.app_context():
        actions = [l.action for l in AuditLog.query.filter_by(expense_id=audited_id).all()]
        assert "reconcile" in actions


def test_batch_approve_partial(client, app, audited_id, submitted_id):
    login_accountant(client, app)
    r = client.post("/reconcile/approve-batch", json={"ids": [audited_id, submitted_id]})
    body = r.get_json()
    assert body["approved"] == [audited_id]
    assert body["skipped"] == [submitted_id]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_reconcile_approve.py -q`
Expected: FAIL — 404

- [ ] **Step 3: log helper**

`app/audit/log.py` 追加：

```python
def record_reconcile(expense, actor_user_id):
    db.session.add(AuditLog(
        expense_id=expense.id, actor_user_id=actor_user_id, action="reconcile",
        before_json=None, after_json={"status": "reconciled"},
        ts=datetime.now(timezone.utc),
    ))
```

- [ ] **Step 4: 路由實作**

`app/reconcile/routes.py` 追加（頂部 import 補 `from datetime import datetime, timezone`、`from app.auth.decorators import current_user`、`from app.audit.log import record_reconcile`）：

```python
def _approve_one(e, actor_id):
    """狀態必須是 audited。回 True 表示這次真的核銷成功。"""
    updated = (Expense.query
               .filter(Expense.id == e.id, Expense.status == "audited")
               .update({"status": "reconciled",
                        "reconciled_by": actor_id,
                        "reconciled_at": datetime.now(timezone.utc)},
                       synchronize_session=False))
    if not updated:
        return False                      # 併發：別人先核掉了
    db.session.refresh(e)
    record_reconcile(e, actor_id)
    return True


@reconcile_bp.post("/<int:eid>/approve")
@role_required("accountant")
def approve(eid):
    e = db.session.get(Expense, eid)
    if e is None:
        return jsonify(status="error", message="not found"), 404
    if not _approve_one(e, current_user().id):
        db.session.rollback()
        return jsonify(status="error", message="not_reconcilable"), 409
    db.session.commit()
    return jsonify(status="ok")


@reconcile_bp.post("/approve-batch")
@role_required("accountant")
def approve_batch():
    ids = (request.get_json(silent=True) or {}).get("ids") or []
    if not isinstance(ids, list):
        return jsonify(status="error", message="ids required"), 400
    actor_id = current_user().id
    approved, skipped = [], []
    for eid in ids:
        e = db.session.get(Expense, eid)
        if e is not None and _approve_one(e, actor_id):
            approved.append(eid)
        else:
            skipped.append(eid)
    db.session.commit()
    return jsonify(status="ok", approved=approved, skipped=skipped)
```

- [ ] **Step 5: 跑測試**

Run: `python3 -m pytest -q`
Expected: 全綠

- [ ] **Step 6: Commit**

```bash
git add app/reconcile/routes.py app/audit/log.py tests/test_reconcile_approve.py
git commit -m "feat(reconcile): 逐筆與批次核銷(條件更新防併發，留軌跡)"
```

---

### Task 8: 退回

**Files:**
- Modify: `app/reconcile/routes.py`、`app/audit/log.py`（加 `record_reject`）
- Test: `tests/test_reconcile_reject.py`

**Interfaces:**
- Produces: `POST /reconcile/<int:eid>/reject` body `{"reason": str}` → 200；原因空白回 400 `{"message":"reason_required"}`；超過 200 字回 400 `{"message":"reason_too_long"}`；狀態不是 `audited` / `reconciled` 回 409 `{"message":"not_rejectable"}`。
  `app/audit/log.py::record_reject(expense, actor_user_id, reason)`。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_reconcile_reject.py
def test_reject_audited(client, app, audited_id):
    login_accountant(client, app)
    r = client.post(f"/reconcile/{audited_id}/reject", json={"reason": "金額與照片不符"})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, audited_id)
        assert e.status == "rejected"
        assert e.reject_reason == "金額與照片不符"


def test_reject_reconciled(client, app, reconciled_id):
    """已核銷的單要改帳 → 會計退回，主管改完重送。"""
    login_accountant(client, app)
    r = client.post(f"/reconcile/{reconciled_id}/reject", json={"reason": "科目錯了"})
    assert r.status_code == 200


def test_reason_required(client, app, audited_id):
    login_accountant(client, app)
    r = client.post(f"/reconcile/{audited_id}/reject", json={"reason": "   "})
    assert r.status_code == 400
    assert r.get_json()["message"] == "reason_required"


def test_cannot_reject_submitted(client, app, submitted_id):
    login_accountant(client, app)
    r = client.post(f"/reconcile/{submitted_id}/reject", json={"reason": "x"})
    assert r.status_code == 409


def test_reject_never_shows_to_employee(client, app, audited_id):
    login_accountant(client, app)
    client.post(f"/reconcile/{audited_id}/reject", json={"reason": "金額不符"})
    login_employee(client, app)
    r = client.get("/expenses/submitted")     # 員工複查端點
    body = r.get_json()
    dumped = str(body)
    assert "金額不符" not in dumped
    assert "rejected" not in dumped
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_reconcile_reject.py -q`
Expected: FAIL — 404

- [ ] **Step 3: log helper**

`app/audit/log.py` 追加：

```python
def record_reject(expense, actor_user_id, reason):
    db.session.add(AuditLog(
        expense_id=expense.id, actor_user_id=actor_user_id, action="reject",
        before_json={"status": expense.status},
        after_json={"status": "rejected", "reason": reason},
        ts=datetime.now(timezone.utc),
    ))
```

- [ ] **Step 4: 路由實作**

```python
@reconcile_bp.post("/<int:eid>/reject")
@role_required("accountant")
def reject(eid):
    e = db.session.get(Expense, eid)
    if e is None:
        return jsonify(status="error", message="not found"), 404
    reason = ((request.get_json(silent=True) or {}).get("reason") or "").strip()
    if not reason:
        return jsonify(status="error", message="reason_required"), 400
    if len(reason) > 200:
        return jsonify(status="error", message="reason_too_long"), 400
    if e.status not in ("audited", "reconciled"):
        return jsonify(status="error", message="not_rejectable"), 409
    record_reject(e, current_user().id, reason)
    e.status = "rejected"
    e.reject_reason = reason
    e.reconciled_by = None            # 退回即撤銷核銷
    e.reconciled_at = None
    db.session.commit()
    return jsonify(status="ok")
```

（`record_reject` 要在改 status **之前**呼叫，before_json 才記得到原狀態。）

- [ ] **Step 5: 跑測試**

Run: `python3 -m pytest -q`
Expected: 全綠。特別確認 `test_reject_never_shows_to_employee` 通過——員工複查端點是白名單回傳，本來就不該漏 `status` / `reject_reason`。若它失敗，去 `app/expenses/routes.py` 的 `/expenses/submitted`（350 行附近的 `keep` tuple）確認白名單。

- [ ] **Step 6: Commit**

```bash
git add app/reconcile/routes.py app/audit/log.py tests/test_reconcile_reject.py
git commit -m "feat(reconcile): 會計退回(原因必填，已核銷亦可退，員工端不外洩)"
```

---

### Task 9: 會計改金額／科目

**Files:**
- Modify: `app/reconcile/routes.py`
- Test: `tests/test_reconcile_edit.py`

**Interfaces:**
- Produces: `PATCH /reconcile/<int:eid>` body `{"amount": num, "category_id": int}` → 200；金額 0 回 400 `amount_zero`；狀態不是 `audited` / `reconciled` 回 409 `not_editable`。改動寫 `audit_log`（action=`edit`），**不動燈號**（不設 `is_modified_by_user` / `is_modified_by_manager`）。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_reconcile_edit.py
def test_accountant_edits_amount_and_category(client, app, audited_id, cat_id):
    login_accountant(client, app)
    r = client.patch(f"/reconcile/{audited_id}", json={"amount": -250, "category_id": cat_id})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, audited_id)
        assert float(e.amount) == -250.0
        assert e.category_id == cat_id


def test_edit_writes_log(client, app, audited_id):
    login_accountant(client, app)
    client.patch(f"/reconcile/{audited_id}", json={"amount": 999})
    with app.app_context():
        actions = [l.action for l in AuditLog.query.filter_by(expense_id=audited_id).all()]
        assert "edit" in actions


def test_edit_does_not_change_light(client, app, audited_id):
    login_accountant(client, app)
    before = client.get("/reconcile/pending").get_json()
    light_before = [i for g in before["groups"] for i in g["items"] if i["id"] == audited_id][0]["light"]
    client.patch(f"/reconcile/{audited_id}", json={"amount": 777})
    after = client.get("/reconcile/pending").get_json()
    light_after = [i for g in after["groups"] for i in g["items"] if i["id"] == audited_id][0]["light"]
    assert light_after == light_before


def test_edit_zero_rejected(client, app, audited_id):
    login_accountant(client, app)
    r = client.patch(f"/reconcile/{audited_id}", json={"amount": 0})
    assert r.status_code == 400
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_reconcile_edit.py -q`
Expected: FAIL — 405/404

- [ ] **Step 3: 實作**

`app/reconcile/routes.py` 追加（頂部 import 補 `from app.audit.log import snapshot, log_edit_if_changed`、`from app.expenses.amount import parse_amount`、`from app.expenses.tasks import _valid_category_id`）：

```python
@reconcile_bp.patch("/<int:eid>")
@role_required("accountant")
def edit(eid):
    e = db.session.get(Expense, eid)
    if e is None:
        return jsonify(status="error", message="not found"), 404
    if e.status not in ("audited", "reconciled"):
        return jsonify(status="error", message="not_editable"), 409
    data = request.get_json(silent=True) or {}
    before = snapshot(e)
    if "amount" in data:
        amount, err = parse_amount(data["amount"])
        if err:
            return jsonify(status="error", message=err), 400
        e.amount = amount
        e.amount_parse_ok = amount is not None
    if "category_id" in data:
        e.category_id = _valid_category_id(data["category_id"])
    # 會計改動只留軌跡，不碰 is_modified_by_user / is_modified_by_manager —— 燈號語意不變
    log_edit_if_changed(e, current_user().id, before)
    db.session.commit()
    return jsonify(status="ok")
```

- [ ] **Step 4: 跑測試**

Run: `python3 -m pytest -q`
Expected: 全綠

- [ ] **Step 5: Commit**

```bash
git add app/reconcile/routes.py tests/test_reconcile_edit.py
git commit -m "feat(reconcile): 會計就地改金額/科目(留軌跡，不動燈號)"
```

---

### Task 10: 會計新增單據

**Files:**
- Modify: `app/reconcile/routes.py`
- Test: `tests/test_reconcile_manual.py`

**Interfaces:**
- Produces: `POST /reconcile/manual` body `{"store_id":int,"business_date":"YYYY-MM-DD","summary":str,"amount":num,"category_id":int}` → 200 `{"status":"ok","id":N}`。建出來的單：`status="reconciled"`、`is_no_receipt=True`、`has no image`、`created_by`＝會計、`reconciled_by`＝會計、`note=None`、`day_seq` 依當店當日流水號指派。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_reconcile_manual.py
def test_manual_creates_reconciled(client, app, store_id, cat_id):
    login_accountant(client, app)
    r = client.post("/reconcile/manual", json={
        "store_id": store_id, "business_date": "2026-07-01",
        "summary": "補水電", "amount": 1200, "category_id": cat_id,
    })
    assert r.status_code == 200
    eid = r.get_json()["id"]
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "reconciled"
        assert e.is_no_receipt is True
        assert e.reconciled_by is not None
        assert e.note is None
        assert e.day_seq is not None


def test_manual_allows_negative(client, app, store_id, cat_id):
    login_accountant(client, app)
    r = client.post("/reconcile/manual", json={
        "store_id": store_id, "business_date": "2026-07-01",
        "summary": "退款", "amount": -500, "category_id": cat_id,
    })
    assert r.status_code == 200


def test_manual_requires_valid_store(client, app, cat_id):
    login_accountant(client, app)
    r = client.post("/reconcile/manual", json={
        "store_id": 99999, "business_date": "2026-07-01",
        "summary": "x", "amount": 100, "category_id": cat_id,
    })
    assert r.status_code == 400


def test_manual_shows_in_list_as_reconciled(client, app, store_id, cat_id):
    login_accountant(client, app)
    client.post("/reconcile/manual", json={
        "store_id": store_id, "business_date": "2026-07-01",
        "summary": "補水電", "amount": 1200, "category_id": cat_id,
    })
    body = client.get("/reconcile/pending?status=reconciled").get_json()
    items = [i for g in body["groups"] for i in g["items"]]
    assert any(i["summary"] == "補水電" for i in items)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_reconcile_manual.py -q`
Expected: FAIL — 404

- [ ] **Step 3: 實作**

先確認既有的 `day_seq` 指派邏輯在哪（`app/expenses/routes.py` 的 submit handler，搜 `day_seq`），**重用同一個 helper**；若那段是行內程式碼，把它抽成 `app/expenses/logic.py::next_day_seq(store_id, business_date) -> int` 再兩邊共用（順手把 submit 改成呼叫它，跑一次 `python3 -m pytest -q` 確認沒破）。

```python
@reconcile_bp.post("/manual")
@role_required("accountant")
def manual():
    data = request.get_json(silent=True) or {}
    store = db.session.get(Store, data.get("store_id") or 0)
    if store is None:
        return jsonify(status="error", message="store required"), 400
    bd = _parse_date(data.get("business_date"))
    if bd is None:
        return jsonify(status="error", message="business_date required"), 400
    amount, err = parse_amount(data.get("amount"))
    if err or amount is None:
        return jsonify(status="error", message=err or "amount required"), 400

    actor = current_user()
    now = datetime.now(timezone.utc)
    e = Expense(
        store_id=store.id, created_by=actor.id, status="reconciled",
        created_at=now, submitted_at=now, business_date=bd,
        day_seq=next_day_seq(store.id, bd),
        summary=(data.get("summary") or "").strip() or None,
        category_id=_valid_category_id(data.get("category_id")),
        amount=amount, amount_parse_ok=True,
        is_no_receipt=True, is_modified_by_user=True,
        audited_by=actor.id, audited_at=now,      # 不回頭走主管打勾
        reconciled_by=actor.id, reconciled_at=now,
    )
    db.session.add(e)
    db.session.flush()
    record_reconcile(e, actor.id)
    db.session.commit()
    return jsonify(status="ok", id=e.id)
```

- [ ] **Step 4: 跑測試**

Run: `python3 -m pytest -q`
Expected: 全綠

- [ ] **Step 5: Commit**

```bash
git add app/reconcile/routes.py app/expenses/logic.py app/expenses/routes.py tests/test_reconcile_manual.py
git commit -m "feat(reconcile): 會計新增單據(直接已核銷、無單據、可負數)"
```

---

### Task 11: 主管端逾期未打勾提醒

**Files:**
- Modify: `app/audit/routes.py`
- Test: `tests/test_audit_overdue.py`

**Interfaces:**
- Produces: `GET /audit/overdue` → `{"status":"ok","count":N,"oldest_business_date":"YYYY-MM-DD"|null}`。定義：`status == "submitted"` 且 `business_date < 今天的營業日`（今天的營業日＝`compute_business_date(now_utc)`）。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_audit_overdue.py
def test_today_submitted_not_overdue(client, app, submitted_today_id):
    login_manager(client, app)
    body = client.get("/audit/overdue").get_json()
    assert body["count"] == 0


def test_yesterday_submitted_is_overdue(client, app, submitted_yesterday_id):
    login_manager(client, app)
    body = client.get("/audit/overdue").get_json()
    assert body["count"] == 1
    assert body["oldest_business_date"] is not None


def test_audited_not_overdue(client, app, audited_yesterday_id):
    login_manager(client, app)
    body = client.get("/audit/overdue").get_json()
    assert body["count"] == 0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_audit_overdue.py -q`
Expected: FAIL — 404

- [ ] **Step 3: 實作**

```python
@audit_bp.get("/overdue")
@role_required("manager", "super_admin")
def overdue():
    from app.expenses.logic import compute_business_date
    store_id, err = _scope_store_id()
    if err:
        return err
    today_bd = compute_business_date(datetime.now(timezone.utc))
    rows = (Expense.query
            .filter(Expense.store_id == store_id,
                    Expense.status == "submitted",
                    Expense.business_date < today_bd)
            .order_by(Expense.business_date.asc()).all())
    oldest = rows[0].business_date.isoformat() if rows else None
    return jsonify(status="ok", count=len(rows), oldest_business_date=oldest)
```

- [ ] **Step 4: 跑測試**

Run: `python3 -m pytest -q`
Expected: 全綠

- [ ] **Step 5: Commit**

```bash
git add app/audit/routes.py tests/test_audit_overdue.py
git commit -m "feat(audit): 逾期未打勾提醒端點"
```

---

### Task 12: 會計面板前端（清單／篩選／合計／負數紅字）

**Files:**
- Create: `app/static/js/reconcile_api.js`、`app/static/js/reconcile.js`
- Modify: `app/static/js/main.js:159-172`（角色分流）、`app/static/css/`（新增 `.rc-*` 樣式，檔名照現有 css 結構）、`app/static/sw.js`（bump cache 版號）
- Test: `tests/js/reconcile.test.mjs`

**Interfaces:**
- Consumes: Task 6–10 的端點。
- Produces: `showReconcilePanel(identity)`（`reconcile.js` 具名匯出）；純邏輯函式 `fmtAmount(n) -> {text, negative}`（金額格式化＋負數旗標）、`groupTotals(groups) -> {reconciled, pending, count}`，兩者從 `reconcile.js` 匯出供 node 測試。

- [ ] **Step 1: 寫失敗的前端純邏輯測試**

```javascript
// tests/js/reconcile.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fmtAmount } from '../../app/static/js/reconcile.js';

test('負數帶 negative 旗標', () => {
  const r = fmtAmount(-1250.5);
  assert.equal(r.negative, true);
  assert.equal(r.text, '-1,250.5');
});

test('正數不帶旗標', () => {
  const r = fmtAmount(1250);
  assert.equal(r.negative, false);
  assert.equal(r.text, '1,250');
});

test('零視為非負', () => {
  assert.equal(fmtAmount(0).negative, false);
});

test('null 顯示破折號', () => {
  assert.equal(fmtAmount(null).text, '—');
});
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `node --test tests/js/reconcile.test.mjs`
Expected: FAIL — 找不到模組

- [ ] **Step 3: 寫 API 模組**

```javascript
// app/static/js/reconcile_api.js
async function j(url, opts) {
  const r = await fetch(url, opts);
  let data = {};
  try { data = await r.json(); } catch (e) { /* 非 JSON：留空物件 */ }
  return { status: r.status, data };
}

export const rcApi = {
  pending: (q) => j('/reconcile/pending' + (q ? '?' + new URLSearchParams(q) : '')),
  approve: (id) => j(`/reconcile/${id}/approve`, { method: 'POST' }),
  approveBatch: (ids) => j('/reconcile/approve-batch', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids }),
  }),
  reject: (id, reason) => j(`/reconcile/${id}/reject`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  }),
  edit: (id, patch) => j(`/reconcile/${id}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  }),
  manual: (payload) => j('/reconcile/manual', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  stores: () => j('/admin/stores'),
  categories: () => j('/expenses/categories'),
};
```

- [ ] **Step 4: 寫面板（先讓純邏輯函式存在，測試轉綠）**

```javascript
// app/static/js/reconcile.js
import { rcApi } from './reconcile_api.js';
import { escapeHtml } from './admin_util.js';

/** 金額格式化：回 {text, negative}。負數要紅字。 */
export function fmtAmount(n) {
  if (n === null || n === undefined) return { text: '—', negative: false };
  const num = Number(n);
  return {
    text: num.toLocaleString('en-US', { maximumFractionDigits: 2 }),
    negative: num < 0,
  };
}

/** 從 groups 算合計（後端也算，這支供前端即時篩選後重算用）。 */
export function groupTotals(groups) {
  let reconciled = 0, pending = 0, count = 0;
  groups.forEach((g) => g.items.forEach((i) => {
    count += 1;
    const a = Number(i.amount || 0);
    if (i.status === 'reconciled') reconciled += a;
    else pending += a;
  }));
  return { reconciled, pending, count };
}

function amountCell(n) {
  const { text, negative } = fmtAmount(n);
  return `<span class="rc-amt${negative ? ' rc-neg' : ''}">${text}</span>`;
}

export async function showReconcilePanel(identity) {
  // shell（tabs：核銷 / 我的密碼）＋ 篩選列＋合計列＋依營業日分組的表格
  // 版面照 app/static/js/admin.js 的 .admin-panel / .ap-tabs / .ap-body 結構，
  // class 前綴用 rc-，避免跟 ap-* 撞。
  // 每列動作：核銷、退回（prompt 原因，必填）、就地改金額/科目。
  // 表頭一顆「全選」checkbox → 「一鍵核銷勾選的」按鈕呼叫 rcApi.approveBatch。
  // 一顆「新增單據」→ 表單（店/日期/摘要/金額/科目）→ rcApi.manual。
  // 金額欄一律用 amountCell() 產生，負數自動紅字。
  // 清單不顯示 note（後端也不會回）。
}
```

實作 `showReconcilePanel` 的完整版面：照 `app/static/js/admin.js:36-57`（shell）與 `app/static/js/admin_audit.js`（清單＋逐列動作＋lightbox 看原圖）的既有寫法照抄結構，只換 API 與欄位。

- [ ] **Step 5: 跑前端測試**

Run: `node --test tests/js/reconcile.test.mjs`
Expected: PASS

- [ ] **Step 6: main.js 角色分流**

`app/static/js/main.js` 頂部加 `import { showReconcilePanel } from './reconcile.js';`，並把 159-172 那段的分流改成：

```javascript
      if (cfg.identity.role === 'accountant') {
        showReconcilePanel(cfg.identity);
      } else if (cfg.identity.role === 'manager' || cfg.identity.role === 'super_admin') {
        showAdminPanel(cfg.identity);
      } else {
        showAppView(cfg.identity);
      }
```

同樣的分流也要補在 `app/static/js/auth.js` 登入成功之後的導向（搜 `showAdminPanel`，照同樣三分支改）。

- [ ] **Step 7: CSS 與 sw 版號**

在現有 css 檔加 `.rc-*` 樣式（表格、篩選列、合計列），其中負數紅字：

```css
.rc-neg { color: #c62828; }
```

`app/static/sw.js` 的 cache 版號 bump（現在是 `calc-v37` 之類，往上加一號），否則會計面板的新 js 不會被拉到。

- [ ] **Step 8: 手動驗證**

Run: `FLASK_APP=wsgi.py SECRET_KEY=dev APP_ENV=dev E2E_LOGIN_BYPASS=1 python3 -m flask run --port 5001`
用 `/dev/login-test`（員工）建幾張單 → `/dev/login-manager` 打勾 → 需要一個會計捷徑：在 `app/dev/routes.py` 加 `/dev/login-accountant`（照 `login_manager` 複製，role 改 `accountant`、`store_id=None`），登入後確認：跨店都看得到、負數紅字、批次核銷、退回、改金額。

- [ ] **Step 9: Commit**

```bash
git add app/static/js/reconcile.js app/static/js/reconcile_api.js app/static/js/main.js app/static/js/auth.js app/static/css app/static/sw.js app/dev/routes.py tests/js/reconcile.test.mjs
git commit -m "feat(reconcile-ui): 會計面板(清單/篩選/合計/批次核銷/退回/新增單，負數紅字)"
```

---

### Task 13: 備註欄前端 ＋ 逾期提醒橫幅

**Files:**
- Modify: `app/static/js/pending.js`（員工暫存區：備註輸入）、`app/static/js/review.js`（員工複查：唯讀顯示備註）、`app/static/js/admin_audit.js`（主管：備註可改 ＋ 逾期橫幅 ＋ 被退回的單標示）、`app/static/sw.js`（版號）
- Test: 手動驗證（純 DOM 行為，無獨立純邏輯可測）

**Interfaces:**
- Consumes: Task 3／4／5／11 的端點與欄位（`note`、`is_rejected`、`reject_reason`、`GET /audit/overdue`）。

- [ ] **Step 1: 員工暫存區加備註輸入**

`app/static/js/pending.js`：每張 draft 卡片加一個 `<input class="pd-note" maxlength="200" placeholder="備註（可留空）">`，`change` 時 `PATCH /expenses/<id> {note}`。送出後的單不再顯示輸入框（改唯讀文字）。

- [ ] **Step 2: 員工複查顯示備註（唯讀）**

`app/static/js/review.js`：每列多顯示 `note`（有值才顯示）。不顯示誰改過。

- [ ] **Step 3: 主管稽核區——備註可改、退回標示、逾期橫幅**

`app/static/js/admin_audit.js`：
1. 每列備註改成可編輯輸入框，`change` → `PATCH /audit/<id> {note}`。
2. `is_rejected` 為 true 的列加 class `ap-row-rejected`（底色紅），並顯示「會計退回：<reject_reason>」。
3. 清單載入時同時打 `GET /audit/overdue`，`count > 0` 就在清單上方插入橫幅：`有 N 筆 <oldest_business_date> 以前的單還沒打勾`。

CSS 補：

```css
.ap-row-rejected { background: #ffebee; }
.ap-overdue { background: #fff3e0; border-left: 4px solid #ef6c00; padding: 8px 12px; margin-bottom: 8px; }
```

- [ ] **Step 4: sw 版號 bump**

`app/static/sw.js` 再加一號。

- [ ] **Step 5: 手動驗證**

跑起 server：員工建單填備註 → 送出後改不動（輸入框消失）→ 主管稽核區看得到備註且改得動 → 會計端**看不到備註** → 會計退回 → 主管清單那列變紅並顯示原因 → 主管重新打勾 → 會計端又看得到。

- [ ] **Step 6: Commit**

```bash
git add app/static/js/pending.js app/static/js/review.js app/static/js/admin_audit.js app/static/css app/static/sw.js
git commit -m "feat(ui): 備註欄(員工填/主管改)、退回標示、逾期未打勾橫幅"
```

---

### Task 14: 端到端驗收與收尾

**Files:**
- Test: `tests/test_reconcile_flow.py`

- [ ] **Step 1: 寫整條流程的測試**

```python
# tests/test_reconcile_flow.py
def test_full_cycle(client, app, store_id, cat_id):
    """員工送出 → 主管打勾 → 會計退回 → 主管改完重送 → 會計核銷。"""
    eid = employee_submit(client, app, store_id, amount=500, note="老闆交代")

    login_manager(client, app)
    assert client.post(f"/audit/{eid}/check").status_code == 200

    login_accountant(client, app)
    assert client.post(f"/reconcile/{eid}/reject", json={"reason": "金額不符"}).status_code == 200

    login_manager(client, app)
    pending = client.get("/audit/pending").get_json()
    row = [i for g in pending["groups"] for i in g["items"] if i["id"] == eid][0]
    assert row["is_rejected"] is True
    assert row["note"] == "老闆交代"
    client.patch(f"/audit/{eid}", json={"amount": 450})
    assert client.post(f"/audit/{eid}/check").status_code == 200

    login_accountant(client, app)
    body = client.get("/reconcile/pending").get_json()
    row = [i for g in body["groups"] for i in g["items"] if i["id"] == eid][0]
    assert row["status"] == "audited"
    assert "note" not in row                 # 會計永遠看不到備註
    assert client.post(f"/reconcile/{eid}/approve").status_code == 200

    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "reconciled"
        assert e.reject_reason is None or e.status == "reconciled"
```

- [ ] **Step 2: 跑全部測試**

Run: `python3 -m pytest -q && node --test tests/js/*.mjs`
Expected: 全綠

- [ ] **Step 3: 手動驗收（照 Task 12 Step 8 的流程完整跑一次）**

- [ ] **Step 4: Commit**

```bash
git add tests/test_reconcile_flow.py
git commit -m "test(reconcile): 送出→打勾→退回→重送→核銷 端到端"
```

---

## 下一份計畫（不在本計畫範圍）

`accounting_periods` 表、月結日設定、認列期間與「挪下期」、寬限期與封月、月報表、上期未處理單清單。等這份驗收完再寫——因為「挪下期」按鈕依賴期間表，硬塞進來會讓核銷這段沒辦法獨立驗收。
