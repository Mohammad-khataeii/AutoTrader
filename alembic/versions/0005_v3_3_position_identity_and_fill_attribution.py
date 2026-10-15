from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_v3_3_ledger"
down_revision = "0004_v3_2_exit_plan_quantities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fills", sa.Column("position_id", sa.String(length=64), nullable=True))
    op.create_index("ix_fills_position_id", "fills", ["position_id"])
    op.execute(
        """
        UPDATE fills
        SET position_id = positions.position_id
        FROM positions
        WHERE fills.symbol = positions.symbol
          AND fills.position_id IS NULL
        """
    )
    op.execute("ALTER TABLE positions DROP CONSTRAINT IF EXISTS positions_symbol_key")
    op.execute("DROP INDEX IF EXISTS ix_positions_symbol")
    op.create_index("ix_positions_symbol", "positions", ["symbol"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_positions_symbol", table_name="positions")
    op.create_unique_constraint("positions_symbol_key", "positions", ["symbol"])
    op.drop_index("ix_fills_position_id", table_name="fills")
    op.drop_column("fills", "position_id")
