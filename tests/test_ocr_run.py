import json
import logging
import time
from datetime import datetime, timezone
from app.extensions import db
from app.models import Store, User, Device, Expense, OcrLog
import app.expenses.tasks as tasks


def _mk(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="e", role="employee", store_id=s.id); u.set_password("1234")
        db.session.add(u); db.session.commit()
        e = Expense(store_id=s.id, created_by=u.id, status="pending_ocr",
                    created_at=datetime.now(timezone.utc))
        db.session.add(e); db.session.commit()
        return e.id


def _patch(monkeypatch, result):
    monkeypatch.setattr(tasks, "recognize_with_retry",
                        lambda *a, **k: result)


def test_success_sets_draft_and_logs(app, monkeypatch):
    eid = _mk(app)
    _patch(monkeypatch, {"fields": {"summary": "全家", "amount": 1290, "category_id": None,
                                    "confidence": 0.9, "is_handwritten": False, "raw": {}},
                         "final_outcome": "success",
                         "attempts": [{"attempt": 1, "outcome": "success", "error_type": None,
                                       "http_status": None, "duration_ms": 50}]})
    tasks._run_ocr(app, eid, b"img", "image/jpeg")
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "draft" and e.ocr_failed is False and float(e.amount) == 1290.0
        assert e.ocr_attempts == 1
        assert OcrLog.query.filter_by(expense_id=eid, outcome="success").count() == 1


def test_fatal_sets_draft_failed(app, monkeypatch):
    eid = _mk(app)
    _patch(monkeypatch, {"fields": None, "final_outcome": "fatal",
                         "attempts": [{"attempt": 1, "outcome": "fatal", "error_type": "schema",
                                       "http_status": None, "duration_ms": 30}]})
    tasks._run_ocr(app, eid, b"img", "image/jpeg")
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "draft" and e.ocr_failed is True and e.ocr_last_error == "schema"


def test_exhausted_below_limit_stays_pending(app, monkeypatch):
    eid = _mk(app)
    app.config["OCR_MAX_ROUNDS"] = 3
    _patch(monkeypatch, {"fields": None, "final_outcome": "exhausted",
                         "attempts": [{"attempt": 1, "outcome": "retryable", "error_type": "overloaded",
                                       "http_status": 503, "duration_ms": 40}]})
    tasks._run_ocr(app, eid, b"img", "image/jpeg")
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "pending_ocr" and e.ocr_failed is False  # 留給背景重排
        assert e.ocr_attempts == 1 and e.ocr_last_error == "overloaded"


def test_exhausted_at_limit_marks_failed(app, monkeypatch):
    eid = _mk(app)
    app.config["OCR_MAX_ROUNDS"] = 1   # 第一輪就達上限
    _patch(monkeypatch, {"fields": None, "final_outcome": "exhausted",
                         "attempts": [{"attempt": 1, "outcome": "retryable", "error_type": "rate_limit",
                                       "http_status": 429, "duration_ms": 40}]})
    tasks._run_ocr(app, eid, b"img", "image/jpeg")
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "draft" and e.ocr_failed is True


def test_unexpected_exception_does_not_strand_row_in_pending(app, monkeypatch):
    # 回歸守門：recognize_with_retry 拋出未分類例外時，這筆單不能永遠卡在 pending_ocr
    eid = _mk(app)

    def boom(*a, **k):
        raise Exception("boom")

    monkeypatch.setattr(tasks, "recognize_with_retry", boom)
    tasks._run_ocr(app, eid, b"img", "image/jpeg")
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "draft"
        assert e.ocr_failed is True
        assert e.status != "pending_ocr"


def _mk_with_device(app):
    """建一組 store/user/device + 一筆 pending_ocr，回 (expense_id, user_id)。"""
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="e", role="employee", store_id=s.id); u.set_password("1234")
        dev = Device(client_uid="devOcr", store_id=s.id, is_approved=True)
        db.session.add_all([u, dev]); db.session.commit()
        e = Expense(store_id=s.id, created_by=u.id, status="pending_ocr",
                    created_at=datetime.now(timezone.utc))
        db.session.add(e); db.session.commit()
        return e.id, u.id


def test_hallucinated_infinite_amount_does_not_break_pending_json(app, monkeypatch):
    """C2 的 OCR 路徑：json.loads('{"amount": 1e999}') → inf 是合法 JSON，Gemini 幻覺金額
    會走進 coerce_amount。裸 float() 會把 inf 存進 DB → /expenses/pending 回傳裸 Infinity
    token → 瀏覽器嚴格 JSON.parse 丟例外 → 員工暫存區整頁死掉（那正是唯一能修那筆的畫面）。
    垃圾金額必須落成 amount=None + amount_parse_ok=False，讓該筆亮紅/黃燈由員工手 key。"""
    eid, uid = _mk_with_device(app)
    hallucinated = json.loads('{"amount": 1e999}')["amount"]    # float('inf')
    _patch(monkeypatch, {"fields": {"summary": "全家", "amount": hallucinated,
                                    "category_id": None, "confidence": 0.9,
                                    "is_handwritten": False, "raw": {}},
                         "final_outcome": "success",
                         "attempts": [{"attempt": 1, "outcome": "success", "error_type": None,
                                       "http_status": None, "duration_ms": 50}]})
    tasks._run_ocr(app, eid, b"img", "image/jpeg")
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "draft"
        assert e.amount is None, "非有限的幻覺金額不得存進 DB"
        assert e.amount_parse_ok is False

    c = app.test_client(); c.set_cookie("device_uid", "devOcr")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    resp = c.get("/expenses/pending")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Infinity" not in body and "NaN" not in body

    def _strict(tok):   # Python 的 json 預設會吃 Infinity/NaN，瀏覽器 JSON.parse 不會
        raise ValueError(f"non-standard JSON token: {tok}")

    parsed = json.loads(body, parse_constant=_strict)
    assert parsed["status"] == "ok"
    assert parsed["expenses"][0]["amount"] is None


def test_unexpected_exception_logs_error(app, monkeypatch, caplog):
    # 防呆路徑觸發時要留下 log 訊號（原本靜默吞掉，正式環境完全看不到）
    eid = _mk(app)

    def boom(*a, **k):
        raise Exception("boom")

    monkeypatch.setattr(tasks, "recognize_with_retry", boom)
    with caplog.at_level(logging.ERROR, logger="app.expenses.tasks"):
        tasks._run_ocr(app, eid, b"img", "image/jpeg")
    assert any(
        r.levelno >= logging.ERROR and str(eid) in r.getMessage()
        for r in caplog.records
    )
