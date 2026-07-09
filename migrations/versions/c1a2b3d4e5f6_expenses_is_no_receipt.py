"""expenses: is_no_receipt flag (無單據建帳標記)

Revision ID: c1a2b3d4e5f6
Revises: 68b03ba4051f
Create Date: 2026-07-09 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1a2b3d4e5f6'
down_revision = '68b03ba4051f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        # Boolean NOT NULL 用 sa.false()（Postgres 不吃 sa.text('0')）
        batch_op.add_column(sa.Column('is_no_receipt', sa.Boolean(),
                                      nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.drop_column('is_no_receipt')
