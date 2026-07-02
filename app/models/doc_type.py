from app.extensions import db


class DocType(db.Model):
    __tablename__ = "doc_types"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    # 保存天數；0=核銷後即刪，None=附件到期銷毀(天數 Phase 3 定)
    retention_days = db.Column(db.Integer, nullable=True)
    physical_return_required = db.Column(
        db.Boolean, nullable=False, default=False
    )
    purge_policy = db.Column(db.String(50), nullable=True)
