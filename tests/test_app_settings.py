from app.extensions import db
from app.periods.settings import (get_setting, set_setting,
                                   get_close_day, get_lock_offset_hours)


def test_defaults_when_unset(app):
    with app.app_context():
        db.create_all()
        assert get_close_day() == 1
        assert get_lock_offset_hours() == 36
        assert get_setting("nonexistent") is None


def test_set_then_get(app):
    with app.app_context():
        db.create_all()
        set_setting("period_close_day", "5")
        db.session.commit()
        assert get_close_day() == 5
        set_setting("period_close_day", "10")   # 覆寫既有
        db.session.commit()
        assert get_close_day() == 10
