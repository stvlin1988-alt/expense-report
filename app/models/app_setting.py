from app.extensions import db


class AppSetting(db.Model):
    """全站 key/value 設定（目前僅月結日與鎖定偏移；只有經理能改）。"""
    __tablename__ = "app_settings"

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.String(255), nullable=False)
