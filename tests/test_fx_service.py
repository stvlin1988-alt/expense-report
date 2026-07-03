import json
from app.extensions import db
from app.models.fx_rate import FxRate


def test_fxrate_model_persists(app):
    with app.app_context():
        db.create_all()
        row = FxRate(base="USD", rates_json=json.dumps({"USD": 1.0}))
        db.session.add(row)
        db.session.commit()
        got = FxRate.query.filter_by(base="USD").first()
        assert got is not None
        assert json.loads(got.rates_json)["USD"] == 1.0
        assert got.fetched_at is not None


from datetime import datetime, timezone, timedelta
import app.fx.service as svc

SAMPLE = {"TWD": 32.0, "JPY": 155.0, "USD": 1.0, "THB": 36.0, "EUR": 0.92}


def test_get_rates_fetches_and_caches_when_empty(app, monkeypatch):
    monkeypatch.setattr(svc, "_fetch_remote_rates", lambda: dict(SAMPLE))
    with app.app_context():
        db.create_all()
        rates, fetched = svc.get_rates()
        assert rates == SAMPLE
        assert fetched is not None
        assert FxRate.query.filter_by(base="USD").count() == 1


def test_get_rates_returns_cache_within_ttl_without_fetch(app, monkeypatch):
    calls = {"n": 0}

    def fake():
        calls["n"] += 1
        return dict(SAMPLE)

    monkeypatch.setattr(svc, "_fetch_remote_rates", fake)
    with app.app_context():
        db.create_all()
        svc.get_rates()
        svc.get_rates()
        assert calls["n"] == 1  # TTL 內不重抓


def test_get_rates_refreshes_when_stale(app, monkeypatch):
    monkeypatch.setattr(svc, "_fetch_remote_rates", lambda: dict(SAMPLE))
    with app.app_context():
        db.create_all()
        db.session.add(FxRate(
            base="USD", rates_json=json.dumps({"USD": 1.0}),
            fetched_at=datetime.now(timezone.utc) - timedelta(hours=7)))
        db.session.commit()
        rates, _ = svc.get_rates()
        assert rates == SAMPLE


def test_get_rates_falls_back_to_stale_cache_on_failure(app, monkeypatch):
    monkeypatch.setattr(svc, "_fetch_remote_rates", lambda: None)
    old = {"USD": 1.0, "TWD": 30.0}
    with app.app_context():
        db.create_all()
        db.session.add(FxRate(
            base="USD", rates_json=json.dumps(old),
            fetched_at=datetime.now(timezone.utc) - timedelta(hours=7)))
        db.session.commit()
        rates, _ = svc.get_rates()
        assert rates == old


def test_get_rates_none_when_no_cache_and_fetch_fails(app, monkeypatch):
    monkeypatch.setattr(svc, "_fetch_remote_rates", lambda: None)
    with app.app_context():
        db.create_all()
        rates, fetched = svc.get_rates()
        assert rates is None and fetched is None


def test_get_rates_insert_race_falls_back_to_reread(app, monkeypatch):
    """兩 worker 同時發現無快取列並各自成功 fetch：先 commit 的那個成功 insert，
    後 commit 的那個應在 IntegrityError 後 rollback + 重讀，回競爭者的列，
    而不是讓例外冒出（500）。"""
    monkeypatch.setattr(svc, "_fetch_remote_rates", lambda: dict(SAMPLE))
    competing = {"TWD": 99.0, "JPY": 199.0, "USD": 1.0, "THB": 39.0, "EUR": 0.99}

    with app.app_context():
        db.create_all()

        orig_commit = db.session.commit
        state = {"raced": False}

        def racy_commit():
            if not state["raced"]:
                state["raced"] = True
                # 模擬另一個 worker 搶先用獨立連線 insert+commit 同一 base 列，
                # 讓本 worker 待會兒的 flush 真的撞 unique(base) 約束。
                with db.engine.connect() as conn:
                    conn.execute(
                        FxRate.__table__.insert().values(
                            base="USD",
                            rates_json=json.dumps(competing),
                            fetched_at=datetime.now(timezone.utc),
                        )
                    )
                    conn.commit()
            orig_commit()

        monkeypatch.setattr(db.session, "commit", racy_commit)

        rates, fetched = svc.get_rates()

        assert rates == competing
        assert fetched is not None
        assert FxRate.query.filter_by(base="USD").count() == 1
