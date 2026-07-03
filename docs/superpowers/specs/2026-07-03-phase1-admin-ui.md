# Phase 1 — 後台管理 UI（Plan 3b）

> 狀態：設計定案（2026-07-03），待寫實作計畫。
> 前置：Plan 1（foundation）、Plan 2（認證與裝置，含 `/admin/*` 寫入端點）、Plan 3a（計算機終端＋隱蔽登入）皆已完成 merge。
> 範圍切分：本份 = **3b 後台管理 UI（前端為主 + 少量後端補充）**。covert 登入的 **stealth 混淆強化（動態發 code / WASM / 誘餌流量）另立 Plan 3c**，本文件不含。

---

## 1. 目標與定位

隱蔽登入成功後，`manager` / `super_admin` 進入**正常清爽的管理後台**，管理帳號、裝置、店別、自己的密碼，並可替員工代錄人臉。後台的**寫入端點在 Plan 2 已完成**（`/admin/stores`、`/admin/users`、`/admin/users/<id>/password`、`/admin/me/password`、`/admin/devices` list、`/admin/devices/<id>/approve`、`/revoke`、`/face/enroll`）；3b 主要是**前端 UI** + **少量後端補充**（清單 GET 端點、停用/復用、以及新裝置自動入列的前端調整）。

延續 Plan 3a 的鐵律：單一可見網址 `/`（後台是前端 view state，網址列不洩底）；4 位純數字 PIN；時間台灣時間；狀態進 DB；與 webapp 完全隔離。

### 非目標（明確排除）
- **stealth 混淆強化** → Plan 3c（動態 gated 載入、WASM、誘餌流量、偽裝端點）。
- 雜支系統本體（拍單→OCR→暫存→稽核→核銷）→ 後續階段。
- accountant / employee 的專屬畫面（3b 只做 manager/super_admin 後台；其餘角色登入後仍到占位頁）。
- audit log 專屬 UI（寫入操作若需稽核，沿用/延後，非 3b 重點）。

---

## 2. 技術與慣例

- Flask Jinja + 原生 JS（ES modules）+ `fetch`，**無打包**（延續 3a）。
- 後台是**登入後前端 view state**：`auth.js` 驗證成功後依角色呼叫 `showAdminPanel()`（manager/super_admin）或既有 `showAppView()`（其他）。網址列永遠只有 `/`。
- 視覺 = **正常清爽管理面板**（表格/表單/分頁），非 covert 深色風。只有通過隱蔽登入者看得到，且沿用 30 分 idle 閘。
- 所有密碼/PIN 輸入：4 位純數字（前端 `inputmode=numeric maxlength=4` + 濾非數字；後端 `is_valid_pin` 已於 3a 建立並在寫入端點驗證）。
- 前端純邏輯（scope 過濾、表單驗證）以 `node --test` 覆蓋；DOM/相機膠合手動驗證（需以 super_admin 帳號經隱蔽登入進後台，dev 可用 VirtualCam）。

---

## 3. 角色與可視 scope（沿用 Plan 2 §6）

| 能力 | super_admin | manager | accountant/employee |
|---|---|---|---|
| 進後台 | ✅ 全域 | ✅ 限本店 | ❌ |
| 調店（檢視店別切換） | ✅ 全部店/選單一店 | 固定本店 | — |
| 新增店 | ✅ | ❌ | — |
| 帳號：建/列/改密碼/停用復用 | 任一被管理 user | 限本店 employee | — |
| 代錄他人人臉 | 任一被管理 user | 限本店 employee | — |
| 裝置：核准/換機/撤銷/列 | 全域 | 限本店 | — |

- **可視店（visible_stores）**：super_admin = 全部；manager = `[自己的 store]`。使用者/裝置清單與所有下拉皆依此 scope，且再依「目前檢視店別」過濾。
- scope 判斷一律以**後端**為準（前端過濾只是體驗）；沿用既有 `_manages` / `_manages_device` / `_visible_device_query`。

---

## 4. 進入與導覽

### 4.1 登入後分流（改 `app/static/js/auth.js`）
`submit()` 收到 `/auth/verify` 回 `{status:"ok", id, name, role}` 後：
- `role` ∈ {`manager`,`super_admin`} → `showAdminPanel({name, role, ...})`。
- 否則 → 既有 `showAppView(...)` 占位頁。
- 同理 `main.js` 的「已登入 session 暗號快捷」（`cfg.identity`）也依 role 導向後台或占位頁。

### 4.2 後台面板結構（單頁 view state）
- 頂部列：標題、（super_admin）**調店切換**下拉（全部店 / 各店）、登出。
- 分頁（tabs）：**帳號** / **裝置** / **店別**（僅 super_admin）/ **我的密碼**。
- 切分頁只換 DOM 區塊，不換網址。
- 登出：沿用 3a 的 `location.reload()`。

---

## 5. 後端補充（新增/修改端點）

### 5.1 `GET /admin/users`（新增）
- `@role_required("manager","super_admin")`。
- 查詢 scope：super_admin → 全部，可帶 `?store_id=` 過濾；manager → 僅 `store_id == actor.store_id` 的 user。
- 回：`{status:"ok", users:[{id, name, role, store_id, active, has_face}]}`；`has_face = user.face_encoding is not None`（**不回 encoding 本身**）。

### 5.2 `GET /admin/stores`（新增）
- `@role_required("manager","super_admin")`。
- super_admin → 全部店；manager → 僅本店（`[actor.store]`，可能為空清單若 manager 無 store）。
- 回：`{status:"ok", stores:[{id, name, code}]}`。

### 5.3 `POST /admin/users/<int:user_id>/active`（新增，停用/復用）
- `@role_required("manager","super_admin")`。
- body `{active: bool}`（非 bool → 400）。
- target 不存在 → 404；`_manages(actor, target)` 不成立 → 403。
- **禁止停用自己**（`target.id == actor.id` → 400，避免自我鎖死）。
- **禁止停用最後一位在職 super_admin**（若 target.role==super_admin 且停用後無其他 active super_admin → 400，避免全域鎖死）。
- 通過 → `target.active = active`；commit；回 `{status:"ok"}`。
- 註：停用會即時影響登入候選（`/auth/verify` 只挑 `active=True`）與裝置閘（綁定 user 停用→該裝置擋下），皆為既有行為。

### 5.4 新裝置自動入列（改前端 `app/static/js/main.js` + `auth.js`）
- 照 webapp：**開頁時自動 `POST /api/v1/register-device`**（帶 `device_name`，uid 由 cookie/伺服器），使未知裝置一連就建立 `is_approved=False` 待核准列、進後台佇列。
- 從 `auth.js` 的「開登入 modal 才 register」**移除**，改由 `main.js` 於頁面載入時呼叫一次（已核准裝置則更新 `last_seen_at`，靠 cookie 不重複建列）。
- 註：此為後台裝置核准佇列的前置；register-device 已於 Plan 2 完成，含 30 分未核准 TTL 清理。stealth 化（偽裝/誘餌）屬 Plan 3c。

### 5.5 修正：PIN 格式檢查排序（3a 遺留 Minor）
- `app/admin/routes.py` 的 `reset_password` 與 `approve_device`（new_user 分支）：把 `is_valid_pin` 檢查**移到各自的物件級授權（403）檢查之後**，使「越權 + 格式錯」一致回 403（不對越權者洩漏 PIN 格式）。`change_own_password` 已是 wrong-old→format 正確序，不動。

---

## 6. 帳號管理（帳號分頁）

- **清單**：讀 `GET /admin/users`（依目前檢視店別再過濾）。欄位：姓名、角色、店、在職（active）、有無人臉。空清單顯示提示。
- **創帳號（直接創帳號 / 公務機共用員工）**：表單 = 姓名 + 4 位 PIN + 角色 +（super_admin）店別下拉（讀 `GET /admin/stores`）。
  - manager：角色固定 employee、店固定本店（前端鎖定，後端 `create_user` 亦強制）。
  - super_admin：角色可選、店必選。
  - 送 `POST /admin/users`。成功 → 重載清單。
- **重設密碼**：對清單某 user → 輸入新 4 位 PIN → `POST /admin/users/<id>/password`。
- **停用/復用**：對清單某 user → 切換 → `POST /admin/users/<id>/active {active}`。UI 反映 active 狀態；自己/最後 super_admin 的停用鈕停用或後端擋（顯示原因）。
- **代錄員工臉**：對清單某 user →「錄臉」→ 開相機（`Camera` helper）擷取單張 → `POST /face/enroll {face_image, user_id}`（後端 `_can_enroll` 把關）。成功後該列「有無人臉」更新。影像不落地（延續鐵律）。

---

## 7. 裝置管理（裝置分頁，核心）

- **清單**：讀 `GET /admin/devices`（super_admin 可帶 `?store_id=` 依調店過濾；manager 自動限本店，含未歸屬待核准）。欄位：裝置名、client_uid 尾碼、店、綁定使用者、狀態（**待核准** / 已核准 / 已撤銷）。
- **待核准佇列置頂**：`is_approved=False` 的裝置（未知裝置連過來）明顯標示、排最上，方便管理者處理。
- **核准 + 綁定流程**（走既有 `POST /admin/devices/<id>/approve`）：對一台待核准裝置，三選一：
  1. **綁到現有使用者**：選 user（scope 內）→ body `{bound_user_id}`。
  2. **建新帳號並綁定**：填 姓名 + 4 位 PIN + 角色 +（super_admin）店 → body `{new_user:{name,password,role,store_id?}}`。
  3. **裸核准（指派店）**：super_admin 選店 → body `{store_id}`；manager 裸核准自動歸本店。
- **換機（撤舊發新）**：核准新機並 `bound_user_id` 綁到某人時，後端**自動撤銷該 user 其他已核准裝置**（既有行為）。UI 提示「將撤銷 X 的舊裝置」。
- **撤銷（掛失）**：對某裝置 → `POST /admin/devices/<id>/revoke`。
- 所有操作後重載清單。錯誤（403/404/400）顯示對應訊息。

---

## 8. 我的密碼（我的密碼分頁）

- 表單：舊 PIN + 新 4 位 PIN → `POST /admin/me/password`。
- 錯舊密碼 → 顯示「舊密碼錯誤」；新非 4 位 → 前端擋 + 後端 400。成功 → 提示。

---

## 9. 元件邊界與檔案

**後端（修改 `app/admin/routes.py`）**
- 新增 `list_users`（GET /admin/users）、`list_stores`（GET /admin/stores）、`set_user_active`（POST /admin/users/<id>/active）。
- 修 `reset_password`、`approve_device` 的 PIN 檢查排序。
- 沿用既有 `_manages` / `_visible_device_query` / `_manages_device`。若檔案過大，可將裝置相關抽到 `app/admin/devices.py`（同 blueprint），但以最小改動為先，不強制重構。

**前端（新增，ES modules）**
| 檔 | 職責 |
|---|---|
| `app/static/js/admin.js` | 後台面板殼：分頁導覽、調店切換、登出、掛載各分頁；`showAdminPanel(identity)` 匯出 |
| `app/static/js/admin_accounts.js` | 帳號分頁：清單/創帳號/改密碼/停用/代錄臉 |
| `app/static/js/admin_devices.js` | 裝置分頁：清單/待核准/核准綁定/換機/撤銷 |
| `app/static/js/admin_api.js` | 後台 fetch 薄封裝（GET users/stores/devices、各 POST），回傳 `{status,...}` |
- `auth.js`：`submit()` 成功後依 role 呼叫 `showAdminPanel` 或 `showAppView`；`main.js`：改開頁 register-device、identity 快捷依 role 導向。
- CSS：`app.css` 加一組正常面板樣式（表格/表單/分頁/按鈕），與 covert 計算機樣式共存但區隔。

---

## 10. 測試策略

- **後端（pytest）**：
  - `GET /admin/users`：super_admin 全部 / 帶 store_id 過濾 / manager 限本店；回傳含 `has_face` 且不含 encoding。
  - `GET /admin/stores`：super_admin 全部 / manager 限本店。
  - `POST /admin/users/<id>/active`：正常停用/復用；禁停自己（400）；禁停最後 super_admin（400）；越權 403；不存在 404；非 bool 400。
  - PIN 排序修正：越權 + 格式錯 → 回 403（非 400）。
  - 既有寫入端點（create/reset/approve/revoke）Plan 2 已覆蓋，不重複。
- **前端純邏輯（node --test）**：admin_api 的回應正規化、scope/店別過濾顯示、表單 4 位 PIN 驗證等可抽出的純函式。
- **端到端（手動）**：以 super_admin（bootstrap 建）經隱蔽登入進後台，走一輪：創帳號→代錄臉→用該員工登入；未知裝置開頁→後台待核准→核准綁定→該裝置可登入；換機撤舊；停用帳號後該人登入被擋；調店過濾。dev 用 VirtualCam 餵臉。
- 沿用 SDD：逐 task implementer + task review + fix，最終全 branch review，測試 OK + user 明說才 merge、不 push。

---

## 11. 風險與註記

- **register-device 改開頁自動呼叫**：未知（含路人）裝置一連就進待核准佇列，可能有雜訊；靠既有 30 分 TTL 清理收斂。真正的偽裝/誘餌/gated 化屬 **Plan 3c**。
- **停用最後 super_admin / 停用自己**：已加後端守門，避免全域鎖死。
- **manager 無 store 的邊界**：Plan 2 允許但少見；`GET /admin/stores` 回空、創帳號店別為本店（None）需在 UI 明確處理或後端擋（沿用既有 create_user store 驗證）。
- **後台仍在單一網址 `/`**：重整回計算機，需重新隱蔽登入才回後台（延續 3a；已核准裝置 6 秒內暗號 + 若 session 在則快捷）。
- **檔案大小**：`admin.js` 系列刻意切三檔避免單檔膨脹；後端 admin/routes.py 若加完仍偏大，實作計畫可評估抽 devices 子模組。
- **關聯 Plan 3c**：3b 完成後，covert 登入與 register-device 會在 3c 被 stealth 化（動態 gated 載入 + WASM + 誘餌流量），屆時 3b 的後台不受影響（後台在登入後、非 covert 面）。
