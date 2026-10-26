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

describe("readiness and mounted resource refresh", () => {
  it("rejects HTML and incomplete readiness JSON without inferring disabled trading", async () => {
    const html = new ApiClient(
      "Basic local",
      async () =>
        new Response("<html>App</html>", {
          headers: { "content-type": "text/html" },
        }),
    );
    await expect(html.request("/readyz")).rejects.toThrow("JSON was expected");
    const incomplete = new ApiClient("Basic local", async () =>
      Response.json({ ready: true }),
    );
    await expect(incomplete.request("/readyz")).rejects.toThrow(
      "Execution mode could not be verified",
    );
  });
  it("manual refresh includes only enabled mounted resources", async () => {
    const transport = vi.fn(async (_path: any, _options: any) =>
      Response.json({ ok: true }),
    );
    const api = new ApiClient("Basic local", transport as typeof fetch);
    api.entry("/visible").active = 1;
    api.entry("/hidden").active = 0;
    await api.refreshVisible();
    expect(transport).toHaveBeenCalledTimes(1);
    expect(transport.mock.calls[0][0]).toBe("/visible");
  });
});

describe("browser cookie sessions", () => {
  it("sends same-origin cookies and CSRF proof without a stored password", async () => {
    const transport = vi.fn(async () => Response.json({ok:true}));
    const api = new ApiClient("", transport as typeof fetch);
    api.csrfToken = "fixture-csrf";
    await api.request("/api/personal-paper/control/pause", "POST");
    const options = (transport.mock.calls as any)[0][1];
    expect(options.credentials).toBe("same-origin");
    expect(options.headers["X-CSRF-Token"]).toBe("fixture-csrf");
    expect(options.headers.Authorization).toBeUndefined();
  });
  it("expires the workspace on an unauthorized response", async () => {
    const api = new ApiClient("", async () => new Response("expired", {status:401}));
    const expired = vi.fn();api.onUnauthorized = expired;
    await expect(api.request("/api/personal-paper")).rejects.toThrow(/sign-in/);
    expect(expired).toHaveBeenCalledTimes(1);
  });
});
