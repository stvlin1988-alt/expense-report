"""expenses: day_seq (當日店內序號，單號 MMDD-NN)

Revision ID: f3a1c5e7b9d2
Revises: e7d9f1b3a5c2
Create Date: 2026-07-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f3a1c5e7b9d2'
down_revision = 'e7d9f1b3a5c2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('day_seq', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.drop_column('day_seq')
