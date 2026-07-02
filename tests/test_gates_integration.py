"""裝置閘 / idle 閘 HTTP 整合測試。

單元測試（test_gates.py）只測 is_seed_mode() 純函式，沒有任何測試真的
發一個 HTTP request 去打 register_gates() 掛上的兩個 before_request。
這裡用 Flask test client 打一個「不存在但非豁免」的路徑，驗證：
- 裝置閘 403 device_not_approved / 放行後 404（路由本身不存在）
- seed mode 直接繞過裝置閘
- idle 閘 401 session_expired，或放行並滑動續命
"""
import time

import numpy as np

from app.extensions import db
from app.models.user import User
from app.models.device import Device


PROBE = "/nonexistent-gate-probe"  # 非豁免路徑（不是 /static/、/api/v1/、/health、/sw.js、/auth/logout），用來觸發 gate


def _make_non_seed(app):
    """建立 super_admin(有臉) + 一台已核准裝置 client_uid='devOK' → 脫離 seed mode。"""
    with app.app_context():
        db.create_all()
        sa = User(name="業主", role="super_admin")
        sa.set_password("pw")
        sa.face_encoding = np.zeros(128, dtype=np.float64).tobytes()
        db.session.add(sa)
        db.session.add(Device(client_uid="devOK", is_approved=True))
        db.session.commit()
        return sa.id


def test_device_gate_blocks_unapproved_device(app):
    _make_non_seed(app)
    c = app.test_client()
    c.set_cookie("device_uid", "unapproved-uid")
    r = c.get(PROBE)
    assert r.status_code == 403
    assert r.get_json()["status"] == "device_not_approved"


def test_device_gate_blocks_missing_cookie(app):
    _make_non_seed(app)
    c = app.test_client()
    r = c.get(PROBE)  # 沒帶 device_uid cookie
    assert r.status_code == 403
    assert r.get_json()["status"] == "device_not_approved"


def test_device_gate_allows_approved_device(app):
    _make_non_seed(app)
    c = app.test_client()
    c.set_cookie("device_uid", "devOK")
    r = c.get(PROBE)
    assert r.status_code == 404  # 兩閘通過（無 session→idle 略過），路由不存在


def test_seed_mode_bypasses_device_gate(app):
    # 不建立任何 super_admin/裝置 → seed mode True → 裝置閘放行
    with app.app_context():
        db.create_all()
    c = app.test_client()
    c.set_cookie("device_uid", "whatever")
    r = c.get(PROBE)
    assert r.status_code == 404  # 放行 → 路由不存在


def test_exempt_path_bypasses_device_gate_even_when_unapproved(app):
    _make_non_seed(app)
    c = app.test_client()
    c.set_cookie("device_uid", "unapproved-uid")
    r = c.get("/health")
    assert r.status_code != 403


def test_idle_gate_expires_stale_session(app):
    sa_id = _make_non_seed(app)
    c = app.test_client()
    c.set_cookie("device_uid", "devOK")
    with c.session_transaction() as s:
        s["user_id"] = sa_id
        s["_last_request_at"] = int(time.time()) - 2000  # >1800 秒前
    r = c.get(PROBE)
    assert r.status_code == 401
    assert r.get_json()["status"] == "session_expired"

    # session 應已被清空
    with c.session_transaction() as s:
        assert "user_id" not in s


def test_idle_gate_allows_and_slides_fresh_session(app):
    sa_id = _make_non_seed(app)
    c = app.test_client()
    c.set_cookie("device_uid", "devOK")
    with c.session_transaction() as s:
        s["user_id"] = sa_id
        s["_last_request_at"] = int(time.time()) - 100
    r = c.get(PROBE)
    assert r.status_code == 404  # 通過（route 不存在）

    # _last_request_at 應被滑動更新到接近現在，而不是停在 100 秒前
    with c.session_transaction() as s:
        assert s["_last_request_at"] >= int(time.time()) - 5


def test_idle_gate_skips_when_no_session_user(app):
    sa_id = _make_non_seed(app)
    c = app.test_client()
    c.set_cookie("device_uid", "devOK")
    # 沒有 session["user_id"] → idle 閘直接略過
    r = c.get(PROBE)
    assert r.status_code == 404
