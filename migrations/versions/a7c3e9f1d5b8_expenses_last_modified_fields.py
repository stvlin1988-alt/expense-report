"""expenses: last_modified_fields (最後改了哪些欄位)

Revision ID: a7c3e9f1d5b8
Revises: f3a1c5e7b9d2
Create Date: 2026-07-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7c3e9f1d5b8'
down_revision = 'f3a1c5e7b9d2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_modified_fields', sa.String(length=32), nullable=True))


def downgrade():
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.drop_column('last_modified_fields')
