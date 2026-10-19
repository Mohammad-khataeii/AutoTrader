import React, { useState } from "react";
import { useApi, useResource, errorMessage } from "./api";
import { date, stateName } from "./model";
import { Badge, Confirm, Panel, ResourceState, Technical } from "./ui";
export function PilotPanel({ auth: _auth }: { auth: string }) {
  const api = useApi();
  const data = useResource("/api/pilots", { poll: 15000 });
  const [start, setStart] = useState(false);
  const [requestId, setRequestId] = useState("");
  const [report, setReport] = useState<any>(null);
  const [error, setError] = useState("");
  return (
    <div className="page-stack">
      <Panel>
        <div className="section-heading">
          <h2>30-day prospective paper pilot</h2>
          <button
            disabled={
              !data.data || data.data.some((p: any) => p.state === "ACTIVE")
            }
            onClick={() => {
              setRequestId(crypto.randomUUID());
              setStart(true);
            }}
          >
            Start 30-day paper pilot
          </button>
        </div>
        <p className="muted">
          Starting freezes a configuration for new observations. A pilot is only
          complete after its actual observation window has elapsed.
        </p>
        <ResourceState resource={data} label="Paper pilots" />
        {error && (
          <p role="alert" className="notice warning">
            {error}
          </p>
        )}
      </Panel>
      {(data.data ?? []).map((p: any) => (
        <Panel key={p.pilot_id}>
          <Badge>
            {stateName(p.mode)} · {stateName(p.state)}
          </Badge>
          <p>
            {date(p.started_at, true)} to {date(p.planned_end_at, true)}
          </p>
          <p className="small muted">{p.performance_label}</p>
          <div className="toolbar">
            <button
              onClick={async () => {
                try {
                  setReport(
                    await api.request(`/api/pilots/${p.pilot_id}/report`),
                  );
                  setError("");
                } catch (e) {
                  setError(errorMessage(e));
                }
              }}
            >
              View JSON report
            </button>
            <button
              onClick={async () => {
                try {
                  await api.download(
                    `/api/pilots/${p.pilot_id}/report?format=csv`,
                    `${p.pilot_id}.csv`,
                  );
                  setError("");
                } catch (e) {
                  setError(errorMessage(e));
                }
              }}
            >
              Export CSV report
            </button>
          </div>
          <Technical value={p} label="Frozen pilot configuration" />
        </Panel>
      ))}
      {report && (
        <Technical value={report} label="View requested pilot report" />
      )}
      {start && (
        <Confirm
          title="Start a new 30-day observation?"
          action="Start pilot"
          onCancel={() => setStart(false)}
          onConfirm={async () => {
            await api.request("/api/pilots", "POST", { request_id: requestId });
            await api.refresh("/api/pilots");
          }}
        >
          <p>
            This freezes the current configuration and starts a durable
            observation period. It does not approve a strategy, reset financial
            history or enable real-money execution.
          </p>
        </Confirm>
      )}
    </div>
  );
}
