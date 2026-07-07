import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

from flask import current_app
from app.extensions import db
from app.models import Expense
from app.ocr.provider import get_provider, coerce_amount

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=4)


def _valid_category_id(cid):
    if cid is None:
        return None
    from app.models import Category
    return cid if db.session.get(Category, cid) is not None else None


def _run_ocr(app, expense_id, image_bytes, content_type):
    with app.app_context():
        try:
            result = get_provider().recognize(image_bytes, content_type)
        except Exception as e:
            logger.warning("OCR run failed: %s", e); result = None
        e = db.session.get(Expense, expense_id)
        if e is None or e.status != "pending_ocr":
            return
        if not result:
            e.status = "draft"; e.amount_parse_ok = False
        else:
            amount, ok = coerce_amount(result.get("amount"))
            e.summary = result.get("summary")
            e.category_id = _valid_category_id(result.get("category_id"))
            e.amount = amount
            e.amount_parse_ok = ok
            e.ocr_confidence = result.get("confidence")
            e.ocr_is_handwritten = result.get("is_handwritten")
            e.ocr_raw = result.get("raw")
            e.status = "draft"
        db.session.commit()


def schedule_ocr(expense_id, image_bytes, content_type):
    app = current_app._get_current_object()
    if app.config.get("EXPENSE_OCR_SYNC"):
        _run_ocr(app, expense_id, image_bytes, content_type)   # 測試/可預測
    else:
        _executor.submit(_run_ocr, app, expense_id, image_bytes, content_type)


def reconcile_stale(user_id):
    """暫存區列表拉取時就地收斂：逾時仍 pending_ocr → draft 空欄紅燈。"""
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=current_app.config.get("OCR_STALE_SECONDS", 120))
    stale = (Expense.query
             .filter(Expense.created_by == user_id,
                     Expense.status == "pending_ocr",
                     Expense.created_at < cutoff).all())
    for e in stale:
        e.status = "draft"; e.amount_parse_ok = False
    if stale:
        db.session.commit()
