from app.extensions import db


class Handover(db.Model):
    __tablename__ = "handovers"
    TYPES = ("shift", "day")

    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey("stores.id"), nullable=False, index=True)
    closed_at = db.Column(db.DateTime(timezone=True), nullable=False)
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    type = db.Column(db.String(8), nullable=False)  # shift | day
