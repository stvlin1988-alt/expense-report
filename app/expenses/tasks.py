import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

from flask import current_app
from app.extensions import db
from app.models import Expense, OcrLog
from app.ocr.provider import get_provider, coerce_amount
from app.ocr.retry import recognize_with_retry
from app.storage.r2 import get_storage

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=4)


def _aware_utc(dt):
    """SQLite 存 DateTime(timezone=True) 讀回會變 naive；補回 UTC 才能跟
    tz-aware 的 now()/cutoff 比較（同一個坑在 app/expenses/logic.py 也有）。"""
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _valid_category_id(cid):
    """cid 是原始 JSON 值，型別不可信（dict/list/字串/bool 都可能送進來）。
    比照 app/reconcile/routes.py 的 _coerce_id：拒絕 bool、int() 包在 try 裡失敗回 None，
    避免非法型別直接餵進 db.session.get() 炸 InvalidRequestError/DataError → 500。
    查不到的 id 一樣回 None（清空科目）——語意不變。"""
    if cid is None or isinstance(cid, bool):
        return None
    try:
        cid = int(cid)
    except (TypeError, ValueError):
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
        try:
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
        except Exception:   # 任何未預期例外都不能讓這筆卡在 pending_ocr
            logger.exception("unexpected OCR failure, converging expense_id=%s to draft/ocr_failed", expense_id)
            try:
                db.session.rollback()
                e2 = db.session.get(Expense, expense_id)
                if e2 is not None and e2.status == "pending_ocr":
                    e2.ocr_attempts += 1
                    e2.status = "draft"; e2.ocr_failed = True; e2.amount_parse_ok = False
                    e2.ocr_last_error = "unexpected"
                    db.session.commit()
            except Exception:   # 收斂路徑本身要 best-effort，不能再讓 worker 掛掉
                logger.exception("failed to converge stranded OCR row expense_id=%s", expense_id)
                db.session.rollback()
            return
        db.session.commit()


def schedule_ocr(expense_id, image_bytes, content_type):
    app = current_app._get_current_object()
    if app.config.get("EXPENSE_OCR_SYNC"):
        _run_ocr(app, expense_id, image_bytes, content_type)   # 測試/可預測
    else:
        _executor.submit(_run_ocr, app, expense_id, image_bytes, content_type)


def reconcile_stale(user_id):
    """暫存區列表拉取時就地收斂：逾時仍 pending_ocr 的單，
    未達重排上限且原圖還在 → 從 R2 重抓再跑一輪 OCR；否則收斂成 draft+ocr_failed。
    重排節流：ocr_scheduled_at 在節流窗內（近期才排過）→ 略過，避免在途/剛排的
    那一輪被同一次 list-pull 重複送 OCR（async 模式 schedule_ocr 是 fire-and-forget，
    重複送會打兩次 Gemini + 產生重複 ocr_log）。"""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(
        seconds=current_app.config.get("OCR_STALE_SECONDS", 120))
    throttle_cutoff = now - timedelta(
        seconds=current_app.config.get("OCR_RESCHEDULE_THROTTLE_SECONDS", 120))
    max_rounds = current_app.config.get("OCR_MAX_ROUNDS", 3)
    stale = (Expense.query
             .filter(Expense.created_by == user_id,
                     Expense.status == "pending_ocr",
                     Expense.created_at < cutoff).all())
    storage = get_storage()
    changed = False
    for e in stale:
        scheduled_at = _aware_utc(e.ocr_scheduled_at)
        # 1) 收斂條件優先於節流：達上限或無圖，即使剛排程也要收斂
        if e.ocr_attempts >= max_rounds or not e.image_key:
            e.status = "draft"; e.ocr_failed = True; e.amount_parse_ok = False
            e.ocr_last_error = e.ocr_last_error or "gave_up"
            changed = True
            continue
        # 2) 節流：近期已排過一輪，交給該輪自然收斂，不重排
        if scheduled_at is not None and scheduled_at >= throttle_cutoff:
            continue
        # 3) 其餘情況：未達上限、有圖、節流窗外 → 重抓再排一輪
        image_bytes = None
        try:
            image_bytes = storage.get(e.image_key)
        except Exception:
            image_bytes = None
        if image_bytes:
            e.ocr_scheduled_at = now
            changed = True   # 節流時間戳必須 commit，讓並發的 list-pull 看到
            schedule_ocr(e.id, image_bytes, "image/jpeg")   # 跑新一輪（含重試）
        else:
            e.status = "draft"; e.ocr_failed = True; e.amount_parse_ok = False
            e.ocr_last_error = e.ocr_last_error or "gave_up"
            changed = True
    if changed:
        db.session.commit()
