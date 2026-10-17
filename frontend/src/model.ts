import type { Row } from "./api";
export const number = (value: unknown): number | undefined =>
  value === "" || value == null || !Number.isFinite(Number(value))
    ? undefined
    : Number(value);
export const money = (value: unknown) =>
  number(value) == null
    ? "Unavailable"
    : new Intl.NumberFormat("en-IE", {
        style: "currency",
        currency: "EUR",
      }).format(number(value)!);
export const percent = (value: unknown) =>
  number(value) == null
    ? "Unavailable"
    : `${(number(value)! * 100).toFixed(2)}%`;
export function date(value: unknown, detailed = false) {
  if (
    value === "" ||
    value == null ||
    !Number.isFinite(
      new Date(typeof value === "number" ? value : String(value)).getTime(),
    )
  )
    return "Unavailable";
  return new Intl.DateTimeFormat(
    "en-GB",
    detailed
      ? {
          year: "numeric",
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          timeZoneName: "short",
        }
      : { year: "numeric", month: "short", day: "numeric" },
  ).format(new Date(typeof value === "number" ? value : String(value)));
}
export const shortId = (value: string) => value.slice(0, 8);
const names: Record<string, string> = {
  A2_CONFIRMED_PULLBACK: "A2 Confirmed Pullback",
  B2_CONFIRMED_COMPRESSION: "B2 Confirmed Compression",
  C2_LIQUID_RETEST: "C2 Liquidity Retest",
  D2_MOMENTUM_QUALITY: "D2 Momentum Quality",
  E2_ABSOLUTE_RELATIVE_STRENGTH: "E2 Relative Strength",
  F2_RESTRICTED_RANGE: "F2 Restricted Range",
  A_TREND_PULLBACK: "Trend Pullback",
  B_COMPRESSION_BREAKOUT: "Compression Breakout",
  C_BREAKOUT_RETEST: "Breakout Retest",
  D_VOLUME_ACCUMULATION: "Volume Accumulation",
  E_RELATIVE_STRENGTH: "Relative Strength",
  F_MEAN_REVERSION: "Mean Reversion",
};
export const strategyName = (id: string = "") =>
  names[id] ?? humanize(id || "Strategy unavailable");
export const humanize = (value: unknown) =>
  String(value ?? "Unavailable")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
export const stateName = (value: unknown) =>
  ({
    SHADOW_ACTIVE: "Active",
    ACTIVE: "Active",
    SYNTHETIC_ACCEPTANCE: "Test simulation",
    PAUSED: "Paused",
    STOPPED: "Stopped",
    CREATING: "Initializing",
    RESEARCH_ONLY: "Research mode",
    HEALTHY: "Healthy",
    RUNNING: "Running",
    COMPLETED: "Completed",
    INTERRUPTED: "Interrupted",
    EMERGENCY: "Emergency halt",
  })[String(value)] ?? humanize(value);
export const dataKind = (value: unknown) =>
  value === "LIVE_MARKET_SHADOW"
    ? "Live-market simulation"
    : value === "SYNTHETIC_ACCEPTANCE"
      ? "Test simulation"
      : "Simulation · source unavailable";
export function parse(value: any): Row {
  if (value && typeof value === "object") return value;
  try {
    return JSON.parse(value ?? "{}");
  } catch {
    return {};
  }
}
export function lastEvaluation(experiment: Row) {
  if (
    experiment.last_evaluation_at &&
    Number.isFinite(new Date(experiment.last_evaluation_at).getTime())
  )
    return experiment.last_evaluation_at;
  return (experiment.history?.decisions ?? [])
    .map((r: Row) => r.created_at)
    .filter((v: string) => Number.isFinite(new Date(v).getTime()))
    .sort(
      (a: string, b: string) => new Date(b).getTime() - new Date(a).getTime(),
    )[0];
}
export const isOpen = (position: Row) =>
  !position.closed_at && (number(position.quantity) ?? 0) > 0;
export function officialActions(control: string): string[] {
  if (control === "RUNNING") return ["pause", "stop", "emergency"];
  if (control === "PAUSED") return ["resume", "stop", "emergency"];
  if (control === "STOPPED") return ["start", "emergency"];
  if (control === "EMERGENCY") return ["resume"];
  return [];
}
export function rejection(reason: unknown): string {
  if (!reason) return "No recorded explanation";
  const key = String(reason);
  return (
    {
      decision_not_accepted: "No qualifying trade",
      research_only: "No strategy is approved for the official account",
      shadow_frozen_source_changed:
        "Strategy configuration changed; new entries blocked",
    }[key] ?? key.replace(/_/g, " ")
  );
}
export function systemStatus(system?: Row, control?: string, failed = false) {
  if (failed) return "Degraded";
  if (system?.service) {
    if (system.service.worker !== "ok") return "Offline";
    if (
      system.service.postgresql !== "ok" ||
      (system.service.redis !== undefined && system.service.redis !== "ok") ||
      (system.risk_state !== undefined && !["HEALTHY", "STOPPED"].includes(system.risk_state)) ||
      system.official_reconciliation?.stale === true ||
      system.official_reconciliation?.status === "INCONSISTENT" ||
      system.shadows?.some((s: Row) => s.scan_observation?.exception || (s.risk_state !== undefined && !["HEALTHY", "STOPPED"].includes(s.risk_state)) || s.runtime_compatibility?.compatible === false || s.reconciliation?.stale === true || s.reconciliation?.status === "INCONSISTENT") ||
      system.market_data?.state !== "OK" ||
      system.market_data?.fresh === false ||
      system.current_system_errors?.length
    )
      return "Degraded";
    return "Running";
  }
  if (!system) return "Checking";
  if (
    system.worker !== "ok" ||
    system.postgresql !== "ok" ||
    system.redis !== "ok" ||
    system.exchange_data !== "OK" ||
    system.reconciliation?.problems?.length ||
    !["HEALTHY", undefined].includes(system.risk_state)
  )
    return "Degraded";
  if (["PAUSED", "STOPPED", "EMERGENCY"].includes(control ?? ""))
    return stateName(control);
  return "Running";
}
export function currentMark(
  position: Row,
  execution: Row | undefined,
  fetchedAt?: number,
  now = Date.now(),
) {
  const row = execution?.positions?.find(
    (r: Row) => r.position_id === position.position_id,
  );
  const age = number(row?.book_age_seconds),
    mid = number(row?.midpoint_mark);
  if (
    !row ||
    !fetchedAt ||
    now < fetchedAt ||
    row.unavailable_reason ||
    age == null ||
    age < 0 ||
    age + (now - fetchedAt) / 1000 > 90 ||
    mid == null ||
    mid <= 0 ||
    mid < number(row.best_bid)! ||
    mid > number(row.best_ask)! ||
    !(number(row.best_bid)! > 0) ||
    !(number(row.best_ask)! > number(row.best_bid)!)
  )
    return undefined;
  return { price: mid, pnl: number(row.unrealized_pnl) };
}

export const conditionName = (code: string) =>
  ({
    context_ready: "completed context unavailable",
    higher_timeframe_bullish: "15m/1h trend not bullish",
    ema9_recovery: "EMA9 recovery not confirmed",
    close_recovery: "close recovery not confirmed",
    previous_high_reclaimed: "previous high not reclaimed",
    retest_available: "retest level unavailable",
    prebreak_compression: "pre-breakout range not compressed",
    previous_breakout: "previous close did not confirm breakout",
    range_held: "breakout range not held",
    no_close_reversal: "close weakened",
    breakout_volume: "breakout volume below frozen threshold",
  } as Record<string, string>)[code] ?? rejection(code);
export function decisionSummary(e: Row | undefined) {
  if (!e) return "No recorded evaluation yet";
  if (e.final_state === "ACCEPTED") return "Simulated entry accepted";
  const failures: string[] = e.independently_failed ?? [];
  return failures.length
    ? `No qualifying entry. Unmet: ${failures.slice(0, 2).map(conditionName).join("; ")}${failures.length > 2 ? `; ${failures.length - 2} other conditions` : ""}.`
    : rejection(e.reason);
}
