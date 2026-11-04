"""Separate virtual allocations, intents, positions, signals and journal."""
import sqlalchemy as sa
from alembic import op

revision = '0001_multi_paper'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    state = op.create_table('paper_multi_state', sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('generation',sa.Integer(),nullable=False),sa.Column('payload',sa.Text()),sa.CheckConstraint('id = 1'))
    op.bulk_insert(state,[{'id':1,'generation':0,'payload':None}])
    op.create_table('paper_multi_events',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('event_key',sa.String(160),nullable=False,unique=True),
        sa.Column('kind',sa.String(40),nullable=False),sa.Column('cohort',sa.String(3)),
        sa.Column('cash_delta',sa.Numeric(38,24),nullable=False),sa.Column('payload',sa.Text(),nullable=False))
    op.create_index('ix_paper_multi_events_kind','paper_multi_events',['kind'])
    op.create_index('ix_paper_multi_events_cohort','paper_multi_events',['cohort'])
    op.create_table('paper_multi_signals',sa.Column('id',sa.String(64),primary_key=True),
        sa.Column('cutoff',sa.BigInteger(),nullable=False),sa.Column('due_at',sa.BigInteger(),nullable=False),
        sa.Column('payload',sa.Text(),nullable=False))
    op.create_index('ix_paper_multi_signals_cutoff','paper_multi_signals',['cutoff'])
    op.create_index('ix_paper_multi_signals_due_at','paper_multi_signals',['due_at'])
    op.create_table('paper_multi_scan',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('payload',sa.Text(),nullable=False))
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("CREATE FUNCTION protect_multi_paper_history() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Multi paper history is append-only'; END $$")
        for table in ('paper_multi_events','paper_multi_signals'):
            op.execute(f'CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION protect_multi_paper_history()')


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM paper_multi_events')):
        raise RuntimeError('Paper history exists; preserve it and use forward recovery')
    if op.get_bind().dialect.name == 'postgresql':
        for table in ('paper_multi_events','paper_multi_signals'):
            op.execute(f'DROP TRIGGER {table}_immutable ON {table}')
        op.execute('DROP FUNCTION protect_multi_paper_history()')
    for table in ('paper_multi_scan','paper_multi_signals','paper_multi_events','paper_multi_state'):
        op.drop_table(table)
