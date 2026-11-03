"""Separate synthetic perpetuals state and event history."""
import sqlalchemy as sa
from alembic import op

revision = "0001_paper_perpetuals"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    state = op.create_table(
        "paper_perp_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("payload", sa.Text()),
        sa.CheckConstraint("id = 1", name="paper_perp_singleton"),
    )
    op.bulk_insert(state, [{"id": 1, "generation": 0, "payload": None}])
    op.create_table(
        "paper_perp_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payload", sa.Text(), nullable=False),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM paper_perp_events")):
        raise RuntimeError("Perpetuals history exists; preserve it and use an approved forward recovery.")
    op.drop_table("paper_perp_events")
    op.drop_table("paper_perp_state")
