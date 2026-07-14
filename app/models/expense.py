from app.extensions import db


class Expense(db.Model):
    __tablename__ = "expenses"

    STATUSES = ("pending_ocr", "draft", "submitted", "audited", "reconciled", "rejected")

    # 「主管已打勾／已認列」的狀態集合。本 branch 前，audited 是終態，等於這個語意；
    # 本 branch 把 audited 變成過渡態（會計會把它推進 reconciled，或退回 rejected），
    # 所以任何原本寫 status=="audited" 代表「主管已打勾」的彙整查詢，都要改用這個集合，
    # 否則會計一動手，該單就從彙整裡悄悄消失（C1 finding）。
    # 含 rejected：那筆錢確實花掉了（單據存在、現金離開收銀機），交接班對的是「這班花了多少」；
    # 會計退回只是對金額/科目有異議，不代表沒花。
    CHECKED_STATUSES = ("audited", "reconciled", "rejected")

    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey("stores.id"), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False)
    submitted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    business_date = db.Column(db.Date, nullable=True)
    day_seq = db.Column(db.Integer, nullable=True)  # 當日店內序號，送出時指派；單號=MMDD-NN

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
    ocr_scheduled_at = db.Column(db.DateTime(timezone=True), nullable=True)

    no_receipt_reason = db.Column(db.Text, nullable=True)
    is_no_receipt = db.Column(db.Boolean, nullable=False, default=False)
    doc_type_id = db.Column(db.Integer, db.ForeignKey("doc_types.id"), nullable=True)

    audited_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    audited_at = db.Column(db.DateTime(timezone=True), nullable=True)
    is_modified_by_manager = db.Column(db.Boolean, nullable=False, default=False)
    handover_id = db.Column(db.Integer, db.ForeignKey("handovers.id"), nullable=True, index=True)
    last_modified_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    last_modified_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_modified_fields = db.Column(db.String(32), nullable=True)  # 最後一次改了哪些欄位: "amount"/"category"/"amount,category"

    # 會計核銷
    reconciled_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reconciled_at = db.Column(db.DateTime(timezone=True), nullable=True)
    reject_reason = db.Column(db.String(200), nullable=True)  # 會計退回原因
    # 主管被會計退回（rejected）後改完重新打勾（check()）的時間戳；用來讓會計端
    # 一眼認出「這張是重送過的」，因為 check() 會清掉 reject_reason，資料上
    # 分不出跟從沒被退過的單的差異。首次從 submitted 打勾不設此欄。
    resubmitted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    note = db.Column(db.String(200), nullable=True)  # 員工備註；門市內部欄位，會計看不到

    __table_args__ = (
        db.Index("ix_expenses_store_status", "store_id", "status"),
        db.Index("ix_expenses_created_by_status", "created_by", "status"),
        db.Index("ix_expenses_store_bizdate", "store_id", "business_date"),
    )
