from datetime import datetime, timezone
from app.extensions import db


class Device(db.Model):
    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey("stores.id"), nullable=True)
    bound_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    client_uid = db.Column(db.String(64), unique=True, nullable=False)
    fingerprint = db.Column(db.Text, nullable=True)  # 僅稽核，永不作認證判斷
    device_name = db.Column(db.String(100), nullable=False, default="Unknown")
    is_approved = db.Column(db.Boolean, nullable=False, default=False)
    is_revoked = db.Column(db.Boolean, nullable=False, default=False)
    last_seen_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    store = db.relationship("Store")
    bound_user = db.relationship("User", foreign_keys=[bound_user_id])
