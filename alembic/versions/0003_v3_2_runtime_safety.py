from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_v3_2_runtime_safety"
down_revision = "0002_v2_runtime_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_state",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("state", sa.String(length=32), index=True),
        sa.Column("reason", sa.Text()),
        sa.Column("payload_json", sa.Text(), default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("system_state")
