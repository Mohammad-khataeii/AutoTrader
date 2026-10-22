import React, { useEffect, useId, useRef, useState } from "react";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { errorMessage, type Row, type Snapshot } from "./api";
import { date, money, number } from "./model";
import { personalText } from "./presentation";
export function Panel({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <section className={`panel ${className}`}>{children}</section>;
}
export function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: string;
}) {
  return (
    <span className={`badge ${tone}`}>
      <span className="status-dot" />
      {typeof children === "string" ? personalText(children) : children}
    </span>
  );
}
export function Pnl({ value }: { value: unknown }) {
  const n = number(value);
  return (
    <span
      className={
        n == null || Math.abs(n) < 0.005 ? "" : n < 0 ? "loss" : "gain"
      }
    >
      {money(value)}
    </span>
  );
}
export function Empty({
  title = "No activity yet.",
  children,
}: {
  title?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-mark">—</div>
      <h3>{title}</h3>
      <p>
        {children ??
          "The strategy is monitoring the market and waiting for a qualifying signal."}
      </p>
    </div>
  );
}
export function ResourceState({
  resource,
  label,
}: {
  resource: Snapshot;
  label: string;
}) {
  if (resource.error)
    return (
      <div className="notice warning" role="alert">
        <strong>{label} could not be refreshed.</strong> {resource.error}
        {resource.updatedAt && (
          <span>
            {" "}
            Last successful update: {date(resource.updatedAt, true)}.
          </span>
        )}
      </div>
    );
  if (!resource.data)
    return (
      <div className="loading" role="status">
        Loading {label.toLowerCase()}…
      </div>
    );
  return null;
}
export function Technical({
  value,
  label = "Technical details",
}: {
  value: unknown;
  label?: string;
}) {
  return (
    <details className="disclosure">
      <summary>{label}</summary>
      <p className="small muted">Raw records preserve original technical identifiers and financial object names.</p>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
export type Column = { label: string; render: (row: Row) => React.ReactNode };
export function CompactTable({
  rows,
  columns,
  label,
  empty,
}: {
  rows: Row[];
  columns: Column[];
  label: string;
  empty?: React.ReactNode;
}) {
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(rows.length / 15));
  const current = Math.min(page, pages - 1);
  if (!rows.length) return <>{empty ?? <Empty />}</>;
  return (
    <>
      <div className="table-wrap" tabIndex={0} role="region" aria-label={label}>
        <table>
          <caption className="sr-only">{label}</caption>
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.label} scope="col">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(current * 15, current * 15 + 15).map((r, i) => (
              <tr
                key={
                  r.key ??
                  r.order_id ??
                  r.fill_id ??
                  r.position_id ??
                  `${r.strategy_id ?? "row"}-${i}`
                }
              >
                {columns.map((c) => (
                  <td key={c.label}>{c.render(r)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="pagination">
          <span>
            {current * 15 + 1}–{Math.min(rows.length, (current + 1) * 15)} of{" "}
            {rows.length}
          </span>
          <button
            aria-label="Previous page"
            disabled={!current}
            onClick={() => setPage(current - 1)}
          >
            <ChevronLeft size={16} />
          </button>
          <button
            aria-label="Next page"
            disabled={current === pages - 1}
            onClick={() => setPage(current + 1)}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </>
  );
}
const LazyEquityChart = React.lazy(() => import("./Chart").then(m => ({ default: m.EquityChart })));
export function EquityChart(props: { rows: Row[]; title?: string; caption?: string }) {
  return <React.Suspense fallback={<div className="chart-empty" role="status">Loading equity history…</div>}><LazyEquityChart {...props} /></React.Suspense>;
}
export function Confirm({
  title,
  children,
  action,
  danger = false,
  onCancel,
  onConfirm,
}: {
  title: string;
  children: React.ReactNode;
  action: string;
  danger?: boolean;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    ref.current?.showModal();
    return () => ref.current?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby={id}
      onCancel={(e) => {
        if (busy) e.preventDefault();
        else onCancel();
      }}
    >
      <h2 id={id}>{title}</h2>
      <div className="dialog-body">{children}</div>
      {error && (
        <p role="alert" className="notice warning">
          {error}
        </p>
      )}
      <div className="dialog-actions">
        <button autoFocus disabled={busy} onClick={onCancel}>
          Cancel
        </button>
        <button
          className={danger ? "danger-button" : "primary"}
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError("");
            try {
              await onConfirm();
              onCancel();
            } catch (e) {
              setError(errorMessage(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "Working…" : action}
        </button>
      </div>
    </dialog>
  );
}
