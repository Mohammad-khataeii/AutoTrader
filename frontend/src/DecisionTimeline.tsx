import React, { useState } from "react";
import { useResource, type Row } from "./api";
import { date, rejection, conditionName } from "./model";
import { Panel, ResourceState, Technical } from "./ui";
export function DecisionTimeline({ identity }: { identity: string }) {
  const [cursor, setCursor] = useState("");
  const resource = useResource(
    `/api/shadow/${identity}/pages/decisions?limit=10${cursor ? "&cursor=" + encodeURIComponent(cursor) : ""}`,
    { poll: cursor ? 0 : 30000 },
  );
  return (
    <Panel>
      <div className="section-heading">
        <h2>Recent decisions</h2>
        {cursor && <button onClick={() => setCursor("")}>Latest</button>}
      </div>
      <ResourceState resource={resource} label="Decision timeline" />
      {(resource.data?.items ?? []).map((r: Row) => {
        const e = r.explanation;
        return (
          <article className="decision-item" key={r.decision_id}>
            <div className="section-heading">
              <strong>
                {r.symbol} ·{" "}
                {r.accepted ? "Decision accepted" : "No qualifying entry"}
              </strong>
              <span className="muted small">{date(r.created_at, true)}</span>
            </div>
            <p>{rejection(e?.reason ?? r.rejected_reason)}</p>
            {e && (
              <>
                <p className="muted small">
                  {e.regime ?? "Regime unavailable"} · Risk{" "}
                  {e.risk?.reached ? "evaluated" : "not reached"} · Execution{" "}
                  {e.execution?.reached ? "evaluated" : "not reached"}
                </p>
                <details>
                  <summary>Why this decision?</summary>
                  <p>
                    Independently unmet conditions:{" "}
                    {e.independently_failed?.length
                      ? e.independently_failed.map(conditionName).join(", ")
                      : "None recorded"}
                    .
                  </p>
                  <p>
                    Momentum veto:{" "}
                    {e.momentum_veto === true
                      ? "Present"
                      : e.momentum_veto === false
                        ? "Absent"
                        : "Unobserved"}
                    . A concurrent veto is not evidence that it was the only
                    blocker.
                  </p>
                  <p>
                    Unobserved conditions:{" "}
                    {e.unknown_conditions?.join(", ") || "None"}.
                  </p>
                  <Technical value={e} />
                </details>
              </>
            )}
            {!e && (
              <p className="muted small">
                Original recorded decision. Structured condition evidence was
                not captured for this evaluation.
              </p>
            )}
          </article>
        );
      })}
      {resource.data?.items?.length === 0 && (
        <p className="muted">No recorded evaluations yet.</p>
      )}
      {resource.data?.next_cursor && (
        <button onClick={() => setCursor(resource.data.next_cursor)}>
          Earlier decisions
        </button>
      )}
    </Panel>
  );
}
