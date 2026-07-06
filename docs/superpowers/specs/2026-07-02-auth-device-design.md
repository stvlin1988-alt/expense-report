# 登入與裝置認證設計（Plan 2）

> 日期：2026-07-02　範圍：expense-report 的**認證子系統**（裝置綁定 + 密碼＋人臉雙因子 best-match 登入 + 30 分鐘 idle session）。
> 參考 webapp `app_unified` 的既有做法**重寫**（守鐵律：與 webapp 完全隔離、不 import、不連其 DB/R2）。
> 計算機／幣別換算的登入頁工具屬**另一份 spec/plan**，本文件不含。

---

## 0. 修訂既有 spec

本設計**取代** `docs/superpowers/specs/2026-07-01-expense-report-design.md` §3 中的 device / enrollment 決策：

- **砍掉 `enrollment_codes`（一次性綁定碼）**：不再用綁定碼流程。改為 webapp 式「未認證裝置自動進後台佇列 → 管理者核准」。
- `devices` 表以本文件 §3 的 `Device` 定義為準（加 `client_uid`、`is_approved`/`is_revoked`）。
- 其餘 §2 角色、鐵律（fingerprint 永不作認證判斷、影像不落地、時間存 UTC、狀態進 DB、營業日 08:00）不變。

---

## 1. 認證模型總覽

兩個 cookie 各司其職：

| Cookie | 效期 | 屬性 | 用途 |
|---|---|---|---|
| `device_uid` | 10 年（持久） | httpOnly, Secure, SameSite=Lax | **這台機器是誰**。認證唯一依據；伺服器產生的隨機 UID。 |
| session（Flask signed cookie） | 30 分鐘 idle（硬上限 35 分） | httpOnly, Secure, SameSite=Lax | **現在誰登入、還有效多久**。 |

每個受保護 request 的把關順序（`before_request`）：
1. **裝置閘**：`device_uid` 對應的 `Device` 存在、`is_approved=True`、`is_revoked=False`、綁定 user（若有）未停用。否則擋下、要求重新核准。
2. **Session 閘**：已登入且未 idle 逾時（§9）。

裝置持久、人 30 分鐘要重登（重打密碼＋臉）；裝置本身**不需**重新核准。

> **鐵律**：`fingerprint` 只寫入 `Device` 供稽核，**永不參與**任何認證/查詢判斷（記取 webapp fingerprint 碰撞教訓）。認證一律用 `client_uid`。

---

## 2. 首次啟用（seed mode）

解「要先有已核准裝置才能登入、要先能登入才能核准裝置」的雞生蛋問題。

**進入條件（任一成立）**：
1. DB 沒有任何 `super_admin`，或
2. 有 super_admin 但**沒有任何** `is_approved=True` 的裝置，或
3. 所有 super_admin 都沒有 `face_encoding`（人臉資料損壞/未錄）。

**seed mode 行為**：目前裝置被允許在**不需既有核准裝置**的前提下，完成：建立業主 super_admin（沿用 Task 5 的 `seed_admin` 或後台建立）、為其**錄臉**、把**當前裝置設為 `is_approved=True`** 並綁定該 super_admin。完成後條件不再成立 → 自動退出 seed mode，之後一律走正常核准流程。

seed mode 判定為伺服器端函式 `is_seed_mode() -> bool`，狀態全由 DB 推導（不用 module-level 變數）。

---

## 3. 資料模型

### 3.1 `User`（修改既有）
Task 5 已有 `id, store_id, name, role, password_hash, active, created_at` 與 `set_password/check_password/is_admin`。新增：

- `face_encoding`：`LargeBinary`，nullable。128 維 `float64` 的 raw bytes（`numpy.ndarray.tobytes()`，共 1024 bytes）。**只存數字向量，不存任何影像**。

### 3.2 `Device`（新表，取代舊 devices 定義）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | Integer PK | |
| `store_id` | Integer FK→stores, nullable | 裝置所屬店（全域角色如會計/super_admin 可為 null） |
| `bound_user_id` | Integer FK→users, nullable, ON DELETE SET NULL | 綁定的代表使用者；換機時改綁 |
| `client_uid` | String, **unique**, not null | 伺服器產生的裝置識別（對應 `device_uid` cookie）；認證唯一依據 |
| `fingerprint` | Text, nullable | **僅稽核**，永不用於認證/查詢比對 |
| `device_name` | String, default "Unknown" | 顯示用標籤 |
| `is_approved` | Boolean, not null, default False | 管理者核准 |
| `is_revoked` | Boolean, not null, default False | 掛失/換機撤銷 |
| `last_seen_at` | DateTime(UTC), not null | 最近一次 register/活動 |
| `created_at` | DateTime(UTC), not null | |

- 唯一性：`client_uid` unique。
- Python-side default 用 `datetime.now(timezone.utc)`（時間存 UTC）。

---

## 4. 登入流 `POST /auth/verify`（免帳號 best-match）

輸入：`{ password, face_image }`（`face_image` = base64 單張畫面）。**不輸入帳號。**

**步驟**：
1. **候選 scope（決策 B — 2026-07-06 修訂為「公務機模式」）**：已核准裝置（由 device gate 保證能到達 `/auth/verify`）上，候選為**所有在職 user**（`active=True`），**不再受裝置所屬店別限制**。
   - **修訂理由**：公務機＝實體門市多帳號共用手機，需讓任一帳號皆能在該裝置登入；帳號之間以**密碼**唯一區分（見步驟 2），人臉為輔。
   - **原設計（舊版決策 B，已淘汰）**：候選 scope 到「該裝置所屬店的在職 user（`store_id == device.store_id`）＋全域角色（`accountant`/`super_admin`）」，公務機在 A 店只比對 A 店的人＋全域角色。因共用需求移除此店別限制。
   - **安全影響**：任一已核准且未撤銷的裝置可登入任一帳號；裝置本身仍須經核准/未撤銷（device gate）才能到達本流程，但**裝置不再作為「限制哪些帳號可登入」的邊界**。門市以「一台裝置＝一組已知帳號密碼」的實體控管取代原本的店別軟性隔離。
   - **實作**：`_candidate_users()` 回 `User.query.filter_by(active=True).all()`（`app/auth/routes.py`）。
2. **密碼篩選**：候選中 `check_password(password)` 為真者 → `pin_users`。空 → 回 `wrong_password`（統一 JSON 狀態、不指名帳號，不洩漏「哪個帳號存在」）。**公務機模式下密碼即帳號的區分依據，故各帳號密碼須唯一**；兩帳號同密碼且同臉時步驟 4 會判 `ambiguous` 整批拒。
3. 分「已錄臉」/「未錄臉」；若無人已錄臉 → 回 `need_face_enroll`（請管理者協助錄臉）。
4. **人臉比對**：伺服器把 `face_image` 解碼進**記憶體** → `face_recognition` 算單張 encoding（跑在 thread executor + `timeout`，避免 dlib 卡 worker）→ 用 numpy 對候選的 `face_encoding` 算 L2 距離：
   - `threshold = 0.45`：最小距離 > 0.45 → `face_mismatch`。
   - `ambiguous_margin = 0.05`：前兩名距離差 < 0.05 → 視為撞臉、**整批拒**（`ambiguous`），避免同密碼兩張相近的臉互登。
   - 偵測不到臉 → `face_not_found`。
5. **成功**：`login()`（寫 `session['user_id']`、`session.permanent = True`、初始化 `session['_last_request_at']`）。**該次 face_image 立即從記憶體丟棄，絕不落地。**
6. 額外閘：命中的 user 所屬店若被停用 → `store_disabled`。

**防濫用**：`/auth/verify` 以 `flask-limiter` 限 `20/min`（測試環境豁免）。

**回傳**：一律 JSON 狀態碼字串（`ok` / `wrong_password` / `need_face_enroll` / `face_mismatch` / `face_not_found` / `ambiguous` / `store_disabled`）；成功不回傳任何 token（session 由 cookie 承載）。

---

## 5. 裝置註冊 `POST /api/v1/register-device`

前端載入時自動呼叫（未登入也可）。

- UID 來源優先序：`device_uid` cookie > body.`client_uid` > 伺服器新發（`uuid4().hex`）。
- 行為：以 `client_uid` 查 `Device`；找到 → 更新 `last_seen_at`（SEEN）；找不到 → 新建一筆 `is_approved=False` 的待核准裝置，回寫 `device_uid` cookie。
- `fingerprint`、`device_name` 一併存入（fingerprint **僅稽核**）。
- **自動清理**：每次呼叫順帶刪除「未核准且建立超過 30 分鐘」的裝置（`_cleanup_pending_devices`），避免佇列堆垃圾。
- 此 endpoint 不套 idle 逾時、不需登入。

---

## 6. 後台管理

管理後台限**管理者以上**使用（`manager` / `super_admin`；`accountant` 專責帳務、`employee` 無後台）。所有寫入操作記稽核（沿用/擴充 `audit_log` 或專屬 log，Plan 內定）。

### 6.0 權限與可視範圍（scope）

| 功能 | super_admin | manager | 備註 |
|---|---|---|---|
| 調店（檢視店別切換） | 全部店，或選單一店只看該店 | 限本店（等同固定） | §6.1 |
| 新增店 | ✅ | ❌ | 開店為 super_admin 專屬（原 spec §2） |
| 直接創帳號（公務機共用員工） | 任一店 | 限本店員工 | §6.3 |
| 修改/重設他人密碼 | 任一被管理 user | 限本店員工 | §6.4 |
| 修改自己密碼 | ✅ | ✅ | 任何登入者皆可改自己 |
| 裝置核准/換機/撤銷 | 全域 | 限本店 | §6.5 |
| 錄入他人人臉 | 任一被管理 user | 限本店員工 | §7 |

- **可視店（visible_stores）**：super_admin = 全部；manager = `[自己的 store]`。使用者/裝置清單與各下拉皆依此 scope。

### 6.1 調店（檢視店別切換）
- 後台清單（帳號/裝置）依「目前檢視店別」過濾。
- **super_admin**：預設看全部；可用店別篩選（如 `?store_id=` 或下拉）**只看某一店**。此為**檢視過濾、非持久狀態**（不改自身歸屬、不寫 DB）。
- **manager**：固定本店，無切換。

### 6.2 店別管理（Store）
- 沿用 Task 2 的 `stores(id, name, code, active, created_at)`；**store 停用 = `active=False`**，作為 §4 登入時 `store_disabled` 的判定依據（不新增 `login_enabled` 欄位）。
- **新增店**（super_admin）：提供 `name` + `code`（`code` unique）。店別清單參考 webapp 概念（name 唯一）。

### 6.3 帳號管理 — 直接創帳號（公務機共用員工）
- 為**使用公務機、不綁個人手機**的員工直接建立帳號：輸入 `name` + 密碼 + `role` + `store` → 建 `User` 並 `set_password`。
- 這些員工**不走裝置核准/換機流程**；他們在**任一已核准的公務機**上以「密碼＋人臉」登入（§4 公務機模式：已核准裝置放行任一在職帳號）。人臉可於建立後由管理者錄入（§7）。
- 與 §6.5 的「核准裝置 + 建新帳號」不同：後者綁**個人裝置**、前者為**共用機用戶**、與裝置解耦。

### 6.4 密碼管理
- **管理者重設他人密碼**：super_admin 對任一被管理 user、manager 對本店員工，`set_password(新密碼)`。
- **自助改自己密碼**：任何登入者可改自己密碼（需通過目前 session；是否要求重驗舊密碼於 Plan 決定，預設要求）。

### 6.5 裝置管理
**分權（決策 C）**：`super_admin` 全域；`manager` 限本店（`Device.store_id == 自己的 store` 或裝置綁定 user 屬本店）。
- **列出**待核准/已核准裝置（依 scope）。
- **核准 + 建新帳號**：核准**個人裝置**並同時建 user、綁 `bound_user_id`。
- **核准 + 綁既有帳號（換機）**：核准新裝置綁到既有 user，並把該 user 舊裝置 `is_revoked=True`（撤舊發新）。
- **撤銷**：`is_revoked=True`。

---

## 7. 人臉錄入

- 管理者在後台為指定 user 錄臉；seed mode 時業主自錄。
- 流程：前端擷取單張畫面 base64 → `POST` → 伺服器記憶體解碼 → `face_recognition.face_encodings` 取 128 維 → `tobytes()` 存 `User.face_encoding` → **原始畫面即丟**。
- 偵測不到臉 → 回錯誤要求重拍。
- 前端相機以共用 helper（擷取單張，不錄影、不存檔、不進相簿）。

---

## 8. Idle 30 分鐘逾時

- `session['_last_request_at']`（epoch 秒）；`before_request` 的 `_enforce_session_idle`：
  - 略過靜態資源、`/api/v1/*`（裝置端點）、登出端點。
  - 已登入且 `now - _last_request_at > 30*60` → 登出、`session.clear()`。
  - 否則把 `_last_request_at` 更新為 `now`（**滑動**：有操作就續命）。
- `PERMANENT_SESSION_LIFETIME = timedelta(minutes=35)`（30 分鐘 idle + 緩衝的硬上限）。
- **不輪詢**（守鐵律）：逾時判定純伺服器端；前端僅用**單一** 30 分鐘倒數計時器，到點導向登入頁（非輪詢、非 keepalive ping）。

---

## 9. 對 Task 5 既有登入的影響

- Task 5 的 `POST /auth/login`（name + password）與其測試 **移除/改寫**，由 `/auth/verify`（免帳號、密碼＋臉 best-match）取代。
- **續用**：`User.set_password/check_password/is_admin`、`super_admin` seed、`role_required` decorator、`/auth/logout`（改為清 session）。
- 登入建立 session 的方式沿用 `session['user_id']`（不引入 Flask-Login，與現有程式一致）。`role_required`/`current_user` 保留；本 plan 亦補上 §1 裝置閘的 `before_request`。

---

## 10. Build／部署策略（解 dlib 慢 build 雷）

**根因**：`dlib` 預設從原始碼編譯，Zeabur 每次 build 重編 → 數十分鐘。

**解法（照 webapp 已驗證做法）**：
1. **預編 wheel 直接 commit 進 git**（決策 D，不用 LFS），置於 repo `wheels/`：
   - `dlib-20.0.1-cp312-cp312-linux_x86_64.whl`（3.9M）
   - `face_recognition_models-0.3.0-py2.py3-none-any.whl`（96M）
   - 兩檔自 webapp `app_unified/wheels/` 複製（同 Python 3.12 / linux x86_64，相容）。
2. **`Dockerfile`**（`zbpack.json: {"use_dockerfile": true}`）：
   - `FROM python:3.12-slim`
   - `apt-get install libgomp1 libopenblas0 liblapack3`（dlib runtime 相依）
   - `pip install --upgrade pip setuptools wheel`
   - **先** `COPY wheels/` → `pip install --no-deps wheels/*.whl`（dlib + models，零編譯）
   - 再 `COPY requirements.txt` → `pip install -r requirements.txt`（`face_recognition` 純 Python，靠上面 wheel 滿足 dlib/models 相依）
   - **最後** `COPY` app 程式碼
   - `RUN python -c "import dlib; print('dlib OK')"` 驗證
3. **關鍵**：wheel/deps 安裝層排在 app code 之前 → 改 app code 不動 dlib 層（layer cache 命中）→ **dlib 零編譯**，build 從數十分鐘降到約 1–2 分。
4. `wsgi.py` 加 `pkg_resources` shim（`face_recognition_models` 需要，新版 setuptools 移除了 `pkg_resources`）。
5. **代價**：repo 增約 100M（models wheel）。已接受，直接 commit。

**依賴（鎖版，`requirements.txt`）**：`face_recognition`、`numpy`、`Pillow`（face_recognition 相依）、`flask-limiter`；`dlib` / `face_recognition_models` 由 wheel 提供（不列 pip 版本解析）。gunicorn 部署沿用 webapp 模式。

**本機 dev**：測試以 mock 跑（見 §11），不需本機裝 dlib；要真臉端到端才裝同組 wheel。系統相依（libopenblas 等）在 plan 標明。

---

## 11. 測試策略

- **單元**：
  - best-match 距離挑選為**純函式**（吃候選 encodings + 送入 encoding，回 matched/ambiguous/none），用假 128 維向量單測 threshold 0.45 / margin 0.05 / 撞臉整批拒。
  - `is_seed_mode()` 各條件。
  - idle 逾時計算、`_cleanup_pending_devices` TTL。
  - 候選 scope（公務機模式：已核准裝置放行任一在職帳號；密碼區分帳號、同密碼同臉判 ambiguous）。
- **整合**（`face_recognition` **mock**，不真跑 dlib）：register-device（新建/認領/SEEN）、裝置閘擋未核准、seed mode 首次啟用、`/auth/verify` 各回傳狀態、rate-limit、裝置核准/換機（撤舊發新）/撤銷。
- 全程**不真呼叫 dlib**；只在需要時本機手動驗證真臉。

---

## 12. 鐵律遵循檢查

- 影像不落地：登入/錄臉的單張畫面僅在記憶體、算完 encoding 即丟；DB 只存數字向量、無照片。相機不錄影、不進相簿。✅
- fingerprint 永不作認證：只寫入供稽核，認證一律 `client_uid`。✅
- 前端不輪詢：idle 逾時伺服器端判定；前端僅單一計時器導頁。✅
- 狀態全進 DB：裝置/使用者/session idle 標記皆持久或 session cookie，無 module-level 跨 request 狀態。✅
- 時間存 UTC。✅

---

## 13. 範圍外（後續各自 JIT plan）

- 登入頁工具：Apple 風計算機 + 幣別換算（JPY/USD/THB/EUR）。
- 上傳 + OCR、暫存區、店管理者稽核、會計核銷（原 spec 後續）。
- 進階加固（延後項，見 `.superpowers/sdd/progress.md`）：`current_user` 補 active 重查已由本 plan 的裝置/session 閘涵蓋一部分；login constant-time 時間側通道仍待評估。
