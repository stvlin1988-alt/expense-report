# Phase 1 — 公開計算機終端 + 隱蔽登入前端（Plan 3a）

> 狀態：設計定案（2026-07-03），待寫實作計畫。
> 前置：Plan 1（foundation）、Plan 2（認證與裝置）後端已完成並 merge。本 plan 是**第一批 HTML 前端**。
> 範圍切分：本份 = **3a 終端/登入**；後台管理 UI（店/帳號/密碼/裝置核准）另立 **3b**。兩份做完再一起整合測試。

---

## 1. 目標與定位

門市公用手機擺在檯面，任何人都看得到螢幕。因此登入入口必須**藏在一台真正能用的計算機後面**：

- 對外＝一台可用的 Apple iOS 風計算機（含即時匯率換算），旁人只當它是計算機。
- 只有知道**隱蔽指令**的人，能在限定時間內叫出「密碼＋人臉」登入。
- 全程符合既有鐵律：影像不落地、fingerprint 不作認證、前端不輪詢、時間顯示台灣時間、狀態進 DB。

本 plan 完成後即可在**瀏覽器端端到端驗證**：首次啟用 bootstrap 建業主並錄臉 → 暗號 → 密碼＋刷臉 → 登入成功。

### 非目標（明確排除）
- 後台管理 UI（新增店、直接創帳號、改密碼、裝置核准/換機/撤銷、調店檢視）→ **3b**。
- 管理者替員工代錄臉、使用者清單 UI → **3b**（需要使用者清單端點與畫面）。
- 上傳單據 / OCR / 暫存區 / 稽核 / 核銷 → Phase 1 後續。
- 登入後真正的業務首頁（員工上傳頁、管理者後台）→ 尚未建，先以占位畫面銜接。

---

## 2. 技術與慣例

- Flask Jinja 伺服器渲染 + 原生 JS（ES2015+）+ `fetch`，**無 npm / 打包 / 前端框架**（與 webapp 一致、零 build 步驟）。
- 新增 `web` blueprint；模板放 `app/templates/`、靜態放 `app/static/`（Flask app factory 預設路徑，需新建目錄）。
- 參考 webapp（`~/projects/webapp/app2_weather/`、`app_unified/`）的隱蔽登入 pattern：`tap_detector.js` / `modal_auth.js` / `face_capture.js` / `camera.js` / `sw.js`——沿用結構，改寫對接本專案後端。
- 與 webapp 完全隔離：獨立模板/靜態，不共用檔案。

---

## 3. 網址隱蔽模型（單一可見網址）

**需求**：使用者端可見網址不得出現 `home` / `enroll` 等洩底字眼；瀏覽器網址列、歷史、自動完成都不能透露系統存在。

**做法：單一網址 + 前端切畫面**
- 使用者可見網址**永遠是 `/`**。登入後的「占位首頁」「更新人臉」都是**同一頁內用 JS 切換 DOM 畫面**（view state），不是獨立路由。
- 分頁 `<title>` 與 `manifest.json` 名稱一律無害字樣（「計算機 / Calculator」）。
- 後端 API 路徑（`/auth/verify`、`/face/enroll`、`/api/v1/*`）只出現在開發者工具 Network，不出現在網址列。威脅模型是**門市旁人（不開 devtools）**，故可接受；且這些是既有已測路徑，不改。
- **重整行為**：重整 → 回計算機（更隱蔽）。若 session 仍有效，伺服器渲染 `/` 時把身分注入模板；使用者按暗號可直接回到登入後畫面、不需重打密碼。

---

## 4. 路由與 Gate

### 4.1 新增路由

| 路由 | 方法 | 用途 | Gate 行為 |
|---|---|---|---|
| `/` | GET | 計算機終端（唯一可見頁）。伺服器注入 `seed_mode`、`identity`；**`secret_hash` 僅在「已核准裝置 or seed mode」才注入**（未核准裝置注入 `null`，見 §5.2）| **豁免** device/idle gate |
| `/api/v1/fx` | GET | 匯率快取讀取（見 §7） | 豁免（在 `/api/v1/` 前綴下，既有豁免） |

> 不新增 `/home`、`/enroll` 路由（改為前端 view state，符合 §3）。
> 既有 `/auth/*`、`/face/*`、`/admin/*`、`/api/v1/register-device` 不變。

### 4.2 Gate 調整（`app/auth/gates.py`）
- 把 `/` 加入 `_EXEMPT_PATHS`（幌子頁必須任何裝置都能載入，否則未核准裝置會看到 JSON 403、破壞幌子）。
- `/api/v1/` 前綴已豁免（含 `register-device`、`fx`）。
- **既有 JSON gate 邏輯維持**：`/auth/*`、`/face/*`、`/admin/*` 仍受 device gate（未核准裝置回 `device_not_approved` 403）+ idle gate（逾時回 `session_expired` 401）保護。這正是隱蔽登入所需——未核准裝置能看到計算機，但送出登入會被後端擋下（前端隱蔽處理）。
- seed mode 下 gate 本就全放行，`/` 照常渲染 bootstrap 旗標。

---

## 5. 計算機終端 UI（`/`）

### 5.1 版面（Apple iOS 風）
兩個 tab 共用同一組數字鍵盤：

```
┌──────────────────────────┐
│  [ 計算機 ]   [ 匯率 ]    │  頂部 tab
│                    0     │  顯示區（右對齊大字）
├──────────────────────────┤
│  AC    ±     %     ÷      │  淺灰功能鍵
│  7     8     9     ×      │  深灰數字 / 橘色運算子
│  4     5     6     −      │
│  1     2     3     +      │
│  0(寬)       .     =      │
└──────────────────────────┘
```

- **計算機 tab**：標準四則運算，離線可用。行為需像真計算機（AC 清除、±正負、% 百分比、連續運算、小數點）。
- **匯率 tab**：上方來源幣別 chip（TWD / JPY / USD / THB / EUR），用同一鍵盤輸入金額，下方即時列出換算到其他幣別的金額（讀 `/api/v1/fx`）。運算子鍵在此 tab 淡化停用。切回計算機 tab 保留/清空由實作決定，但兩 tab 不得互相污染狀態。
- 視覺走 iOS 計算機質感：深色底、圓角按鈕、橘色運算子；響應式，適配公用手機直式螢幕。

### 5.2 隱蔽指令觸發

- **暗號序列**：鍵位 `0 7 8 × 2 =`（即輸入 `078*2` 後按 `=`）。
- **偵測**：自上次清除（AC / 進入頁面）起累積的輸入字串 == `078*2`，且此刻按下 `=` → **不計算 156**，改為清空顯示並：
  - 一般模式 → 跳出**登入 modal**（§6.1）。
  - seed mode → 跳出 **bootstrap modal**（§6.2）。
- **未觸發時**：`078*2=` 正常顯示 `156`，與一般計算機無異。
- **條件式注入（隱蔽登入的真正防線）**：`secret_hash` **只對「已核准裝置（`is_device_authorized(device_uid)`）或 seed mode」注入**；未核准裝置注入 `null`。
  - 未核准裝置：頁面**完全沒有** `secret_hash`，打 `078*2=` 只會顯示 `156`（純計算機），看原始碼也翻不到任何 hash——連「這裡藏了登入」都察覺不到。
  - seed mode（系統全新、尚無已核准裝置）**必須注入**，否則第一個人無法完成首次設定（bootstrap 自行建立+核准當前裝置）→ 雞生蛋。這是唯一信任窗口，與 Plan 2 既有 seed 開放一致。
  - 新增「第二台以後」未核准裝置的核准由後台處理（**Plan 3b** 裝置核准 UI）；3a 測試以 bootstrap 建的業主帳號端到端驗證即可。
- **6 秒窗 + 銷毀注入資料**：計算機**開啟（頁面載入）起算 6 秒**。
  - 若未在窗內完成暗號 → 本次工作階段**鎖定觸發**（`triggerLocked = true`），之後純為一般計算機、無法叫出系統；**須重整 / 重開** PWA 才能再試。
  - 6 秒到時**主動銷毀整包注入資料**：清空記憶體中的 `cfg`（`secretHash`/`identity`）並把 DOM 的 `<script id="app-config">` 內容抹成 `{}`——即使 6 秒後 inspect DOM 也翻不到 hash。
  - 6 秒起算點 = 頁面載入時（本 plan 定案；若日後要改「首次按鍵起算」再調）。
- **暗號混淆**：`078*2` 以伺服器注入的 **未加鹽 sha256 hex**（`secret_hash`，來源 config/env）比對；原始碼看不到明碼。定位為輕度混淆（防路人瞄原始碼），真正安全靠裝置閘＋密碼＋人臉三層，不依賴暗號保密。
  - 為何未加鹽：hash 要在前端比對就得把鹽也送到瀏覽器，鹽被迫公開即退化成未加鹽；暗號空間極小，加鹽無實質防護價值，故不加鹽以免徒增複雜度。
  - 暗號值可經 config/env 設定（預設 `078*2`），改暗號不動 code。

---

## 6. 登入 / bootstrap / 錄臉流程

### 6.0 密碼政策 + 登出行為（2026-07-03 追加）
- **密碼一律 4 位純數字 PIN**（`^\d{4}$`）。前端輸入框強制（`inputmode=numeric`、`maxlength=4`、即時濾掉非數字），後端在所有「設密碼」入口驗證（`is_valid_pin`）：`/auth/bootstrap`、`/admin/users`、`/admin/users/<id>/password`、`/admin/me/password`、`/admin/devices/<id>/approve`(new_user)。`/auth/verify` **不驗格式**（僅比對，格式不符自然不中）。model `set_password` 不驗（僅路由入口驗，限制 blast radius）。
- **登出 = 重整頁面**（`location.reload()`）：清 session 後重載 → 回計算機、6 秒暗號窗重新起算、已核准裝置重新取得 `secret_hash`，登出後可立即再按暗號登入（否則舊 6 秒窗早已過期、暗號叫不出登入）。

### 6.1 登入 modal（一般模式）
1. 開啟 modal 當下才 `POST /api/v1/register-device`（**不在每次公開瀏覽就註冊**，避免 pending 洗版）——設 `device_uid` cookie、若為新裝置則入 pending 佇列（供 3b 後台核准）。
2. 自動開相機（沿用 `Camera` helper：`getUserMedia` → 單張畫面 → canvas → base64 jpeg，**不錄影、不進相簿、不落地**）。
3. 使用者輸入密碼 → 送 `POST /auth/verify {password, face_image}`。
4. 依回傳 `status` **隱蔽處理**（§6.4）。

### 6.2 bootstrap modal（seed mode）
- 條件：伺服器渲染 `/` 時 `is_seed_mode()` 為真（無 super_admin / 無已核准裝置 / 所有 super_admin 無臉）。
- 暗號改叫出 bootstrap modal：輸入姓名 + 密碼 + 開相機錄臉 → `POST /auth/bootstrap {name, password, face_image}`。
- 成功（`status=ok`）→ 提示後 reload；此時已非 seed mode，且當前裝置已被核准、業主已登入 → 進登入後畫面。
- `face_not_found` → 提示重拍臉；`already_initialized` → reload 回一般模式。

### 6.3 登入後畫面 + 更新人臉（前端 view state）
- 登入成功後（`/auth/verify` 或 bootstrap 回 `ok`）→ JS 切到**登入後占位畫面**（非換網址）：顯示姓名、角色、登出鈕、「更新人臉」動作。
  - 員工 / 管理者 / 業主現階段都導到同一占位畫面（上傳頁與後台尚未建；3a/3b/後續會替換導向邏輯）。
- **更新人臉（本人重錄）**：占位畫面上的動作，開相機拍單張 → `POST /face/enroll {face_image}`（不帶 `user_id` = 錄本人；後端 `_can_enroll` 已允許本人）。
- **登出**：`POST /auth/logout` → 切回計算機畫面。
- 「管理者替員工代錄臉 / 選擇使用者」不在 3a（需使用者清單，屬 3b）。

### 6.4 隱蔽回饋（威脅模型：門市旁人看得到螢幕）
`/auth/verify` 各 `status` 的前端呈現：

| status | 意義 | 前端呈現 |
|---|---|---|
| `ok` | 成功 | 切登入後畫面（依 role） |
| `wrong_password` | 密碼錯 | **同一句無害訊息**（如「無法計算，請重試」） |
| `face_mismatch` / `ambiguous` / `face_not_found` | 臉不符/不明/沒抓到臉 | 同上無害訊息 |
| `need_face_enroll` | 密碼中了但該帳號無臉（且此狀態**不建立 session**） | 同上無害訊息。新帳號的臉由管理者在 **3b** 代錄；3a 不自助處理 |
| `device_not_approved` | 裝置未核准（後端 gate 擋下） | 同上無害訊息。此時裝置已於步驟 1 入 pending，待 3b 核准後再試 |
| `store_disabled` | 店停用 | 同上無害訊息 |

- 失敗一律回**同一句無害訊息**，不透露「這是登入」「錯在密碼還是臉」。
- 成功才有明顯轉場。
- 允許 Enter 送出、關閉 modal（背景點擊 / ×）時**停止相機**釋放鏡頭。

---

## 7. 匯率服務（真實可用）

需求：計算機的匯率換算要能實際使用、用**現在的匯率**。

- **來源**：`open.er-api.com`（免金鑰、含 TWD）。⚠️ 這是**新增外部依賴**，部署後伺服器會對外連線抓匯率。
- **快取進 DB**（遵守鐵律「狀態進 DB、workers>1 不用 module-level dict」）：新增 `fx_rate_cache`（`base`、`rates` JSON、`fetched_at`）——單列或以 base 為鍵。
- **端點 `GET /api/v1/fx`**：
  - 若 `fetched_at` 超過 TTL（**預設 6 小時**）→ 伺服器抓外部 API，更新快取後回傳。
  - 未過期 → 直接回快取。
  - 外部抓取失敗 → 回上次快取（graceful degradation）；若從未成功過 → 回明確錯誤狀態，前端匯率 tab 顯示「暫時無法取得匯率」，計算機 tab 不受影響。
- 幣別集合：TWD / JPY / USD / THB / EUR（交叉換算，前端以 base rates 自行算交叉匯率）。
- 前端**載入時抓一次**、切到匯率 tab 時可再讀快取；**不輪詢**。

---

## 8. PWA 殼

- `base.html`：共用骨架（無害 title、viewport、manifest link、SW 註冊、CSS）。
- `manifest.json`：無害名稱/圖示，`display: standalone`，可加到主畫面當「計算機」。
- `sw.js`（改寫自 webapp）：
  - `/static/*` cache-first（計算機離線可用）。
  - `/auth/*`、`/face/*`、`/api/*` **network-first 且絕不快取**（認證/影像/匯率不得留快取）。
  - 導覽 network-first，離線 fallback 到快取的計算機殼。
  - 所有 fallback 保證回傳 Response（避免 webapp 踩過的 `respondWith(undefined)` 例外）。
- Service worker 註冊寫在 `base.html` 或獨立小 JS。

---

## 9. 元件邊界（各自單一職責、可獨立理解/測試）

| 元件 | 職責 | 依賴 |
|---|---|---|
| `web` blueprint（後端）| 渲染 `/`（注入 seed_mode / secret_hash / identity）、`/api/v1/fx` | models、gates、config |
| `fx_rate_cache` model + FX service | 抓取/快取/回傳匯率 | DB、外部 API |
| `calculator.js` | 純計算機邏輯（四則、AC、±、%、小數） | 無 |
| `currency.js` | 匯率 tab：讀 `/api/v1/fx`、交叉換算、渲染 | `/api/v1/fx` |
| `secret_trigger.js` | 偵測暗號序列 + 6 秒窗 + hash 比對 → 開對應 modal | 顯示區狀態、`secret_hash` |
| `camera.js`（沿用改寫）| `getUserMedia` 單張擷取 base64、start/stop | 瀏覽器 API |
| `auth_modal.js` | 登入 modal：register-device → verify → 隱蔽回饋 → 切畫面 | `/api/v1/register-device`、`/auth/verify`、camera |
| `bootstrap_modal.js` | bootstrap modal：建業主+錄臉 | `/auth/bootstrap`、camera |
| `app_view.js` | 登入後占位畫面 + 更新人臉 + 登出（view state 切換） | `/face/enroll`、`/auth/logout` |
| `sw.js` + `manifest.json` | PWA 殼、快取策略 | 瀏覽器 API |

---

## 10. 測試策略

- **後端（pytest 自動化）**：
  - `/` 渲染成功；未核准裝置也能取得 `/`（gate 豁免生效）。
  - `/` 在 seed mode 注入 `seed_mode=true`、非 seed mode 注入 `false`；注入 `secret_hash`。
  - 已登入 session 時 `/` 注入 identity；未登入時不注入。
  - `/api/v1/fx`：快取新鮮時回快取、過期時觸發刷新（外部呼叫以 mock 隔離，不打真 API）；抓取失敗回舊快取；DB 快取讀寫正確。
  - gate：`/` 豁免、`/auth/verify` 對未核准裝置仍 403。
- **前端 JS**：無 build，優先以純函式切出可測邏輯（計算機運算、交叉換算、暗號序列比對、6 秒窗）——可用輕量 node 測試或於瀏覽器 console 驗證；DOM/相機部分靠手動。
- **端到端（手動瀏覽器）**：
  - seed mode：暗號 → bootstrap → 建業主+錄臉 → 進占位畫面。
  - 一般模式：暗號 → 密碼+刷臉 → 登入成功；密碼/臉錯 → 無害訊息。
  - 6 秒窗逾時 → 觸發鎖定、僅剩一般計算機。
  - 未核准裝置：暗號可開 modal，送出得無害訊息；裝置入 pending。
  - 刷臉可用你的**真實人臉照片**，或沿用 webapp 的 VirtualCam（v4l2loopback）手法餵樣本臉。
- 全套沿用 SDD：逐 task implementer + task review + fix，最終全 branch review，測試 OK + user 明說才 merge 回 master、不 push。

---

## 11. 風險與註記

- **外部依賴 open.er-api.com**：部署會對外連線；抓取失敗需 graceful（回舊快取 / 停用匯率 tab），不得拖垮計算機或登入。依賴版本/行為變動風險低（純 HTTP GET JSON）。
- **暗號輕度混淆**：hash 比對只擋「看原始碼的路人」，非強保密；真正防線是裝置閘＋密碼＋人臉。
- **6 秒窗起算點**：定為頁面載入；PWA 於背景喚醒/前景切換的計時行為需在實作時確認（以 `visibilitychange` / 載入事件為準）。
- **pending 裝置洗版**：register-device 只在開登入 modal 時觸發，已降低；30 分 TTL 清理沿用既有邏輯。
- **登入後占位畫面**是暫時銜接，之後由上傳頁（員工）與後台（3b）替換導向。
