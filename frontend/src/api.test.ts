import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "./api";
describe("shared authenticated resources", () => {
  it("deduplicates in-flight loads and reuses unchanged data", async () => {
    let resolve!: (value: Response) => void;
    const fetcher = vi.fn(
      () =>
        new Promise<Response>((r) => {
          resolve = r;
        }),
    );
    const api = new ApiClient("Basic fixture", fetcher as typeof fetch);
    const first = api.load("/api/research"),
      second = api.load("/api/research", true);
    expect(fetcher).toHaveBeenCalledTimes(1);
    resolve(Response.json({ run: "frozen" }));
    await Promise.all([first, second]);
    expect(await api.load("/api/research")).toEqual({ run: "frozen" });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0]).toBeDefined();
  });
  it("retains valid data and its timestamp when a refresh fails", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ equity: "500" }))
      .mockResolvedValueOnce(
        new Response("gateway unavailable", { status: 503 }),
      );
    const api = new ApiClient("Basic fixture", fetcher);
    await api.load("/api/overview");
    const before = api.entry("/api/overview").snapshot;
    await api.load("/api/overview", true);
    expect(api.entry("/api/overview").snapshot.data).toEqual(before.data);
    expect(api.entry("/api/overview").snapshot.updatedAt).toBe(
      before.updatedAt,
    );
    expect(api.entry("/api/overview").snapshot.error).toMatch(
      /temporarily unavailable/,
    );
    expect(api.entry("/api/overview").snapshot.loading).toBe(false);
  });
  it("clears a previous refresh error after recovery and keeps credentials scoped", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(new Response("no", { status: 401 }))
      .mockResolvedValueOnce(Response.json({ ok: true }));
    const api = new ApiClient("Basic fixture", fetcher);
    await api.load("/api/overview");
    expect(api.entry("/api/overview").snapshot.error).toMatch(/sign-in/);
    await api.load("/api/overview", true);
    expect(api.entry("/api/overview").snapshot.error).toBeUndefined();
    expect(fetcher.mock.calls[1][1].headers.Authorization).toBe(
      "Basic fixture",
    );
  });
  it("aborts in-flight reads on logout and does not issue new requests", async () => {
    const fetcher = vi.fn(
      (_path, init) =>
        new Promise<Response>((_resolve, reject) =>
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          ),
        ),
    );
    const api = new ApiClient("Basic fixture", fetcher as typeof fetch);
    const pending = api.load("/api/history");
    api.dispose();
    await pending;
    await api.load("/api/history");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
