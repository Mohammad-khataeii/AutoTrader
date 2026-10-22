import React from "react";
import { Compass } from "lucide-react";
import { type Row, useResource } from "./api";
import { date, humanize, strategyName } from "./model";
import { qualificationLabel, personalText } from "./presentation";
import { Badge, Panel, ResourceState } from "./ui";

export const opportunityState = (row: Row) => row.qualification_state ?? (row.economic_eligible ? "RESEARCH_CANDIDATE" : row.technical_eligible ? "COST_CONSTRAINED" : "WATCH");
const healthLabel = (value: unknown) => ({CURRENT:"Current",WAITING_NEXT_CANDLE:"Waiting for next candle",STALE_QUOTES:"Stale quotes",RECENT_OBSERVATION:"Recent quote observation",HEALTHY:"Healthy",DELAYED:"Delayed",FAILED:"Failed",RECOVERING:"Recovering",PARTIAL:"Partial",NOT_RECORDED:"Not recorded"} as Record<string,string>)[String(value)] ?? humanize(value ?? "Unknown");
export function OpportunityHealth({data}: {data?: Row}) {
  return <div className="insight-metrics opportunity-health" aria-label="Observation health">
    <div><span>Research schedule</span><strong>{healthLabel(data?.research_freshness?.state)}</strong><span className="small muted">Next evaluation due {date(data?.research_freshness?.next_evaluation_due_at, true)}</span></div>
    <div><span>Executable price evidence</span><strong>{healthLabel(data?.market_freshness?.state)}</strong><span className="small muted">Snapshot prices never authorize an entry. A fresh book is required.</span></div>
    <div><span>Worker / scanner</span><strong>{healthLabel(data?.worker_health?.state)} / {healthLabel(data?.scanner_health?.state)}</strong><span className="small muted">{personalText(data?.worker_health?.reason ?? "Health observation unavailable")}</span></div>
  </div>;
}
export function OpportunityPreview() {
  const result = useResource("/api/opportunities?limit=1", { ttl: 60000 });
  const row = result.data?.rows?.[0];
  return <Panel className="opportunity-preview"><div className="section-heading"><h2>Latest opportunity insight</h2><Compass size={18} /></div>
    <ResourceState resource={result} label="Opportunity observations" />
    {row ? <><p><strong>{row.symbol}</strong> · {strategyName(row.strategy_id)}</p><p>{personalText(row.explanation)}</p><Badge>{qualificationLabel(opportunityState(row))}</Badge><p className="small muted">Observed {date(row.as_of, true)}. Research: {humanize(result.data?.research_freshness?.state ?? "Unknown")}. A feasible setup is not evidence of predictive value.</p></> : <p className="muted">No successor observation has been recorded yet. Missing evidence is shown as unknown.</p>}
  </Panel>;
}
