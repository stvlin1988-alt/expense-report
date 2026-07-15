"""stores.viewable (檢視顯示開關，與 active 對外連結分開)

Revision ID: c7e1a2b3d4f5
Revises: fdc6539dcebf
Create Date: 2026-07-15

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7e1a2b3d4f5'
down_revision = 'fdc6539dcebf'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('stores', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'viewable', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    with op.batch_alter_table('stores', schema=None) as batch_op:
        batch_op.drop_column('viewable')
