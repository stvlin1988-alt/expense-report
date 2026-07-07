# Phase 1 稽核（店管理者交接班打勾）設計

日期：2026-07-07
狀態：設計定稿，待寫 plan
前置：Plan 4（拍單+OCR+暫存區+送出+無單據建帳）已完成並 merge master（tip c5cf186）。

## 1. 目標與範圍

實體門市雜支流程的**第二層覆核**：員工在暫存區確認送出（`submitted`）後，**店管理者（manager）交接班時逐筆核對、可微調金額/分類、打勾稽核**（`audited`）。因一天有 2–3 班交接班，需支援**交班分區間**與**結班封當日**，並提供**當日總表**（各交班區間小計 + 當日總額）供對數。

原始構想見 `2026-07-01-expense-report-design.md`（狀態機 `submitted → audited → reconciled`、兩層覆核、`audit_log` 覆寫軌跡）。本 spec 只做**稽核（audited）**；會計核銷（`reconciled`）為後續 task。

### 範圍內
- 店管理者稽核 UI（後台新增「稽核」分頁）：待稽核清單 + 當日總表。
- 稽核時可改金額/分類；打勾 `submitted → audited`（單向、鎖定）。
- 交班（分區間）/ 結班（封當日）/ 取消上一次（修正按錯）。
- `audit_log` 全程軌跡（含員工暫存區改動 + 主管稽核改動 + 打勾）。
- Scope：manager 限本店；super_admin 可調店；會計不涉入。

### 範圍外（後續 task）
- 會計紅綠燈核銷（`reconciled`）、覆核頁、月結報表。
- 退回（reject）/ 作廢（void）。
- 稽核時的批次打勾（本 task 逐筆打勾）。

## 2. 狀態機

```
pending_ocr → draft → submitted → audited
                        │           │
                        │           └─ 打勾（POST /audit/<id>/check），單向、鎖定
                        └─ 員工送出（既有 POST /expenses/<id>/submit）
```

- `audited` 為本 task 的終點；audited 後 manager **不可再改、不可取消打勾**（鎖定）。發現錯誤留待會計核銷處理。
- 交班/結班**不改 status**（audited 不變），只是把 audited 的單「歸班」（蓋 `handover_id`）。

## 3. 資料模型

### 3.1 `expenses` 新增欄位（migration）
| 欄位 | 型別 | 說明 |
|---|---|---|
| `audited_by` | FK users, nullable | 打勾的主管 |
| `audited_at` | DateTime(tz), nullable | 打勾時間（UTC 存） |
| `is_modified_by_manager` | Bool, default false | 主管稽核時改過金額/分類 |
| `handover_id` | FK handovers, nullable, index | 歸屬的交班/結班區間；打勾當下為 null（=「當前未歸班」） |

（既有 `is_modified_by_user` 保留，代表員工暫存區改過。）

### 3.2 新表 `handovers`（一筆 = 一次交班或結班）
| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | PK | |
| `store_id` | FK stores, index | 哪一店 |
| `closed_at` | DateTime(tz) | 交/結班時間 |
| `closed_by` | FK users | 執行的主管 |
| `type` | String(8) | `shift`（交班）/ `day`（結班） |

- 不另存「第 N 班」「第幾日」序號 —— 靠 `closed_at` 排序、以 `type='day'` 切分推導（見 §5.3）。

### 3.3 新表 `audit_log`（全程軌跡）
| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | PK | |
| `expense_id` | FK expenses, index | |
| `actor_user_id` | FK users | 誰做的 |
| `action` | String(16) | `edit`（改金額/分類）/ `check`（打勾）。日後 `reconcile` |
| `before_json` | JSON, nullable | 改動前 `{amount, category_id}`；`check` 時為 null |
| `after_json` | JSON, nullable | 改動後 `{amount, category_id}`；`check` 時記 `{status:"audited"}` |
| `ts` | DateTime(tz) | UTC |

**寫入時機**：
1. 員工暫存區 `PATCH /expenses/<id>` 改到 amount 或 category_id → `edit`。
2. 主管 `PATCH /audit/<id>` 改 → `edit`。
3. 主管打勾 `POST /audit/<id>/check` → `check`。

交班/結班本身以 `handovers` 表為記錄，不再寫 audit_log。

## 4. 交班 / 結班 語意

- **交班（type=shift）**：關閉當前區間、當日繼續（下一區間開始）。
- **結班（type=day）**：關閉當前區間並**封存當日**。結班後：
  - **未打勾（submitted）的單留在待稽核**，不併入已結班那天；日後打勾會歸到下一天。
  - 結班後新打勾的單屬於新的一天。
- **只有已打勾（audited）的單會被歸班**（蓋 handover_id）；未打勾的不受交班/結班影響。
- 交班/結班時：把該店所有 `status=audited 且 handover_id IS NULL` 的單蓋上新建的 handover_id。
- super_admin 交班/結班需指定 `store_id`（交班是「對某一店結算」）。

**取消（修正按錯）**：`POST /audit/handover/undo {store_id?}` 刪除該店**最近一筆** handover、把其單的 `handover_id` 退回 null（回到「當前未歸班」）。限該批單皆尚未 `reconciled`（本 task 未有 reconcile，故恆可取消；先寫好守門為日後鋪路）。

## 5. 端點（新 `audit_bp`，前綴 `/audit`）

全部 `@role_required("manager", "super_admin")`。Scope 規則統一（§5.4）。

### 5.1 稽核操作
| 端點 | 作用 | 重點 |
|---|---|---|
| `GET /audit/pending` | 待稽核清單 | 篩 `status=submitted`（scope）；依 `business_date` 分組，每組附**日小計**（該組金額加總）；組內依 `submitted_at`。回每筆 serialize（含 thumb_url、summary、amount、category_id、light）。 |
| `PATCH /audit/<eid>` | 主管改金額/分類 | 僅 `status=submitted` 可改（audited 鎖定 → 409）；scope 檢查；`category_id` 走 `_valid_category_id`、amount 走 `Decimal` 解析（沿用 `/expenses` PATCH 邏輯）；設 `is_modified_by_manager=true`；寫 `audit_log(edit, before/after)`。 |
| `POST /audit/<eid>/check` | 打勾 | 僅 `status=submitted`（否則 409）；設 `status=audited`、`audited_by`、`audited_at`；`handover_id` 保持 null；寫 `audit_log(check)`。 |

### 5.2 交班 / 結班
| 端點 | 作用 |
|---|---|
| `POST /audit/handover {type: "shift"\|"day", store_id?}` | 建 handover（type）、把本店 `audited 且 handover_id=null` 的單蓋章。manager 用本店；super_admin 需帶 `store_id`。回新 handover 摘要（含蓋章筆數、小計）。若無可歸班的單，回 400（避免空交班）。 |
| `POST /audit/handover/undo {store_id?}` | 刪該店最近一筆 handover、其單 handover_id 退回 null。限未 reconciled。回被退回的筆數。 |

### 5.3 當日總表
`GET /audit/summary {store_id?}`：回**當前稽核日**的分組結構。

- **當前稽核日**定義：該店最近一筆 `type='day'`（上次結班）的 `closed_at` **之後**至今的所有 handover（皆為 `type='shift'`，或恰好尚未結班），**加上**「當前未歸班」（`audited 且 handover_id=null`）。若從未結班，當前稽核日 = 全部 handover + 當前未歸班。
- 回傳結構：
  ```
  {
    intervals: [
      { handover_id, type, seq, closed_at, subtotal, count },   // 各交班區間，seq 依 closed_at 排序
      ...
    ],
    open: { subtotal, count },   // 當前未歸班（尚未交/結班的已打勾單）
    day_total: <各 interval subtotal + open.subtotal>
  }
  ```
- **歷史**（已結班的過去日）：`GET /audit/summary?before=<handover_id>` 回上一個稽核日的同結構（以 `type='day'` 邊界往前推）。前端「當日總表」子區預設今日，可往前翻。

### 5.4 Scope 規則（統一）
稽核所有操作皆 **per-store**（交班/結班/總表本質綁單一店），故一律需要一個明確 store：
- `manager`：`store_id` 參數忽略，一律用 `actor.store_id`；操作的單必須 `expense.store_id == actor.store_id`，否則 403。
- `super_admin`：**必須指定 `store_id`**（前端調店下拉選定單一店，不接受「全部店」）。未帶或帶無效 `store_id` → 400。指定後等同 manager 對該店操作。
- 沿用 `app/admin/routes.py` 既有 super_admin `store_id` filter + manager 限本店的寫法；差別是稽核不支援「全部店」彙整（避免跨店日總額無意義的合併）。

### 5.5 員工端連動（既有端點加寫 log）
`PATCH /expenses/<id>`（員工暫存區）：當 payload 改到 `amount` 或 `category_id` 時，加寫一筆 `audit_log(edit, before/after)`，actor = 該員工。行為與回傳不變，只多一筆 log。

## 6. UI（後台新增「稽核」分頁）

manager / super_admin 登入落在 `showAdminPanel`（`app/static/js/admin.js`，分頁式）。tabs 陣列加一個 **「稽核」**（manager + super_admin 皆見；會計無此後台）。super_admin 用既有頂部調店下拉決定看哪店。

super_admin 若頂部調店下拉停在「全部店」，稽核分頁顯示「請先選擇一家店」提示（稽核為 per-store，不做跨店彙整，見 §5.4）；選定某店後才載入。

分頁內兩個子區（子分頁或上下分區）：

### ① 待稽核（未打勾）
沿用員工暫存區（`pending.js`）的表格風格，資料是**全店員工**的 `submitted`：
- 依營業日分組，每組標日小計。
- 每列：縮圖、摘要、**分類下拉（可改）**、**金額（可改）**、燈號、**[打勾]** 鈕。
- 改金額/分類 → `PATCH /audit/<eid>`（即時、寫 log；失敗於該列出聲，沿用 Plan 4 的即時修正 pattern）。
- 打勾 → `POST /audit/<eid>/check`，該列移出。
- 底部：**「當前班即時小計」** + **「交班」** 鈕 + **「結班」** 鈕 + **「取消上一次」**。
- 共用員工端 `expenses_util.js` 的 `categoryOptionsHtml`。

### ② 當日總表
- 各交班區間一列：第 N 班、`shift`/`day` 標記、交班時間、小計、筆數。
- **當前未歸班**一列：即時小計（可展開看已打勾明細）。
- 最底：**當日總額**。
- 可往前翻看歷史稽核日（`?before=`）；預設當前稽核日。

### 前端切檔（沿用 admin_accounts.js / admin_devices.js 模式）
- `admin_audit.js` — 稽核分頁殼 + 待稽核/總表兩子區 + 交班/結班/取消。
- `admin_api.js` 加 audit 方法（pending / patch / check / handover / undo / summary）。
- CSS 沿用既有 `.pd-table` / `.ap-*`；bump `sw.js` CACHE_NAME。

## 7. 錯誤處理與邊界
- PATCH / check 對非 `submitted` 的單 → 409（audited 已鎖、pending_ocr/draft 尚未送出）。
- 跨店操作 → 403。
- 空交班（無可歸班的 audited 單）→ 400。
- undo 對無 handover 的店 → 400；對已 reconciled 批 → 409（守門，日後生效）。
- amount 解析失敗 → 沿用 `/expenses` PATCH 行為（`amount_parse_ok=false`）。
- 併發：兩位主管同時對本店交班 → handover 以 `closed_at` 排序，蓋章用「當下 audited 且 handover_id=null」原子條件（`UPDATE ... WHERE handover_id IS NULL`），避免重複歸班。

## 8. 測試
**後端（pytest）**
- migration：expenses 新欄位 + handovers + audit_log 建表。
- 狀態轉換：check `submitted→audited`；check/PATCH 對 audited/其他狀態 → 409。
- audit_log：員工 PATCH 改金額 → 寫 edit（before/after 正確）；主管 PATCH → edit；check → check。
- scope：manager 稽核他店 → 403；super_admin 帶 store_id 可；manager 忽略 store_id 用本店。
- 交班/結班：交班蓋章當前 audited-open 的單、type 正確；結班後（a）未打勾的單仍在 pending（b）之後打勾的單 handover_id=null 屬新日；空交班 → 400。
- undo：退回最近 handover、單 handover_id 回 null；無 handover → 400。
- summary：intervals + open + day_total 加總正確；結班邊界切分正確（`before=` 取前一日）。
- pending：分組 + 日小計正確、只列本店 submitted。

**前端（node --test，純邏輯）**
- summary 分組/加總的純函式（若前端也算）；`categoryOptionsHtml` 重用；交班區間顯示格式化。
- DOM 膠合（admin_audit.js）走手動 e2e（可用 Plan 4 的 `/dev/login-test` 捷徑，但需 manager 身分 → 加一個 dev 捷徑或 seed manager）。

## 9. 決策紀錄
1. 稽核動作 = 改（金額/分類）+ 打勾；**不做退回/作廢**。
2. `audit_log` **完整表**，記員工暫存區改 + 主管稽核改 + 打勾（全程軌跡）。
3. audited **鎖定**（單向，manager 不可再改/取消打勾）。
4. 稽核頁 = 待稽核（依營業日分組+日小計）+ 當日總表（交班區間+當日總額）兩子區。
5. **交班（type=shift）分區間 / 結班（type=day）封當日**；只有 audited 的單會被歸班；結班後未打勾的單滾到下一天；按錯可「取消上一次」。
6. Scope：manager 本店、super_admin 調店、會計不涉入。
7. 模組：新 `audit_bp`（`/audit`），與既有 `admin`/`expenses` 分離；`audit_log` 寫入做共用 helper 供 `/expenses` 與 `/audit` 呼叫。
