import sqlalchemy as sa
from alembic import op

revision = "0008_cache_write_usage"
down_revision = "0007_ai_usage_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_usage",sa.Column("cache_write_tokens",sa.Integer(),nullable=False,server_default="0"))


def downgrade() -> None:
    op.drop_column("ai_usage","cache_write_tokens")
