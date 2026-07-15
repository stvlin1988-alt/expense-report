from app.extensions import db
from app.models import AppSetting

DEFAULTS = {"period_close_day": "1", "period_lock_offset_hours": "36"}


def get_setting(key):
    row = db.session.get(AppSetting, key)
    if row is not None:
        return row.value
    return DEFAULTS.get(key)


def set_setting(key, value):
    row = db.session.get(AppSetting, key)
    if row is not None:
        row.value = str(value)
    else:
        db.session.add(AppSetting(key=key, value=str(value)))


def get_close_day():
    return int(get_setting("period_close_day"))


def get_lock_offset_hours():
    return int(get_setting("period_lock_offset_hours"))
