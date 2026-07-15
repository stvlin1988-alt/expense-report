from datetime import datetime, timezone
from app.extensions import db


class Store(db.Model):
    __tablename__ = "stores"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(30), unique=True, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)      # 對外連結 kill-switch：停用→該店裝置擋在計算機外
    viewable = db.Column(db.Boolean, nullable=False, default=True)    # 檢視顯示：不勾→從選店選單/月報表等檢視隱藏（不影響營運）
    created_at = db.Column(
        db.DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    users = db.relationship("User", back_populates="store")
