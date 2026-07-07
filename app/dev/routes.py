"""開發專用登入捷徑（一鍵進 app，跳過密碼/人臉）。

安全上鎖（雙重）：
1. 此 blueprint 只在 create_app 內、`E2E_LOGIN_BYPASS` 為真且非 production 時才註冊；
   production 連路由都不存在（404）。
2. 路由內再擋一次 production。
測試用，勿在正式環境開啟。
"""
import base64
import os
import time

from flask import Blueprint, current_app, redirect, session, jsonify

from app.extensions import db
from app.models import Store, User

dev_bp = Blueprint("dev", __name__, url_prefix="/dev")

_SAMPLE_RECEIPT = "tests/fixtures/receipts/01_familymart.jpg"


def _blocked():
    return (current_app.config.get("APP_ENV") == "production"
            or not current_app.config.get("E2E_LOGIN_BYPASS"))


def _ensure_test_employee():
    """確保有一間測試店 + 一個 employee（無需臉，捷徑登入不驗臉）。"""
    store = Store.query.filter_by(code="E2E").first()
    if store is None:
        store = Store(name="測試門市", code="E2E")
        db.session.add(store); db.session.commit()
    emp = User.query.filter_by(name="測試員工").first()
    if emp is None:
        emp = User(name="測試員工", role="employee", store_id=store.id)
        emp.set_password("1234")
        db.session.add(emp); db.session.commit()
    return emp


@dev_bp.get("/login-test")
def login_test():
    if _blocked():
        return jsonify(status="not_found"), 404
    emp = _ensure_test_employee()
    session["user_id"] = emp.id
    session.permanent = True
    session["_last_request_at"] = int(time.time())
    return redirect("/")


@dev_bp.get("/sample-receipt")
def sample_receipt():
    """回一張樣本收據(base64 data URL)，讓拍單在無相機下也能測 UI 流程。"""
    if _blocked():
        return jsonify(status="not_found"), 404
    path = os.path.normpath(os.path.join(current_app.root_path, "..", _SAMPLE_RECEIPT))
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return jsonify(image="data:image/jpeg;base64," + b64)
