import { type Row, useResource } from "./api";
import { date, money, percent } from "./model";
import { Badge, CompactTable, Panel, ResourceState } from "./ui";

const words = (value: unknown) =>
  typeof value === "string" ? value.replaceAll("_", " ").toLowerCase() : "Unavailable";

export function ConsolidationPanel() {
  const resource = useResource("/api/research/consolidation", { poll: 60000 });
  const data = resource.data as Row | undefined;
  const model = data?.evaluation;
  const collection = data?.collection;
  const capacity = data?.capacity;
  const plan = data?.archive_plan;
  return <Panel>
    <div className="section-heading">
      <h2>Personal Plan research and learning</h2>
      <Badge>Paper advisory</Badge>
    </div>
    <ResourceState resource={resource} label="Research collection" />
    {data && <>
      <p>Research status {words(data.status)}. Last collection {date(collection?.observed_at, true)}.</p>
      {data.collection_stale && <p className="muted">The last collection is stale. Review the research worker and source coverage.</p>}
      <p>{data.source_count ?? 0} collected sources · {data.unique_market_candle_contents ?? 0} distinct candle records · {data.source_errors ?? 0} quarantined records.</p>
      <p>{data.review_tasks?.REVIEWED ?? 0} reviewed horizons · {data.review_tasks?.PENDING ?? 0} pending · {data.reviewed_forecasts ?? 0} reviewed forecasts.</p>
      <p>Scorer {words(data.scoring_state)}. Model approval is manual.</p>
      {Object.entries(data.recent_reconciled_fees_eur_by_source ?? {}).map(([source, value]) =>
        <p key={source}>Recent reconciled simulated fees · {source.slice(-12)} · {money(value)}</p>)}
      {data.model_candidate && <p>Candidate {String(data.model_candidate.id).slice(0, 12)} · {words(data.model_candidate.status)} · {model?.holdout_episodes ?? 0} holdout episodes.</p>}
      {model?.holdout && <p>Modeled holdout mean net return {percent(model.holdout.model?.expectancy)} · deterministic comparison {percent(model.holdout.deterministic?.expectancy)} · no-trade baseline 0%. These are conditional historical estimates.</p>}
      {plan && <p>{plan.active_shadows} active or provisioning shadow experiments · capacity {plan.maximum_active_shadows} · {plan.archived_shadows} archived.</p>}
      {capacity && <p>Backup capacity {words(capacity.status)} · estimated shortfall {(capacity.shortfall_bytes / 1024 ** 3).toFixed(2)} GiB.</p>}
      {plan?.records?.length > 0 && <CompactTable label="Shadow inventory" rows={plan.records} columns={[
        { label: "Strategy", render: (r: Row) => r.strategy ?? "Unavailable" },
        { label: "State", render: (r: Row) => r.archived ? "Archived" : words(r.state) },
        { label: "Closed", render: (r: Row) => r.closed },
        { label: "Net realized", render: (r: Row) => money(r.realized_net_eur) },
        { label: "Frozen source refusals", render: (r: Row) => r.frozen_source },
      ]}/>}
      {!!data.recent_reviews?.length && <CompactTable label="Recent decision postmortems" rows={data.recent_reviews} columns={[
        { label: "Decision time", render: (r: Row) => date(r.observed_at, true) },
        { label: "Symbol / horizon", render: (r: Row) => `${r.symbol} · ${r.horizon} min` },
        { label: "Evidence", render: (r: Row) => words(r.classification) },
        { label: "Reason", render: (r: Row) => r.why ?? "Unavailable" },
      ]}/>}
      {data.recent_forecasts?.slice(0, 5).map((r: Row) =>
        <p key={r.symbol + r.created_at + r.prediction.model_id}>
          {r.symbol} · {date(r.created_at, true)} · {words(r.prediction.status)} · modeled mean net {percent(r.prediction.conditional_expected_net_return)} · training downside {percent(r.prediction.downside_return)}
        </p>)}
      <p className="muted">{data.evidence_scope}</p>
    </>}
  </Panel>;
}
