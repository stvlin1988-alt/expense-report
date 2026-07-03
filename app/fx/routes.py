from flask import Blueprint, jsonify

from app.fx.service import get_rates, BASE, CURRENCIES

fx_bp = Blueprint("fx", __name__)


@fx_bp.get("/api/v1/fx")
def fx():
    rates, fetched_at = get_rates()
    if rates is None:
        return jsonify(status="unavailable", base=BASE, currencies=CURRENCIES)
    return jsonify(status="ok", base=BASE, currencies=CURRENCIES,
                   rates=rates, fetched_at=fetched_at)
