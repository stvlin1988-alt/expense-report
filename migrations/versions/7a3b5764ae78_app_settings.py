"""app_settings

Revision ID: 7a3b5764ae78
Revises: a1b2c3d4e5f6
Create Date: 2026-07-15 11:45:13.847790

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7a3b5764ae78'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('app_settings',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', sa.String(length=255), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )


def downgrade():
    op.drop_table('app_settings')
