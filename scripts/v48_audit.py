"""Read-only audit of a local restored Aruba diagnostic snapshot."""
import json
import os
from collections import Counter, defaultdict
from decimal import Decimal as D
from pathlib import Path

import psycopg


def main():
    with psycopg.connect(os.environ['AUTOTRADER_TEST_PG_ADMIN_URL'],dbname='v48_aruba_primary') as connection:
        connection.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        funding=connection.execute("SELECT count(*),sum(cash_delta) FROM financial_journal WHERE event_type='INITIAL_FUNDING'").fetchone()
        assert funding[0]==1 and funding[1]==7000
        rows=connection.execute('SELECT payload_json FROM strategy_signals').fetchall()
        grouped=defaultdict(lambda:{'evaluations':0,'technical':0,'economic':0,'rejections':Counter()})
        rr=[];rewards=[];risks=[];costs=[]
        from statistics import median
        for raw, in rows:
            row=json.loads(raw);e=row['evidence'];g=grouped[row['strategy_id']]
            g['evaluations']+=1;g['technical']+=bool(e.get('technical_eligible'));g['economic']+=bool(e.get('economic_eligible'))
            g['rejections'].update(e.get('reasons',[]))
            m=(e.get('economics') or {}).get('measurements',{})
            if e.get('technical_eligible') and m.get('net_reward_risk') is not None:
                rr.append(D(m['net_reward_risk']));rewards.append(D(m['conditional_target_net_eur'][0]))
                risks.append(D(m['expected_net_stop_loss_eur']));costs.append(D(m['estimated_total_round_trip_cost_eur']))
        counts={table:connection.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ['orders','fills','positions','trading_decisions','financial_journal']}
        markets=connection.execute('SELECT count(DISTINCT symbol),min(created_at),max(created_at) FROM trading_decisions').fetchone()
        body={'status':'PASS','evidence_category':'READ_ONLY_V471_ARUBA_DIAGNOSTIC_SNAPSHOT','funding_count':funding[0],
            'initial_capital':'7000','counts':counts,'distinct_markets':markets[0],'decision_window':[str(x) for x in markets[1:]],
            'strategies':dict(grouped),'technical_payoff_summary':{'samples':len(rr),'median_net_reward_risk':str(median(rr)) if rr else None,
            'best_net_reward_risk':str(max(rr)) if rr else None,'median_first_target_net_gain':str(median(rewards)) if rewards else None,
            'median_stop_loss':str(median(risks)) if risks else None,'median_roundtrip_cost':str(median(costs)) if costs else None},
            'audit_limit':'Later equivalent saved history, not a claim that this is exactly the earlier 14:24:49 archive. All are development observations, never a fresh holdout.'}
    Path('docs/evidence/v4_8/audit-snapshot.json').write_text(json.dumps(body,indent=2)+'\n')
    print(json.dumps(body,indent=2))

if __name__=='__main__':main()
