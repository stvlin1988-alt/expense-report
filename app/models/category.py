from app.extensions import db


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(
        db.Integer, db.ForeignKey("categories.id"), nullable=True
    )
    name = db.Column(db.String(100), nullable=False)
    level = db.Column(db.Integer, nullable=False)  # 1=科目, 2=項目
    active = db.Column(db.Boolean, nullable=False, default=True)
    sort = db.Column(db.Integer, nullable=False, default=0)
