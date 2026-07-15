from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from app.expenses.logic import TW_TZ
from app.extensions import db
from app.models import AccountingPeriod, Expense
from app.periods.settings import get_close_day, get_lock_offset_hours


def _aware_utc(dt):
    """SQLite 存 DateTime(timezone=True) 讀回會變 naive；補回 UTC 才能跟
    tz-aware 的 now_utc 比較（同一個坑在 app/expenses/logic.py 等模組也有）。"""
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _clamped(year, month, day):
    """該月第 day 天；月份不足（如 2/31）clamp 到月底。"""
    last = monthrange(year, month)[1]
    return date(year, month, min(day, last))


def _add_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _sub_month(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _period_start(d, close_day):
    """d 所屬期間起始（<= d 的最近換期日）。"""
    this_month = _clamped(d.year, d.month, close_day)
    if d >= this_month:
        return this_month
    y, m = _sub_month(d.year, d.month)
    return _clamped(y, m, close_day)


def canonical_bounds(d, close_day):
    start = _period_start(d, close_day)
    ny, nm = _add_month(start.year, start.month)
    next_start = _clamped(ny, nm, close_day)
    return start, next_start - timedelta(days=1)


def lock_at_for(next_start, offset_hours):
    local_midnight = datetime(next_start.year, next_start.month, next_start.day,
                              tzinfo=TW_TZ)
    return (local_midnight + timedelta(hours=offset_hours)).astimezone(timezone.utc)


def label_for(start):
    return f"{start.year:04d}-{start.month:02d}"


def get_or_create_period(business_date):
    p = (AccountingPeriod.query
         .filter(AccountingPeriod.start_date <= business_date,
                 AccountingPeriod.end_date >= business_date)
         .first())
    if p is not None:
        return p

    close_day = get_close_day()
    start, end = canonical_bounds(business_date, close_day)

    # 尊重既有相鄰期：經理可能手動延長過上一期 end_date，順延起始避免重疊/留洞。
    prev = (AccountingPeriod.query
            .filter(AccountingPeriod.start_date < start)
            .order_by(AccountingPeriod.start_date.desc())
            .first())
    if prev is not None and prev.end_date >= start:
        start = prev.end_date + timedelta(days=1)

    next_start = end + timedelta(days=1)
    p = AccountingPeriod(
        label=label_for(start), start_date=start, end_date=end,
        lock_at=lock_at_for(next_start, get_lock_offset_hours()), status="open")
    db.session.add(p)
    db.session.flush()
    return p


def successor_bounds(period, close_day):
    """period 之後那一期（下一標籤月）的 (start, end, label)。
    start 接在 period.end_date+1；標籤月＝period.label 月 +1（權威，不看 start_date，
    因為調整後 start_date 可能落在上一個日曆月而算錯月份）。"""
    y, m = int(period.label[:4]), int(period.label[5:7])
    ny, nm = _add_month(y, m)          # 下一標籤月
    ny2, nm2 = _add_month(ny, nm)      # 再下個月，用來算 end 邊界
    start = period.end_date + timedelta(days=1)
    end = _clamped(ny2, nm2, close_day) - timedelta(days=1)
    return start, end, f"{ny:04d}-{nm:02d}"


def effective_status(period, now_utc):
    if period.status == "closed":
        return "closed"
    today_tw = now_utc.astimezone(TW_TZ).date()
    if today_tw <= period.end_date:
        return "open"
    return "closing"


def is_period_closed(period_id, now_utc):
    """寫入閘：period_id 為 None（單子還沒歸期）一律不擋。"""
    if period_id is None:
        return False
    p = db.session.get(AccountingPeriod, period_id)
    if p is None:
        return False
    return effective_status(p, now_utc) == "closed"


def _next_period_of(period):
    return get_or_create_period(period.end_date + timedelta(days=1))


def _do_close(period, now_utc, closed_by=None):
    """封月核心：條件更新設 closed（+ closed_by）並把 audited/rejected 單挪到下一期，
    submitted 留原期不動。以條件更新確保多個呼叫者（多個 worker，或系統自動封月與會計
    提前手動封月）同時碰到時只有一個真的封月。回傳這次呼叫是否真的封了月。
    不自行 commit，交由呼叫端。"""
    updated = (AccountingPeriod.query
               .filter(AccountingPeriod.id == period.id,
                       AccountingPeriod.status != "closed")
               .update({"status": "closed", "closed_at": now_utc, "closed_by": closed_by},
                       synchronize_session=False))
    if not updated:
        return False

    nxt = _next_period_of(period)
    if nxt.status != "closed":
        (Expense.query
         .filter(Expense.period_id == period.id,
                 Expense.status.in_(("audited", "rejected")))
         .update({"period_id": nxt.id}, synchronize_session=False))
    db.session.refresh(period)
    return True


def maybe_autoclose(period, now_utc):
    """碰觸即檢查：若該期已過鎖定時刻且尚未封月，封月並把 audited/rejected 單挪到下一期，
    submitted 留原期不動。自動封月是系統動作、無 actor（closed_by=None），故不寫單據級
    audit_log（挪期由 period_id 現值 + 該期 closed_at 可追溯；move_period 的軌跡留給
    會計手動挪期的 Task 10）。不自行 commit，交由呼叫端。"""
    if period.status == "closed" or _aware_utc(now_utc) < _aware_utc(period.lock_at):
        return False
    return _do_close(period, now_utc)


def close_period_now(period, now_utc, closed_by):
    """會計提前封月：限期間已結束（寬限期 closing）才可封。
    open（進行中）不可封——會把該期剩餘日的單卡死（那些日子仍 canonically 屬本期），
    要提早鎖請先調 end_date 讓期間進入寬限期（Task 15）。"""
    if effective_status(period, now_utc) != "closing":
        return False
    return _do_close(period, now_utc, closed_by=closed_by)


def backfill_periods():
    """對所有 period_id 為 None 且 business_date 已知的既有單，依 business_date
    指派 period_id。冪等（無待補單時回 0）。不自行 commit，交由呼叫端。"""
    rows = (Expense.query
            .filter(Expense.period_id.is_(None),
                    Expense.business_date.isnot(None))
            .all())
    for e in rows:
        e.period_id = get_or_create_period(e.business_date).id
    return len(rows)
