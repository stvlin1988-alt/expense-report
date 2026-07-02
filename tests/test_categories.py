from app.extensions import db
from app.models.category import Category
from app.seeds.seed_categories import seed_categories
from app.seeds.categories_data import CATEGORY_DATA


def test_seed_creates_two_levels(app):
    with app.app_context():
        db.create_all()
        seed_categories()

        top = Category.query.filter_by(level=1).all()
        assert len(top) == len(CATEGORY_DATA) == 11

        water = Category.query.filter_by(name="水電瓦斯", level=1).one()
        items = Category.query.filter_by(parent_id=water.id, level=2).all()
        assert {i.name for i in items} == {"水費", "電費", "瓦斯費"}


def test_seed_is_idempotent(app):
    with app.app_context():
        db.create_all()
        seed_categories()
        seed_categories()
        assert Category.query.filter_by(level=1).count() == 11
