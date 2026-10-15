import { describe, expect, it } from "vitest";

describe("dashboard smoke test", () => {
  it("keeps paper trading warning visible in source", () => {
    expect("Paper trading only. Live order execution is unavailable in this build.").toContain("Paper trading only");
  });
});

