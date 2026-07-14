"""GET /reconcile/stores：會計端選店下拉（id+name，不含 code/secret）。
不可讓會計去打 /admin/stores（該路由是 manager/super_admin 專用，見 CLAUDE.md 對過度授權的鐵律）。"""
import time
import pytest
from app.extensions import db
from app.models import Store, User, Device

# 登入 helper 照 tests/test_reconcile_list.py 現成寫法


def _set_session(client, uid):
    client.set_cookie("device_uid", "dev1")
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["_last_request_at"] = int(time.time())


def login_accountant(client, app):
    with app.app_context():
        uid = User.query.filter_by(role="accountant").first().id
    _set_session(client, uid)


def login_manager(client, app):
    with app.app_context():
        uid = User.query.filter_by(role="manager").first().id
    _set_session(client, uid)


@pytest.fixture
def two_stores(app):
    with app.app_context():
        db.create_all()
        s1 = Store(name="A店", code="A")
        s2 = Store(name="B店", code="B")
        db.session.add_all([s1, s2])
        db.session.commit()

        mgr = User(name="主管A", role="manager", store_id=s1.id)
        mgr.set_password("0000")
        acct = User(name="會計", role="accountant")  # 跨店角色，不吃 store_id
        acct.set_password("0000")
        dev = Device(client_uid="dev1", store_id=s1.id, is_approved=True)
        db.session.add_all([mgr, acct, dev])
        db.session.commit()
        return {"store_ids": [s1.id, s2.id]}


def test_accountant_sees_all_stores(client, app, two_stores):
    login_accountant(client, app)
    r = client.get("/reconcile/stores")
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "ok"
    ids = {s["id"] for s in data["stores"]}
    assert ids == set(two_stores["store_ids"])
    # 白名單：只回 id/name，不帶 code/secret 等欄位
    for s in data["stores"]:
        assert set(s.keys()) == {"id", "name"}


def test_unauthenticated_401(client, app, two_stores):
    r = client.get("/reconcile/stores")
    assert r.status_code == 401


def test_manager_forbidden(client, app, two_stores):
    login_manager(client, app)
    r = client.get("/reconcile/stores")
    assert r.status_code == 403
