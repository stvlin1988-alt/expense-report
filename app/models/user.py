from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db

ROLES = ("employee", "manager", "accountant", "super_admin")


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(
        db.Integer, db.ForeignKey("stores.id"), nullable=True
    )
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="employee")
    password_hash = db.Column(db.String(255), nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    store = db.relationship("Store", back_populates="users")

    ADMIN_ROLES = ("super_admin",)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role in self.ADMIN_ROLES
