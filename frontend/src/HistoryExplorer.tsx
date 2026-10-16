import React, { useState } from "react";
import { useResource } from "./api";
import { date, humanize, rejection } from "./model";
import { Panel, CompactTable, ResourceState, Technical } from "./ui";
export function HistoryExplorer() {
  const [kind, setKind] = useState("decisions"),
    [cursors, setCursors] = useState<string[]>([]);
  const cursor = cursors[cursors.length - 1];
  const resource = useResource(
    `/api/history/page/${kind}?limit=30${cursor ? "&cursor=" + encodeURIComponent(cursor) : ""}`,
    { ttl: 60000 },
  );
  return (
    <Panel>
      <div className="section-heading">
        <h2>Official account history</h2>
        <label className="inline-label">
          Records
          <select
            aria-label="History record type"
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setCursors([]);
            }}
          >
            {[
              "decisions",
              "signals",
              "journal",
              "equity",
              "incidents",
              "exit_intents",
              "transitions",
            ].map((k) => (
              <option key={k} value={k}>
                {humanize(k)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ResourceState resource={resource} label="History page" />
      <CompactTable
        label="Official decision history"
        rows={resource.data?.items ?? []}
        columns={[
          { label: "Time", render: (r) => date(r.created_at, true) },
          { label: "Coin", render: (r) => r.symbol ?? "—" },
          {
            label: "Activity",
            render: (r) =>
              humanize(
                r.action ?? r.event_type ?? r.to_status ?? r.status ?? kind,
              ),
          },
          {
            label: "Recorded reason",
            render: (r) =>
              rejection(r.rejected_reason ?? r.reason ?? r.message),
          },
          { label: "Evidence", render: (r) => <Technical value={r} /> },
        ]}
      />
      <div className="pagination">
        <button
          disabled={!cursors.length}
          onClick={() => setCursors(cursors.slice(0, -1))}
        >
          Previous history
        </button>
        <span className="muted small">
          30 records per API page · full history retained
        </span>
        <button
          disabled={!resource.data?.next_cursor}
          onClick={() => setCursors([...cursors, resource.data.next_cursor])}
        >
          Earlier history
        </button>
      </div>
    </Panel>
  );
}
