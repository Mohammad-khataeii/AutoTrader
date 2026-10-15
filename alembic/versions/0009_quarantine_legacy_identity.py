"""Clear unproven derived links after preserving their original migration report."""
from alembic import op

revision='0009_legacy_quarantine'
down_revision='0008_cache_write_usage'
branch_labels=None
depends_on=None


def upgrade()->None:
    conn=op.get_bind()
    # Only derived, explicitly unresolved metadata is corrected. The old guessed
    # ID remains in legacy_attribution_report; economic fields are never changed.
    if conn.dialect.name=='postgresql':
        op.execute('ALTER TABLE fills DISABLE TRIGGER immutable_fills')
    else:
        op.execute('DROP TRIGGER immutable_fills_update')
    op.execute("UPDATE fills SET position_id=NULL WHERE attribution_status='UNRESOLVED'")
    if conn.dialect.name=='postgresql':
        op.execute('ALTER TABLE fills ENABLE TRIGGER immutable_fills')
        op.create_check_constraint('ck_confirmed_fill_identity','fills',"attribution_status <> 'CONFIRMED' OR (account_id IS NOT NULL AND position_id IS NOT NULL AND simulated AND quantity > 0 AND price > 0 AND fee >= 0 AND (side <> 'SELL' OR exit_intent_id IS NOT NULL))")
    else:
        # SQLite batch recreation would copy immutable fill rows and dependent
        # foreign keys. Keep its integration-only schema non-destructive; the
        # production PostgreSQL constraint is exercised by PostgreSQL tests.
        op.execute("CREATE TRIGGER immutable_fills_update BEFORE UPDATE ON fills BEGIN SELECT RAISE(ABORT, 'immutable financial history'); END")


def downgrade()->None:
    raise RuntimeError('Unproven legacy attribution must not be reintroduced automatically.')
