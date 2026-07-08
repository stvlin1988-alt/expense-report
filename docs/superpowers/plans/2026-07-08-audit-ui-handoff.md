# 稽核 UI 交接核對強化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 補齊稽核 UI 交接核對所需：單據顯示建立時間、當日總表 inline 展開看每班明細（含稽核者/稽核時間/主管改過標記）、翻閱歷史稽核日、放大看原單、暫存區重整鈕+辨識中標示。

**Architecture:** 後端新增明細序列化 `serialize_audit_item`（疊在 `serialize_expense` 上，補稽核欄位+原圖 URL+分類名）與三個唯讀端點（某班明細 / 當前未歸班明細 / 歷史結班日清單）；`/audit/pending` 改用同序列化以取得原圖 URL。前端在 `admin_audit.js` 加建立時間欄、inline 展開明細、歷史日下拉、放大原圖 lightbox；`pending.js` 加重整鈕+辨識中標示。時間一律台灣時間、純函式格式化。

**Tech Stack:** Flask / Flask-SQLAlchemy 2.0 / pytest；前端 ESM + `node --test`。系統 python3.12，無 venv。

依據 spec：`docs/superpowers/specs/2026-07-08-audit-ui-handoff-design.md`。

## Global Constraints

- 時間 UI 一律台灣時間（Asia/Taipei）顯示，DB 存 UTC；時間格式化用純函式（`node --test`）。
- per-store scope 沿用 `_scope_store_id`（manager 本店 / super_admin 需 store_id）；跨店 403、找不到 404。
- 前端不輪詢：暫存區靠「重整」鈕手動刷新，不加輪詢/cron。
- 影像不落地：放大原圖用 R2 presigned URL（`serialize_expense(..., with_main=True)` 的 `image_url`）。
- 不新增 Python 依賴。
- 每次改前端 JS/CSS 必 bump `app/static/sw.js` 的 `CACHE_NAME`（現值 `calc-v20`）。
- 沿用回傳慣例 `jsonify(status="ok", ...)`；沿用既有 `serialize_expense`、`@role_required`、`current_user()`。
- 疊在 branch `feat/phase1-audit` 上（不另開 branch）。

---

### Task 1: 明細序列化 + 某班/當前未歸班明細端點 + pending 改用

**Files:**
- Create: `app/audit/serialize.py`
- Modify: `app/audit/routes.py`（import、`_audit_maps` helper、兩端點、`pending()` 改用）
- Test: `tests/test_audit_items.py`

**Interfaces:**
- Produces:
  - `serialize_audit_item(e, storage, actor_name_by_id, cat_name_by_id) -> dict`：`serialize_expense(e, storage, with_main=True)` 疊加 `audited_by`、`audited_by_name`、`audited_at`(iso|None)、`is_modified_by_manager`、`business_date`(iso|None)、`category_name`。
  - `GET /audit/handover/<int:hid>/items`：回 `{status:"ok", items:[...]}`（該 handover 的單，scope 驗證）。
  - `GET /audit/open-items`：回 `{status:"ok", items:[...]}`（`audited 且 handover_id IS NULL`）。
  - `pending()` 的 items 改用 `serialize_audit_item`（取得 image_url）。

- [ ] **Step 1: 寫失敗測試**

`tests/test_audit_items.py`：
```python
import time
from datetime import datetime, timezone, date
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense, Handover, Category


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); s2 = Store(name="B", code="B")
        db.session.add_all([s, s2]); db.session.commit()
        mgr = User(name="小王", role="manager", store_id=s.id); mgr.set_password("1234")
        emp = User(name="員工", role="employee", store_id=s.id); emp.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        cat = Category(name="食材", level=2, sort=1)
        db.session.add_all([mgr, emp, dev, cat]); db.session.commit()
        now = datetime.now(timezone.utc)
        h = Handover(store_id=s.id, closed_at=now, closed_by=mgr.id, type="shift")
        hb = Handover(store_id=s2.id, closed_at=now, closed_by=mgr.id, type="shift")
        db.session.add_all([h, hb]); db.session.commit()
        # 已歸班（屬 h）
        e1 = Expense(store_id=s.id, created_by=emp.id, status="audited", created_at=now,
                     business_date=date(2026, 7, 8), amount=Decimal("100"), category_id=cat.id,
                     audited_by=mgr.id, audited_at=now, is_modified_by_manager=True, handover_id=h.id)
        # 當前未歸班（audited, handover_id null）
        e2 = Expense(store_id=s.id, created_by=emp.id, status="audited", created_at=now,
                     amount=Decimal("50"), audited_by=mgr.id, audited_at=now, handover_id=None)
        db.session.add_all([e1, e2]); db.session.commit()
        return mgr.id, s.id, h.id, hb.id, e1.id, e2.id


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_handover_items(app):
    mgr_id, sid, hid, _, e1, _ = _seed(app)
    body = _client(app, mgr_id).get(f"/audit/handover/{hid}/items").get_json()
    assert body["status"] == "ok" and len(body["items"]) == 1
    it = body["items"][0]
    assert it["id"] == e1 and it["audited_by_name"] == "小王"
    assert it["is_modified_by_manager"] is True and it["category_name"] == "食材"
    assert "image_url" in it and it["audited_at"] is not None


def test_handover_items_cross_store_forbidden(app):
    mgr_id, sid, _, hb, _, _ = _seed(app)
    assert _client(app, mgr_id).get(f"/audit/handover/{hb}/items").status_code == 403


def test_handover_items_not_found_404(app):
    mgr_id, sid, _, _, _, _ = _seed(app)
    assert _client(app, mgr_id).get("/audit/handover/9999/items").status_code == 404


def test_open_items_only_audited_unassigned(app):
    mgr_id, sid, _, _, _, e2 = _seed(app)
    body = _client(app, mgr_id).get("/audit/open-items").get_json()
    assert body["status"] == "ok"
    assert [it["id"] for it in body["items"]] == [e2]   # 只回當前未歸班那筆
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_audit_items.py -q`
Expected: FAIL（404，端點不存在）

- [ ] **Step 3: 建 serialize_audit_item**

`app/audit/serialize.py`：
```python
from app.expenses.serialize import serialize_expense


def serialize_audit_item(e, storage, actor_name_by_id, cat_name_by_id):
    d = serialize_expense(e, storage, with_main=True)
    d["audited_by"] = e.audited_by
    d["audited_by_name"] = actor_name_by_id.get(e.audited_by)
    d["audited_at"] = e.audited_at.isoformat() if e.audited_at else None
    d["is_modified_by_manager"] = e.is_modified_by_manager
    d["business_date"] = e.business_date.isoformat() if e.business_date else None
    d["category_name"] = cat_name_by_id.get(e.category_id)
    return d
```

- [ ] **Step 4: routes.py 加 helper + 兩端點 + pending 改用**

`app/audit/routes.py`：檔頭 import 補：
```python
from app.models import User, Category
from app.audit.serialize import serialize_audit_item
```
加 helper（放 `_load_in_scope` 附近）：
```python
def _audit_maps(expenses):
    uids = {e.audited_by for e in expenses if e.audited_by}
    cids = {e.category_id for e in expenses if e.category_id}
    names = {u.id: u.name for u in User.query.filter(User.id.in_(uids)).all()} if uids else {}
    cats = {c.id: c.name for c in Category.query.filter(Category.id.in_(cids)).all()} if cids else {}
    return names, cats
```
在 `pending()` 內，把序列化那行改成（先建 maps）：
```python
        storage = get_storage()
        names, cats = _audit_maps(items)
        out.append({
            "business_date": bd, "subtotal": subtotal,
            "items": [serialize_audit_item(x, storage, names, cats) for x in items],
        })
```
（原本 `serialize_expense(x, storage)`；`items` 為該組清單。`storage = get_storage()` 已在 pending 內、保留。）
加兩個端點（放檔案末）：
```python
@audit_bp.get("/handover/<int:hid>/items")
@role_required("manager", "super_admin")
def handover_items(hid):
    store_id, err = _scope_store_id()
    if err:
        return err
    h = db.session.get(Handover, hid)
    if h is None:
        return jsonify(status="error", message="not found"), 404
    if h.store_id != store_id:
        return jsonify(status="error", message="forbidden"), 403
    rows = (Expense.query
            .filter_by(store_id=store_id, handover_id=hid)
            .order_by(Expense.submitted_at.asc(), Expense.created_at.asc()).all())
    storage = get_storage()
    names, cats = _audit_maps(rows)
    return jsonify(status="ok",
                   items=[serialize_audit_item(e, storage, names, cats) for e in rows])


@audit_bp.get("/open-items")
@role_required("manager", "super_admin")
def open_items():
    store_id, err = _scope_store_id()
    if err:
        return err
    rows = (Expense.query
            .filter(Expense.store_id == store_id, Expense.status == "audited",
                    Expense.handover_id.is_(None))
            .order_by(Expense.audited_at.asc()).all())
    storage = get_storage()
    names, cats = _audit_maps(rows)
    return jsonify(status="ok",
                   items=[serialize_audit_item(e, storage, names, cats) for e in rows])
```

- [ ] **Step 5: 跑測試 + 回歸**

Run:
```bash
python3 -m pytest tests/test_audit_items.py tests/test_audit_pending.py -q && python3 -m pytest -q
```
Expected: PASS（`test_audit_pending` 仍過——`serialize_audit_item` 為 `serialize_expense` 超集，原斷言不受影響）。

- [ ] **Step 6: commit**

```bash
git add app/audit/serialize.py app/audit/routes.py tests/test_audit_items.py
git commit -m "feat(audit): serialize_audit_item + 某班/當前未歸班明細端點 + pending 帶原圖URL"
```

---

### Task 2: 歷史結班日清單端點

**Files:**
- Modify: `app/audit/routes.py`
- Test: `tests/test_audit_days.py`

**Interfaces:**
- Produces: `GET /audit/days`：回 `{status:"ok", days:[{handover_id, closed_at}]}`（該店 `type='day'`，`closed_at desc`）。

- [ ] **Step 1: 寫失敗測試**

`tests/test_audit_days.py`：
```python
import time
from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models import Store, User, Device, Handover


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        mgr = User(name="mgr", role="manager", store_id=s.id); mgr.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add_all([mgr, dev]); db.session.commit()
        base = datetime(2026, 7, 6, 10, tzinfo=timezone.utc)
        d1 = Handover(store_id=s.id, closed_at=base, closed_by=mgr.id, type="day")
        sh = Handover(store_id=s.id, closed_at=base + timedelta(hours=5), closed_by=mgr.id, type="shift")
        d2 = Handover(store_id=s.id, closed_at=base + timedelta(days=1), closed_by=mgr.id, type="day")
        db.session.add_all([d1, sh, d2]); db.session.commit()
        return mgr.id, d1.id, d2.id


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_days_only_day_type_desc(app):
    mgr_id, d1, d2 = _seed(app)
    body = _client(app, mgr_id).get("/audit/days").get_json()
    assert body["status"] == "ok"
    ids = [d["handover_id"] for d in body["days"]]
    assert ids == [d2, d1]          # 只含 type=day，closed_at desc；不含 shift
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_audit_days.py -q`
Expected: FAIL（404）

- [ ] **Step 3: 加端點**

`app/audit/routes.py` 末加：
```python
@audit_bp.get("/days")
@role_required("manager", "super_admin")
def days():
    store_id, err = _scope_store_id()
    if err:
        return err
    rows = (Handover.query
            .filter_by(store_id=store_id, type="day")
            .order_by(Handover.closed_at.desc(), Handover.id.desc()).all())
    return jsonify(status="ok",
                   days=[{"handover_id": h.id, "closed_at": h.closed_at.isoformat()} for h in rows])
```

- [ ] **Step 4: 跑測試 + commit**

Run: `python3 -m pytest tests/test_audit_days.py -q`
Expected: PASS
```bash
git add app/audit/routes.py tests/test_audit_days.py
git commit -m "feat(audit): GET /audit/days 歷史結班日清單(供翻閱下拉)"
```

---

### Task 3: 前端 — 建立時間欄 + 放大原圖 lightbox + 時間純函式 + api 方法

**Files:**
- Modify: `app/static/js/audit_util.js`（`formatDateTimeTW`）
- Modify: `app/static/js/admin_api.js`（3 方法）
- Modify: `app/static/js/admin_audit.js`（建立時間欄、縮圖可放大、lightbox）
- Modify: `app/static/css/app.css`（lightbox、可點縮圖）
- Modify: `app/static/sw.js`（bump）
- Test: `tests/js/audit.mjs`（補 `formatDateTimeTW`）

**Interfaces:**
- Produces:
  - `formatDateTimeTW(iso) -> "MM/DD HH:mm" | "—"`（Asia/Taipei）
  - `api.auditHandoverItems(hid, storeId)` / `api.auditOpenItems(storeId)` / `api.auditDays(storeId)`
  - `openImageLightbox(url)`（admin_audit.js 內部）
- Consumes（Task 4）：上述皆供 Task 4 的展開明細/歷史下拉使用。

- [ ] **Step 1: 寫純邏輯失敗測試**

`tests/js/audit.mjs` 追加（保留既有 `formatMoney` 測試）：
```javascript
import { formatMoney, formatDateTimeTW } from '../../app/static/js/audit_util.js';

test('formatDateTimeTW Asia/Taipei', () => {
  // 2026-07-08T06:23:00Z = 台灣 14:23
  assert.equal(formatDateTimeTW('2026-07-08T06:23:00Z'), '07/08 14:23');
});
test('formatDateTimeTW null/空', () => {
  assert.equal(formatDateTimeTW(null), '—');
  assert.equal(formatDateTimeTW(''), '—');
});
```
（若檔案原本 `import { formatMoney } ...`，改成一併 import `formatDateTimeTW`。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `node --test tests/js/audit.mjs`
Expected: FAIL（`formatDateTimeTW` 未匯出）

- [ ] **Step 3: 加 formatDateTimeTW**

`app/static/js/audit_util.js` 末加：
```javascript
export function formatDateTimeTW(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Taipei', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(d);
  const g = (t) => (parts.find((x) => x.type === t) || {}).value;
  return `${g('month')}/${g('day')} ${g('hour')}:${g('minute')}`;
}
```
（Node 13+ 內建 full-ICU，`Asia/Taipei` 可用；既有 `renderSummary` 已用同 timeZone。）

- [ ] **Step 4: 跑測試確認通過**

Run: `node --test tests/js/audit.mjs`
Expected: PASS

- [ ] **Step 5: admin_api 加 3 方法**

`app/static/js/admin_api.js` 於 `api` 物件內加（沿用 `req`/`withStore`）：
```javascript
  auditHandoverItems: (hid, storeId) => req('GET', withStore(`/audit/handover/${hid}/items`, storeId)),
  auditOpenItems: (storeId) => req('GET', withStore('/audit/open-items', storeId)),
  auditDays: (storeId) => req('GET', withStore('/audit/days', storeId)),
```

- [ ] **Step 6: admin_audit.js — 建立時間欄 + 縮圖可放大 + lightbox**

`app/static/js/admin_audit.js`：
- 檔頭 import 併入 `formatDateTimeTW`：`import { formatMoney, formatDateTimeTW } from './audit_util.js';`
- `renderPending` 的表頭 `<tr>` 加一欄「建立」（在「摘要」前）：
```javascript
        <thead><tr><th>圖</th><th>建立</th><th>摘要</th><th>分類</th><th>金額</th><th>燈</th><th></th></tr></thead>
```
- `rowHtml(e, tree)` 改：縮圖可放大、加建立時間欄：
```javascript
function rowHtml(e, tree) {
  const thumb = e.thumb_url
    ? `<img src="${e.thumb_url}" loading="lazy" width="48" class="au-thumb" data-zoom="${e.image_url || ''}">`
    : '—';
  return `<tr data-id="${e.id}">
    <td>${thumb}</td>
    <td class="au-time">${formatDateTimeTW(e.created_at)}</td>
    <td>${escapeHtml(e.summary || '')}</td>
    <td><select data-f="category">${categoryOptionsHtml(tree, e.category_id)}</select></td>
    <td><input value="${e.amount ?? ''}" inputmode="decimal" data-f="amount" style="width:80px"></td>
    <td>${lightLabel(e.light)}</td>
    <td><button data-act="check">打勾</button><div class="pd-row-err" data-f="err"></div></td>
  </tr>`;
}
```
- 在 `wireRows(body, sid)` 迴圈內，綁縮圖放大：
```javascript
    const thumbEl = tr.querySelector('.au-thumb');
    if (thumbEl) thumbEl.addEventListener('click', () => openImageLightbox(thumbEl.dataset.zoom));
```
- 檔案末加 lightbox：
```javascript
export function openImageLightbox(url) {
  if (!url) return;
  const ov = document.createElement('div');
  ov.className = 'au-lightbox';
  const img = document.createElement('img');
  img.src = url; img.alt = '原單';
  ov.appendChild(img);
  const close = () => { ov.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = (ev) => { if (ev.key === 'Escape') close(); };
  ov.addEventListener('click', close);
  document.addEventListener('keydown', onKey);
  document.body.appendChild(ov);
}
```
（`openImageLightbox` export 供 Task 4 明細縮圖共用。）

- [ ] **Step 7: CSS + bump sw**

`app/static/css/app.css` 加：
```css
.au-thumb { cursor: zoom-in; }
.au-time { white-space: nowrap; color: #666; font-size: .85rem; }
.au-lightbox { position: fixed; inset: 0; background: rgba(0,0,0,.8); display: flex;
  align-items: center; justify-content: center; z-index: 1000; cursor: zoom-out; }
.au-lightbox img { max-width: 92vw; max-height: 92vh; box-shadow: 0 4px 24px rgba(0,0,0,.5); }
```
`app/static/sw.js`：`CACHE_NAME` `calc-v20` → `calc-v21`。

- [ ] **Step 8: 前端測試 + 後端回歸 + commit**

Run:
```bash
node --test tests/js/*.mjs && python3 -m pytest -q
```
Expected: PASS
```bash
git add app/static/js/audit_util.js app/static/js/admin_api.js app/static/js/admin_audit.js app/static/css/app.css app/static/sw.js tests/js/audit.mjs
git commit -m "feat(audit-ui): 待稽核建立時間欄 + 放大原圖 lightbox + formatDateTimeTW + api 方法"
```

---

### Task 4: 前端 — 當日總表 inline 展開明細 + 歷史稽核日下拉

**Files:**
- Modify: `app/static/js/admin_audit.js`（`renderSummary` + `toggleDetail`）
- Modify: `app/static/css/app.css`（展開子表、下拉、改過標記）
- Modify: `app/static/sw.js`（bump）
- Test: 手動 e2e

**Interfaces:**
- Consumes: `api.auditDays`, `api.auditSummary(sid, before)`, `api.auditHandoverItems`, `api.auditOpenItems`, `openImageLightbox`, `formatDateTimeTW`
- Produces: `renderSummary(body, sid, beforeId)`（beforeId 省略＝今日）；每班/當前未歸班可 inline 展開。

- [ ] **Step 1: 改寫 renderSummary（下拉 + 可展開列）**

`app/static/js/admin_audit.js` 把 `renderSummary` 換成：
```javascript
async function renderSummary(body, sid, beforeId) {
  body.innerHTML = '載入中…';
  const [{ data: daysData }, { data }] = await Promise.all([
    api.auditDays(sid), api.auditSummary(sid, beforeId || undefined),
  ]);
  const days = (daysData && daysData.days) || [];
  const cur = String(beforeId || '');
  const dayOpts = ['<option value="">今日（當前）</option>'].concat(
    days.map((d) => `<option value="${d.handover_id}"${String(d.handover_id) === cur ? ' selected' : ''}>${formatDateTimeTW(d.closed_at)}</option>`)
  ).join('');
  const intervals = data.intervals || [];
  const open = data.open || { subtotal: 0, count: 0 };
  const intervalRows = intervals.map((it) => `
    <tr class="au-int" data-hid="${it.handover_id}">
      <td>第 ${it.seq} 班${it.type === 'day' ? '（結班）' : ''} ▸</td>
      <td>${formatDateTimeTW(it.closed_at)}</td>
      <td>${it.count} 筆</td><td>${formatMoney(it.subtotal)}</td>
    </tr>`).join('');
  const openRow = beforeId ? '' : `
    <tr class="au-int au-open-row" data-open="1">
      <td>當前未歸班 ▸</td><td>—</td><td>${open.count} 筆</td><td>${formatMoney(open.subtotal)}</td>
    </tr>`;
  body.innerHTML = `
    <div class="au-day-nav">稽核日：<select id="au-day-select">${dayOpts}</select></div>
    <table class="pd-table"><thead><tr><th>區間</th><th>交班時間</th><th>筆數</th><th>小計</th></tr></thead>
    <tbody>${intervalRows}${openRow}</tbody>
    <tfoot><tr><td colspan="3"><b>當日總額</b></td><td><b>${formatMoney(data.day_total)}</b></td></tr></tfoot>
    </table>`;
  body.querySelector('#au-day-select').addEventListener('change',
    (ev) => renderSummary(body, sid, ev.target.value));
  body.querySelectorAll('tr.au-int').forEach((tr) =>
    tr.addEventListener('click', () => toggleDetail(tr, sid)));
}

async function toggleDetail(tr, sid) {
  const next = tr.nextElementSibling;
  if (next && next.classList.contains('au-detail')) { next.remove(); return; }
  // 收合其他已展開的明細（一次只開一個）
  tr.parentElement.querySelectorAll('tr.au-detail').forEach((r) => r.remove());
  const detailTr = document.createElement('tr');
  detailTr.className = 'au-detail';
  detailTr.innerHTML = '<td colspan="4">載入中…</td>';
  tr.after(detailTr);
  const hid = tr.dataset.hid;
  const { data } = hid ? await api.auditHandoverItems(hid, sid) : await api.auditOpenItems(sid);
  const items = (data && data.items) || [];
  const cell = detailTr.querySelector('td');
  if (!items.length) { cell.textContent = '（無明細）'; return; }
  cell.innerHTML = `
    <table class="au-detail-table"><thead><tr>
      <th>建立</th><th>圖</th><th>摘要</th><th>分類</th><th>金額</th><th>燈</th><th>稽核者</th><th>稽核時間</th>
    </tr></thead><tbody>
    ${items.map((e) => `
      <tr>
        <td class="au-time">${formatDateTimeTW(e.created_at)}</td>
        <td>${e.thumb_url ? `<img src="${e.thumb_url}" width="40" class="au-thumb" data-zoom="${e.image_url || ''}">` : '—'}</td>
        <td>${escapeHtml(e.summary || '')}</td>
        <td>${escapeHtml(e.category_name || '')}</td>
        <td>${e.amount ?? ''}${e.is_modified_by_manager ? ' <span class="au-mod">主管改</span>' : ''}</td>
        <td>${lightLabel(e.light)}</td>
        <td>${escapeHtml(e.audited_by_name || '')}</td>
        <td class="au-time">${formatDateTimeTW(e.audited_at)}</td>
      </tr>`).join('')}
    </tbody></table>`;
  cell.querySelectorAll('.au-thumb').forEach((img) =>
    img.addEventListener('click', (ev) => { ev.stopPropagation(); openImageLightbox(img.dataset.zoom); }));
}
```
註：`toggleDetail` 內縮圖點擊 `stopPropagation` 避免冒泡到列的收合。`escapeHtml`、`lightLabel` 已 import（Task 9 既有）。

- [ ] **Step 2: CSS + bump sw**

`app/static/css/app.css` 加：
```css
.au-day-nav { margin: 8px 0; font-size: .9rem; }
.au-day-nav select { font-size: 16px; padding: 4px; }
tr.au-int { cursor: pointer; }
tr.au-int:hover { background: #f5faff; }
.au-detail > td { background: #fafafa; padding: 8px; }
.au-detail-table { width: 100%; border-collapse: collapse; font-size: .85rem; }
.au-detail-table th, .au-detail-table td { border-bottom: 1px solid #eee; padding: 4px 6px; text-align: left; }
.au-mod { color: #d17b00; font-size: .75rem; border: 1px solid #d17b00; border-radius: 3px; padding: 0 3px; }
```
`app/static/sw.js`：`CACHE_NAME` `calc-v21` → `calc-v22`。

- [ ] **Step 3: 前端回歸 + 手動 e2e**

Run: `node --test tests/js/*.mjs && python3 -m pytest -q`（皆綠）。
手動：`/dev/login-manager` → 稽核 → 當日總表：
- 稽核日下拉：今日 / 各結班日切換，數字對。
- 點某班/當前未歸班 → 就地展開明細（建立時間/縮圖/摘要/分類/金額/燈/稽核者/稽核時間/主管改標記）；再點收合；縮圖點開放大。

- [ ] **Step 4: commit**

```bash
git add app/static/js/admin_audit.js app/static/css/app.css app/static/sw.js
git commit -m "feat(audit-ui): 當日總表 inline 展開每班明細 + 歷史稽核日下拉"
```

---

### Task 5: 前端 — 暫存區重整鈕 + 辨識中標示

**Files:**
- Modify: `app/static/js/pending.js`
- Modify: `app/static/css/app.css`（辨識中樣式，可選）
- Modify: `app/static/sw.js`（bump）
- Test: 手動 e2e

**Interfaces:**
- Consumes: 既有 `showPendingView(onBack)`
- Produces: 暫存區標題列「重整」鈕；`pending_ocr` 列顯示「🕓 辨識中…」。

- [ ] **Step 1: pending.js 加重整鈕 + 辨識中**

`app/static/js/pending.js`：
- 在標題區（`<h2>暫存區</h2>` 之後、`pd-noreceipt` 鈕附近）加重整鈕：
```javascript
      <h2>暫存區</h2>
      <button class="modal-btn" id="pd-refresh" type="button">↻ 重整</button>
      <button class="modal-btn" id="pd-noreceipt" type="button">＋無單據建帳</button>
```
- `document.getElementById('pd-back')...` 之後，綁重整：
```javascript
  document.getElementById('pd-refresh').addEventListener('click', () => showPendingView(onBack));
```
- 每列組裝時，`pending_ocr` 列在摘要欄顯示辨識中提示。把摘要 `<td>` 改為：
```javascript
      <td>${e.status === 'pending_ocr'
        ? '<span class="pd-ocring">🕓 辨識中…（稍後按重整）</span>'
        : `<input value="${escapeHtml(e.summary || '')}" data-f="summary">`}</td>
```
（`pending_ocr` 列本就無可編輯資料；顯示提示即可。其餘 draft 列不變。）

- [ ] **Step 2: CSS + bump sw**

`app/static/css/app.css` 加：
```css
.pd-ocring { color: #888; font-size: .85rem; }
```
`app/static/sw.js`：`CACHE_NAME` `calc-v22` → `calc-v23`。

- [ ] **Step 3: 前端回歸 + 手動 e2e**

Run: `node --test tests/js/*.mjs && python3 -m pytest -q`（皆綠——本 task 未動純邏輯模組）。
手動：`/dev/login-test` → 拍單 → 暫存區立刻看到該列「🕓 辨識中…」→ 按「↻ 重整」→ 幾秒後顯示辨識結果（金額）。

- [ ] **Step 4: commit**

```bash
git add app/static/js/pending.js app/static/css/app.css app/static/sw.js
git commit -m "feat(expense-ui): 暫存區重整鈕 + pending_ocr 辨識中標示"
```

---

## Self-Review 檢核（已於撰寫後執行）

- **Spec coverage**：建立時間(T3,T4)、當日總表展開明細(T4+後端 T1)、歷史稽核日下拉(T4+後端 T2)、放大原圖(T3 lightbox+T4 明細)、暫存區重整+辨識中(T5)、明細顯示稽核者/時間/主管改過(T1 序列化+T4 顯示) 皆有對應。
- **型別一致**：`serialize_audit_item`(4 參數)、`_audit_maps`(回 names,cats)、`auditHandoverItems/auditOpenItems/auditDays`、`formatDateTimeTW`、`openImageLightbox`、`renderSummary(body,sid,beforeId)`、`toggleDetail(tr,sid)` 跨 task 命名一致。`req` 回 `{status,data}`、`withStore` 附 `?store_id=`（沿用既有）。
- **回歸**：T1 改 `pending()` 序列化為超集 → `test_audit_pending` 不受影響（Step 5 明列一起跑）。前端 lightbox/展開為新增，不動既有打勾/交班邏輯。
- **鐵律**：時間台灣（formatDateTimeTW 純函式+測試）；不輪詢（重整鈕）；影像 presigned（image_url）；無新 Python 依賴；每個前端 task bump sw（v20→v21→v22→v23）。
- **無 placeholder**：各 step 附實際程式碼與指令。
- **注意**：T3 `tests/js/audit.mjs` 既有 import 行需併入 `formatDateTimeTW`；`admin_audit.js` 的 `escapeHtml`/`lightLabel`/`categoryOptionsHtml` 於 Task 9 已 import，T4 沿用。
