from app.extensions import db
from app.models.doc_type import DocType
from app.seeds.seed_doc_types import seed_doc_types


def test_seed_doc_types(app):
    with app.app_context():
        db.create_all()
        seed_doc_types()

        by_name = {d.name: d for d in DocType.query.all()}
        assert by_name["統一發票"].retention_days == 30
        assert by_name["統一發票"].physical_return_required is False
        assert by_name["收據"].retention_days == 0
        assert by_name["小白單"].physical_return_required is True
        assert by_name["水電勞健保規費"].retention_days == 60
        assert by_name["水電勞健保規費"].physical_return_required is True


def test_seed_doc_types_idempotent(app):
    with app.app_context():
        db.create_all()
        seed_doc_types()
        seed_doc_types()
        assert DocType.query.count() == 4
