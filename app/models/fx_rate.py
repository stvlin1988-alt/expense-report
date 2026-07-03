from datetime import datetime, timezone

from app.extensions import db


class FxRate(db.Model):
    """匯率快取：以 base 幣別為鍵存一份 rates JSON。狀態進 DB，workers>1 共用。"""
    __tablename__ = "fx_rate_cache"

    id = db.Column(db.Integer, primary_key=True)
    base = db.Column(db.String(3), unique=True, nullable=False)
    rates_json = db.Column(db.Text, nullable=False)  # {"JPY":..,"USD":..,...}
    fetched_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
