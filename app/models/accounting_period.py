from app.extensions import db


class AccountingPeriod(db.Model):
    """會計期間。由「月結日 + 鎖定偏移」設定推導、首尾相接、自動延展。
    status 持久值只有 open / closed；closing（寬限期）由 now 相對 end_date/lock_at 衍生。"""
    __tablename__ = "accounting_periods"

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(16), nullable=False)          # 依起始日所屬月份命名，如 2026-01
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False, index=True)
    lock_at = db.Column(db.DateTime(timezone=True), nullable=False)
    status = db.Column(db.String(16), nullable=False, default="open")
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    closed_at = db.Column(db.DateTime(timezone=True), nullable=True)
