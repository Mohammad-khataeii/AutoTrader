import { describe, expect, it } from "vitest";
import {
  currentMark,
  date,
  lastEvaluation,
  money,
  officialActions,
  percent,
  rejection,
  stateName,
  systemStatus,
} from "./model";
describe("honest financial presentation", () => {
  it("distinguishes zero from unavailable and preserves losses", () => {
    expect(money(0)).toBe("€0.00");
    expect(money(-3.8036)).toBe("-€3.80");
    for (const missing of ["", null, undefined, NaN])
      expect(money(missing)).toBe("Unavailable");
    expect(percent(null)).toBe("Unavailable");
  });
  it("shows open P&L only while an actual executable mark remains fresh", () => {
    const position = { position_id: "p" },
      now = Date.now();
    const valid = {
      positions: [
        {
          position_id: "p",
          book_age_seconds: "5",
          best_bid: "100",
          best_ask: "101",
          midpoint_mark: "100.5",
          unrealized_pnl: "-1",
        },
      ],
    };
    expect(currentMark(position, valid, now, now)).toEqual({
      price: 100.5,
      pnl: -1,
    });
    expect(currentMark(position, valid, now - 86000, now)).toBeUndefined();
    expect(currentMark(position, valid, now + 1, now)).toBeUndefined();
    expect(currentMark(position, { positions: [] }, now, now)).toBeUndefined();
    expect(
      currentMark(
        position,
        { positions: [{ ...valid.positions[0], unavailable_reason: "stale" }] },
        now,
        now,
      ),
    ).toBeUndefined();
  });
  it("does not invent evaluation timestamps or more specific rejection causes", () => {
    expect(lastEvaluation({ history: { decisions: [] } })).toBeUndefined();
    expect(
      lastEvaluation({
        history: {
          decisions: [
            { created_at: "invalid" },
            { created_at: "2026-10-16T12:00:00Z" },
          ],
        },
      }),
    ).toBe("2026-10-16T12:00:00Z");
    expect(rejection("decision_not_accepted")).toBe("No qualifying opportunity");
    expect(rejection(undefined)).toBe("No recorded explanation");
    expect(date(0)).not.toBe("Unavailable");
  });
  it("offers only valid official controls and reports degraded services", () => {
    expect(stateName("ACTIVE")).toBe("Active");
    expect(stateName("RESEARCH_ONLY")).toBe("Research mode");
    expect(officialActions("STOPPED")).toEqual(["start", "emergency"]);
    expect(officialActions("UNKNOWN")).toEqual([]);
    expect(systemStatus({ worker: "unavailable" }, "RUNNING")).toBe("Degraded");
  });
});

it("separates worker and market health from stopped official entries", () => {
  const system = {
    service: { worker: "ok", postgresql: "ok" },
    market_data: { state: "OK", fresh: true },
    official: { control: "STOPPED" },
    risk_state: "STOPPED",
    current_system_errors: [],
  };
  expect(systemStatus(system, "STOPPED")).toBe("Running");
  expect(
    systemStatus(
      { ...system, market_data: { state: "OK", fresh: false } },
      "STOPPED",
    ),
  ).toBe("Degraded");
  expect(
    systemStatus(
      { ...system, service: { worker: "stale_or_absent" } },
      "STOPPED",
    ),
  ).toBe("Offline");
});
