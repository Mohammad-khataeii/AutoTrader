import sqlalchemy as sa
from alembic import op

revision = "0007_ai_usage_details"
down_revision = "0006_v34_accounting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_usage", sa.Column("provider", sa.String(32), nullable=False, server_default="openai"))
    op.add_column("ai_usage", sa.Column("candidate_symbol", sa.String(32), nullable=False, server_default="unknown"))
    op.add_column("ai_usage", sa.Column("cached_input_tokens", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("ai_usage", sa.Column("pricing_json", sa.Text(), nullable=False, server_default="{}"))
    # Historical AI estimates are not invoices. Preserve them and freeze affected
    # months with a disclosed hold rather than pretending their cost is zero.
    import json
    conn=op.get_bind()
    rows=conn.execute(sa.text("SELECT created_at,estimated_cost_usd FROM ai_assessments WHERE provider='openai'")).all()
    months={str(row[0])[:7] for row in rows}
    for month in months:
        exists=conn.scalar(sa.text("SELECT COUNT(*) FROM ai_budgets WHERE month=:month"),{'month':month})
        if exists:
            conn.execute(sa.text("UPDATE ai_budgets SET reserved=reserved+10 WHERE month=:month"),{'month':month})
        else:
            conn.execute(sa.text("INSERT INTO ai_budgets(month,spent,reserved) VALUES (:month,0,10)"),{'month':month})
        conn.execute(sa.text("INSERT INTO ai_usage(request_id,month,model,status,reserved_cost,input_tokens,output_tokens,provider,candidate_symbol,cached_input_tokens,pricing_json,error) VALUES (:id,:month,'legacy-unverified','UNKNOWN',10,0,0,'openai','unresolved',0,:prices,:error)"),
            {'id':'legacy_'+month,'month':month,'prices':json.dumps({'origin':'unverified legacy AI estimates'}),'error':'Legacy paid usage requires explicit billing reconciliation; original assessments preserved.'})


def downgrade() -> None:
    for field in ("pricing_json", "cached_input_tokens", "candidate_symbol", "provider"):
        op.drop_column("ai_usage",field)
