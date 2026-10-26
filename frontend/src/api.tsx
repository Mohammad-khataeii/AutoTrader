import React, {
  createContext,
  useContext,
  useEffect,
  useSyncExternalStore,
} from "react";
import { personalText } from "./presentation";
export type Row = Record<string, any>;
export type Snapshot = {
  data?: any;
  error?: string;
  loading: boolean;
  updatedAt?: number;
  observedAt?: number;
};
type Entry = {
  snapshot: Snapshot;
  listeners: Set<() => void>;
  pending?: Promise<any>;
  controller?: AbortController;
  active: number;
};
export function errorMessage(error: unknown): string {
  return error instanceof Error
    ? personalText(error.message)
    : "The request could not be completed. Please try again.";
}
export class ApiClient {
  csrfToken = "";
  onUnauthorized?: () => void;
  private entries = new Map<string, Entry>();
  private disposed = false;
  constructor(
    private auth: string,
    private transport: typeof fetch = (...args) => fetch(...args),
  ) {}
  entry(path: string): Entry {
    if (!this.entries.has(path))
      this.entries.set(path, {
        snapshot: { loading: false },
        listeners: new Set(),
        active: 0,
      });
    return this.entries.get(path)!;
  }
  subscribe = (path: string, listener: () => void) => {
    const entry = this.entry(path);
    entry.listeners.add(listener);
    return () => {
      entry.listeners.delete(listener);
    };
  };
  private update(entry: Entry, values: Partial<Snapshot>) {
    if (this.disposed) return;
    entry.snapshot = { ...entry.snapshot, ...values };
    entry.listeners.forEach((listener) => listener());
  }
  async request(
    path: string,
    method = "GET",
    body?: Row,
    signal?: AbortSignal,
  ): Promise<any> {
    const response = await this.transport(path, {
      method,
      signal,
      credentials: "same-origin",
      headers: { ...(this.auth ? { Authorization: this.auth } : {}), "Content-Type": "application/json",
        ...(this.csrfToken && method !== "GET" ? { "X-CSRF-Token": this.csrfToken } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
    if (!response.ok) {
      let detail: unknown;
      try {
        detail = (await response.json()).detail;
      } catch {
        /* A gateway may return HTML. */
      }
      if (response.status === 401) {
        this.onUnauthorized?.();
        throw new Error(
          "Your sign-in was not accepted. Sign out and sign in again.",
        );
      }
      if (response.status >= 500)
        throw new Error(
          "The server is temporarily unavailable. Your last successful data is still shown.",
        );
      const reason =
        typeof detail === "string"
          ? personalText(detail.replace(/_/g, " "))
          : "The server could not complete this action.";
      throw new Error(`${reason} (${response.status})`);
    }
    if (!response.headers.get("content-type")?.includes("application/json"))
      throw new Error(
        "The server returned an invalid response. JSON was expected; status is unverified.",
      );
    const data = await response.json();
    if (path === "/readyz" && typeof data.live_trading_enabled !== "boolean")
      throw new Error(
        "Execution mode could not be verified from the readiness response.",
      );
    return data;
  }
  load(path: string, force = false, ttl = 30000): Promise<any> {
    const entry = this.entry(path);
    if (entry.pending) return entry.pending;
    if (
      !force &&
      entry.snapshot.updatedAt &&
      Date.now() - entry.snapshot.updatedAt < ttl
    )
      return Promise.resolve(entry.snapshot.data);
    if (this.disposed) return Promise.resolve(undefined);
    const requestedAt = Date.now();
    entry.controller = new AbortController();
    this.update(entry, { loading: true });
    entry.pending = this.request(
      path,
      "GET",
      undefined,
      entry.controller.signal,
    )
      .then((data) => {
        this.update(entry, {
          data,
          updatedAt: Date.now(),
          observedAt: requestedAt,
          error: undefined,
        });
        return data;
      })
      .catch((error) => {
        if (error?.name !== "AbortError")
          this.update(entry, { error: errorMessage(error) });
        return undefined;
      })
      .finally(() => {
        entry.pending = undefined;
        this.update(entry, { loading: false });
      });
    return entry.pending;
  }
  async refreshVisible() {
    await this.refresh(
      ...[...this.entries]
        .filter(([, entry]) => entry.active > 0)
        .map(([path]) => path),
    );
  }
  async refresh(...paths: string[]) {
    await Promise.all(paths.map((path) => this.load(path, true)));
  }
  async download(path: string, filename: string) {
    const response = await this.transport(path, {
      credentials: "same-origin",
      headers: this.auth ? { Authorization: this.auth } : {},
      cache: "no-store",
    });
    if (!response.ok)
      throw new Error(
        response.status === 401
          ? "Please sign in again to export this history."
          : "The export is unavailable. Please try again.",
      );
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  dispose() {
    this.disposed = true;
    this.entries.forEach((entry) => entry.controller?.abort());
    this.entries.clear();
  }
}
export const ApiContext = createContext<ApiClient | null>(null);
export function useApi() {
  const api = useContext(ApiContext);
  if (!api) throw new Error("Sign in required");
  return api;
}
export function useResource(
  path: string,
  {
    enabled = true,
    poll = 0,
    ttl = 30000,
  }: { enabled?: boolean; poll?: number; ttl?: number } = {},
): Snapshot {
  const api = useApi();
  const snapshot = useSyncExternalStore(
    (listener) => api.subscribe(path, listener),
    () => api.entry(path).snapshot,
  );
  useEffect(() => {
    if (!enabled) return;
    const entry = api.entry(path);
    entry.active += 1;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let running = false;
    let first = true;
    const tick = async () => {
      if (stopped || running || document.visibilityState === "hidden") return;
      running = true;
      await api.load(path, !first && Boolean(poll), ttl);
      first = false;
      running = false;
      if (!stopped && poll) timer = setTimeout(tick, poll);
    };
    const visibility = () => {
      clearTimeout(timer);
      if (document.visibilityState === "visible") void tick();
    };
    void tick();
    document.addEventListener("visibilitychange", visibility);
    return () => {
      stopped = true;
      entry.active = Math.max(0, entry.active - 1);
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [api, path, enabled, poll, ttl]);
  return snapshot;
}
