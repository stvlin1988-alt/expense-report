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
