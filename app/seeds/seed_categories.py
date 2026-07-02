from app.extensions import db
from app.models.category import Category
from app.seeds.categories_data import CATEGORY_DATA


def seed_categories():
    """Idempotent：已存在同名同層就跳過。"""
    for s_idx, (top_name, items) in enumerate(CATEGORY_DATA.items()):
        top = Category.query.filter_by(name=top_name, level=1).first()
        if top is None:
            top = Category(name=top_name, level=1, sort=s_idx)
            db.session.add(top)
            db.session.flush()
        for i_idx, item_name in enumerate(items):
            exists = Category.query.filter_by(
                name=item_name, level=2, parent_id=top.id
            ).first()
            if exists is None:
                db.session.add(Category(
                    name=item_name, level=2, parent_id=top.id, sort=i_idx
                ))
    db.session.commit()
