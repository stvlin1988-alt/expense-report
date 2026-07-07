import time
from app.extensions import db
from app.models import Store, User, Device, Category


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A"); db.session.add(s); db.session.commit()
        u = User(name="員工A", role="employee", store_id=s.id); u.set_password("0000")
        dev = Device(client_uid="devEmp", store_id=s.id, is_approved=True)
        p = Category(name="廚房支出", level=1, sort=1)
        db.session.add_all([u, dev, p]); db.session.commit()
        c1 = Category(name="食材", level=2, parent_id=p.id, sort=1)
        c2 = Category(name="中廚物料", level=2, parent_id=p.id, sort=2)
        inactive = Category(name="停用項", level=2, parent_id=p.id, sort=3, active=False)
        db.session.add_all([c1, c2, inactive]); db.session.commit()
        return s.id, u.id


def _client(app, user_id):
    c = app.test_client(); c.set_cookie("device_uid", "devEmp")
    with c.session_transaction() as sess:
        sess["user_id"] = user_id; sess["_last_request_at"] = int(time.time())
    return c


def test_categories_tree(app):
    sid, uid = _seed(app)
    c = _client(app, uid)
    body = c.get("/expenses/categories").get_json()
    assert body["status"] == "ok"
    assert len(body["categories"]) == 1
    grp = body["categories"][0]
    assert grp["name"] == "廚房支出"
    names = [i["name"] for i in grp["items"]]
    assert names == ["食材", "中廚物料"]        # 依 sort、排除停用


def test_categories_requires_login(app):
    _seed(app)
    c = app.test_client(); c.set_cookie("device_uid", "devEmp")
    assert c.get("/expenses/categories").status_code == 401
