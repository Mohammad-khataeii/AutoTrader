import React, { useState } from "react";
import { ChevronLeft } from "lucide-react";
import { useResource, type Row } from "./api";
import {
  currentMark,
  date,
  humanize,
  isOpen,
  money,
  number,
  parse,
  rejection,
  shortId,
  strategyName,
} from "./model";
import {
  Badge,
  CompactTable,
  Empty,
  Panel,
  Pnl,
  ResourceState,
  Technical,
} from "./ui";
export function Trades() {
  const official = useResource("/api/overview", { poll: 20000 });
  const shadow = useResource("/api/shadow", { poll: 20000 });
  const [tab, setTab] = useState("Open positions");
  const [account, setAccount] = useState("all");
  const [selected, setSelected] = useState<Row | null>(null);
  const execution = useResource("/api/execution", {
    enabled: selected?.account === "official" && selected?.kind === "position",
    poll:
      selected?.account === "official" && isOpen(selected?.record ?? {})
        ? 15000
        : 0,
  });
  const history = useResource("/api/history", {
    enabled: selected?.account === "official",
    ttl: 60000,
  });
  const accounts = [
    { id: "official", name: "Official", data: official.data },
    ...(shadow.data?.experiments ?? []).map((e: Row) => ({
      id: e.experiment_id,
      name: `${strategyName(e.manifest?.strategy_id)} · ${shortId(e.experiment_id)}`,
      data: e,
    })),
  ];
  const rows: Row[] = accounts.flatMap((a) =>
    (a.data?.positions ?? []).map((r: Row) => ({
      key: `${a.id}:${r.position_id}`,
      account: a.id,
      accountName: a.name,
      kind: "position",
      record: r,
      symbol: r.symbol,
    })),
  );
  const visible = rows.filter(
    (r) =>
      (account === "all" || r.account === account) &&
      (tab === "Open positions" ? isOpen(r.record) : !isOpen(r.record)),
  );
  const allOrders: Row[] = accounts
    .flatMap((a) =>
      (a.data?.orders ?? []).map((r: Row) => ({
        key: `${a.id}:${r.order_id}`,
        account: a.id,
        accountName: a.name,
        kind: "order",
        record: r,
        symbol: r.symbol,
      })),
    )
    .filter((r) => account === "all" || r.account === account);
  const chosenAccount = accounts.find((a) => a.id === selected?.account);
  const data = chosenAccount?.data;
  const currentRecord = (
    data?.[selected?.kind === "order" ? "orders" : "positions"] ?? []
  ).find((r: Row) =>
    selected?.kind === "order"
      ? r.order_id === selected.record.order_id
      : r.position_id === selected?.record.position_id,
  );
  const chosen = currentRecord ?? selected?.record;
  const openPosition = selected?.kind === "position" && isOpen(chosen ?? {});
  const fills = (data?.fills ?? []).filter((f: Row) =>
    selected?.kind === "order"
      ? f.order_id === chosen.order_id
      : f.position_id === chosen.position_id,
  );
  const orders = (data?.orders ?? []).filter((o: Row) =>
    selected?.kind === "order"
      ? o.order_id === chosen?.order_id
      : chosen?.position_id && o.position_id === chosen.position_id,
  );
  const historyData =
    selected?.account === "official" ? history.data : data?.history;
  const linkedIds = new Set(
    orders.map((o: Row) => o.decision_id).filter(Boolean),
  );
  const decisions = (historyData?.decisions ?? []).filter((d: Row) =>
    linkedIds.has(d.decision_id),
  );
  const targets = (data?.targets ?? []).filter(
    (t: Row) => t.position_id === chosen?.position_id,
  );
  const intents = (historyData?.exit_intents ?? []).filter(
    (i: Row) => i.position_id === chosen?.position_id,
  );
  const mark =
    selected?.account === "official" && currentRecord
      ? currentMark(chosen, execution.data, execution.observedAt)
      : undefined;
  if (selected)
    return (
      <div className="page-stack">
        <button className="text-button" onClick={() => setSelected(null)}>
          <ChevronLeft size={16} /> Back to trades
        </button>
        <div className="section-heading">
          <div>
            <h2 className="page-title">{selected.symbol}</h2>
            <p className="muted">
              {selected.accountName} · Simulated{" "}
              {selected.kind === "order" ? "order" : "position"}
            </p>
          </div>
          <Badge>
            {selected.kind === "order"
              ? humanize(chosen.status)
              : isOpen(chosen)
                ? "Open"
                : "Closed"}
          </Badge>
        </div>
        {!currentRecord && (
          <p role="alert" className="notice warning">
            This record is outside the latest returned history window. Showing
            the previously loaded record; current valuation is unavailable.
          </p>
        )}
        <Panel>
          <dl className="facts">
            <div>
              <dt>
                {selected.kind === "order" ? "Limit price" : "Entry price"}
              </dt>
              <dd>{money(chosen.average_entry_price ?? chosen.limit_price)}</dd>
            </div>
            <div>
              <dt>Quantity</dt>
              <dd>{chosen.quantity ?? "Unavailable"}</dd>
            </div>
            <div>
              <dt>Current price</dt>
              <dd>{openPosition ? money(mark?.price) : "Not applicable"}</dd>
            </div>
            <div>
              <dt>{openPosition ? "Marked P&L" : "Realized P&L"}</dt>
              <dd>
                {selected.kind === "order" ? (
                  "Not applicable"
                ) : (
                  <Pnl value={openPosition ? mark?.pnl : chosen.realized_pnl} />
                )}
              </dd>
            </div>
            <div>
              <dt>Protective stop</dt>
              <dd>{money(chosen.protective_stop)}</dd>
            </div>
            <div>
              <dt>Opened</dt>
              <dd>{date(chosen.opened_at ?? chosen.created_at, true)}</dd>
            </div>
            <div>
              <dt>Closed</dt>
              <dd>
                {chosen.closed_at ? date(chosen.closed_at, true) : "Not closed"}
              </dd>
            </div>
            <div>
              <dt>Recorded fees in returned fills</dt>
              <dd>
                {fills.length
                  ? money(
                      fills.reduce(
                        (sum: number, f: Row) => sum + (number(f.fee) ?? 0),
                        0,
                      ),
                    )
                  : "Unavailable"}
              </dd>
            </div>
          </dl>
          {openPosition && !mark && (
            <p className="notice">
              Current price and open P&L are unavailable without a fresh, valid
              mark for this account. No price is inferred from a historical
              signal.
            </p>
          )}
          {mark && (
            <p className="small muted">
              P&L uses the fresh midpoint mark. Exit fees, spread and executable
              depth can change the final result.
            </p>
          )}
          <ResourceState resource={execution} label="Execution quote" />
        </Panel>
        <Panel>
          <h2>Entry and exit explanation</h2>
          {decisions.length ? (
            decisions.map((d: Row, i: number) => {
              const payload = parse(d.payload_json);
              return (
                <p key={i}>
                  {payload.explanation ??
                    rejection(d.rejected_reason ?? payload.rejected_reason)}
                </p>
              );
            })
          ) : (
            <p className="muted">
              No linked decision explanation is available in the returned
              history window.
            </p>
          )}
          {intents.map((i: Row, n: number) => (
            <p key={n}>
              Recorded exit: {rejection(i.reason)} · {humanize(i.status)}
            </p>
          ))}
          {!intents.length && chosen.closed_at && (
            <p className="muted">
              The closed quantity is recorded. An exit reason is not present in
              the returned intent history.
            </p>
          )}
        </Panel>
        <details className="panel disclosure">
          <summary>Protective targets and partial fills</summary>
          <CompactTable
            label="Protective targets"
            rows={targets.length ? targets : (chosen.take_profit_targets ?? [])}
            columns={[
              { label: "Target", render: (r) => r.target_number ?? "—" },
              {
                label: "Price",
                render: (r) => money(r.target_price ?? r.price),
              },
              {
                label: "Planned",
                render: (r) =>
                  r.original_planned_quantity ?? r.quantity ?? "Unavailable",
              },
              {
                label: "Filled",
                render: (r) => r.filled_quantity ?? "Unavailable",
              },
              { label: "Status", render: (r) => humanize(r.status) },
            ]}
          />
          <h3>Confirmed fills</h3>
          <CompactTable
            label="Trade fills"
            rows={fills}
            columns={[
              { label: "Side", render: (r) => humanize(r.side) },
              { label: "Quantity", render: (r) => r.quantity },
              { label: "Price", render: (r) => money(r.price) },
              { label: "Fee", render: (r) => money(r.fee) },
            ]}
          />
        </details>
        <Technical
          value={{
            position: chosen,
            orders,
            fills,
            targets,
            decisions,
            exit_intents: intents,
            execution: execution.data?.positions?.find(
              (r: Row) => r.position_id === chosen.position_id,
            ),
          }}
        />
        <p className="muted small">
          Recent API records may be limited. Complete shadow histories remain
          available under Experiments → Export.
        </p>
      </div>
    );
  return (
    <div className="page-stack">
      <div className="section-heading">
        <div>
          <h2 className="page-title">Trading activity</h2>
          <p className="muted">
            Every position belongs to one virtual account.
          </p>
        </div>
        <Badge>All trades simulated</Badge>
      </div>
      <div className="section-heading">
        <div className="segmented" role="tablist" aria-label="Trade view">
          {["Open positions", "Trade history"].map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
        </div>
        <label className="inline-label">
          Account
          <select
            aria-label="Trade account"
            value={account}
            onChange={(e) => setAccount(e.target.value)}
          >
            <option value="all">All accounts</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ResourceState resource={official} label="Official trades" />
      <ResourceState resource={shadow} label="Shadow trades" />
      <Panel>
        <CompactTable
          label={tab}
          rows={visible}
          columns={[
            {
              label: "Coin",
              render: (r) => (
                <button
                  className="table-link"
                  aria-label={`View ${r.symbol} ${r.accountName}`}
                  onClick={() => setSelected(r)}
                >
                  {r.symbol}
                </button>
              ),
            },
            { label: "Account", render: (r) => r.accountName },
            { label: "Side", render: () => "Buy" },
            {
              label: "Entry",
              render: (r) => money(r.record.average_entry_price),
            },
            {
              label: "Current price",
              render: (r) =>
                isOpen(r.record)
                  ? money(
                      r.account === "official"
                        ? currentMark(
                            r.record,
                            execution.data,
                            execution.observedAt,
                          )?.price
                        : undefined,
                    )
                  : "—",
            },
            {
              label: "P&L",
              render: (r) => (
                <Pnl
                  value={
                    isOpen(r.record)
                      ? r.account === "official"
                        ? currentMark(
                            r.record,
                            execution.data,
                            execution.observedAt,
                          )?.pnl
                        : undefined
                      : r.record.realized_pnl
                  }
                />
              ),
            },
            {
              label: "Status",
              render: (r) => (isOpen(r.record) ? "Open" : "Closed"),
            },
          ]}
        />
      </Panel>
      {tab === "Trade history" && (
        <details className="panel disclosure">
          <summary>
            Orders, rejections and execution details ({allOrders.length})
          </summary>
          <CompactTable
            label="Recorded orders"
            rows={allOrders}
            columns={[
              {
                label: "Coin",
                render: (r) => (
                  <button className="table-link" onClick={() => setSelected(r)}>
                    {r.symbol}
                  </button>
                ),
              },
              { label: "Account", render: (r) => r.accountName },
              { label: "Side", render: (r) => humanize(r.record.side) },
              { label: "Status", render: (r) => humanize(r.record.status) },
              { label: "Filled", render: (r) => r.record.filled_quantity },
            ]}
          />
        </details>
      )}
    </div>
  );
}
