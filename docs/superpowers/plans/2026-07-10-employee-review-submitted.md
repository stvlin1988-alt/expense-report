# 員工「複查」區（唯讀）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓員工在主管交班／結班之前，唯讀複查自己這一班已送出的單的金額。

**Architecture:** 後端加一個唯讀端點 `GET /expenses/submitted`，以「本人 + `submitted`/`audited` + `handover_id IS NULL` + `submitted_at` 晚於本店最近一次 handover」界定「當班未交/結班」的單，回傳沿用 `serialize_expense` 再補分類名。前端加一個唯讀表格畫面與一顆員工按鈕，不含任何寫入。

**Tech Stack:** Flask / SQLAlchemy（後端 pytest）、原生 ESM 前端（DOM 膠合，本機 e2e）。

## Global Constraints

- 時間 UI 一律台灣時間（DB 存 UTC）；本功能前端沿用既有 `formatDateTimeTW` 若需顯示時間。
- 前端不輪詢；複查區靠「重整」鈕重抓。
- 唯讀：不新增／不修改任何寫入端點，不動 handover 與稽核鎖定邏輯。
- 所有前端輸出的使用者資料（摘要／分類名／金額／單號）一律 `escapeHtml`（XSS）。
- spec：`docs/superpowers/specs/2026-07-10-employee-review-submitted-design.md`。

---

### Task 1: 後端 `GET /expenses/submitted` 唯讀端點

**Files:**
- Modify: `app/expenses/routes.py`（import 加 `Handover`；檔尾新增 `submitted()` 路由）
- Test: `tests/test_expense_submitted.py`（新建）

**Interfaces:**
- Consumes：既有 `current_user()`（`app/auth/decorators.py`）、`serialize_expense(e, storage, with_main=False, name_by_id=None)`（`app/expenses/serialize.py`）、`get_storage()`、model `Expense`/`Category`/`Handover`。
- Produces：HTTP `GET /expenses/submitted` → `{"status":"ok","expenses":[<serialize_expense 輸出 + "category_name">...]}`；未登入 → `401 {"status":"error","message":"unauthenticated"}`。

- [ ] **Step 1: 寫失敗測試**

新建 `tests/test_expense_submitted.py`：

```python
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from app.extensions import db
from app.models import Expense, Store, User, Device, Handover, Category
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


def _mk(sid, uid, status, amt, submitted_at, handover_id=None, day_seq=1,
        category_id=None, image_key=None):
    return Expense(store_id=sid, created_by=uid, status=status,
                   created_at=datetime.now(timezone.utc), submitted_at=submitted_at,
                   amount=Decimal(str(amt)), handover_id=handover_id, day_seq=day_seq,
                   category_id=category_id, image_key=image_key)


def test_lists_own_submitted_and_audited(app):
    r2mod._mock_singleton = None
    sid, uid, uid2 = _seed(app)
    with app.app_context():
        now = datetime.now(timezone.utc)
        db.session.add_all([
            _mk(sid, uid, "submitted", 100, now, day_seq=1),
            _mk(sid, uid, "audited", 200, now, day_seq=2),
            _mk(sid, uid, "draft", 300, None, day_seq=None),        # 不列
            _mk(sid, uid, "pending_ocr", 0, None, day_seq=None),    # 不列
            _mk(sid, uid2, "submitted", 999, now, day_seq=3),       # 他人不列
        ]); db.session.commit()
    c = _client(app, uid)
    body = c.get("/expenses/submitted").get_json()
    assert body["status"] == "ok"
    assert sorted(e["amount"] for e in body["expenses"]) == [100.0, 200.0]


def test_excludes_handed_over(app):
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        now = datetime.now(timezone.utc)
        h = Handover(store_id=sid, closed_at=now - timedelta(hours=1),
                     closed_by=uid, type="shift")
        db.session.add(h); db.session.commit()
        db.session.add(_mk(sid, uid, "audited", 100, now, handover_id=h.id, day_seq=1))
        db.session.commit()
    c = _client(app, uid)
    assert c.get("/expenses/submitted").get_json()["expenses"] == []


def test_time_boundary_clears_before_last_handover(app):
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        base = datetime.now(timezone.utc)
        h = Handover(store_id=sid, closed_at=base, closed_by=uid, type="shift")
        db.session.add(h); db.session.commit()
        db.session.add_all([
            _mk(sid, uid, "submitted", 100, base - timedelta(minutes=5), day_seq=1),  # 交班前→清
            _mk(sid, uid, "submitted", 200, base + timedelta(minutes=5), day_seq=2),  # 交班後→留
        ]); db.session.commit()
    c = _client(app, uid)
    body = c.get("/expenses/submitted").get_json()
    assert [e["amount"] for e in body["expenses"]] == [200.0]


def test_day_handover_also_clears(app):
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        base = datetime.now(timezone.utc)
        h = Handover(store_id=sid, closed_at=base, closed_by=uid, type="day")
        db.session.add(h); db.session.commit()
        db.session.add(_mk(sid, uid, "submitted", 100, base - timedelta(minutes=5), day_seq=1))
        db.session.commit()
    c = _client(app, uid)
    assert c.get("/expenses/submitted").get_json()["expenses"] == []


def test_includes_category_name_and_image_url(app):
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        cat = Category(name="餐費", level=1, sort=1, active=True)
        db.session.add(cat); db.session.commit()
        db.session.add(_mk(sid, uid, "submitted", 100, datetime.now(timezone.utc),
                           day_seq=1, category_id=cat.id, image_key="m1.jpg"))
        db.session.commit()
    c = _client(app, uid)
    row = c.get("/expenses/submitted").get_json()["expenses"][0]
    assert row["category_name"] == "餐費"
    assert "m1.jpg" in row["image_url"]


def test_unauth_401(app):
    r2mod._mock_singleton = None
    _seed(app)
    c = app.test_client(); c.set_cookie("device_uid", "devEmp")  # 裝置過閘但無 session
    assert c.get("/expenses/submitted").status_code == 401
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_expense_submitted.py -q`
Expected: FAIL（404 / route 不存在，斷言全掛）

- [ ] **Step 3: 實作端點**

在 `app/expenses/routes.py` 把 import 那行的 model 補上 `Handover`：

```python
from app.models import Expense, Category, User, AuditLog, Handover
```

在檔尾（`categories()` 之後）新增：

```python
@expense_bp.get("/submitted")
def submitted():
    """員工唯讀複查區：本人這一班已送出、主管尚未交/結班的單。
    界定＝本人 + submitted/audited + handover_id 空 + submitted_at 晚於本店最近一次 handover。
    交班與結班都建 Handover，故兩者一致地以時間界清空複查區（含主管沒核到的 submitted）。"""
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    last = (Handover.query.filter_by(store_id=user.store_id)
            .order_by(Handover.closed_at.desc(), Handover.id.desc()).first())
    q = (Expense.query
         .filter(Expense.created_by == user.id,
                 Expense.status.in_(["submitted", "audited"]),
                 Expense.handover_id.is_(None)))
    if last is not None:
        q = q.filter(Expense.submitted_at > last.closed_at)
    rows = q.order_by(Expense.day_seq.asc(), Expense.submitted_at.asc()).all()
    storage = get_storage()
    cids = {e.category_id for e in rows if e.category_id}
    cat_names = ({c.id: c.name for c in Category.query.filter(Category.id.in_(cids)).all()}
                 if cids else {})
    out = []
    for e in rows:
        d = serialize_expense(e, storage, with_main=True)
        d["category_name"] = cat_names.get(e.category_id)
        out.append(d)
    return jsonify(status="ok", expenses=out)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_expense_submitted.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: 跑全套後端測試確認無回歸**

Run: `python3 -m pytest -q`
Expected: 全綠（新增 6 筆，其餘不變）

- [ ] **Step 6: Commit**

```bash
git add app/expenses/routes.py tests/test_expense_submitted.py
git commit -m "feat(expense): 員工複查唯讀端點 GET /expenses/submitted"
```

---

### Task 2: 前端員工「複查」唯讀畫面 + 入口按鈕

**Files:**
- Modify: `app/static/js/expenses_api.js`（加 `listSubmitted`）
- Create: `app/static/js/review.js`（`showReviewView`）
- Modify: `app/static/js/auth.js`（員工區加「複查」按鈕與導覽）
- Modify: `app/static/sw.js`（快取版號 calc-v35 → calc-v36）

**Interfaces:**
- Consumes：Task 1 的 `GET /expenses/submitted`；既有 `escapeHtml`（`admin_util.js`）、`openImageLightbox`（`lightbox.js`）、`showAppView`（`auth.js`）。
- Produces：`export function showReviewView(onBack)`（`review.js`）、`export const listSubmitted`（`expenses_api.js`）。

> 說明：本 Task 為 DOM 膠合，依專案慣例無自動化 JS 測試，以本機 e2e 驗收（見 Step 6）。

- [ ] **Step 1: 加 API 函式**

在 `app/static/js/expenses_api.js` 檔尾（`getExpenseLogs` 之後）新增：

```javascript
export const listSubmitted = () => jsonFetch('/expenses/submitted');
```

- [ ] **Step 2: 新建唯讀複查畫面**

新建 `app/static/js/review.js`：

```javascript
import { escapeHtml } from './admin_util.js';
import { openImageLightbox } from './lightbox.js';
import { listSubmitted } from './expenses_api.js';

const root = () => document.getElementById('modal-root');

// 員工唯讀複查：本班已送出、主管尚未交/結班的單。只能看，不能改。
export async function showReviewView(onBack) {
  root().innerHTML = `
    <div class="modal-backdrop"><div class="modal-box wide">
      <h2>複查（本班已送出）</h2>
      <button class="modal-btn" id="rv-refresh" type="button">↻ 重整</button>
      <div id="rv-msg" class="modal-msg"></div>
      <div class="pd-table-wrap">
        <table id="rv-table"><thead><tr>
          <th>單號</th><th>圖</th><th>摘要</th><th>分類</th><th>金額</th>
        </tr></thead><tbody></tbody></table>
      </div>
      <button class="modal-btn secondary" id="rv-back" type="button">返回</button>
    </div></div>`;
  document.getElementById('rv-back').addEventListener('click', onBack);
  document.getElementById('rv-refresh').addEventListener('click', () => showReviewView(onBack));

  const { data } = await listSubmitted();
  const rows = (data && data.expenses) || [];
  const tbody = document.querySelector('#rv-table tbody');
  rows.forEach((e) => {
    const tr = document.createElement('tr');
    const thumb = e.thumb_url
      ? `<img src="${e.thumb_url}" loading="lazy" width="48" class="au-thumb" data-zoom="${e.image_url || ''}">`
      : '—';
    tr.innerHTML = `
      <td>${escapeHtml(e.doc_no || '')}</td>
      <td>${thumb}</td>
      <td>${escapeHtml(e.summary || '')}</td>
      <td>${escapeHtml(e.category_name || '')}</td>
      <td>${e.amount ?? ''}</td>`;
    const thumbEl = tr.querySelector('.au-thumb');
    if (thumbEl && thumbEl.dataset.zoom) {
      thumbEl.addEventListener('click', () => openImageLightbox(thumbEl.dataset.zoom));
    }
    tbody.appendChild(tr);
  });
  if (!rows.length) {
    document.getElementById('rv-msg').textContent = '本班沒有已送出的單';
  }
}
```

- [ ] **Step 3: 員工區加入口按鈕**

在 `app/static/js/auth.js`：

（a）檔首 import 區，`showPendingView` import 之後加：

```javascript
import { showReviewView } from './review.js';
```

（b）`showAppView` 的 template，於「確認區」按鈕那行之後加一顆複查鈕（同樣只給員工）：

```javascript
        ${isEmployee ? '<button class="modal-btn" id="av-pending" type="button">確認區</button>' : ''}
        ${isEmployee ? '<button class="modal-btn" id="av-review" type="button">複查</button>' : ''}
```

（c）`if (isEmployee) { ... }` 區塊內，`av-pending` 綁定之後加：

```javascript
    document.getElementById('av-review').addEventListener('click', () => {
      cam.stop();
      showReviewView(() => showAppView(identity));
    });
```

- [ ] **Step 4: bump service worker 快取版號**

在 `app/static/sw.js` 把 `calc-v35` 改成 `calc-v36`（CACHE_NAME 那行）。

Run: `grep -n "calc-v36" app/static/sw.js`
Expected: 印出含 `calc-v36` 的那行

- [ ] **Step 5: 前端無回歸快檢（既有 JS 純邏輯測試）**

Run: `node --test tests/js/*.mjs`
Expected: 全綠（本 Task 未動純邏輯模組，數量不變）

- [ ] **Step 6: 本機 e2e 驗收**

啟動（見 spec / 記憶啟動指令）：
```bash
cd ~/projects/expense-report
set -a; . ./.env; set +a
E2E_LOGIN_BYPASS=1 FLASK_APP=wsgi.py python3 -m flask db upgrade
E2E_LOGIN_BYPASS=1 FLASK_APP=wsgi.py python3 -m flask run --port 5001 --no-reload
```
驗收步驟（瀏覽器硬重整讓 sw 換新版）：
1. `/dev/login-test`（員工）→ 拍單（`/dev/sample-receipt`）→ 確認區送出 1~2 筆。
2. 回主畫面按「複查」→ 應看到剛送出的單（單號/圖可放大/摘要/分類名/金額），**無任何輸入框或編輯鈕**。
3. `/dev/login-manager`（主管，同店）→ 稽核打勾 → 交班。
4. 回員工「複查」按「↻ 重整」→ 該班單應**清空**（顯示「本班沒有已送出的單」）。
5. 另驗結班：員工再送出新單 → 主管稽核 → 結班 → 員工複查重整應同樣清空。

- [ ] **Step 7: Commit**

```bash
git add app/static/js/expenses_api.js app/static/js/review.js app/static/js/auth.js app/static/sw.js
git commit -m "feat(expense-ui): 員工複查唯讀畫面 + 入口按鈕 + sw calc-v36"
```

---

## 完成後

- 全套 `python3 -m pytest -q` + `node --test tests/js/*.mjs` 綠。
- user 本機 e2e 驗收 OK。
- user 明說才 fast-forward merge 回 master、不 push（依專案慣例）。
