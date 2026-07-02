from app.extensions import db
from app.models.doc_type import DocType

# (name, retention_days, physical_return_required, purge_policy)
DOC_TYPES = [
    ("統一發票", 30, False, "days_after_upload"),
    ("收據", 0, False, "on_reconcile"),
    ("小白單", None, True, "attachment_expire"),
    ("水電勞健保規費", 60, True, "days_after_upload"),
]


def seed_doc_types():
    """Idempotent：已存在同名就跳過。"""
    for name, days, ret, policy in DOC_TYPES:
        if DocType.query.filter_by(name=name).first() is None:
            db.session.add(DocType(
                name=name, retention_days=days,
                physical_return_required=ret, purge_policy=policy,
            ))
    db.session.commit()
