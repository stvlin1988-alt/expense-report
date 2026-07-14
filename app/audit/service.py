from app.extensions import db
from app.models import Expense, Handover
from app.expenses.logic import iso_utc


def _sum(store_id, handover_id):
    # audited_at IS NOT NULL＝真的經過主管打勾（/audit/<id>/check）。會計自建的 manual 單
    # 沒有這個時間戳，且永遠不會被交班掃描收編（handover_id 恆為 NULL），所以若不排除，
    # 它會永久灌進 open 小計與 day_total，且沒有任何操作能把它清掉。
    # 主管端彙整＝「這幾班門市花了多少」，manual 是會計自己補的帳，不屬於任何班別。
    rows = (Expense.query
            .filter_by(store_id=store_id, handover_id=handover_id)
            .filter(Expense.status.in_(Expense.CHECKED_STATUSES),
                    Expense.audited_at.isnot(None)).all())
    subtotal = sum(float(x.amount) for x in rows if x.amount is not None)
    return subtotal, len(rows)


def compute_summary(store_id, before_id=None):
    """當前稽核日（before_id=None）或指定結班日的分區間彙整。"""
    if before_id is None:
        last_day = (Handover.query
                    .filter_by(store_id=store_id, type="day")
                    .order_by(Handover.closed_at.desc(), Handover.id.desc()).first())
        lower = last_day.closed_at if last_day else None
        q = Handover.query.filter_by(store_id=store_id)
        if lower is not None:
            q = q.filter(Handover.closed_at > lower)
        handovers = q.order_by(Handover.closed_at.asc(), Handover.id.asc()).all()
        include_open = True
    else:
        end = db.session.get(Handover, before_id)
        prev = (Handover.query
                .filter(Handover.store_id == store_id, Handover.type == "day",
                        Handover.closed_at < end.closed_at)
                .order_by(Handover.closed_at.desc(), Handover.id.desc()).first())
        q = Handover.query.filter(Handover.store_id == store_id,
                                  Handover.closed_at <= end.closed_at)
        if prev is not None:
            q = q.filter(Handover.closed_at > prev.closed_at)
        handovers = q.order_by(Handover.closed_at.asc(), Handover.id.asc()).all()
        include_open = False

    intervals = []
    day_total = 0.0
    for i, h in enumerate(handovers, start=1):
        subtotal, count = _sum(store_id, h.id)
        intervals.append({"handover_id": h.id, "type": h.type, "seq": i,
                          "closed_at": iso_utc(h.closed_at), "subtotal": subtotal,
                          "count": count})
        day_total += subtotal

    open_block = {"subtotal": 0.0, "count": 0}
    if include_open:
        s, c = _sum(store_id, None)
        open_block = {"subtotal": s, "count": c}
        day_total += s
    return {"intervals": intervals, "open": open_block, "day_total": day_total}
