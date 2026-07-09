"""expenses: last_modified_by / last_modified_at

Revision ID: e7d9f1b3a5c2
Revises: c1a2b3d4e5f6
Create Date: 2026-07-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e7d9f1b3a5c2'
down_revision = 'c1a2b3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_modified_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('last_modified_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.drop_column('last_modified_at')
        batch_op.drop_column('last_modified_by')
