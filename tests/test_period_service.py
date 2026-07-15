from datetime import date, datetime, timezone

from app.extensions import db
from app.models import AccountingPeriod
from app.periods.service import get_or_create_period, effective_status


def test_get_or_create_creates_once(app):
    with app.app_context():
        db.create_all()
        p1 = get_or_create_period(date(2026, 1, 10))
        db.session.commit()
        p2 = get_or_create_period(date(2026, 1, 20))  # 同期
        assert p1.id == p2.id
        assert p1.label == "2026-01"
        assert p1.start_date == date(2026, 1, 1)
        assert p1.end_date == date(2026, 1, 31)
        assert AccountingPeriod.query.count() == 1


def test_get_or_create_next_month_is_new_period(app):
    with app.app_context():
        db.create_all()
        jan = get_or_create_period(date(2026, 1, 10))
        db.session.commit()
        feb = get_or_create_period(date(2026, 2, 3))
        db.session.commit()
        assert feb.id != jan.id
        assert feb.start_date == date(2026, 2, 1)  # 首尾相接


def test_effective_status_open_closing_closed(app):
    with app.app_context():
        db.create_all()
        p = get_or_create_period(date(2026, 1, 10))
        db.session.commit()
        # 期間內
        assert effective_status(p, datetime(2026, 1, 15, 3, 0, tzinfo=timezone.utc)) == "open"
        # 已過 end_date、未到 lock_at（lock=2/2 04:00 UTC）
        assert effective_status(p, datetime(2026, 2, 1, 6, 0, tzinfo=timezone.utc)) == "closing"
        # 持久封月優先
        p.status = "closed"
        assert effective_status(p, datetime(2026, 1, 15, 3, 0, tzinfo=timezone.utc)) == "closed"
