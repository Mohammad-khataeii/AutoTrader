"""Extend the existing paid usage ledger without rewriting financial history."""
import sqlalchemy as sa
from alembic import op

revision = '0010_v41_ai_quotas'
down_revision = '0009_legacy_quarantine'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column('event_fingerprint',sa.String(128)),
        sa.Column('request_category',sa.String(64),nullable=False,server_default='qualified_candidate'),
        sa.Column('quota_timestamp',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column('estimated_input_tokens',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('reserved_output_tokens',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('provider_response_id',sa.String(256)),
        sa.Column('actual_reported_cost',sa.Numeric(18,8)),
        sa.Column('cache_status',sa.String(32),nullable=False,server_default='MISS'),
    ):
        op.add_column('ai_usage',column)
    op.execute('UPDATE ai_usage SET quota_timestamp=created_at')
    op.execute("UPDATE ai_usage SET status='OUTCOME_UNKNOWN' WHERE status='UNKNOWN'")
    op.create_index('ix_ai_usage_quota_timestamp','ai_usage',['quota_timestamp'])
    op.create_index('ix_ai_usage_event_fingerprint','ai_usage',['event_fingerprint'])


def downgrade() -> None:
    raise RuntimeError('Quota and uncertain billing history must not be discarded automatically.')
