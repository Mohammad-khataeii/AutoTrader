import React, { useEffect, useState } from "react";

type Row = Record<string, any>;
export function PilotPanel({ auth }: { auth: string }) {
  const [pilots, setPilots] = useState<Row[]>([]);
  const [report, setReport] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() {
    const response = await fetch("/api/pilots", { headers: { Authorization: auth } });
    if (!response.ok) throw new Error(`Pilot status: ${response.status}`);
    setPilots(await response.json());
  }
  useEffect(() => { void load().catch(e => setError(String(e))); }, [auth]);
  async function exportReport(id: string, format: "json" | "csv") {
    const response = await fetch(`/api/pilots/${id}/report?format=${format}`, { headers: { Authorization: auth } });
    if (!response.ok) throw new Error(`Report unavailable: ${response.status}`);
    if (format === "json") { setReport(await response.json()); return; }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a"); link.href = url; link.download = `${id}.csv`; link.click(); URL.revokeObjectURL(url);
  }
  return <section className="panel"><h2>30-day prospective paper pilot</h2><p>Starting a pilot freezes its configuration and records new observations. With no approved strategy it runs in RESEARCH_ONLY mode. Engineering simulations have a separate label and database. A pilot is complete only after its actual observation window has elapsed.</p><button disabled={busy || pilots.some(p => p.state === "ACTIVE")} onClick={async () => { setBusy(true); setError(""); try { const response = await fetch("/api/pilots", { method: "POST", headers: { Authorization: auth, "Content-Type": "application/json" }, body: JSON.stringify({ request_id: crypto.randomUUID() }) }); if (!response.ok) throw new Error(JSON.stringify(await response.json())); await load(); } catch (e) { setError(String(e)); } finally { setBusy(false); } }}>Start 30-day paper pilot</button>{error && <p role="alert">{error}</p>}{pilots.map(p => <article key={p.pilot_id}><h3>{p.mode} · {p.state}</h3><p>{p.pilot_id} · {p.started_at} to {p.planned_end_at}</p><p>{p.performance_label}</p><p>Frozen configuration: {p.config_fingerprint}</p><button onClick={() => void exportReport(p.pilot_id, "json").catch(e => setError(String(e)))}>View JSON report</button><button onClick={() => void exportReport(p.pilot_id, "csv").catch(e => setError(String(e)))}>Export CSV report</button></article>)}{!pilots.length && <p>No pilot has been started.</p>}{report && <pre>{JSON.stringify(report, null, 2)}</pre>}</section>;
}
