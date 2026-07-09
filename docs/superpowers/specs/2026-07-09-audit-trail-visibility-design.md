# 稽核軌跡可視化 + 操作記錄查詢頁 設計（audit trail visibility）

> Phase 1 稽核（Plan 5/7）的軌跡補強。緣起＝user 要確認「員工新建/修改單據看得到是誰做的、主管簽核也要在單子上備註」，並要一個獨立頁籤集中查修改 log。從 master 開 branch 走 SDD。

## 1. 背景

系統目前**資料層幾乎全都有記**，但**記了卻沒顯示 / 沒地方查**：

- `expenses.created_by` 有存建立者，但 `serialize_expense` 沒回、前端只顯示建立「時間」不顯示建立「者」。
- `AuditLog` 完整記錄每次金額/分類改動（`actor_user_id` + `before_json`/`after_json` + `ts`，員工確認區改、主管稽核改都寫），但**整個 codebase 沒有任何讀出 AuditLog 的 API 或 UI**——只進不出。
- 單子上只有 `is_modified_by_user` / `is_modified_by_manager` 兩個布林旗標（燈號/「主管改」標記），只知道被改過，看不到誰改、幾點改。
- 主管簽核（`audited_by`/`audited_at`）已在「當日總表」明細顯示「稽核者」欄——**這塊已達要求，不動**。

## 2. 範圍（要做）

1. **建立者上單**：`serialize_expense` 補建立者姓名；員工確認區、主管稽核清單/總表列上顯示建立者。
2. **最後修改者 + 時間**：單子上顯示「最後修改：X（時間）」（只有改過才顯示，不分角色只顯示最後一次）。
3. **每單展開軌跡**：員工確認區、主管稽核列上可點開看該單完整軌跡（誰、幾點、動作＝修改/簽核）。兩端共用一個端點。
4. **獨立「操作記錄」查詢頁籤**：後台新增頁籤，manager（本店）/ super_admin（調店選單一店）可看，employee 不可見。依**日期** + **員工**篩選，列出全店操作記錄（誰、幾點、哪張單、動作）。

## 3. 範圍外（不做，YAGNI / 屬後續階段）

- 不追蹤 summary（摘要）/ no_receipt_reason 改動——只追蹤金額 + 分類（沿用現有 `AuditLog` 粒度）。
- 軌跡/log **不顯示 before→after 具體值**——只顯示誰、幾點、動作。
- 精簡行**不分**「員工最後改 / 主管最後改」兩行——只顯示最後一次。
- 操作記錄頁**不做**依單號/依動作類型篩選（只做日期 + 員工）。
- 會計核銷紅綠燈、月結/Dashboard、退回/駁回、搜尋全文——後續階段。

## 4. 鐵律 / 約束

- 時間 UI 一律台灣時間（Asia/Taipei）顯示，DB 存 UTC。時間格式化用純函式（`formatDateTimeTW` 已有，可 `node --test`）；後端時間欄一律 `iso_utc()` 補 UTC 標記。
- per-store scope 沿用 audit 既有 `_scope_store_id()`（`app/audit/routes.py`）：manager 用本店、super_admin 需帶 `store_id`（GET 讀 query）；缺→400、跨店→403。
- 前端不輪詢：軌跡展開、操作記錄查詢皆按需（點擊/選日期）呼叫，不輪詢、不 cron。
- 不新增 Python 依賴。
- 每次改前端 JS/CSS 必 bump `app/static/sw.js` 的 `CACHE_NAME`。
- 沿用回傳慣例 `jsonify(status="ok", ...)`；沿用既有 `serialize_expense` / `serialize_audit_item`。
- 冗餘欄位 migration：nullable FK + timestamp，**無 Boolean server_default 的雷**（Plan 5/6 的 `sa.false()` 教訓不適用）。

## 5. 資料層

### 5.1 `expenses` 加兩冗餘欄
```
last_modified_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
last_modified_at = db.Column(db.DateTime(timezone=True), nullable=True)
```
一支 alembic migration（跟 `audited_by`/`audited_at` 同型別、同 pattern）。

### 5.2 寫入點：`log_edit_if_changed` 同步蓋欄
`app/audit/log.py` 的 `log_edit_if_changed(expense, actor_user_id, before)`：當**真的有寫 edit**（`after != before`）時，除了 `db.session.add(AuditLog(...))`，同步：
```
expense.last_modified_by = actor_user_id
expense.last_modified_at = ts   # 與該筆 AuditLog.ts 同一時戳
```
員工確認區 PATCH（`app/expenses/routes.py`）與主管稽核 PATCH（`app/audit/routes.py`）都經過此 helper，自然涵蓋兩端。**簽核（`record_check`）不算修改，不蓋 last_modified。**

### 5.3 `serialize_expense` 補三欄
`app/expenses/serialize.py` `serialize_expense(e, storage, with_main=False, name_by_id=None)`：新增選填 `name_by_id`（`{user_id: name}` 預載 dict，避免 N+1），補：
```
d["created_by_name"]       = name_by_id.get(e.created_by) if name_by_id else None
d["last_modified_by_name"] = name_by_id.get(e.last_modified_by) if name_by_id else None
d["last_modified_at"]      = iso_utc(e.last_modified_at)   # None→None
```
呼叫端（確認區列表、稽核列表）在序列化前，一次撈本批相關 `created_by` + `last_modified_by` 的 `User.id→name`，傳入 `name_by_id`。`serialize_audit_item` 沿用同一 `name_by_id`（它已用 `actor_name_by_id`；統一成一個 dict 即可）。

## 6. 後端端點

### 6.1 每單軌跡（兩端共用）
`GET /expenses/<int:id>/logs` → `{status:"ok", logs:[{actor_name, ts, action}]}`
- `logs` 依 `AuditLog.ts` 升冪；`ts` 用 `iso_utc()`。
- `action` 對映：`"edit"→"修改"`、`"check"→"簽核"`（純函式 `action_label`，可測；未知值回原字串）。
- `actor_name`：查 `User.name`（批次或單查皆可，單張軌跡筆數少）。
- **權限**：載入 expense→找不到 404；`created_by == current_user.id`（本人）**或** `current_user.role in ("manager","super_admin")` 且 `expense.store_id` 在其 scope 內 → 放行；否則 403。employee 只能看本人的單。放在 `expenses` blueprint（員工/主管皆可達）。

### 6.2 操作記錄查詢（集中頁）
`GET /audit/logs?date=YYYY-MM-DD&actor_id=<optional>` → `{status:"ok", items:[...], actors:[{id,name}]}`
- `@role_required("manager","super_admin")`，scope 沿用 `_scope_store_id()`（super_admin 需帶 `store_id`，缺→400，跨店→403）。
- `date`：台灣日期。後端把該台灣日 `00:00–24:00` 轉 UTC 範圍，查該範圍內、且 `expense.store_id` 在 scope 的 `AuditLog`（join expenses 篩 store）。
- `actor_id`（選填）：再篩 `AuditLog.actor_user_id == actor_id`。
- `items` 每筆：`{expense_id, summary, actor_name, ts, action}`（`ts` iso_utc、`action` 同 6.1 對映、`summary` 取該單摘要供辨識）；依 `ts` 降冪（新的在上）。
- `actors`：該 scope 店的 users（`{id,name}`，供前端員工下拉）。
- 可用日期：前端日期用 `<input type="date">`（不另做 available-dates 端點，YAGNI；預設今日台灣日）。

## 7. 前端

### 7.1 列顯示（員工確認區 + 主管稽核）
- `app/static/js/pending.js`（員工確認區）、`app/static/js/admin_audit.js`（主管待稽核清單 + 當日總表）：
  - 列上補「建立者」（`created_by_name`）。
  - 有 `last_modified_at` 時，列上補精簡行「最後修改：`last_modified_by_name`（`formatDateTimeTW(last_modified_at)`）」。
  - 列上加「軌跡」展開鈕：點擊呼叫 `GET /expenses/<id>/logs`，就地 inline 展開列出 `誰・時間・動作`。展開 render 用共用 util。

### 7.2 共用軌跡 render util
- `app/static/js/audit_util.js`（已存在）加純函式：`action_label(action)`、`renderTrailRows(logs)`（回 HTML 字串，`formatDateTimeTW` 格式化 ts）——可 `node --test`。

### 7.3 操作記錄查詢頁籤（新）
- 後台導覽 `app/static/js/admin.js` 加頁籤「操作記錄」（僅 manager/super_admin 顯示；super_admin 沿用頂部調店切換）。
- 新檔 `app/static/js/admin_logs.js`：日期 `<input type="date">`（預設今日）+ 員工下拉（來自 `actors`）→ 呼叫 `GET /audit/logs`，表格列出 `時間・員工・單號＋摘要・動作`。
- `app/static/js/admin_api.js`（或 `expenses_api.js`）加對應 API 方法。

### 7.4 sw.js
bump `app/static/sw.js` `CACHE_NAME`（現 calc-v30 → 下一版）。

## 8. 測試

**pytest**：
- migration upgrade/downgrade smoke（兩新欄存在、nullable）。
- `log_edit_if_changed`：有改→寫 AuditLog + 蓋 `last_modified_by/at`；無改→都不動；`record_check` 不蓋 last_modified。
- `serialize_expense`：帶 `name_by_id` 回三新欄（含 None 情境）。
- `GET /expenses/<id>/logs`：本人 200、同店主管 200、跨店 403、非本人 employee 403、不存在 404、action 對映正確、依 ts 升冪。
- `GET /audit/logs`：scope（manager 本店 / super_admin 選店 / 缺 store_id 400 / 跨店 403）、date 台灣日邊界（08:00 分界不涉此頁，用日曆日 00:00–24:00 TW）、actor_id 篩選、items 內容 + 降冪、actors 清單。

**node --test**：
- `action_label` 對映（edit/check/未知）。
- `renderTrailRows` 純邏輯（含空陣列、多筆排序輸出）。
- `formatDateTimeTW` 既有測試沿用。

## 9. 開發 / 交付流程

從 master 開 branch `feat/audit-trail-visibility` → SDD subagent-driven 逐 task（implementer + task review + fix，最終 opus 全 branch review）→ 本機 e2e（`/dev/login-test` 拍單改單、`/dev/login-manager` 稽核改單 + 操作記錄頁）→ user 明說才 fast-forward merge master、不 push。
