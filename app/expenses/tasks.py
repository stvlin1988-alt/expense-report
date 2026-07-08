import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

from flask import current_app
from app.extensions import db
from app.models import Expense, OcrLog
from app.ocr.provider import get_provider, coerce_amount
from app.ocr.retry import recognize_with_retry

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=4)


def _valid_category_id(cid):
    if cid is None:
        return None
    from app.models import Category
    return cid if db.session.get(Category, cid) is not None else None


def _last_error(attempts):
    return attempts[-1]["error_type"] if attempts else None


def _write_ocr_logs(expense, attempts):
    now = datetime.now(timezone.utc)
    for a in attempts:
        db.session.add(OcrLog(
            expense_id=expense.id, store_id=expense.store_id,
            attempt=a["attempt"], outcome=a["outcome"], error_type=a["error_type"],
            http_status=a["http_status"], duration_ms=a["duration_ms"], ts=now))


def _run_ocr(app, expense_id, image_bytes, content_type):
    with app.app_context():
        e = db.session.get(Expense, expense_id)
        if e is None or e.status != "pending_ocr":
            return
        e.ocr_attempts += 1
        result = recognize_with_retry(get_provider(), image_bytes, content_type, current_app.config)
        _write_ocr_logs(e, result["attempts"])
        outcome = result["final_outcome"]
        if outcome == "success":
            f = result["fields"]
            amount, ok = coerce_amount(f.get("amount"))
            e.summary = f.get("summary")
            e.category_id = _valid_category_id(f.get("category_id"))
            e.amount = amount
            e.amount_parse_ok = ok
            e.ocr_confidence = f.get("confidence")
            e.ocr_is_handwritten = f.get("is_handwritten")
            e.ocr_raw = f.get("raw")
            e.status = "draft"
            e.ocr_failed = False
        elif outcome == "fatal":
            e.status = "draft"; e.ocr_failed = True; e.amount_parse_ok = False
            e.ocr_last_error = _last_error(result["attempts"])
        else:  # exhausted
            e.ocr_last_error = _last_error(result["attempts"])
            if e.ocr_attempts >= current_app.config.get("OCR_MAX_ROUNDS", 3):
                e.status = "draft"; e.ocr_failed = True; e.amount_parse_ok = False
            # 未達上限 → 維持 pending_ocr，待 reconcile_stale 重排
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
