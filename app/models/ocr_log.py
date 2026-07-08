from app.extensions import db


class OcrLog(db.Model):
    __tablename__ = "ocr_log"

    id = db.Column(db.Integer, primary_key=True)
    expense_id = db.Column(db.Integer, db.ForeignKey("expenses.id"), nullable=False, index=True)
    store_id = db.Column(db.Integer, db.ForeignKey("stores.id"), nullable=False, index=True)
    attempt = db.Column(db.Integer, nullable=False)
    outcome = db.Column(db.String(16), nullable=False)      # success | retryable | fatal
    error_type = db.Column(db.String(16), nullable=True)    # rate_limit | overloaded | server | timeout | parse | schema | bad_request | other
    http_status = db.Column(db.Integer, nullable=True)
    duration_ms = db.Column(db.Integer, nullable=True)
    ts = db.Column(db.DateTime(timezone=True), nullable=False)
