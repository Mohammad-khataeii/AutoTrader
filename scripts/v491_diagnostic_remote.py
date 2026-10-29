"""Read-only audit rows streamed through gzip, without whole-history SQL JSON aggregates."""
from __future__ import annotations
import argparse
import sys
import json
import subprocess
import gzip
import re
from datetime import datetime, timezone, timedelta
from typing import Any
PROJECT='autotrader-aruba-test'
OFFICIAL='autotrader_aruba_staging'
NAME=re.compile(r'autotrader_(aruba_staging|paper_[a-f0-9]{32}|shadow_[a-f0-9]{32})\Z')
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


def stream_query(pg, database, sql):
 assert NAME.fullmatch(database)
 cmd=['docker','exec',pg,'psql','-qAt','-v','ON_ERROR_STOP=1','-U','autotrader','-d',database,'-c',"BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;SET LOCAL work_mem='2MB';SET LOCAL statement_timeout='60s';"+sql+';COMMIT;']
 p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 try:
  for line in p.stdout:
   if line.strip():yield json.loads(line,parse_float=str)
  err=p.stderr.read();rc=p.wait()
  if rc:raise RuntimeError('bounded_stream_failed:'+database+':'+str(rc)+':'+str(sanitize(err.decode()))[:300])
 finally:
  if p.poll() is None:
   p.terminate();p.wait(timeout=10)
  p.stdout.close();p.stderr.close()

def collect(hours=12,output=None):
    if hours not in {12,24,48}:raise ValueError('bounded_window_required')
    output=output or sys.stdout.buffer
    now=datetime.now(timezone.utc);since=(now-timedelta(hours=hours)).isoformat();until=now.isoformat()
    pg=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+PROJECT,'--filter','label=com.docker.compose.service=postgres']).decode().strip();assert re.fullmatch('[a-f0-9]+',pg)
    registry_rows=list(stream_query(pg, OFFICIAL,"SELECT json_build_object('primary',(SELECT payload_json::json FROM system_state WHERE key='personal_paper_v47'),'shadows',COALESCE((SELECT json_agg(json_build_object('database_name',database_name,'state',state,'manifest',manifest_json::json,'created_at',created_at)) FROM shadow_experiments),'[]'::json))"))
    if len(registry_rows)!=1:raise ValueError('single_registry_required')
    registry=registry_rows[0]
    names=[OFFICIAL,registry['primary']['database_name'],*[r['database_name'] for r in registry['shadows']]];assert len(set(names))==len(names) and len(names)>=2
    out=gzip.GzipFile(fileobj=output,mode='wb',compresslevel=3,mtime=0)
    def emit(r):out.write((json.dumps(sanitize(r),separators=(',',':'))+'\n').encode());out.flush()
    emit({'type':'header','schema':'bounded-12h-audit/1','observed_at':until,'since':since,'until':until,'registry':registry,'project':PROJECT,'hours':hours,'read_only':True,'remote_files_created':False,'cutoff_limit':'Per-database repeatable-read snapshots; financial current state can postdate the fixed event cutoff.'})
    sections={'orders':('orders','*',None),'fills':('fills','*',None),'positions':('positions','*',None),'plans':('exit_plans','*',None),'intents':('exit_intents','*',None),'targets':('exit_targets','*',None),'journal':('financial_journal','*',None),'signals':('strategy_signals','created_at,signal_id,symbol,strategy_id,payload_json',f"created_at>='{since}' AND created_at<='{until}'"),'decisions':('trading_decisions','created_at,decision_id,symbol,action,accepted,rejected_reason,payload_json',f"created_at>='{since}' AND created_at<='{until}'"),'incidents':('system_incidents','created_at,severity,status,message',f"created_at>='{since}'"),'events':('system_events','created_at,severity,message',f"created_at>='{since}'")}
    counts={}
    for name in names:
     statements=["SELECT json_build_object('section','snapshot','row',json_build_object('at',transaction_timestamp(),'database',current_database()))"]
     for section,(table,columns,where) in sections.items():
      if name==OFFICIAL and section in {'signals','decisions'}:continue
      statements.append("SELECT json_build_object('section',"+repr(section)+",'row',row_to_json(t)) FROM (SELECT "+columns+' FROM '+table+(' WHERE '+where if where else '')+' ORDER BY created_at) t')
     # Full causal state records are streamed, never json_agg'ed together.
     where=f"updated_at>='{since}' AND updated_at<='{until}' AND (key IN ('worker','position_monitor','paper_scan','benchmark_sync','market_metrics','personal_paper_v47','paper_research_review') OR state='EXIT_ASSESSMENT' OR key LIKE 'raoe_event:%' OR key LIKE 'raoe49_outcome:%' OR key LIKE 'benchmark_cycle:%' OR key LIKE 'raoe_discovery%'"+ (" OR key LIKE 'closed_bar:%'" if name==registry['primary']['database_name'] else '')+')'
     statements.append("SELECT json_build_object('section','states','row',row_to_json(t)) FROM (SELECT key,state,reason,created_at,updated_at,CASE WHEN octet_length(payload_json)<=262144 THEN payload_json ELSE json_build_object('payload_omitted',true,'bytes',octet_length(payload_json),'reason','single_row_byte_limit')::text END AS payload_json FROM system_state WHERE "+where+' ORDER BY updated_at,key) t')
     statements.append("SELECT json_build_object('section','financial','row',json_build_object('funding',(SELECT json_agg(t) FROM (SELECT account_id,count(*) AS events,sum(cash_delta)::text AS cash FROM financial_journal WHERE event_type='INITIAL_FUNDING' GROUP BY account_id)t),'accounts',(SELECT json_agg(t) FROM (SELECT account_id,sum(cash_delta)::text AS cash,sum(reserved_delta)::text AS reserved_cash,sum(realized_pnl_delta)::text AS realized_pnl FROM financial_journal GROUP BY account_id)t),'controls',(SELECT json_agg(t) FROM (SELECT account_id,control,initial_cash::text FROM accounts)t)))")
     count={}
     for row in stream_query(pg, name,';'.join(statements)):
      count[row['section']]=count.get(row['section'],0)+1;emit({'database':name,**row})
     counts[name]=count;emit({'type':'database_complete','database':name,'counts':count})
    emit({'type':'complete','status':'PASS','counts':counts,'read_only':True,'single_state_payload_limit_bytes':262144});out.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--hours',type=int,choices=[12,24,48],default=12)
    collect(parser.parse_args().hours)
