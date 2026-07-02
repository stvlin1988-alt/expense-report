from app.extensions import db
from app.models.user import User


def seed_admin(name, password):
    """建立/確保 super_admin（預設=業主本人）。Idempotent by role。"""
    admin = User.query.filter_by(role="super_admin").first()
    if admin is None:
        admin = User(name=name, role="super_admin", store_id=None)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
    return admin
