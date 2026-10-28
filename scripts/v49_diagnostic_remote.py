"""Standard-library, read-only collector streamed to Aruba; creates no remote files.

Only allowlisted database columns and Docker metadata are selected. No process
logs, environments, auth files, keys, shell history or credential stores are read.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import UTC, datetime, timedelta
from typing import Any

PROJECT='autotrader-aruba-test'
OFFICIAL='autotrader_aruba_staging'
NAME=re.compile(r'autotrader_(?:aruba_staging|paper_[a-f0-9]{32}|shadow_[a-f0-9]{32})\Z')
SECRET=re.compile(r'password|secret|api.?key|access.?token|refresh.?token|authorization|private.?key|database_url|redis_url',re.IGNORECASE)


def sanitize(value: Any) -> Any:
    if isinstance(value,dict):
        return {k:('[REDACTED]' if SECRET.search(k) else sanitize(v)) for k,v in value.items()}
    if isinstance(value,list):return [sanitize(v) for v in value]
    if isinstance(value,str):
        if '-----BEGIN' in value or re.search(r'Bearer\s+\S+|(?:password|secret|token|api.?key)\s*[=:]\s*\S+',value,re.IGNORECASE):return '[REDACTED_SENSITIVE_TEXT]'
        value=re.sub(r'([a-z][a-z0-9+.-]*://)[^\s/@]+(?::[^\s/@]*)?@',r'\1[REDACTED]@',value,flags=re.IGNORECASE)
        try:
            parsed=json.loads(value)
            if isinstance(parsed,(dict,list)):return sanitize(parsed)
        except (ValueError,TypeError):pass
    return value


def run(args: list[str]) -> str:
    result=subprocess.run(args,capture_output=True,check=False)
    if result.returncode:raise RuntimeError('read_only_diagnostic_command_failed:'+args[0]+':'+str(sanitize(result.stderr.decode()))[-800:])
    return result.stdout.decode()


def query(container: str, database: str, sql: str) -> Any:
    if not NAME.fullmatch(database):raise ValueError('unregistered_database_name')
    result=run(['docker','exec',container,'psql','-U','autotrader','-d',database,'-qAt','-v','ON_ERROR_STOP=1','-c',
        "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SET LOCAL statement_timeout='90s'; "+sql+'; COMMIT;'])
    return json.loads(result,parse_float=str)


def collect(hours: int) -> dict[str,Any]:
    if hours not in {12,24,48}:raise ValueError('bounded_12_24_48_hour_window_required')
    observed=datetime.now(UTC);since=(observed-timedelta(hours=hours)).isoformat()
    # The timestamp is generated internally, never a supplied SQL fragment.
    ids=run(['docker','ps','-q','--filter','label=com.docker.compose.project='+PROJECT]).split()
    if not ids:raise ValueError('staging_containers_unavailable')
    template=('{"id":{{json .Id}},"image":{{json .Image}},"status":{{json .State.Status}},'
        '"health":{{with index .State "Health"}}{{json .Status}}{{else}}null{{end}},'
        '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
        '"oneoff":{{json (index .Config.Labels "com.docker.compose.oneoff")}},'
        '"revision":{{json (index .Config.Labels "org.opencontainers.image.revision")}}}')
    metadata=[json.loads(line) for line in run(['docker','inspect','--format',template,*ids]).splitlines()]
    services={r['service']:{k:r[k] for k in ['id','image','status','health','revision']}
              for r in metadata if r['oneoff']!='True'}
    pg=services['postgres']['id']
    registry=query(pg,OFFICIAL,"SELECT json_build_object('primary',(SELECT payload_json::json FROM system_state WHERE key='personal_paper_v47'),'shadows',COALESCE((SELECT json_agg(json_build_object('database_name',database_name,'state',state,'manifest',manifest_json::json,'created_at',created_at)) FROM shadow_experiments),'[]'::json))")
    primary=registry['primary']['database_name'] if registry['primary'] else None
    names=[OFFICIAL,*([primary] if primary else []),*[r['database_name'] for r in registry['shadows']]]
    if len(set(names))!=len(names) or not all(NAME.fullmatch(n) for n in names):raise ValueError('database_registry_integrity_failed')
    sections={
      'signals':('strategy_signals','created_at,symbol,strategy_id,payload_json'),
      'decisions':('trading_decisions','created_at,decision_id,symbol,action,accepted,rejected_reason,payload_json'),
      'orders':('orders','created_at,order_id,decision_id,symbol,side,status,quantity,filled_quantity,average_fill_price,simulated,execution_json'),
      'fills':('fills','created_at,fill_id,order_id,symbol,side,quantity,price,fee,simulated'),
      'positions':('positions','created_at,position_id,symbol,quantity,realized_pnl,opened_at,closed_at,state'),
      'risk':('risk_evaluations','created_at,decision_id,accepted,reserved_quote,payload_json'),
      'incidents':('system_incidents','created_at,severity,status,message'),
      'events':('system_events','created_at,severity,message'),
      'journal':('financial_journal','created_at,event_type,cash_delta,realized_pnl_delta'),
    }
    databases=[]
    for name in names:
        values=[]
        for key,(table,columns) in sections.items():
            values.extend(["'"+key+"'",f"COALESCE((SELECT json_agg(t) FROM (SELECT {columns} FROM {table} WHERE created_at>='{since}' ORDER BY created_at LIMIT 100001) t),'[]'::json)"])
        values.extend(["'states'",f"COALESCE((SELECT json_agg(t) FROM (SELECT key,state,reason,updated_at,payload_json FROM system_state WHERE (key IN ('personal_paper_v47','paper_scan','benchmark_sync','market_metrics','worker','worker_instance','scanner','operation','risk','control') OR key LIKE 'raoe_discovery%' OR key LIKE 'benchmark_cycle:%' OR key LIKE 'closed_bar:%' OR key LIKE 'raoe_event:%' OR key LIKE 'raoe_outcome%' OR key LIKE 'raoe49_outcome:%' OR key LIKE 'shadow_archive:%' OR key LIKE 'market_window:%') AND updated_at>='{since}' ORDER BY updated_at LIMIT 100001) t),'[]'::json)"])
        values.extend(["'financial'","json_build_object('funding',(SELECT json_agg(t) FROM (SELECT account_id,count(*) AS events,sum(cash_delta) AS cash FROM financial_journal WHERE event_type='INITIAL_FUNDING' GROUP BY account_id)t),'accounts',(SELECT json_agg(t) FROM (SELECT account_id,sum(cash_delta) AS cash,sum(reserved_delta) AS reserved_cash,sum(realized_pnl_delta) AS realized_pnl FROM financial_journal GROUP BY account_id)t),'controls',(SELECT json_agg(t) FROM (SELECT account_id,control,initial_cash FROM accounts)t),'all_orders',(SELECT count(*) FROM orders),'all_fills',(SELECT count(*) FROM fills))"])
        values.extend(["'snapshot_at'","transaction_timestamp()"])
        body=query(pg,name,'SELECT json_build_object('+','.join(values)+')')
        databases.append({'database':name,**body,'possibly_truncated':[k for k,v in body.items() if isinstance(v,list) and len(v)>100000]})
    return sanitize({'schema':'v49-readonly-diagnostic/1','project':PROJECT,'observed_at':observed.isoformat(),'hours':hours,
        'since':since,'registry':registry,'containers':services,'databases':databases,'remote_mutations':False,
        'limits':['Per-database repeatable-read snapshots; no cross-database atomic snapshot',
          'MarketCandle lacks first-seen timestamps before V4.9 immutable bar records',
          'Each section capped at 100001 rows; possibly_truncated must be checked',
          'Full environment, authentication material and transient process logs are deliberately excluded']})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--hours',type=int,choices=[12,24,48],default=24)
    args=parser.parse_args()
    print(json.dumps(collect(args.hours),separators=(',',':')))
