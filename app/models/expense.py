from app.extensions import db


class Expense(db.Model):
    __tablename__ = "expenses"

    STATUSES = ("pending_ocr", "draft", "submitted", "audited")

    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey("stores.id"), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False)
    submitted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    business_date = db.Column(db.Date, nullable=True)

    summary = db.Column(db.Text, nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    amount = db.Column(db.Numeric(12, 2), nullable=True)
    currency = db.Column(db.String(8), nullable=False, default="TWD")

    status = db.Column(db.String(16), nullable=False, default="pending_ocr", index=True)

    image_key = db.Column(db.String(255), nullable=True)
    thumb_key = db.Column(db.String(255), nullable=True)

    ocr_confidence = db.Column(db.Float, nullable=True)
    ocr_is_handwritten = db.Column(db.Boolean, nullable=True)
    amount_parse_ok = db.Column(db.Boolean, nullable=True)
    is_modified_by_user = db.Column(db.Boolean, nullable=False, default=False)
    ocr_raw = db.Column(db.JSON, nullable=True)
    ocr_attempts = db.Column(db.Integer, nullable=False, default=0)
    ocr_failed = db.Column(db.Boolean, nullable=False, default=False)
    ocr_last_error = db.Column(db.String(32), nullable=True)

    no_receipt_reason = db.Column(db.Text, nullable=True)
    doc_type_id = db.Column(db.Integer, db.ForeignKey("doc_types.id"), nullable=True)

    audited_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    audited_at = db.Column(db.DateTime(timezone=True), nullable=True)
    is_modified_by_manager = db.Column(db.Boolean, nullable=False, default=False)
    handover_id = db.Column(db.Integer, db.ForeignKey("handovers.id"), nullable=True, index=True)

    __table_args__ = (
        db.Index("ix_expenses_store_status", "store_id", "status"),
        db.Index("ix_expenses_created_by_status", "created_by", "status"),
        db.Index("ix_expenses_store_bizdate", "store_id", "business_date"),
    )
