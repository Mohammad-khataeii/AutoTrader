import React, { useEffect, useState } from "react";
import { useResource, type Row } from "./api";
import { date, humanize, money } from "./model";
import { CompactTable, Panel, ResourceState, Technical } from "./ui";
export function TradeFailureExplorer({ auth: _auth }: { auth: string }) {
  const [filters, setFilters] = useState<Row>({});
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Row | null>(null);
  useEffect(() => {
    const timer = setTimeout(() => {
      const params = new URLSearchParams(
        Object.entries(filters).filter(([, v]) => v),
      );
      params.set("limit", "100");
      setQuery(params.toString());
      setSelected(null);
    }, 300);
    return () => clearTimeout(timer);
  }, [filters]);
  const data = useResource(`/api/research/trade-failures?${query}`, {
    enabled: Boolean(query),
    ttl: 300000,
  });
  return (
    <div className="page-stack">
      <Panel>
        <h2>Outcome diagnostics</h2>
        <p className="muted">
          Previously examined historical OHLCV proxies. Diagnostic labels are
          observations; counterfactuals are hypotheses.
        </p>
        <div className="form-grid">
          {[
            "strategy",
            "asset",
            "regime",
            "classification",
            "exit_type",
            "timeframe",
            "start_date",
            "end_date",
          ].map((f) => (
            <label key={f}>
              {humanize(f)}
              <input
                aria-label={`Failure ${f}`}
                type={f.endsWith("date") ? "date" : "text"}
                value={filters[f] ?? ""}
                onChange={(e) =>
                  setFilters({ ...filters, [f]: e.target.value })
                }
              />
            </label>
          ))}
          <label>
            Outcome
            <select
              aria-label="Failure outcome"
              value={filters.outcome ?? "ALL"}
              onChange={(e) =>
                setFilters({ ...filters, outcome: e.target.value })
              }
            >
              <option>ALL</option>
              <option>LOSS</option>
              <option>PROFIT</option>
            </select>
          </label>
        </div>
        <p className="small muted">
          {data.data?.matched ?? 0} matching / {data.data?.total ?? 0}{" "}
          positions. Showing up to 100.
        </p>
        <ResourceState resource={data} label="Decision diagnostics" />
      </Panel>
      <Panel>
        <CompactTable
          label="Historical position outcomes"
          rows={data.data?.positions ?? []}
          columns={[
            {
              label: "Coin",
              render: (r) => (
                <button className="table-link" onClick={() => setSelected(r)}>
                  {r.asset}
                </button>
              ),
            },
            { label: "Strategy", render: (r) => r.strategy },
            { label: "Entry", render: (r) => date(r.entry_timestamp, true) },
            { label: "Net P&L", render: (r) => money(r.net_pnl) },
            { label: "Regime", render: (r) => humanize(r.regime) },
          ]}
        />
        <label>
          Inspect recorded position
          <select
            aria-label="Inspect failure position"
            value={
              selected
                ? `${selected.source_artifact}:${selected.position_id}`
                : ""
            }
            onChange={(e) =>
              setSelected(
                data.data?.positions?.find(
                  (r: Row) =>
                    `${r.source_artifact}:${r.position_id}` === e.target.value,
                ) ?? null,
              )
            }
          >
            <option value="">Choose position</option>
            {(data.data?.positions ?? []).map((r: Row) => (
              <option
                key={`${r.source_artifact}:${r.position_id}`}
                value={`${r.source_artifact}:${r.position_id}`}
              >
                {r.timeframe} · {r.strategy} · {r.position_id}
              </option>
            ))}
          </select>
        </label>
        {selected && (
          <Technical
            value={selected}
            label="View causal features, signal evidence and counterfactuals"
          />
        )}
      </Panel>
      <p className="muted small">{data.data?.limitations?.join(". ")}</p>
    </div>
  );
}
export function MarketDataHealth({ auth: _auth }: { auth: string }) {
  const resource = useResource("/api/market-data/health", { poll: 20000 });
  const d = resource.data;
  return (
    <Panel>
      <h2>Public market-data health</h2>
      <ResourceState resource={resource} label="Market-data health" />
      <dl className="facts">
        {[
          ["Requests", d?.requests],
          ["Recorded HTTP 429 responses", d?.request_429],
          ["Cache hits", d?.candle_cache_hit],
          ["Completed-candle refreshes", d?.candle_refresh],
          ["Candles downloaded", d?.candles_downloaded],
          ["Last successful refresh", date(d?.last_successful_refresh, true)],
        ].map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value ?? "Unavailable"}</dd>
          </div>
        ))}
      </dl>
      <p className="small muted">
        Rate-limit counts are cumulative observations, not proof of a current
        outage.
      </p>
      <Technical
        value={d}
        label="Cache freshness, latency and acquisition policy"
      />
    </Panel>
  );
}
