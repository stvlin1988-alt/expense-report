"""backfill period_id for pre-existing expenses (I1)

在「月結期間」功能上線前就已存在的 expenses（audited/reconciled/rejected...）一律
period_id=NULL；periods 功能只在新單子建立（get_or_create_period 掛勾在 submit/
manual 等寫入路徑）時才會補上 period_id，既有舊單永遠不會被自動補。若不補，這些單
會從期間篩選過的待處理清單/報表裡消失（backfill_periods() 早已寫好且有測試覆蓋，
只是從沒被任何呼叫端呼叫過）。

資料回填，冪等（backfill_periods 內部邏輯保證：只挑 period_id IS NULL 的列）。

Revision ID: fdc6539dcebf
Revises: 351cd5d6a353
Create Date: 2026-07-15 15:29:12.342298

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fdc6539dcebf'
down_revision = '351cd5d6a353'
branch_labels = None
depends_on = None


def upgrade():
    from app.periods.service import backfill_periods
    from app.extensions import db
    backfill_periods()
    db.session.commit()


def downgrade():
    pass  # 資料回填不可逆；不清空 period_id（避免破壞已進行的月結）
