"""expenses: resubmitted_at

Revision ID: a1b2c3d4e5f6
Revises: 99c5ab162dc6
Create Date: 2026-07-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = '99c5ab162dc6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('resubmitted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.drop_column('resubmitted_at')
