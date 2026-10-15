import { describe, expect, it } from "vitest";
import { displayMoney } from "./main";

describe("authoritative financial display", () => {
  it("keeps unavailable valuation distinct from zero", () => {
    expect(displayMoney("")).toBe("Unavailable");
    expect(displayMoney(null)).toBe("Unavailable");
    expect(displayMoney(undefined)).toBe("Unavailable");
    expect(displayMoney("0")).toBe("EUR 0.00");
    expect(displayMoney("480.000000000000")).toBe("EUR 480.00");
  });
});

