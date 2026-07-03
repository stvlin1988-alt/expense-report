"""fx_rate_cache

Revision ID: b7f3c1a9d2e4
Revises: 51e7c6648ba0
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = "b7f3c1a9d2e4"
down_revision = "51e7c6648ba0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fx_rate_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("base", sa.String(length=3), nullable=False),
        sa.Column("rates_json", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("base", name="uq_fx_rate_cache_base"),
    )


def downgrade():
    op.drop_table("fx_rate_cache")
