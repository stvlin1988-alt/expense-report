# 月結（會計期間 ＋ 封月 ＋ 月報表）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在既有「會計核銷」之上加上會計期間（月結週期）、寬限期與自動/手動封月、認列期間歸屬與「挪下期」、月報表交叉表，以及經理端的月結日設定。

**Architecture:** 新增 `accounting_periods`（會計期間，由設定推導＋自動延展）與 `app_settings`（key/value 設定）兩張表，`expenses` 加 `period_id`。期間邊界由「月結日 + 鎖定偏移」純函式算出（半開區間、營業日 08:00 分界沿用 `compute_business_date`）。封月**不用背景排程**：任何請求碰到某期時同步檢查 `now >= lock_at`，成立就在同一交易裡把已打勾未核完的單挪到下一期、沒打勾的留原期、把該期設 `closed`；以資料庫層條件更新確保只封一次。任何寫入若目標單所屬期已 `closed` 一律擋掉。月報表是分店×科目大類的交叉表（大類可展開細類），會計與經理都看得到。

**Tech Stack:** Python / Flask、SQLAlchemy、Alembic（`op.batch_alter_table`）、pytest；前端 vanilla ES module + `node --test`（純邏輯）。

## Global Constraints

- **時間**：DB 一律存 UTC（`DateTime(timezone=True)`）；任何 UI 顯示轉台灣時間（`TW_TZ = timezone(timedelta(hours=8))`，在 `app/expenses/logic.py`）。日期界線用營業日 08:00 分界（`compute_business_date`）。
- **serialize 白名單鐵律**：會計端任何 API 回傳**永遠不含 `note`**（門市內部備註）。既有守門測試 `tests/test_reconcile_list.py::test_note_never_leaks_to_accountant` 必須維持綠。新增的會計端回傳（月報表、上期未處理單、挪期後回傳）同樣不得含 `note`。
- **狀態集合單一定義**：「主管已打勾／已認列」用 `Expense.CHECKED_STATUSES = ("audited","reconciled","rejected")`（`app/models/expense.py:15`），不得再散落硬編字面值。
- **角色對應**（`User.ROLES = ("employee","manager","accountant","super_admin")`）：spec 的**主管**＝`manager`（本店 scope、打勾稽核）、**會計**＝`accountant`（跨店、核銷/封月）、**經理**＝`super_admin`（看月報表，**不碰核銷**）。gating 用既有 `role_required(...)`（`app/auth/decorators.py`）。
- **月結設定權限（2026-07-15 user 修正，覆蓋 spec §6 原表）**：月結設定（月結日 `period_close_day`、鎖定偏移 `period_lock_offset_hours`、農曆年調期間 `end_date`）**由會計（accountant）編輯**；**經理（super_admin）只有觀看權限（唯讀）**。月報表：會計＋經理都看得到（不變）。
- **金額**：允許負數、拒絕 0，集中走 `parse_amount`（`app/expenses/amount.py`）；所有加總用有號數，不得用 `abs`/`max(0,x)`。
- **併發**：狀態轉移與封月一律以資料庫層條件更新（`WHERE ...`）擋競態，不靠先讀後寫。
- **前端不輪詢**、狀態全進 DB；改前端要 bump `app/static/sw.js` 的 `CACHE_NAME`。
- **migration head 現況＝`a1b2c3d4e5f6`**（`a1b2c3d4e5f6_expenses_resubmitted_at.py`）。新 migration 依序接在其後。
- 測試：後端 `python3 -m pytest -q`；前端純邏輯 `node --test tests/js/*.mjs`。
- 分支流程：本計畫從 `master` 開分支 `feat/monthly-closing` 執行；測完、user 明說才 merge，**不 push**。

---

## File Structure

**新增**
- `app/models/app_setting.py` — `AppSetting` key/value 設定 model
- `app/models/accounting_period.py` — `AccountingPeriod` 會計期間 model
- `app/periods/__init__.py` — periods 套件（無 blueprint，純服務）
- `app/periods/settings.py` — 設定讀寫 helper（含 typed getter 與預設值）
- `app/periods/service.py` — 期間邊界純函式、`get_or_create_period`、`effective_status`、`maybe_autoclose`、`assert_period_writable`、`move_to_next_period`、`backfill_periods`
- `app/periods/routes.py` — 經理端月結日設定 API（`period_bp`，掛在 `/api/periods`）
- `app/reports/__init__.py` + `app/reports/routes.py` — 月報表 API（`report_bp`，掛在 `/api/reports`）
- `app/reports/service.py` — 月報表交叉表聚合純函式
- `app/static/js/month_report.js` — 月報表前端（會計/經理共用）
- `app/static/js/periods_api.js`、`app/static/js/reports_api.js` — 前端 fetch 封裝
- 對應 `migrations/versions/*.py` 與 `tests/test_*.py`、`tests/js/*.mjs`

**修改**
- `app/models/__init__.py` — 匯出新 model
- `app/__init__.py` — 註冊 `period_bp`、`report_bp`
- `app/expenses/routes.py` — submit 指派 period + closed gate
- `app/reconcile/routes.py` — pending 加 period 篩選、挪期/封月/上期未處理單端點、各寫入前 closed gate
- `app/reconcile/serialize.py` — 加 `period_id`/`period_label`（維持不含 `note`）
- `app/audit/routes.py` — check 前 closed gate
- `app/audit/log.py` — 新增 `record_move_period`、`record_period_close`
- `app/static/js/reconcile.js` + `reconcile_api.js` — period 篩選、挪期、提前封月、上期未處理單、掛月報表
- `app/static/js/admin.js` — 經理「月結」分頁（月結日設定 + 月報表）
- `app/static/sw.js` — bump `CACHE_NAME`

---

## Phase A — 資料層

### Task 1: `AppSetting` 設定表 ＋ 讀寫 helper

**Files:**
- Create: `app/models/app_setting.py`
- Create: `app/periods/__init__.py`
- Create: `app/periods/settings.py`
- Modify: `app/models/__init__.py`
- Create: `migrations/versions/<rev>_app_settings.py`
- Test: `tests/test_app_settings.py`

**Interfaces:**
- Produces: `AppSetting(key: str PK, value: str)`；`get_setting(key)->str|None`、`set_setting(key, value)`、`get_close_day()->int`、`get_lock_offset_hours()->int`（`app/periods/settings.py`）。預設 `period_close_day="1"`、`period_lock_offset_hours="36"`。

- [ ] **Step 1: 寫 model**

`app/models/app_setting.py`：
```python
from app.extensions import db


class AppSetting(db.Model):
    """全站 key/value 設定（目前僅月結日與鎖定偏移；只有經理能改）。"""
    __tablename__ = "app_settings"

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.String(255), nullable=False)
```

`app/periods/__init__.py`：空檔（套件標記）。

- [ ] **Step 2: 匯出 model**

`app/models/__init__.py` 加：
```python
from app.models.app_setting import AppSetting
```
並把 `"AppSetting"` 加進 `__all__`。

- [ ] **Step 3: 寫 settings helper**

`app/periods/settings.py`：
```python
from app.extensions import db
from app.models import AppSetting

DEFAULTS = {"period_close_day": "1", "period_lock_offset_hours": "36"}


def get_setting(key):
    row = db.session.get(AppSetting, key)
    if row is not None:
        return row.value
    return DEFAULTS.get(key)


def set_setting(key, value):
    row = db.session.get(AppSetting, key)
    if row is not None:
        row.value = str(value)
    else:
        db.session.add(AppSetting(key=key, value=str(value)))


def get_close_day():
    return int(get_setting("period_close_day"))


def get_lock_offset_hours():
    return int(get_setting("period_lock_offset_hours"))
```

- [ ] **Step 4: 寫失敗測試**

`tests/test_app_settings.py`：
```python
from app.periods.settings import (get_setting, set_setting,
                                   get_close_day, get_lock_offset_hours)


def test_defaults_when_unset(app):
    with app.app_context():
        assert get_close_day() == 1
        assert get_lock_offset_hours() == 36
        assert get_setting("nonexistent") is None


def test_set_then_get(app, db_session):
    with app.app_context():
        set_setting("period_close_day", "5")
        db_session.commit()
        assert get_close_day() == 5
        set_setting("period_close_day", "10")   # 覆寫既有
        db_session.commit()
        assert get_close_day() == 10
```
（`app`、`db_session` fixture 見 `tests/conftest.py`；若 fixture 名稱不同，比照既有 `tests/test_reconcile_model.py` 用法對齊。）

- [ ] **Step 5: 產生 migration**

Run: `FLASK_APP=wsgi.py python3 -m flask db migrate -m "app_settings"`
檢查產出的 `upgrade()` 只 `create_table('app_settings', ...)`、`down_revision = 'a1b2c3d4e5f6'`。若 autogenerate 夾帶不相干 diff（如既有表的 index），手動刪掉只留 app_settings。

- [ ] **Step 6: 跑 migration + 測試**

Run: `FLASK_APP=wsgi.py python3 -m flask db upgrade && python3 -m pytest tests/test_app_settings.py -q`
Expected: upgrade 成功、2 passed。

- [ ] **Step 7: 驗證 migration 語法**（config 檔鐵律）

Run: `python3 -c "import ast,glob; [ast.parse(open(f).read()) for f in glob.glob('migrations/versions/*app_settings*.py')]; print('ok')"`
Expected: `ok`

- [ ] **Step 8: Commit**
```bash
git add app/models/app_setting.py app/models/__init__.py app/periods/ tests/test_app_settings.py migrations/versions/*app_settings*.py
git commit -m "feat(periods): app_settings key/value table + typed settings helper"
```

---

### Task 2: `AccountingPeriod` 表 ＋ `expenses.period_id`

**Files:**
- Create: `app/models/accounting_period.py`
- Modify: `app/models/__init__.py`
- Modify: `app/models/expense.py`
- Create: `migrations/versions/<rev>_accounting_periods.py`
- Test: `tests/test_period_model.py`

**Interfaces:**
- Produces: `AccountingPeriod(id, label:str, start_date:date, end_date:date, lock_at:datetime(tz), status:str, closed_by:int?, closed_at:datetime?(tz))`；`status` 只持久化 `"open"`/`"closed"`（`"closing"` 為衍生，見 Task 4）。`Expense.period_id`（FK→accounting_periods，nullable，index）。

- [ ] **Step 1: 寫 model**

`app/models/accounting_period.py`：
```python
from app.extensions import db


class AccountingPeriod(db.Model):
    """會計期間。由「月結日 + 鎖定偏移」設定推導、首尾相接、自動延展。
    status 持久值只有 open / closed；closing（寬限期）由 now 相對 end_date/lock_at 衍生。"""
    __tablename__ = "accounting_periods"

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(16), nullable=False)          # 依起始日所屬月份命名，如 2026-01
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False, index=True)
    lock_at = db.Column(db.DateTime(timezone=True), nullable=False)
    status = db.Column(db.String(16), nullable=False, default="open")
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    closed_at = db.Column(db.DateTime(timezone=True), nullable=True)
```

- [ ] **Step 2: 匯出 + 加 expenses 欄位**

`app/models/__init__.py` 加 `from app.models.accounting_period import AccountingPeriod` 與 `__all__` 補 `"AccountingPeriod"`。

`app/models/expense.py`，在會計核銷欄位區塊之後（`note` 欄位附近）加：
```python
    period_id = db.Column(db.Integer, db.ForeignKey("accounting_periods.id"),
                          nullable=True, index=True)  # 認列期間；預設依 business_date 落期，挪下期即改此欄
```

- [ ] **Step 3: 寫失敗測試**

`tests/test_period_model.py`：
```python
from datetime import date, datetime, timezone
from app.models import AccountingPeriod, Expense


def test_create_period_and_link_expense(app, db_session):
    with app.app_context():
        p = AccountingPeriod(
            label="2026-01", start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
            lock_at=datetime(2026, 2, 2, 4, 0, tzinfo=timezone.utc), status="open")
        db_session.add(p)
        db_session.flush()
        assert p.id is not None
        assert p.status == "open"
        assert p.closed_by is None
```

- [ ] **Step 4: migration**

Run: `FLASK_APP=wsgi.py python3 -m flask db migrate -m "accounting_periods + expenses.period_id"`
檢查 `upgrade()`：`create_table('accounting_periods', ...)` ＋ `batch_alter_table('expenses')` add `period_id` 與 FK；`down_revision` 接 Task 1 的 rev。清掉不相干 diff。

- [ ] **Step 5: upgrade + 測試 + 語法驗證**

Run:
```bash
FLASK_APP=wsgi.py python3 -m flask db upgrade
python3 -m pytest tests/test_period_model.py -q
python3 -c "import ast,glob; [ast.parse(open(f).read()) for f in glob.glob('migrations/versions/*accounting_period*.py')]; print('ok')"
```
Expected: upgrade 成功、1 passed、`ok`。

- [ ] **Step 6: Commit**
```bash
git add app/models/accounting_period.py app/models/__init__.py app/models/expense.py tests/test_period_model.py migrations/versions/*accounting_period*.py
git commit -m "feat(periods): accounting_periods table + expenses.period_id"
```

---

## Phase B — 期間服務（純邏輯）

### Task 3: 期間邊界數學（半開區間、月結日、lock_at）

**Files:**
- Modify: `app/periods/service.py`（新建）
- Test: `tests/test_period_bounds.py`

**Interfaces:**
- Produces:
  - `canonical_bounds(d: date, close_day: int) -> (start: date, end: date)` — d 所屬期間的起訖（半開：close_day 當天算新期起始，end 為下一個 close_day 前一天）。
  - `lock_at_for(next_start: date, offset_hours: int) -> datetime`（UTC，帶 tz）— next_start 台灣時間 00:00 起算 offset 小時。
  - `label_for(start: date) -> str` — `"YYYY-MM"`。

- [ ] **Step 1: 寫失敗測試**

`tests/test_period_bounds.py`：
```python
from datetime import date, timezone
from app.periods.service import canonical_bounds, lock_at_for, label_for


def test_close_day_1_january():
    start, end = canonical_bounds(date(2026, 1, 15), 1)
    assert start == date(2026, 1, 1)
    assert end == date(2026, 1, 31)


def test_close_day_1_boundary_is_new_period():
    # 1 號當天算「新期起始」，不屬於上一期
    start, end = canonical_bounds(date(2026, 2, 1), 1)
    assert start == date(2026, 2, 1)


def test_close_day_5_labels_by_start_month():
    start, end = canonical_bounds(date(2026, 1, 20), 5)
    assert start == date(2026, 1, 5)
    assert end == date(2026, 2, 4)
    assert label_for(start) == "2026-01"


def test_close_day_clamps_short_month():
    # close_day=31，2 月沒有 31 → clamp 到月底；期間首尾仍相接
    start, end = canonical_bounds(date(2026, 2, 10), 31)
    assert start == date(2026, 1, 31)
    assert end == date(2026, 2, 27)   # 下一個換期日 2/28（clamp）前一天


def test_lock_at_default_offset_is_next_day_noon_tw():
    # 2/1 00:00 台灣 + 36h = 2/2 12:00 台灣 = 2/2 04:00 UTC
    la = lock_at_for(date(2026, 2, 1), 36)
    assert la.astimezone(timezone.utc).isoformat() == "2026-02-02T04:00:00+00:00"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_period_bounds.py -q`
Expected: FAIL（`ModuleNotFoundError` 或 `ImportError`）。

- [ ] **Step 3: 實作**

`app/periods/service.py`：
```python
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from app.expenses.logic import TW_TZ


def _clamped(year, month, day):
    """該月第 day 天；月份不足（如 2/31）clamp 到月底。"""
    last = monthrange(year, month)[1]
    return date(year, month, min(day, last))


def _add_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _sub_month(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _period_start(d, close_day):
    """d 所屬期間起始（<= d 的最近換期日）。"""
    this_month = _clamped(d.year, d.month, close_day)
    if d >= this_month:
        return this_month
    y, m = _sub_month(d.year, d.month)
    return _clamped(y, m, close_day)


def canonical_bounds(d, close_day):
    start = _period_start(d, close_day)
    ny, nm = _add_month(start.year, start.month)
    next_start = _clamped(ny, nm, close_day)
    return start, next_start - timedelta(days=1)


def lock_at_for(next_start, offset_hours):
    local_midnight = datetime(next_start.year, next_start.month, next_start.day,
                              tzinfo=TW_TZ)
    return (local_midnight + timedelta(hours=offset_hours)).astimezone(timezone.utc)


def label_for(start):
    return f"{start.year:04d}-{start.month:02d}"
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_period_bounds.py -q`
Expected: 5 passed。

- [ ] **Step 5: Commit**
```bash
git add app/periods/service.py tests/test_period_bounds.py
git commit -m "feat(periods): canonical period boundary math + lock_at"
```

---

### Task 4: `get_or_create_period` ＋ `effective_status`

**Files:**
- Modify: `app/periods/service.py`
- Test: `tests/test_period_service.py`

**Interfaces:**
- Consumes: Task 3 的 `canonical_bounds`/`lock_at_for`/`label_for`；Task 1 的 `get_close_day`/`get_lock_offset_hours`。
- Produces:
  - `get_or_create_period(business_date: date) -> AccountingPeriod` — 找出含此日的期間；沒有就依設定建立（尊重既有相鄰期，不重疊）。呼叫端負責 commit。
  - `effective_status(period, now_utc: datetime) -> str` — `"closed"`（已持久封月）／`"open"`（今天台灣日期 <= end_date）／`"closing"`（已過 end_date、還沒到 lock_at）。

- [ ] **Step 1: 寫失敗測試**

`tests/test_period_service.py`：
```python
from datetime import date, datetime, timezone
from app.models import AccountingPeriod
from app.periods.service import get_or_create_period, effective_status


def test_get_or_create_creates_once(app, db_session):
    with app.app_context():
        p1 = get_or_create_period(date(2026, 1, 10))
        db_session.commit()
        p2 = get_or_create_period(date(2026, 1, 20))   # 同期
        assert p1.id == p2.id
        assert p1.label == "2026-01"
        assert p1.start_date == date(2026, 1, 1)
        assert p1.end_date == date(2026, 1, 31)
        assert AccountingPeriod.query.count() == 1


def test_get_or_create_next_month_is_new_period(app, db_session):
    with app.app_context():
        jan = get_or_create_period(date(2026, 1, 10)); db_session.commit()
        feb = get_or_create_period(date(2026, 2, 3)); db_session.commit()
        assert feb.id != jan.id
        assert feb.start_date == date(2026, 2, 1)      # 首尾相接


def test_effective_status_open_closing_closed(app, db_session):
    with app.app_context():
        p = get_or_create_period(date(2026, 1, 10)); db_session.commit()
        # 期間內
        assert effective_status(p, datetime(2026, 1, 15, 3, 0, tzinfo=timezone.utc)) == "open"
        # 已過 end_date、未到 lock_at（lock=2/2 04:00 UTC）
        assert effective_status(p, datetime(2026, 2, 1, 6, 0, tzinfo=timezone.utc)) == "closing"
        # 持久封月優先
        p.status = "closed"
        assert effective_status(p, datetime(2026, 1, 15, 3, 0, tzinfo=timezone.utc)) == "closed"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_period_service.py -q`
Expected: FAIL（ImportError）。

- [ ] **Step 3: 實作（追加到 `app/periods/service.py`）**
```python
from app.extensions import db
from app.models import AccountingPeriod
from app.periods.settings import get_close_day, get_lock_offset_hours


def get_or_create_period(business_date):
    p = (AccountingPeriod.query
         .filter(AccountingPeriod.start_date <= business_date,
                 AccountingPeriod.end_date >= business_date)
         .first())
    if p is not None:
        return p

    close_day = get_close_day()
    start, end = canonical_bounds(business_date, close_day)

    # 尊重既有相鄰期：經理可能手動延長過上一期 end_date，順延起始避免重疊/留洞。
    prev = (AccountingPeriod.query
            .filter(AccountingPeriod.start_date < start)
            .order_by(AccountingPeriod.start_date.desc())
            .first())
    if prev is not None and prev.end_date >= start:
        from datetime import timedelta
        start = prev.end_date + timedelta(days=1)

    from datetime import timedelta
    next_start = end + timedelta(days=1)
    p = AccountingPeriod(
        label=label_for(start), start_date=start, end_date=end,
        lock_at=lock_at_for(next_start, get_lock_offset_hours()), status="open")
    db.session.add(p)
    db.session.flush()
    return p


def effective_status(period, now_utc):
    if period.status == "closed":
        return "closed"
    today_tw = now_utc.astimezone(TW_TZ).date()
    if today_tw <= period.end_date:
        return "open"
    return "closing"
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_period_service.py -q`
Expected: 3 passed。

- [ ] **Step 5: Commit**
```bash
git add app/periods/service.py tests/test_period_service.py
git commit -m "feat(periods): get_or_create_period + derived effective_status"
```

---

## Phase C — 指派、封月閘、自動封月、回填

### Task 5: submit ／ 會計新增單 指派 `period_id`

**Files:**
- Modify: `app/expenses/routes.py`（submit）
- Modify: `app/reconcile/routes.py`（manual）
- Test: `tests/test_period_assign.py`

**Interfaces:**
- Consumes: `get_or_create_period`。
- Produces: submit 後 `expense.period_id` 指向 `business_date` 所屬期；會計 manual 建單同理（依 `business_date`）。

- [ ] **Step 1: 寫失敗測試**

`tests/test_period_assign.py`（比照 `tests/test_expense_submitted.py` 的登入/建單 helper；下方以既有 fixture 名意示，實作時對齊 conftest）：
```python
from app.models import Expense


def test_submit_assigns_period(app, db_session, employee_draft):
    # employee_draft: 一張已可送出的 draft（fixture 或用既有 helper 建）
    with app.app_context():
        e = db_session.get(Expense, employee_draft.id)
        # ...呼叫 submit 端點（比照 test_expense_submitted 的 client 流程）...
        # 送出後
        db_session.refresh(e)
        assert e.period_id is not None
        p = e.period  # 或 db_session.get(AccountingPeriod, e.period_id)
        assert p.start_date <= e.business_date <= p.end_date
```
> 若無現成 fixture，直接複製 `tests/test_expense_submitted.py` 內建立 draft → 呼叫 `/api/expenses/<id>/submit` 的流程，最後多斷言 `period_id`。

- [ ] **Step 2: 改 submit**

`app/expenses/routes.py` submit 內，`e.day_seq = next_day_seq(...)` 之後、`db.session.commit()` 之前插入：
```python
    from app.periods.service import get_or_create_period
    e.period_id = get_or_create_period(e.business_date).id
```

- [ ] **Step 3: 改 manual**

`app/reconcile/routes.py` `manual()` 建 `Expense(...)` 之後、`db.session.flush()` 之前（或建構時）指派 period。改成：
```python
    db.session.add(e)
    db.session.flush()
    from app.periods.service import get_or_create_period
    e.period_id = get_or_create_period(bd).id
    record_reconcile(e, actor.id)
```

- [ ] **Step 4: 跑測試**

Run: `python3 -m pytest tests/test_period_assign.py tests/test_reconcile_manual.py -q`
Expected: 全 passed（含既有 manual 測試不回歸）。

- [ ] **Step 5: Commit**
```bash
git add app/expenses/routes.py app/reconcile/routes.py tests/test_period_assign.py
git commit -m "feat(periods): assign period_id on submit and accountant manual entry"
```

---

### Task 6: 封月寫入閘 `assert_period_writable`

**Files:**
- Modify: `app/periods/service.py`
- Modify: `app/reconcile/routes.py`（approve/approve_batch/edit/reject/manual）
- Modify: `app/audit/routes.py`（check）
- Modify: `app/expenses/routes.py`（submit）
- Test: `tests/test_period_gate.py`

**Interfaces:**
- Produces: `is_period_closed(period_id: int|None, now_utc: datetime) -> bool` — period 為 None → False（未歸期不擋）；否則 `effective_status == "closed"`。呼叫端據此回 409 `period_closed`。

- [ ] **Step 1: 寫失敗測試**

`tests/test_period_gate.py`：
```python
from datetime import date, datetime, timezone
from app.models import Expense, AccountingPeriod
from app.periods.service import is_period_closed


def test_is_period_closed(app, db_session):
    with app.app_context():
        p = AccountingPeriod(label="2026-01", start_date=date(2026, 1, 1),
                             end_date=date(2026, 1, 31),
                             lock_at=datetime(2026, 2, 2, 4, 0, tzinfo=timezone.utc),
                             status="closed")
        db_session.add(p); db_session.flush()
        now = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
        assert is_period_closed(p.id, now) is True
        assert is_period_closed(None, now) is False


def test_reconcile_approve_blocked_when_closed(app, db_session, client, accountant_login):
    # 建一張 audited 單掛在 closed 期，呼叫 /api/reconcile/<id>/approve → 409 period_closed
    ...
```
> 第二個測試比照 `tests/test_reconcile_approve.py` 建 audited 單 + 會計登入 client，另把該單 `period_id` 指到 `status="closed"` 的期，斷言回應 `409` 且 `message == "period_closed"`。

- [ ] **Step 2: 實作 gate helper（追加 service.py）**
```python
def is_period_closed(period_id, now_utc):
    if period_id is None:
        return False
    p = db.session.get(AccountingPeriod, period_id)
    if p is None:
        return False
    return effective_status(p, now_utc) == "closed"
```

- [ ] **Step 3: 在每個寫入端點前置 gate**

於 `app/reconcile/routes.py` 檔頭加 `from app.periods.service import is_period_closed`，並在下列端點載入單據後、動作前插入（以 `approve` 為例）：
```python
    from datetime import datetime, timezone
    if is_period_closed(e.period_id, datetime.now(timezone.utc)):
        return jsonify(status="error", message="period_closed"), 409
```
套用位置：
- `approve(eid)`：`e` 取得後。
- `approve_batch`：迴圈內每筆 `e` 取得後、`_approve_one` 前（closed 的併入 `skipped`）。
- `edit(eid)`：`not_editable` 檢查通過後。
- `reject(eid)`：`not_rejectable` 檢查通過後。
- `manual`：`bd` 決定後，`get_or_create_period(bd)` 若回傳 closed 期 → 擋（見下）。

`manual` 特例（日期落在已封期要擋）：於 flush/指派 period 後改為：
```python
    period = get_or_create_period(bd)
    if is_period_closed(period.id, datetime.now(timezone.utc)):
        db.session.rollback()
        return jsonify(status="error", message="period_closed"), 409
    e.period_id = period.id
```

`app/audit/routes.py` `check`（打勾）：載入單據後、改 status 前加同一段 gate（`from app.periods.service import is_period_closed`）——**封月後主管不能再對該期 submitted 單打勾**（spec §7）。

`app/expenses/routes.py` `submit`：指派 period 後，若該期已 closed 則擋（極端情況：極晚送出、目標期已封）：
```python
    period = get_or_create_period(e.business_date)
    if is_period_closed(period.id, datetime.now(timezone.utc)):
        return jsonify(status="error", message="period_closed"), 409
    e.period_id = period.id
```
（取代 Task 5 Step 2 的兩行；submit 已 import `datetime, timezone`。）

- [ ] **Step 4: 跑測試**

Run: `python3 -m pytest tests/test_period_gate.py tests/test_reconcile_approve.py tests/test_reconcile_edit.py tests/test_reconcile_reject.py tests/test_audit_check.py -q`
Expected: 全 passed。

- [ ] **Step 5: Commit**
```bash
git add app/periods/service.py app/reconcile/routes.py app/audit/routes.py app/expenses/routes.py tests/test_period_gate.py
git commit -m "feat(periods): reject writes to closed periods across reconcile/audit/submit"
```

---

### Task 7: 自動封月 `maybe_autoclose`（碰觸即檢查）

**Files:**
- Modify: `app/periods/service.py`
- Test: `tests/test_period_autoclose.py`

**Interfaces:**
- Consumes: `get_or_create_period`、`effective_status`。
- Produces: `maybe_autoclose(period, now_utc) -> bool` — 若 `period.status != "closed"` 且 `now_utc >= period.lock_at`：在同一交易裡把該期 `audited`/`rejected` 單的 `period_id` 挪到「下一期」（`get_or_create_period(period.end_date + 1天)`，若下一期已 closed 則不挪、留原期），`submitted` 留原期不動，並以條件更新把 `status` 設 `closed`（`WHERE id=? AND status!='closed'`）。回傳是否真的由本次封月。**不自行 commit**，交由呼叫端。

- [ ] **Step 1: 寫失敗測試**

`tests/test_period_autoclose.py`：
```python
from datetime import date, datetime, timezone, timedelta
from app.models import Expense, AccountingPeriod
from app.periods.service import get_or_create_period, maybe_autoclose


def _mk_expense(db_session, store_id, created_by, bd, status, period_id, amount=100):
    from app.models import Expense
    e = Expense(store_id=store_id, created_by=created_by, created_at=datetime.now(timezone.utc),
                business_date=bd, status=status, amount=amount, amount_parse_ok=True,
                period_id=period_id)
    db_session.add(e); db_session.flush()
    return e


def test_autoclose_moves_checked_leaves_submitted(app, db_session, store, user):
    with app.app_context():
        jan = get_or_create_period(date(2026, 1, 15)); db_session.commit()
        audited = _mk_expense(db_session, store.id, user.id, date(2026, 1, 20), "audited", jan.id)
        submitted = _mk_expense(db_session, store.id, user.id, date(2026, 1, 21), "submitted", jan.id)
        db_session.commit()

        now = jan.lock_at + timedelta(hours=1)
        closed = maybe_autoclose(jan, now)
        db_session.commit()

        assert closed is True
        assert jan.status == "closed"
        db_session.refresh(audited); db_session.refresh(submitted)
        assert audited.period_id != jan.id            # 挪到下一期
        assert submitted.period_id == jan.id          # 留原期
        nxt = db_session.get(AccountingPeriod, audited.period_id)
        assert nxt.start_date == date(2026, 2, 1)


def test_autoclose_idempotent_and_time_gated(app, db_session):
    with app.app_context():
        jan = get_or_create_period(date(2026, 1, 15)); db_session.commit()
        before = jan.lock_at - timedelta(hours=1)
        assert maybe_autoclose(jan, before) is False   # 還沒到鎖定時刻
        assert jan.status == "open"
        after = jan.lock_at + timedelta(hours=1)
        assert maybe_autoclose(jan, after) is True
        db_session.commit()
        assert maybe_autoclose(jan, after) is False     # 已封，不重複
```
> `store`/`user` fixture 比照既有測試（如 `tests/test_reconcile_manual.py`）建立；沒有就在測試內用 `Store`/`User` 直接建。

- [ ] **Step 2: 實作（追加 service.py）**
```python
def _next_period_of(period):
    return get_or_create_period(period.end_date + timedelta(days=1))


def maybe_autoclose(period, now_utc):
    if period.status == "closed" or now_utc < period.lock_at:
        return False

    # 併發：條件更新確保只有一個 worker 真的封這期
    updated = (AccountingPeriod.query
               .filter(AccountingPeriod.id == period.id,
                       AccountingPeriod.status != "closed")
               .update({"status": "closed", "closed_at": now_utc},
                       synchronize_session=False))
    if not updated:
        return False

    nxt = _next_period_of(period)
    if nxt.status != "closed":
        (Expense.query
         .filter(Expense.period_id == period.id,
                 Expense.status.in_(("audited", "rejected")))
         .update({"period_id": nxt.id}, synchronize_session=False))
    db.session.refresh(period)
    return True
```
> 匯入：檔頭已有 `from app.models import AccountingPeriod`；補 `from app.models import Expense` 與 `from datetime import timedelta`（若尚未）。
> **自動封月是系統動作、無 actor**，故不寫單據級 `audit_log`（`move_period` 的軌跡由會計手動挪期 Task 10 負責）。挪期本身以 DB 條件更新完成，可追溯於 `period_id` 現值 + 該期 `closed_at`。

- [ ] **Step 3: 跑測試**

Run: `python3 -m pytest tests/test_period_autoclose.py -q`
Expected: 2 passed。

- [ ] **Step 4: 在讀取當期時觸發 autoclose**

於 `app/reconcile/routes.py` `pending()` 決定「當期」後（Task 9 會加期間篩選），對被查到的期呼叫 `maybe_autoclose(period, now)` 再 commit。此步在 Task 9 一併完成；此處僅實作函式與單元測試。

- [ ] **Step 5: Commit**
```bash
git add app/periods/service.py tests/test_period_autoclose.py
git commit -m "feat(periods): maybe_autoclose moves checked, leaves submitted, closes once"
```

---

### Task 8: 回填既有單據的 `period_id`

**Files:**
- Modify: `app/periods/service.py`（`backfill_periods`）
- Test: `tests/test_period_backfill.py`

**Interfaces:**
- Produces: `backfill_periods() -> int` — 對所有 `period_id IS NULL` 且 `business_date IS NOT NULL` 的單，依 business_date `get_or_create_period` 指派 period_id；回傳處理筆數。冪等（再跑一次回 0）。**不 commit**，呼叫端負責。

- [ ] **Step 1: 寫失敗測試**

`tests/test_period_backfill.py`：
```python
from datetime import date, datetime, timezone
from app.models import Expense
from app.periods.service import backfill_periods


def test_backfill_assigns_and_idempotent(app, db_session, store, user):
    with app.app_context():
        e = Expense(store_id=store.id, created_by=user.id,
                    created_at=datetime.now(timezone.utc),
                    business_date=date(2026, 1, 10), status="audited",
                    amount=100, amount_parse_ok=True, period_id=None)
        db_session.add(e); db_session.commit()
        n = backfill_periods(); db_session.commit()
        assert n == 1
        db_session.refresh(e)
        assert e.period_id is not None
        assert backfill_periods() == 0   # 冪等
```

- [ ] **Step 2: 實作（追加 service.py）**
```python
def backfill_periods():
    rows = (Expense.query
            .filter(Expense.period_id.is_(None),
                    Expense.business_date.isnot(None))
            .all())
    for e in rows:
        e.period_id = get_or_create_period(e.business_date).id
    return len(rows)
```

- [ ] **Step 3: 跑測試 + 對 dev.db 實跑一次**

Run:
```bash
python3 -m pytest tests/test_period_backfill.py -q
FLASK_APP=wsgi.py python3 -c "from wsgi import app; from app.extensions import db; from app.periods.service import backfill_periods; \
ctx=app.app_context(); ctx.push(); n=backfill_periods(); db.session.commit(); print('backfilled', n); ctx.pop()"
```
Expected: 1 passed；印出回填筆數。

- [ ] **Step 4: Commit**
```bash
git add app/periods/service.py tests/test_period_backfill.py
git commit -m "feat(periods): idempotent backfill of period_id for existing expenses"
```

---

## Phase D — 核銷端整合

### Task 9: 核銷清單加「期間」篩選 ＋ serialize 帶 period ＋ 讀取時觸發 autoclose

**Files:**
- Modify: `app/reconcile/routes.py`（`pending`）
- Modify: `app/reconcile/serialize.py`
- Test: `tests/test_reconcile_period_filter.py`、更新 `tests/test_reconcile_list.py`（守 note 不外洩）

**Interfaces:**
- Consumes: `get_or_create_period`、`effective_status`、`maybe_autoclose`、`get_close_day`。
- Produces: `GET /api/reconcile/pending?period_id=<id>`（未帶則預設「當期」＝含今天營業日的期）。回傳新增 `period`：`{id, label, status}`（status 為 `effective_status`）。清單每列 serialize 新增 `period_id`、`period_label`（**仍不含 note**）。

- [ ] **Step 1: 寫失敗測試**

`tests/test_reconcile_period_filter.py`：
```python
def test_pending_defaults_to_current_period(app, db_session, client, accountant_login):
    # 建當期 audited 單 + 上一期 audited 單，pending() 不帶 period_id 應只回當期那筆
    ...
    resp = client.get("/api/reconcile/pending")
    data = resp.get_json()
    assert data["period"]["label"]  # 有當期資訊
    # 只含當期單
    ...


def test_pending_filter_by_period_id(app, db_session, client, accountant_login):
    resp = client.get(f"/api/reconcile/pending?period_id={prev_period_id}")
    ...
```
> 比照 `tests/test_reconcile_list.py` 的 client + 會計登入 fixture。

同時在 `tests/test_reconcile_list.py` 既有 `test_note_never_leaks_to_accountant` 保持不動即可（serialize 新增欄位不得含 note）。

- [ ] **Step 2: 改 serialize**

`app/reconcile/serialize.py`，`serialize_reconcile_item` 回傳 dict 內加（放在 `status` 附近，**note 仍不得出現**）：
```python
        "period_id": e.period_id,
```
`period_label` 由 `pending()` 帶入一個 `period_label_by_id` map（避免 N+1）。改簽名多收一個 map：
```python
def serialize_reconcile_item(e, storage, store_name_by_id, cat_name_by_id,
                             user_name_by_id, period_label_by_id=None):
    period_label_by_id = period_label_by_id or {}
    ...
        "period_id": e.period_id,
        "period_label": period_label_by_id.get(e.period_id),
```
> 其他呼叫點（若有）沿用預設 `None` 不破壞。

- [ ] **Step 3: 改 pending()**

`app/reconcile/routes.py` `pending()`：
```python
    from datetime import datetime, timezone
    from app.periods.service import (get_or_create_period, effective_status,
                                     maybe_autoclose)
    from app.expenses.logic import compute_business_date
    from app.models import AccountingPeriod

    now = datetime.now(timezone.utc)
    pid = _parse_int(request.args.get("period_id"))
    if pid is not None:
        period = db.session.get(AccountingPeriod, pid)
    else:
        period = get_or_create_period(compute_business_date(now))
    # 碰到就檢查是否該自動封月（涵蓋剛好進入鎖定時刻的期）
    if period is not None:
        maybe_autoclose(period, now)
    db.session.commit()
```
在既有 `q = Expense.query.filter(...)` 之外，若 `period` 存在則加 `q = q.filter(Expense.period_id == period.id)`。
組 `period_label_by_id`：查出本頁 rows 的 `period_id` 集合對應 label。
`serialize_reconcile_item(..., period_label_by_id)` 帶入。
回傳 jsonify 增加：
```python
    period_out = ({"id": period.id, "label": period.label,
                   "status": effective_status(period, now)} if period else None)
    return jsonify(status="ok", groups=groups, total=total, period=period_out)
```

- [ ] **Step 4: 跑測試**

Run: `python3 -m pytest tests/test_reconcile_period_filter.py tests/test_reconcile_list.py -q`
Expected: 全 passed（含 note 守門測試綠）。

- [ ] **Step 5: Commit**
```bash
git add app/reconcile/routes.py app/reconcile/serialize.py tests/test_reconcile_period_filter.py
git commit -m "feat(reconcile): period filter + autoclose-on-read + period in payload"
```

---

### Task 10: 「挪下期」端點

**Files:**
- Modify: `app/reconcile/routes.py`
- Modify: `app/audit/log.py`（`record_move_period`）
- Test: `tests/test_reconcile_move_period.py`

**Interfaces:**
- Consumes: `get_or_create_period`、`is_period_closed`。
- Produces: `POST /api/reconcile/<eid>/move-next`（會計）— 把單 `period_id` 改成「目前所屬期的下一期」。下一期若 closed → 409 `next_period_closed`；目前期 closed → 409 `period_closed`；單無 period → 409 `no_period`。留 `move_period` log。

- [ ] **Step 1: 寫失敗測試**

`tests/test_reconcile_move_period.py`：
```python
def test_move_next_changes_period(app, db_session, client, accountant_login):
    # audited 單掛 jan 期 → move-next → period 變 feb
    resp = client.post(f"/api/reconcile/{eid}/move-next")
    assert resp.status_code == 200
    db_session.refresh(e)
    assert e.period_id == feb_id


def test_move_next_rejected_when_next_closed(app, db_session, client, accountant_login):
    # feb 期已 closed → 409 next_period_closed
    ...
```

- [ ] **Step 2: 實作**

`app/audit/log.py` 追加：
```python
def record_move_period(expense, actor_user_id, from_pid, to_pid):
    db.session.add(AuditLog(
        expense_id=expense.id, actor_user_id=actor_user_id, action="move_period",
        before_json={"period_id": from_pid}, after_json={"period_id": to_pid},
        ts=datetime.now(timezone.utc),
    ))
```

`app/reconcile/routes.py` 新端點：
```python
@reconcile_bp.post("/<int:eid>/move-next")
@role_required("accountant")
def move_next(eid):
    from datetime import datetime, timezone, timedelta
    from app.periods.service import get_or_create_period, is_period_closed
    from app.audit.log import record_move_period
    from app.models import AccountingPeriod

    e = db.session.get(Expense, eid)
    if e is None:
        return jsonify(status="error", message="not found"), 404
    if e.period_id is None:
        return jsonify(status="error", message="no_period"), 409
    now = datetime.now(timezone.utc)
    if is_period_closed(e.period_id, now):
        return jsonify(status="error", message="period_closed"), 409
    cur = db.session.get(AccountingPeriod, e.period_id)
    nxt = get_or_create_period(cur.end_date + timedelta(days=1))
    if is_period_closed(nxt.id, now):
        db.session.rollback()
        return jsonify(status="error", message="next_period_closed"), 409
    from_pid = e.period_id
    e.period_id = nxt.id
    record_move_period(e, current_user().id, from_pid, nxt.id)
    db.session.commit()
    return jsonify(status="ok", period_id=nxt.id, period_label=nxt.label)
```

- [ ] **Step 3: 跑測試**

Run: `python3 -m pytest tests/test_reconcile_move_period.py -q`
Expected: passed。

- [ ] **Step 4: Commit**
```bash
git add app/reconcile/routes.py app/audit/log.py tests/test_reconcile_move_period.py
git commit -m "feat(reconcile): move-next-period endpoint with closed-period guards"
```

---

### Task 11: 會計提前手動封月 端點

**Files:**
- Modify: `app/reconcile/routes.py`
- Test: `tests/test_reconcile_close_period.py`

**Interfaces:**
- Consumes: `effective_status`、`maybe_autoclose` 的挪期邏輯（重用一支 `close_period_now`）。
- Produces:
  - `GET /api/reconcile/period/<pid>/close-preview`（會計）— 回 `{unaudited_count}`（該期 `submitted` 筆數），供二次確認視窗顯示「這期還有 N 筆沒打勾」。
  - `POST /api/reconcile/period/<pid>/close`（會計）— 提前封月，**限期間已結束（`effective_status == "closing"`，即寬限期內）**才可封；行為同 autoclose（挪 audited/rejected、留 submitted、設 closed），並記 `closed_by=會計`。
    - `effective_status == "open"`（期間還在進行中）→ 409 `period_not_ended`（想提早鎖進行中的期，請先用「調 end_date」把期間縮到今天/昨天讓它進入寬限期，再封——避免把剩餘日的單卡死，見 Task 15）。
    - `effective_status == "closed"` → 409 `already_closed`。

- [ ] **Step 1: 抽出共用封月核心（service.py）**

把 Task 7 `maybe_autoclose` 內「條件更新設 closed + 挪期」抽成 `_do_close(period, now_utc, closed_by=None) -> bool`，`maybe_autoclose` 呼叫 `_do_close(period, now_utc)`（closed_by=None＝系統）。新增：
```python
def close_period_now(period, now_utc, closed_by):
    """會計提前封月：限期間已結束（寬限期 closing）才可封。
    open（進行中）不可封——會把該期剩餘日的單卡死（那些日子仍 canonically 屬本期），
    要提早鎖請先調 end_date 讓期間進入寬限期（Task 15）。"""
    if effective_status(period, now_utc) != "closing":
        return False
    return _do_close(period, now_utc, closed_by=closed_by)
```
`_do_close` 內 `update({...})` 補 `"closed_by": closed_by`。

- [ ] **Step 2: 寫失敗測試**

`tests/test_reconcile_close_period.py`：
> **測試前置**：提前封月限「寬限期（closing）」才可封。端點用 `datetime.now()`，故測試要建一個**已結束但未鎖**的期：`end_date` 設在過去（今天之前，讓 `effective_status=="closing"`）、`lock_at` 設在未來（還沒到自動封月）。以下 `jan_closing` fixture 指這種期。
```python
def test_close_preview_counts_unaudited(app, db_session, client, accountant_login, jan_closing):
    # jan_closing 期含 2 筆 submitted + 1 筆 audited
    resp = client.get(f"/api/reconcile/period/{jan_closing.id}/close-preview")
    assert resp.get_json()["unaudited_count"] == 2


def test_manual_close_moves_and_locks(app, db_session, client, accountant_login, jan_closing):
    resp = client.post(f"/api/reconcile/period/{jan_closing.id}/close")
    assert resp.status_code == 200
    p = db_session.get(AccountingPeriod, jan_closing.id)
    assert p.status == "closed"
    assert p.closed_by is not None
    # submitted 留原期、audited 挪走
    ...


def test_cannot_close_open_period(app, db_session, client, accountant_login):
    # 進行中（open）的當期 → 409 period_not_ended（提早鎖要先調 end_date）
    from app.periods.service import get_or_create_period
    from app.expenses.logic import compute_business_date
    from datetime import datetime, timezone
    with app.app_context():
        p = get_or_create_period(compute_business_date(datetime.now(timezone.utc)))
        db_session.commit()
        pid = p.id
    resp = client.post(f"/api/reconcile/period/{pid}/close")
    assert resp.status_code == 409
    assert resp.get_json()["message"] == "period_not_ended"


def test_manual_close_already_closed(app, db_session, client, accountant_login, jan_closing):
    jan_closing.status = "closed"; db_session.commit()
    resp = client.post(f"/api/reconcile/period/{jan_closing.id}/close")
    assert resp.status_code == 409
    assert resp.get_json()["message"] == "already_closed"
```

- [ ] **Step 3: 實作端點**
```python
@reconcile_bp.get("/period/<int:pid>/close-preview")
@role_required("accountant")
def close_preview(pid):
    from app.models import AccountingPeriod
    p = db.session.get(AccountingPeriod, pid)
    if p is None:
        return jsonify(status="error", message="not found"), 404
    n = Expense.query.filter(Expense.period_id == pid,
                             Expense.status == "submitted").count()
    return jsonify(status="ok", unaudited_count=n, label=p.label)


@reconcile_bp.post("/period/<int:pid>/close")
@role_required("accountant")
def close_period(pid):
    from datetime import datetime, timezone
    from app.periods.service import close_period_now, effective_status
    from app.models import AccountingPeriod
    p = db.session.get(AccountingPeriod, pid)
    if p is None:
        return jsonify(status="error", message="not found"), 404
    now = datetime.now(timezone.utc)
    st = effective_status(p, now)
    if st == "closed":
        return jsonify(status="error", message="already_closed"), 409
    if st != "closing":
        # open：期間還在進行中，不可提前封（先調 end_date 讓它進寬限期）
        return jsonify(status="error", message="period_not_ended"), 409
    if not close_period_now(p, now, current_user().id):
        db.session.rollback()
        return jsonify(status="error", message="already_closed"), 409
    db.session.commit()
    return jsonify(status="ok")
```

- [ ] **Step 4: 跑測試**

Run: `python3 -m pytest tests/test_reconcile_close_period.py tests/test_period_autoclose.py -q`
Expected: 全 passed（autoclose 不回歸）。

- [ ] **Step 5: Commit**
```bash
git add app/periods/service.py app/reconcile/routes.py tests/test_reconcile_close_period.py
git commit -m "feat(reconcile): accountant early manual close with unaudited-count preview"
```

---

### Task 12: 「上期未處理單」清單端點

**Files:**
- Modify: `app/reconcile/routes.py`
- Test: `tests/test_reconcile_unprocessed.py`

**Interfaces:**
- Produces: `GET /api/reconcile/unprocessed`（會計）— 列出所有 `status="closed"` 期裡仍為 `submitted` 的單（主管沒打勾、封月後留原期不進帳）。回門店、營業日、金額、摘要、原圖 URL；依營業日排序。**不含 note**。

- [ ] **Step 1: 寫失敗測試**

`tests/test_reconcile_unprocessed.py`：
```python
def test_unprocessed_lists_submitted_in_closed_periods(app, db_session, client, accountant_login):
    # closed 期含 1 筆 submitted + 1 筆 audited；open 期含 1 筆 submitted
    resp = client.get("/api/reconcile/unprocessed")
    items = resp.get_json()["items"]
    # 只回 closed 期的那筆 submitted
    assert len(items) == 1
    assert "note" not in items[0]          # 白名單守門
```

- [ ] **Step 2: 實作**
```python
@reconcile_bp.get("/unprocessed")
@role_required("accountant")
def unprocessed():
    from app.models import AccountingPeriod
    closed_ids = [p.id for p in AccountingPeriod.query
                  .filter(AccountingPeriod.status == "closed").all()]
    if not closed_ids:
        return jsonify(status="ok", items=[])
    rows = (Expense.query
            .filter(Expense.period_id.in_(closed_ids),
                    Expense.status == "submitted")
            .order_by(Expense.business_date.asc(), Expense.store_id.asc(),
                      Expense.day_seq.asc()).all())
    storage = get_storage()
    stores, cats, users = _maps(rows)
    items = [{
        "id": e.id,
        "business_date": e.business_date.isoformat() if e.business_date else None,
        "store_id": e.store_id, "store_name": stores.get(e.store_id),
        "summary": e.summary,
        "amount": float(e.amount) if e.amount is not None else None,
        "image_url": storage.presigned_url(e.image_key) if e.image_key else None,
    } for e in rows]
    return jsonify(status="ok", items=items)
```

- [ ] **Step 3: 跑測試**

Run: `python3 -m pytest tests/test_reconcile_unprocessed.py -q`
Expected: passed。

- [ ] **Step 4: Commit**
```bash
git add app/reconcile/routes.py tests/test_reconcile_unprocessed.py
git commit -m "feat(reconcile): unprocessed list (submitted stuck in closed periods)"
```

---

## Phase E — 月報表

### Task 13: 月報表聚合 ＋ 後端端點

**Files:**
- Create: `app/reports/__init__.py`、`app/reports/routes.py`、`app/reports/service.py`
- Modify: `app/__init__.py`（註冊 `report_bp`）
- Test: `tests/test_report_service.py`、`tests/test_report_api.py`

**Interfaces:**
- Produces:
  - `build_cross_table(expenses, categories, stores, now_utc, period) -> dict`（`app/reports/service.py`）— 分店×科目大類交叉表。每格 `{reconciled, pending}`（有號數加總；`period` 若 closed 則 pending 恆 0）。含大類下的細類明細、各店合計（底列）、每列總計（最右欄）。單的大類＝其 category 的 level-1 祖先（category level==1 用自己，level==2 用 parent）。無科目的單歸「未分類」。
  - `GET /api/reports/monthly?period_id=<id>`（`accountant` 或 `super_admin`）— 回該期交叉表；未帶 period_id 用當期。回傳 `period:{id,label,status}` + `stores:[{id,name}]`（欄順序）+ `rows:[{major_id, major_name, total:{reconciled,pending}, per_store:{store_id:{reconciled,pending}}, children:[...同結構(細類)]}]` + `store_totals` + `grand_total`。**不含 note、不含逐單明細**。

- [ ] **Step 1: 寫聚合純函式失敗測試**

`tests/test_report_service.py`：
```python
from datetime import date, datetime, timezone
from app.reports.service import major_category_id


def test_major_category_id_level1_is_self():
    cats = {10: {"level": 1, "parent_id": None}, 20: {"level": 2, "parent_id": 10}}
    assert major_category_id(10, cats) == 10
    assert major_category_id(20, cats) == 10
    assert major_category_id(None, cats) is None
```
（`build_cross_table` 的完整斷言另寫一個測試：兩店、兩大類、含負數、含一筆 pending，驗每格 reconciled/pending、store_totals、grand_total 皆有號加總正確。）

- [ ] **Step 2: 實作 service**

`app/reports/service.py`（核心；完整交叉表組裝依 Interfaces 結構實作，最終回傳 dict）：
```python
def major_category_id(category_id, cats):
    """回科目大類 id（level 1）。level 2 取 parent，level 1 取自己，None→None。"""
    if category_id is None:
        return None
    c = cats.get(category_id)
    if c is None:
        return None
    if c["level"] == 1:
        return category_id
    return c["parent_id"]


def _bucket(status, effective_period_status):
    """回 'reconciled' 或 'pending'；closed 期不應有 pending，但仍以狀態判定。"""
    return "reconciled" if status == "reconciled" else "pending"
```
> 交叉表組裝：迭代 expenses，對每筆算 `major_category_id`，累加到 `rows[major]['per_store'][store]` 與 `children[minor]`，同步累加 `store_totals`、`grand_total`；`amount` 為 None 者略過；有號數加總。`per_store`/合計皆存 `{reconciled, pending}`。回傳結構見 Interfaces。

`app/reports/routes.py`：
```python
from datetime import datetime, timezone
from flask import request, jsonify
from app.extensions import db
from app.models import Expense, Category, Store, AccountingPeriod
from app.auth.decorators import role_required
from app.reports import report_bp
from app.reports.service import build_cross_table
from app.periods.service import (get_or_create_period, effective_status,
                                 maybe_autoclose)
from app.expenses.logic import compute_business_date


@report_bp.get("/monthly")
@role_required("accountant", "super_admin")
def monthly():
    now = datetime.now(timezone.utc)
    pid = request.args.get("period_id", type=int)
    if pid is not None:
        period = db.session.get(AccountingPeriod, pid)
    else:
        period = get_or_create_period(compute_business_date(now))
    if period is None:
        return jsonify(status="error", message="not found"), 404
    maybe_autoclose(period, now)
    db.session.commit()

    rows = Expense.query.filter(
        Expense.period_id == period.id,
        Expense.status.in_(("audited", "reconciled", "rejected"))).all()
    cats = {c.id: {"level": c.level, "parent_id": c.parent_id, "name": c.name}
            for c in Category.query.all()}
    stores = [{"id": s.id, "name": s.name}
              for s in Store.query.order_by(Store.name.asc()).all()]
    table = build_cross_table(rows, cats, stores, now, period)
    table["period"] = {"id": period.id, "label": period.label,
                       "status": effective_status(period, now)}
    table["status"] = "ok"
    return jsonify(**table)
```
> **報表只計「進帳的」單**（`audited`/`reconciled`/`rejected`——即 `CHECKED_STATUSES`）；`submitted` 不進報表（對齊 spec §5.4：沒打勾不進任何帳）。

`app/reports/__init__.py`：
```python
from flask import Blueprint
report_bp = Blueprint("reports", __name__, url_prefix="/api/reports")
from app.reports import routes  # noqa: E402,F401
```

`app/__init__.py` 註冊：
```python
    from app.reports import report_bp
    app.register_blueprint(report_bp)
```

- [ ] **Step 3: 寫 API 測試**

`tests/test_report_api.py`：建兩店、兩大類、混 reconciled/audited/負數單掛同期，會計登入 GET `/api/reports/monthly?period_id=...`，斷言 rows/store_totals/grand_total 的 reconciled/pending 有號加總正確；另斷言 `super_admin` 也 200、`manager`/`employee` 403、回傳無 `note`。

- [ ] **Step 4: 跑測試**

Run: `python3 -m pytest tests/test_report_service.py tests/test_report_api.py -q`
Expected: 全 passed。

- [ ] **Step 5: Commit**
```bash
git add app/reports/ app/__init__.py tests/test_report_service.py tests/test_report_api.py
git commit -m "feat(reports): monthly cross-table (store x major category, reconciled/pending)"
```

---

### Task 14: 月報表前端（會計／經理共用模組）

**Files:**
- Create: `app/static/js/reports_api.js`
- Create: `app/static/js/month_report.js`
- Test: `tests/js/month_report.mjs`

**Interfaces:**
- Consumes: `GET /api/reports/monthly`。
- Produces: `renderMonthReport(container, { periodId })`（`month_report.js`）— 抓資料並畫交叉表：欄＝各店＋總計，列＝科目大類（可展開細類），每格 `open/closing` 顯示「已核銷 / 待核銷」兩數、`closed` 顯示單一數；負數與算出為負的小計/合計標紅。純聚合輔助 `formatCell(cell, periodStatus)` 匯出供測試。

- [ ] **Step 1: 寫前端純邏輯測試**

`tests/js/month_report.mjs`：
```javascript
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatCell } from '../../app/static/js/month_report.js';

test('open period shows reconciled/pending split', () => {
  const out = formatCell({ reconciled: 100, pending: 50 }, 'open');
  assert.equal(out.text, '100 / 50');
});

test('closed period shows single number', () => {
  const out = formatCell({ reconciled: 100, pending: 0 }, 'closed');
  assert.equal(out.text, '100');
});

test('negative total marked red', () => {
  const out = formatCell({ reconciled: -30, pending: 0 }, 'closed');
  assert.equal(out.negative, true);
});
```

- [ ] **Step 2: 實作 `reports_api.js`**
```javascript
export const reportsApi = {
  async monthly(periodId) {
    const q = periodId ? `?period_id=${periodId}` : '';
    const r = await fetch(`/api/reports/monthly${q}`);
    return { status: r.status, data: await r.json() };
  },
};
```

- [ ] **Step 3: 實作 `month_report.js`**

`formatCell` 純函式 + `renderMonthReport(container,{periodId})`（抓資料、建 table、大類列可點開細類、負數紅字）。`formatCell`：
```javascript
export function formatCell(cell, periodStatus) {
  const r = Number(cell.reconciled || 0);
  const p = Number(cell.pending || 0);
  const fmt = (n) => n.toLocaleString('en-US', { maximumFractionDigits: 2 });
  if (periodStatus === 'closed') {
    return { text: fmt(r), negative: r < 0 };
  }
  return { text: `${fmt(r)} / ${fmt(p)}`, negative: r < 0 || p < 0 };
}
```
> `renderMonthReport` 依 Interfaces 畫表：表頭各店＋總計欄；每個大類一列（含展開鈕，點擊 toggle 其 children 細類列）；套 `formatCell`；`negative` 時該格加 `.amount-neg` class（沿用既有負數紅字 CSS，比照 `reconcile.js` 的 `fmtAmount` 用法）。

- [ ] **Step 4: 跑前端測試**

Run: `node --test tests/js/month_report.mjs`
Expected: 3 passed。

- [ ] **Step 5: Commit**
```bash
git add app/static/js/reports_api.js app/static/js/month_report.js tests/js/month_report.mjs
git commit -m "feat(reports): shared month-report frontend module"
```

---

## Phase F — 月結日設定（經理）

### Task 15: 月結日設定 端點（會計可改、經理唯讀）

**Files:**
- Create: `app/periods/routes.py`
- Modify: `app/periods/service.py`（`successor_bounds`）
- Modify: `app/__init__.py`（註冊 `period_bp`）
- Modify: `app/periods/__init__.py`（宣告 blueprint）
- Test: `tests/test_period_settings_api.py`

**Interfaces:**（權限依 2026-07-15 user 修正：**會計編輯、經理唯讀**）
- Produces:
  - `GET /api/periods/settings`（`accountant` **或** `super_admin`——兩者皆可觀看）— 回 `{period_close_day, period_lock_offset_hours}`。
  - `PATCH /api/periods/settings`（**僅 `accountant`**）— 改上述設定；`period_close_day` 限 1–28（避免月底 clamp 混淆）、`period_lock_offset_hours` 限 0–168。驗證失敗回 400。經理（super_admin）呼叫 → 403。
  - `PATCH /api/periods/<pid>/end-date`（**僅 `accountant`**，農曆年調整）— 改該期 `end_date`；不得與相鄰期重疊/留洞、不得改已 closed 期；成功後**重算下一期**（若下一期存在，順移其 start_date 與 lock_at）。

- [ ] **Step 1: 宣告 blueprint**

`app/periods/__init__.py`：
```python
from flask import Blueprint
period_bp = Blueprint("periods", __name__, url_prefix="/api/periods")
from app.periods import routes  # noqa: E402,F401
```
`app/__init__.py` 註冊：
```python
    from app.periods import period_bp
    app.register_blueprint(period_bp)
```

- [ ] **Step 2: 寫失敗測試**

`tests/test_period_settings_api.py`：
```python
def test_accountant_can_get_and_patch_settings(app, db_session, client, accountant_login):
    assert client.get("/api/periods/settings").get_json()["period_close_day"] == 1
    r = client.patch("/api/periods/settings", json={"period_close_day": 5})
    assert r.status_code == 200
    assert client.get("/api/periods/settings").get_json()["period_close_day"] == 5


def test_manager_general_can_view_but_not_edit(app, db_session, client, super_admin_login):
    # 經理(super_admin)：可觀看設定，但不能改
    assert client.get("/api/periods/settings").status_code == 200
    assert client.patch("/api/periods/settings", json={"period_close_day": 5}).status_code == 403


def test_patch_settings_validates_range(app, client, accountant_login):
    assert client.patch("/api/periods/settings", json={"period_close_day": 31}).status_code == 400
    assert client.patch("/api/periods/settings", json={"period_close_day": 0}).status_code == 400


def test_settings_forbidden_for_store_manager_and_employee(app, client, manager_login):
    # 主管(manager)與員工完全看不到
    assert client.get("/api/periods/settings").status_code == 403


def test_edit_end_date_shifts_existing_next_period(app, db_session, client, accountant_login):
    # jan[1/1..1/31], feb[2/1..2/28] 都已存在；把 jan.end_date 改 1/24 → feb.start 應變 1/25
    ...


def test_edit_end_date_creates_next_period_when_absent(app, db_session, client, accountant_login):
    # 只有 jan[1/1..1/31] 存在（feb 還沒被建）；把 jan.end_date 改 1/24
    # → 自動建出下一期 label=2026-02, start=1/25, end=2/28；1/25 的單能落到它
    from app.periods.service import get_or_create_period
    from datetime import date
    # ...PATCH jan end_date=1/24 後...
    with app.app_context():
        nxt = get_or_create_period(date(2026, 1, 25))
        assert nxt.label == "2026-02"
        assert nxt.start_date == date(2026, 1, 25)
        assert nxt.end_date == date(2026, 2, 28)
```

- [ ] **Step 3: 加 `successor_bounds` helper（`app/periods/service.py`）**

調 `end_date` 提早結期時，需把「下一期」明確接上（避免縮短後 `get_or_create_period` 用 canonical 重算出與現有期重疊的期）。下一期的**標籤月**由 `period.label`（權威）推導、**起始**接在 `period.end_date` 之後——不可用 `start_date.month`，因為調整後起始日可能落在上一個日曆月而算錯月份：
```python
def successor_bounds(period, close_day):
    """period 之後那一期（下一標籤月）的 (start, end, label)。
    start 接在 period.end_date+1；標籤月＝period.label 月 +1（權威，不看 start_date）。"""
    y, m = int(period.label[:4]), int(period.label[5:7])
    ny, nm = _add_month(y, m)          # 下一標籤月
    ny2, nm2 = _add_month(ny, nm)      # 再下個月，用來算 end 邊界
    start = period.end_date + timedelta(days=1)
    end = _clamped(ny2, nm2, close_day) - timedelta(days=1)
    return start, end, f"{ny:04d}-{nm:02d}"
```

- [ ] **Step 4: 實作 routes**

`app/periods/routes.py`：
```python
from datetime import date, timedelta
from flask import request, jsonify
from app.extensions import db
from app.models import AccountingPeriod
from app.auth.decorators import role_required
from app.periods import period_bp
from app.periods.settings import get_close_day, get_lock_offset_hours, set_setting
from app.periods.service import lock_at_for, successor_bounds


@period_bp.get("/settings")
@role_required("accountant", "super_admin")   # 會計可改、經理唯讀 → 兩者皆可觀看
def get_settings():
    return jsonify(status="ok",
                   period_close_day=get_close_day(),
                   period_lock_offset_hours=get_lock_offset_hours())


@period_bp.patch("/settings")
@role_required("accountant")                  # 僅會計可編輯（經理唯讀）
def patch_settings():
    data = request.get_json(silent=True) or {}
    if "period_close_day" in data:
        try:
            d = int(data["period_close_day"])
        except (TypeError, ValueError):
            return jsonify(status="error", message="bad_close_day"), 400
        if not (1 <= d <= 28):
            return jsonify(status="error", message="bad_close_day"), 400
        set_setting("period_close_day", d)
    if "period_lock_offset_hours" in data:
        try:
            h = int(data["period_lock_offset_hours"])
        except (TypeError, ValueError):
            return jsonify(status="error", message="bad_offset"), 400
        if not (0 <= h <= 168):
            return jsonify(status="error", message="bad_offset"), 400
        set_setting("period_lock_offset_hours", h)
    db.session.commit()
    return jsonify(status="ok")


@period_bp.patch("/<int:pid>/end-date")
@role_required("accountant")                  # 農曆年調整：僅會計（經理唯讀）
def edit_end_date(pid):
    p = db.session.get(AccountingPeriod, pid)
    if p is None:
        return jsonify(status="error", message="not found"), 404
    if p.status == "closed":
        return jsonify(status="error", message="period_closed"), 409
    try:
        new_end = date.fromisoformat((request.get_json(silent=True) or {}).get("end_date", ""))
    except (TypeError, ValueError):
        return jsonify(status="error", message="bad_date"), 400
    if new_end < p.start_date:
        return jsonify(status="error", message="end_before_start"), 400

    offset = get_lock_offset_hours()
    close_day = get_close_day()
    p.end_date = new_end
    # 本期 lock_at 依新 end_date 重算（換期日=new_end+1 起算 offset）
    p.lock_at = lock_at_for(new_end + timedelta(days=1), offset)

    # 明確維護「下一期」，保證首尾相接、不留孤兒日、不與 canonical 重疊。
    nxt = (AccountingPeriod.query
           .filter(AccountingPeriod.start_date > p.start_date)
           .order_by(AccountingPeriod.start_date.asc()).first())
    if nxt is not None:
        if nxt.status == "closed":
            db.session.rollback()
            return jsonify(status="error", message="next_period_closed"), 409
        nxt.start_date = new_end + timedelta(days=1)
        nxt.lock_at = lock_at_for(nxt.end_date + timedelta(days=1), offset)
        if nxt.start_date > nxt.end_date:
            db.session.rollback()
            return jsonify(status="error", message="would_invert_next"), 400
    else:
        # 下一期還沒被建過 → 現在就建，讓 new_end 之後的日子有歸屬
        s, e, label = successor_bounds(p, close_day)
        db.session.add(AccountingPeriod(
            label=label, start_date=s, end_date=e,
            lock_at=lock_at_for(e + timedelta(days=1), offset), status="open"))
    db.session.commit()
    return jsonify(status="ok")
```
> **限制（Phase 1，記錄於此）**：調 `end_date` **不回溯搬移已指派 `period_id` 的既有單**（`period_id` 是權威且黏著；縮短後落在新界外的既有單仍留原期）。實務上農曆年是**事前**規劃調整，該區間通常還沒有單；若真有少數落界的單，會計用「挪下期」逐筆處理。

- [ ] **Step 5: 跑測試**

Run: `python3 -m pytest tests/test_period_settings_api.py -q`
Expected: 全 passed。

- [ ] **Step 6: Commit**
```bash
git add app/periods/service.py app/periods/routes.py app/periods/__init__.py app/__init__.py tests/test_period_settings_api.py
git commit -m "feat(periods): settings API — accountant edits, general manager view-only"
```

---

### Task 16: 經理「月結」分頁前端（設定唯讀 ＋ 月報表）

**Files:**
- Create: `app/static/js/periods_api.js`
- Modify: `app/static/js/admin.js`
- Test: 手動（前端頁面）

**Interfaces:**
- Consumes: `GET /api/periods/settings`（唯讀觀看）、`renderMonthReport`。
- Produces: admin panel（`super_admin`＝經理）新增「月結」分頁：上半**唯讀顯示**目前月結日/鎖定偏移（純文字，無輸入框、無存檔鈕——經理只有觀看權限）、下半掛 `renderMonthReport`（當期）。**經理端不提供任何編輯月結設定的 UI**（後端 PATCH 對 super_admin 也已 403）。

- [ ] **Step 1: 實作 `periods_api.js`**
```javascript
export const periodsApi = {
  async getSettings() {
    const r = await fetch('/api/periods/settings');
    return { status: r.status, data: await r.json() };
  },
  async patchSettings(body) {
    const r = await fetch('/api/periods/settings', {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return { status: r.status, data: await r.json() };
  },
  // 農曆年提早結期（會計）：改某期 end_date
  async patchEndDate(pid, endDate) {
    const r = await fetch(`/api/periods/${pid}/end-date`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ end_date: endDate }),
    });
    return { status: r.status, data: await r.json() };
  },
};
```
> 註：`patchSettings`/`patchEndDate` 只有會計會呼叫；經理端（Task 16）僅用 `getSettings` 唯讀顯示。

- [ ] **Step 2: admin.js 加分頁**

`admin.js` 頂部 import：
```javascript
import { renderMonthReport } from './month_report.js';
import { periodsApi } from './periods_api.js';
```
`tabs` 陣列（`isSuper` 段）加：
```javascript
    ...(isSuper ? [{ key: 'stores', label: '店別' }, { key: 'monthly', label: '月結' }] : []),
```
render dispatch（`if (state.tab === 'stores') ...` 附近）加：
```javascript
    else if (state.tab === 'monthly') renderMonthly(body, identity);
```
新增 `renderMonthly(container, identity)`：上半用 `periodsApi.getSettings()` 抓現值後**唯讀顯示**「月結日：D 號」「鎖定偏移：H 小時（換期日後 H 小時鎖定）」——純文字，**不放輸入框、不放存檔鈕**（經理只有觀看權限）；下方 `renderMonthReport(reportDiv, {})`（當期）。

- [ ] **Step 3: 手動驗證（本機）**

啟動 server（見結尾「本機測試」），`/dev/login-super` 進管理後台 → 點「月結」分頁 → 看到月結日/鎖定偏移唯讀顯示（無編輯 UI）＋ 月報表交叉表。

- [ ] **Step 4: Commit**
```bash
git add app/static/js/periods_api.js app/static/js/admin.js
git commit -m "feat(admin): general-manager 月結 tab (read-only settings + month report)"
```

---

## Phase G — 核銷端前端 ＋ SW

### Task 17: reconcile.js — 期間篩選／挪期／提前封月／上期未處理單 ＋ 月報表 ＋ SW bump

**Files:**
- Modify: `app/static/js/reconcile_api.js`
- Modify: `app/static/js/reconcile.js`
- Modify: `app/static/sw.js`
- Test: 更新/新增 `tests/js/reconcile.test.mjs`（純邏輯部分）；其餘手動

**Interfaces:**
- Consumes: pending 回傳的 `period`、`GET /api/reconcile/unprocessed`、`POST /api/reconcile/<id>/move-next`、`GET /api/reconcile/period/<pid>/close-preview`、`POST /api/reconcile/period/<pid>/close`、`renderMonthReport`、`GET/PATCH /api/periods/settings`（會計可編輯月結設定）。
- Produces: 會計面板加：期間下拉（切換 `period_id` 重載清單、顯示期間狀態 open/寬限/已封）、每列「挪下期」鈕（呼叫 move-next）、面板「提前封月」鈕（先 close-preview 顯示「還有 N 筆沒打勾」二次確認 → close）、「上期未處理單」入口、「月報表」入口（掛 `renderMonthReport`）、**「月結設定」編輯區**（月結日 1–28、鎖定偏移小時的輸入框 ＋ 儲存鈕 → `periodsApi.patchSettings`；初值用 `periodsApi.getSettings()`）——**編輯月結設定是會計的權限**（經理端唯讀）。

- [ ] **Step 1: reconcile_api.js 加方法**
```javascript
export const rcApi = {
  // ...既有...
  async moveNext(id) {
    const r = await fetch(`/api/reconcile/${id}/move-next`, { method: 'POST' });
    return { status: r.status, data: await r.json() };
  },
  async closePreview(pid) {
    const r = await fetch(`/api/reconcile/period/${pid}/close-preview`);
    return { status: r.status, data: await r.json() };
  },
  async closePeriod(pid) {
    const r = await fetch(`/api/reconcile/period/${pid}/close`, { method: 'POST' });
    return { status: r.status, data: await r.json() };
  },
  async unprocessed() {
    const r = await fetch('/api/reconcile/unprocessed');
    return { status: r.status, data: await r.json() };
  },
};
```
> 若既有 `rcApi` 定義在別處，於同物件追加這些方法，`pending` 增加可選 `periodId` 參數帶入 query。

- [ ] **Step 2: reconcile.js 接線**

- 讀 pending 回傳的 `period`，在面板抬頭顯示期間 label + 狀態徽章（`open`=進行中／`closing`=寬限期／`closed`=已封月）。
- 期間下拉：切換即以 `periodId` 重抓 pending。
- 每列 audited/rejected 狀態的列，加「挪下期」鈕 → `rcApi.moveNext(id)`，成功後重載；錯誤碼對應提示（`next_period_closed`→「下一期已封月」、`period_closed`→「本期已封月」）。
- 「提前封月」鈕：先 `closePreview` → 二次確認視窗顯示「這期還有 N 筆沒打勾，封月後這些單不進帳，確定要封嗎？」→ 確認後 `closePeriod`。
- 「上期未處理單」：`rcApi.unprocessed()` 列表（門店/營業日/金額/摘要/原圖 lightbox）。
- 「月報表」：`renderMonthReport(container, { periodId: 當期 })`。
- **「月結設定」編輯區**（會計權限）：以 `periodsApi.getSettings()` 帶初值，月結日（數字 1–28）與鎖定偏移（小時）輸入框 ＋ 儲存鈕呼叫 `periodsApi.patchSettings({period_close_day, period_lock_offset_hours})`；成功顯示提示、`bad_close_day`/`bad_offset` 顯示對應錯誤。`periods_api.js` 於 Task 16 已建（含 `getSettings`/`patchSettings`/`patchEndDate`），此處 import 使用。
- **「農曆年提早結期」**（會計權限，配合分兩步封月）：當期旁一個「調整結束日」動作，讓會計把當期 `end_date` 改早（呼叫 `periodsApi.patchEndDate(periodId, endDate)`＝`PATCH /api/periods/<pid>/end-date`）。改完期間進入寬限期後，才用「提前封月」鈕鎖定（見上）。`period_not_ended` 錯誤訊息要明確引導：「期間還在進行中，請先『調整結束日』把本期縮到今天／昨天，再提前封月」。
- `periods_api.js` 需補一支 `patchEndDate(pid, endDate)`（`PATCH /api/periods/${pid}/end-date`，body `{end_date}`）。
- `ERR_MSG` 補：`period_closed`（此期已封月）、`next_period_closed`（下一期已封月）、`no_period`（此單尚未歸期）、`already_closed`（已封月）、`period_not_ended`（期間進行中，請先調整結束日）、`bad_close_day`（月結日需 1–28）、`bad_offset`（鎖定偏移需 0–168 小時）、`end_before_start`（結束日不可早於起始日）、`would_invert_next`（會使下一期起訖顛倒）。

- [ ] **Step 3: 純邏輯測試（若抽出 helper）**

若把「期間狀態 → 徽章文案」抽成 `periodBadge(status)` 純函式，在 `tests/js/reconcile.test.mjs` 加：
```javascript
import { periodBadge } from '../../app/static/js/reconcile.js';
test('period badge labels', () => {
  assert.equal(periodBadge('open'), '進行中');
  assert.equal(periodBadge('closing'), '寬限期');
  assert.equal(periodBadge('closed'), '已封月');
});
```

- [ ] **Step 4: bump SW**

`app/static/sw.js`：`CACHE_NAME` 由 `'calc-v42'` 改為 `'calc-v43'`。

- [ ] **Step 5: 跑前端測試 + 手動驗證**

Run: `node --test tests/js/*.mjs`
Expected: 全 passed。
手動：`/dev/login-accountant` 進核銷面板 → 切期間、挪下期、提前封月（看 N 筆提示）、上期未處理單、月報表。

- [ ] **Step 6: Commit**
```bash
git add app/static/js/reconcile_api.js app/static/js/reconcile.js app/static/sw.js tests/js/reconcile.test.mjs
git commit -m "feat(reconcile): period filter, move-next, early close, unprocessed, month report; bump sw"
```

---

## 最終驗證

- [ ] **全測試綠**

Run: `python3 -m pytest -q && node --test tests/js/*.mjs`
Expected: 全 passed（後端在既有 471 之上新增本計畫測試；前端在既有 61 之上新增）。

- [ ] **單一 migration head**

Run: `FLASK_APP=wsgi.py python3 -m flask db heads`
Expected: 只有一個 head（Task 2 的 accounting_periods rev）。

- [ ] **本機 e2e 冒煙**（見下）：拍單→送出（落當期）→主管打勾→會計核銷→月報表看到數字；提前封月後 audited 挪下期、submitted 進「上期未處理單」；經理改月結日生效。

---

## 本機測試

啟動（背景）：
```bash
cd ~/projects/expense-report; set -a; . ./.env; set +a
E2E_LOGIN_BYPASS=1 FLASK_APP=wsgi.py python3 -m flask db upgrade
E2E_LOGIN_BYPASS=1 FLASK_APP=wsgi.py python3 -m flask run --port 5001 --no-reload
```
- 網址 `http://127.0.0.1:5001/`；改後端要重啟（`--no-reload`），改前端 bump sw + 硬重整。
- dev 捷徑：`/dev/login-test`（員工）／`/dev/login-manager`（主管）／`/dev/login-super`（經理=super_admin）／`/dev/login-accountant`（會計）／`/dev/sample-receipt`（樣本圖）。
- ⚠️ `dev.db` 那筆舊測試手動單（id=53）與既有資料 `period_id` 為 NULL，Task 8 backfill 會補上；乾淨測封月建議用新期間的新單。

---

## Self-Review 註記（寫計畫時自查）

- **spec 覆蓋**：§2.1 期間表→T2；§2.2 設定→T1/T15；§2.3 period_id→T2/T5；§3 狀態機封月擋寫→T6；§4 挪下期→T10、上期未處理單→T12；§5.1/5.2 寬限期與自動封月→T4/T7/T9；§5.3 月報表→T13/T14；§5.4 submitted 留原期＋清單→T7/T12；§6 權限（**2026-07-15 user 修正**：月結設定改為**會計編輯、經理唯讀**；核銷/封月＝會計；月報表＝會計＋經理）→T11/T13/T15/T16/T17；§7 邊界（closed 擋寫、挪期下一期不存在自動延展、下一期已封拒絕、併發只封一次、end_date 完整性）→T4/T6/T7/T10/T15；§8 測試→各 task 測試涵蓋（實作時務必補齊 spec §8 逐條，尤其**負數在月報表每格與合計、note 絕不外洩到報表/上期清單**兩條當安全測試寫）。
- **不做（§9）**：反封月、沖帳單、報表匯出（Excel/CSV/PDF）、上期比較、下鑽明細、批次退回/挪期——本計畫均未納入，符合 YAGNI。
- **農曆年提早結帳（2026-07-15 user 確認：分兩步、貼原 spec）**：機制拆成兩個獨立動作並**硬化成可安全組合**——①**調 end_date**（Task 15）把當期縮到今天/昨天，讓期間進入寬限期、並明確把下一期接上（不留孤兒日、不與 canonical 重疊）；②**提前封月**（Task 11）限「寬限期（closing）」才可封（spec §5.1），open 進行中的期不可直接封（回 `period_not_ended`，避免把剩餘日的單卡死）。兩者組合＝先縮界再封，即「即刻結帳」的正確做法。已在對應 task 補上守門與測試。
- **未納入本計畫（另案）**：被退回（`rejected`）單是否進主管逾期提醒的「N 筆待處理退回」獨立計數——屬 audit 端增強、非 spec §1–9 月結範圍，執行前需 user 拍板。
