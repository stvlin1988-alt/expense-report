import json
import urllib.request
from datetime import datetime, timezone, timedelta

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.fx_rate import FxRate

BASE = "USD"
CURRENCIES = ["TWD", "JPY", "USD", "THB", "EUR"]


def _aware(dt):
    """SQLite 取回的 datetime 可能無 tzinfo；一律當成 UTC。"""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _fetch_remote_rates():
    """抓外部匯率，回 {cur: rate_per_USD}；失敗或幣別不齊回 None。"""
    url = current_app.config["FX_API_URL"]
    timeout = current_app.config.get("FX_FETCH_TIMEOUT", 8)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("result") != "success":
        return None
    rates = payload.get("rates") or {}
    if not all(c in rates for c in CURRENCIES):
        return None
    return {c: rates[c] for c in CURRENCIES}


def get_rates():
    """(rates, fetched_at_iso)。TTL 內回快取；過期抓新；失敗回舊快取；
    無快取且抓取失敗 → (None, None)。"""
    row = FxRate.query.filter_by(base=BASE).first()
    ttl = timedelta(seconds=current_app.config.get("FX_TTL_SECONDS", 6 * 3600))
    now = datetime.now(timezone.utc)

    if row is not None and (now - _aware(row.fetched_at)) < ttl:
        return json.loads(row.rates_json), _aware(row.fetched_at).isoformat()

    try:
        remote = _fetch_remote_rates()
    except Exception:
        remote = None

    if remote is not None:
        if row is None:
            row = FxRate(base=BASE, rates_json=json.dumps(remote), fetched_at=now)
            db.session.add(row)
            try:
                db.session.commit()
            except IntegrityError:
                # 另一 worker 同時過 TTL 並先建了列，撞 unique(base) → 收斂重讀。
                db.session.rollback()
                row = FxRate.query.filter_by(base=BASE).first()
                if row is not None:
                    return json.loads(row.rates_json), _aware(row.fetched_at).isoformat()
                return remote, now.isoformat()
        else:
            row.rates_json = json.dumps(remote)
            row.fetched_at = now
            db.session.commit()
        return remote, now.isoformat()

    if row is not None:
        return json.loads(row.rates_json), _aware(row.fetched_at).isoformat()
    return None, None
