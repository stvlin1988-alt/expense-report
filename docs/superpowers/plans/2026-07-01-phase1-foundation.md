# Phase 1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建好 expense-report 專案骨架、資料模型、seed 資料與角色認證基礎，讓 app 能啟動、DB 能遷移、分類/單據類型/店/管理員可 seed、登入與角色權限可用。

**Architecture:** Flask app-factory + SQLAlchemy 2.x ORM + Flask-Migrate(alembic) 遷移。密碼用 Werkzeug 雜湊，session 登入。所有狀態進 DB，不用 module-level 變數。本機 dev 用 SQLite、prod 用 PostgreSQL。

**Tech Stack:** Python 3.11+, Flask 3.1.x, Flask-SQLAlchemy 3.1.x, SQLAlchemy 2.0.x, Flask-Migrate 4.x, python-dotenv, pytest 8.x, Werkzeug（隨 Flask）。

## Global Constraints

- 與 webapp **完全隔離**：獨立 repo / DB / R2 / URL，不 import 或連 webapp 任何東西。
- 依賴**鎖版**（鬆 pin：`Flask==3.1.*` 這種），列在 `requirements.txt`。
- 時間：DB 存 **UTC**（`datetime.now(timezone.utc)`），UI 顯示才轉台灣時間；本計畫不做 UI，統一存 UTC。
- 狀態全進 DB（workers>1 不用 module-level dict 存跨 request state）。
- 角色 enum 固定：`employee | manager | accountant | super_admin`。
- 分類 2 層：`level` 1=會計科目、2=項目；可增可改。
- config 檔（若新增 YAML/JSON）commit 前跑 parser 驗證。
- 每個 task 結束都 commit。

---

### Task 1: 專案骨架 + app factory + health check

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `app/__init__.py`（app factory）
- Create: `app/config.py`
- Create: `wsgi.py`
- Create: `tests/conftest.py`
- Create: `tests/test_app.py`

**Interfaces:**
- Produces: `create_app(config_object=None) -> Flask`（app factory，其他所有 task 靠它建 app）；`app.config['SQLALCHEMY_DATABASE_URI']`。

- [ ] **Step 1: 寫依賴與忽略檔**

`requirements.txt`:
```
Flask==3.1.*
Flask-SQLAlchemy==3.1.*
SQLAlchemy==2.0.*
Flask-Migrate==4.*
python-dotenv==1.*
pytest==8.*
```

`.gitignore`:
```
__pycache__/
*.pyc
.venv/
instance/
.env
*.db
.pytest_cache/
```

- [ ] **Step 2: 寫 config**

`app/config.py`:
```python
import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-key")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///instance/dev.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
```

- [ ] **Step 3: 寫失敗測試（health check）**

`tests/conftest.py`:
```python
import pytest
from app import create_app
from app.config import TestConfig


@pytest.fixture
def app():
    app = create_app(TestConfig)
    yield app


@pytest.fixture
def client(app):
    return app.test_client()
```

`tests/test_app.py`:
```python
def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}
```

- [ ] **Step 4: 跑測試確認 FAIL**

Run: `python -m pytest tests/test_app.py -v`
Expected: FAIL（`create_app` 或 `/health` 不存在）

- [ ] **Step 5: 寫 app factory**

`app/__init__.py`:
```python
from flask import Flask, jsonify


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or "app.config.Config")

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    return app
```

`wsgi.py`:
```python
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
```

- [ ] **Step 6: 跑測試確認 PASS**

Run: `python -m pytest tests/test_app.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add requirements.txt .gitignore app/ wsgi.py tests/
git commit -m "feat: Flask app factory + health check + pytest"
```

---

### Task 2: DB 基礎 + Store 與 User 模型

**Files:**
- Create: `app/extensions.py`（db 實例）
- Create: `app/models/__init__.py`
- Create: `app/models/store.py`
- Create: `app/models/user.py`
- Modify: `app/__init__.py`（註冊 db + migrate）
- Create: `tests/test_models_store_user.py`

**Interfaces:**
- Consumes: `create_app(TestConfig)`。
- Produces: `db`（Flask-SQLAlchemy）; `Store(id, name, code, active, created_at)`; `User(id, store_id, name, role, password_hash, active, created_at)`; `ROLES = ("employee", "manager", "accountant", "super_admin")`。

- [ ] **Step 1: 寫 db 擴充**

`app/extensions.py`:
```python
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()
```

- [ ] **Step 2: 寫失敗測試**

`tests/test_models_store_user.py`:
```python
from app.extensions import db
from app.models.store import Store
from app.models.user import User, ROLES


def test_create_store_and_user(app):
    with app.app_context():
        db.create_all()
        store = Store(name="測試店", code="S001")
        db.session.add(store)
        db.session.commit()

        user = User(store_id=store.id, name="小明", role="employee")
        db.session.add(user)
        db.session.commit()

        assert user.id is not None
        assert user.store.name == "測試店"
        assert "super_admin" in ROLES


def test_accountant_and_admin_have_no_store(app):
    with app.app_context():
        db.create_all()
        acc = User(store_id=None, name="會計", role="accountant")
        db.session.add(acc)
        db.session.commit()
        assert acc.store_id is None
```

- [ ] **Step 3: 跑測試確認 FAIL**

Run: `python -m pytest tests/test_models_store_user.py -v`
Expected: FAIL（模組不存在）

- [ ] **Step 4: 寫 models**

`app/models/__init__.py`:
```python
from app.models.store import Store
from app.models.user import User, ROLES

__all__ = ["Store", "User", "ROLES"]
```

`app/models/store.py`:
```python
from datetime import datetime, timezone
from app.extensions import db


class Store(db.Model):
    __tablename__ = "stores"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(30), unique=True, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    users = db.relationship("User", back_populates="store")
```

`app/models/user.py`:
```python
from datetime import datetime, timezone
from app.extensions import db

ROLES = ("employee", "manager", "accountant", "super_admin")


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(
        db.Integer, db.ForeignKey("stores.id"), nullable=True
    )
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="employee")
    password_hash = db.Column(db.String(255), nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    store = db.relationship("Store", back_populates="users")
```

- [ ] **Step 5: 在 app factory 註冊 db + migrate + import models**

修改 `app/__init__.py`，在 `create_app` 內 `app.config.from_object(...)` 之後、`return app` 之前加：
```python
    from app.extensions import db, migrate
    db.init_app(app)
    migrate.init_app(app, db)

    from app import models  # noqa: F401  確保 models 被載入註冊
```

- [ ] **Step 6: 跑測試確認 PASS**

Run: `python -m pytest tests/test_models_store_user.py -v`
Expected: PASS

- [ ] **Step 7: 初始化 migration 並產生第一版**

```bash
export FLASK_APP=wsgi.py
flask db init
flask db migrate -m "stores + users"
flask db upgrade
```

- [ ] **Step 8: Commit**

```bash
git add app/ tests/ migrations/
git commit -m "feat: db base + Store/User models + initial migration"
```

---

### Task 3: 分類（2 層）模型 + seed

**Files:**
- Create: `app/models/category.py`
- Modify: `app/models/__init__.py`
- Create: `app/seeds/categories_data.py`（附錄 A 資料）
- Create: `app/seeds/seed_categories.py`
- Create: `tests/test_categories.py`

**Interfaces:**
- Consumes: `db`。
- Produces: `Category(id, parent_id, name, level, active, sort)`; `seed_categories() -> None`（idempotent）; `CATEGORY_DATA: dict[str, list[str]]`（科目→項目）。

- [ ] **Step 1: 寫分類資料（來源 spec 附錄 A）**

`app/seeds/categories_data.py`:
```python
# 會計科目（大類）→ 項目（細項）。來源：使用者 excel 0626 / spec 附錄 A。
CATEGORY_DATA = {
    "薪資費用": ["員工薪資", "薪資提存", "津貼", "離職員工薪資", "留停員工薪資",
                 "員工介紹獎金", "年終獎金", "激勵獎金", "生日禮金", "結婚禮金",
                 "彌月禮金", "端午禮金", "中秋禮金", "尾牙禮金", "過年禮金",
                 "奠儀", "住院慰問金", "健檢費", "員工旅遊", "教育補助"],
    "租金支出": ["房租", "停車場租金", "車位租金", "管理費"],
    "郵電費": ["視訊費", "電信網路費"],
    "稅捐": ["營業稅", "娛樂稅", "房屋稅", "房屋租賃稅", "綜所稅申報",
             "汽燃稅", "牌照稅"],
    "水電瓦斯": ["水費", "電費", "瓦斯費"],
    "保險費用": ["健保費", "勞保費", "勞退金", "公共安全申報", "消防安檢申報",
                 "公共意外險", "產物險", "其他保險費"],
    "活動費用": ["現場獎", "會員禮品", "會員活動", "節日禮品.活動"],
    "修繕費用": ["店面維護費", "車輛維護費", "金磚維修費", "其他機台維修費", "掛畫維修"],
    "廚房支出": ["食材", "中廚食材", "中廚物料", "中廚禮品", "中廚茶葉",
                 "中廚修繕費", "中廚雜項支出"],
    "廣告支出": ["廣告費", "簡訊費", "美工製作費"],
    "其他費用": ["神秘彩金", "擋退招/補客", "代書帳務費", "律師顧問費",
                 "裝修工程費", "雜項支出", "團康費用", "公益活動", "公關費", "誤差"],
}
```

- [ ] **Step 2: 寫失敗測試**

`tests/test_categories.py`:
```python
from app.extensions import db
from app.models.category import Category
from app.seeds.seed_categories import seed_categories
from app.seeds.categories_data import CATEGORY_DATA


def test_seed_creates_two_levels(app):
    with app.app_context():
        db.create_all()
        seed_categories()

        top = Category.query.filter_by(level=1).all()
        assert len(top) == len(CATEGORY_DATA) == 11

        water = Category.query.filter_by(name="水電瓦斯", level=1).one()
        items = Category.query.filter_by(parent_id=water.id, level=2).all()
        assert {i.name for i in items} == {"水費", "電費", "瓦斯費"}


def test_seed_is_idempotent(app):
    with app.app_context():
        db.create_all()
        seed_categories()
        seed_categories()
        assert Category.query.filter_by(level=1).count() == 11
```

- [ ] **Step 3: 跑測試確認 FAIL**

Run: `python -m pytest tests/test_categories.py -v`
Expected: FAIL

- [ ] **Step 4: 寫 model + seed**

`app/models/category.py`:
```python
from app.extensions import db


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(
        db.Integer, db.ForeignKey("categories.id"), nullable=True
    )
    name = db.Column(db.String(100), nullable=False)
    level = db.Column(db.Integer, nullable=False)  # 1=科目, 2=項目
    active = db.Column(db.Boolean, nullable=False, default=True)
    sort = db.Column(db.Integer, nullable=False, default=0)
```

`app/seeds/__init__.py`:
```python
```

`app/seeds/seed_categories.py`:
```python
from app.extensions import db
from app.models.category import Category
from app.seeds.categories_data import CATEGORY_DATA


def seed_categories():
    """Idempotent：已存在同名同層就跳過。"""
    for s_idx, (top_name, items) in enumerate(CATEGORY_DATA.items()):
        top = Category.query.filter_by(name=top_name, level=1).first()
        if top is None:
            top = Category(name=top_name, level=1, sort=s_idx)
            db.session.add(top)
            db.session.flush()
        for i_idx, item_name in enumerate(items):
            exists = Category.query.filter_by(
                name=item_name, level=2, parent_id=top.id
            ).first()
            if exists is None:
                db.session.add(Category(
                    name=item_name, level=2, parent_id=top.id, sort=i_idx
                ))
    db.session.commit()
```

- [ ] **Step 5: 掛進 models `__init__`**

在 `app/models/__init__.py` 加 `from app.models.category import Category` 並補進 `__all__`。

- [ ] **Step 6: 跑測試確認 PASS**

Run: `python -m pytest tests/test_categories.py -v`
Expected: PASS

- [ ] **Step 7: 產 migration + Commit**

```bash
flask db migrate -m "categories"
flask db upgrade
git add app/ tests/ migrations/
git commit -m "feat: 2-level Category model + idempotent seed"
```

---

### Task 4: 單據類型 DocType 模型 + retention seed

**Files:**
- Create: `app/models/doc_type.py`
- Modify: `app/models/__init__.py`
- Create: `app/seeds/seed_doc_types.py`
- Create: `tests/test_doc_types.py`

**Interfaces:**
- Consumes: `db`。
- Produces: `DocType(id, name, retention_days, physical_return_required, purge_policy)`; `seed_doc_types() -> None`。`retention_days` 語意：發票=30、水電勞健保規費=60、小白單=None（附件到期銷毀，天數 Phase 3 定）、收據=0（核銷後即刪）。

- [ ] **Step 1: 寫失敗測試（retention 對照 spec §6）**

`tests/test_doc_types.py`:
```python
from app.extensions import db
from app.models.doc_type import DocType
from app.seeds.seed_doc_types import seed_doc_types


def test_seed_doc_types(app):
    with app.app_context():
        db.create_all()
        seed_doc_types()

        by_name = {d.name: d for d in DocType.query.all()}
        assert by_name["統一發票"].retention_days == 30
        assert by_name["統一發票"].physical_return_required is False
        assert by_name["收據"].retention_days == 0
        assert by_name["小白單"].physical_return_required is True
        assert by_name["水電勞健保規費"].retention_days == 60
        assert by_name["水電勞健保規費"].physical_return_required is True


def test_seed_doc_types_idempotent(app):
    with app.app_context():
        db.create_all()
        seed_doc_types()
        seed_doc_types()
        assert DocType.query.count() == 4
```

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python -m pytest tests/test_doc_types.py -v`
Expected: FAIL

- [ ] **Step 3: 寫 model + seed**

`app/models/doc_type.py`:
```python
from app.extensions import db


class DocType(db.Model):
    __tablename__ = "doc_types"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    # 保存天數；0=核銷後即刪，None=附件到期銷毀(天數 Phase 3 定)
    retention_days = db.Column(db.Integer, nullable=True)
    physical_return_required = db.Column(
        db.Boolean, nullable=False, default=False
    )
    purge_policy = db.Column(db.String(50), nullable=True)
```

`app/seeds/seed_doc_types.py`:
```python
from app.extensions import db
from app.models.doc_type import DocType

# (name, retention_days, physical_return_required, purge_policy)
DOC_TYPES = [
    ("統一發票", 30, False, "days_after_upload"),
    ("收據", 0, False, "on_reconcile"),
    ("小白單", None, True, "attachment_expire"),
    ("水電勞健保規費", 60, True, "days_after_upload"),
]


def seed_doc_types():
    for name, days, ret, policy in DOC_TYPES:
        if DocType.query.filter_by(name=name).first() is None:
            db.session.add(DocType(
                name=name, retention_days=days,
                physical_return_required=ret, purge_policy=policy,
            ))
    db.session.commit()
```

- [ ] **Step 4: 掛進 models `__init__`**

在 `app/models/__init__.py` 加 `from app.models.doc_type import DocType` 並補 `__all__`。

- [ ] **Step 5: 跑測試確認 PASS**

Run: `python -m pytest tests/test_doc_types.py -v`
Expected: PASS

- [ ] **Step 6: 產 migration + Commit**

```bash
flask db migrate -m "doc_types"
flask db upgrade
git add app/ tests/ migrations/
git commit -m "feat: DocType model + retention seed"
```

---

### Task 5: 密碼/角色認證 + super_admin seed + 登入

**Files:**
- Modify: `app/models/user.py`（加 set/check password + role helpers）
- Create: `app/auth/__init__.py`
- Create: `app/auth/routes.py`（login/logout）
- Create: `app/auth/decorators.py`（role_required）
- Modify: `app/__init__.py`（註冊 auth blueprint）
- Create: `app/seeds/seed_admin.py`
- Create: `tests/test_auth.py`

**Interfaces:**
- Consumes: `create_app`, `db`, `User`。
- Produces: `User.set_password(pw)`, `User.check_password(pw) -> bool`, `User.is_admin -> bool`; blueprint `auth`（`POST /auth/login`, `POST /auth/logout`）；session key `user_id`；decorator `role_required(*roles)`; `seed_admin(name, password) -> User`（建 super_admin，idempotent）。

- [ ] **Step 1: 寫失敗測試**

`tests/test_auth.py`:
```python
from app.extensions import db
from app.models.user import User
from app.seeds.seed_admin import seed_admin


def test_password_hash_roundtrip(app):
    with app.app_context():
        db.create_all()
        u = User(name="owner", role="super_admin")
        u.set_password("secret123")
        assert u.password_hash != "secret123"
        assert u.check_password("secret123") is True
        assert u.check_password("wrong") is False


def test_seed_admin_idempotent(app):
    with app.app_context():
        db.create_all()
        a = seed_admin("業主", "owner-pw")
        seed_admin("業主", "owner-pw")
        assert a.role == "super_admin"
        assert a.is_admin is True
        assert User.query.filter_by(role="super_admin").count() == 1


def test_login_and_session(app, client):
    with app.app_context():
        db.create_all()
        seed_admin("業主", "owner-pw")

    resp = client.post("/auth/login", json={"name": "業主", "password": "owner-pw"})
    assert resp.status_code == 200
    assert resp.get_json()["role"] == "super_admin"

    bad = client.post("/auth/login", json={"name": "業主", "password": "x"})
    assert bad.status_code == 401
```

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python -m pytest tests/test_auth.py -v`
Expected: FAIL

- [ ] **Step 3: User 加密碼與角色 helper**

在 `app/models/user.py` 頂部加 `from werkzeug.security import generate_password_hash, check_password_hash`，並在 `User` class 內加：
```python
    ADMIN_ROLES = ("super_admin",)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role in self.ADMIN_ROLES
```

- [ ] **Step 4: 寫 auth blueprint + decorator + admin seed**

`app/auth/__init__.py`:
```python
from app.auth.routes import auth_bp

__all__ = ["auth_bp"]
```

`app/auth/routes.py`:
```python
from flask import Blueprint, request, session, jsonify
from app.extensions import db
from app.models.user import User

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    user = User.query.filter_by(name=data.get("name"), active=True).first()
    if user is None or not user.check_password(data.get("password", "")):
        return jsonify(error="invalid credentials"), 401
    session["user_id"] = user.id
    return jsonify(id=user.id, name=user.name, role=user.role)


@auth_bp.post("/logout")
def logout():
    session.pop("user_id", None)
    return jsonify(status="ok")
```

`app/auth/decorators.py`:
```python
from functools import wraps
from flask import session, jsonify
from app.models.user import User


def current_user():
    uid = session.get("user_id")
    return User.query.get(uid) if uid else None


def role_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if user is None:
                return jsonify(error="unauthenticated"), 401
            if roles and user.role not in roles:
                return jsonify(error="forbidden"), 403
            return fn(*args, **kwargs)
        return wrapper
    return deco
```

`app/seeds/seed_admin.py`:
```python
from app.extensions import db
from app.models.user import User


def seed_admin(name, password):
    """建立/確保 super_admin（預設=業主本人）。Idempotent by role。"""
    admin = User.query.filter_by(role="super_admin").first()
    if admin is None:
        admin = User(name=name, role="super_admin", store_id=None)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
    return admin
```

- [ ] **Step 5: 註冊 blueprint**

在 `app/__init__.py` 的 `create_app` 內、`return app` 前加：
```python
    from app.auth import auth_bp
    app.register_blueprint(auth_bp)
```

- [ ] **Step 6: 跑全部測試確認 PASS**

Run: `python -m pytest -v`
Expected: 全部 PASS

- [ ] **Step 7: 產 migration + Commit**

```bash
flask db migrate -m "user password fields"
flask db upgrade
git add app/ tests/ migrations/
git commit -m "feat: password auth + roles + super_admin seed + login"
```

---

## Self-Review

**Spec coverage（對 Phase 1 foundation 範圍）：**
- §2 角色 → Task 2（User.role enum）+ Task 5（super_admin seed、role_required）✅
- §3 stores/users/categories/doc_types 模型 → Task 2/3/4 ✅
- §3 分類 seed（附錄 A）→ Task 3 ✅
- §6 retention → Task 4 ✅
- Global：UTC 存時間 ✅、依賴鎖版 ✅、alembic 遷移 ✅、狀態進 DB ✅
- **本計畫範圍外（後續計畫）**：devices/enrollment_codes、expenses/line_items/audit_log、OCR、R2、暫存區、稽核、核銷、business_date、PWA 前端。

**Placeholder scan：** 無 TBD/TODO；每個 code step 都有完整程式碼。

**Type consistency：** `create_app`、`db`、`User(role=...)`、`seed_categories()`、`seed_doc_types()`、`seed_admin(name,password)`、`role_required(*roles)` 跨 task 命名一致。

## 後續 Phase 1 計畫（各自 just-in-time 撰寫）

1. **裝置認證**：devices + enrollment_codes、綁定碼流程、裝置 token（httpOnly cookie）、換機、fingerprint 僅稽核。
2. **上傳 + OCR**：`OCRProvider` 介面 + Gemini adapter（mock 測試）、無狀態辨識、expenses 建 draft、business_date 08:00 計算、R2 上傳(SSE)、無圖建帳。
3. **暫存區**：draft 確認/修改、is_modified_by_user、紅綠燈信心度、送出。
4. **店管理者稽核**：未打勾清單、即時累加日總額、逐筆打勾（audited）。
5. **會計核銷**：紅綠燈儀表板、左圖右表覆核（簽章 URL）、綠燈批次核銷（reconciled）。
