from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_v3_2_exit_plan_quantities"
down_revision = "0003_v3_2_runtime_safety"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("positions", sa.Column("original_quantity", sa.Numeric(28, 12), nullable=True))
    op.add_column("positions", sa.Column("target_1_quantity", sa.Numeric(28, 12), nullable=True))
    op.add_column("positions", sa.Column("target_2_quantity", sa.Numeric(28, 12), nullable=True))
    op.add_column("positions", sa.Column("target_3_quantity", sa.Numeric(28, 12), nullable=True))
    op.add_column("positions", sa.Column("target_1_filled_quantity", sa.Numeric(28, 12), nullable=True, server_default="0"))
    op.add_column("positions", sa.Column("target_2_filled_quantity", sa.Numeric(28, 12), nullable=True, server_default="0"))
    op.add_column("positions", sa.Column("target_3_filled_quantity", sa.Numeric(28, 12), nullable=True, server_default="0"))
    op.execute("UPDATE positions SET original_quantity = quantity WHERE original_quantity IS NULL")


def downgrade() -> None:
    for column in [
        "target_3_filled_quantity",
        "target_2_filled_quantity",
        "target_1_filled_quantity",
        "target_3_quantity",
        "target_2_quantity",
        "target_1_quantity",
        "original_quantity",
    ]:
        op.drop_column("positions", column)
