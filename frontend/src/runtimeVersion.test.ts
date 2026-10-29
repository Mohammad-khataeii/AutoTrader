import { describe, expect, it } from "vitest";
import { releaseVersion } from "./runtimeVersion";

describe("backend-driven version label", () => {
  it("shows the active backend release rather than a frontend constant", () => {
    expect(releaseVersion("4.9.1-dev.2")).toBe("4.9.1");
    expect(releaseVersion("4.9.1.dev2")).toBe("4.9.1");
    expect(releaseVersion("4.9.1-paper.1")).toBe("4.9.1");
    expect(releaseVersion("4.10.0-rc.3")).toBe("4.10.0");
    expect(releaseVersion("5.0.0")).toBe("5.0.0");
  });
  it("does not invent a version when the server is unavailable", () => {
    expect(releaseVersion(null)).toBeNull();
    expect(releaseVersion(undefined)).toBeNull();
    expect(releaseVersion(4.9)).toBeNull();
    expect(releaseVersion("4.8")).toBeNull();
    expect(releaseVersion("not-a-version")).toBeNull();
  });
});
