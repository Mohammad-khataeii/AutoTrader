import { useResource } from "./api";
import { releaseVersion } from "./runtimeVersion";

/** The backend build comes from its running /healthz response, not package.json. */
export function useBackendVersion() {
  const health = useResource("/healthz", { poll: 60000, ttl: 60000 });
  const raw = !health.error && health.data?.status === "ok" && health.data?.mode === "paper"
    ? health.data.version
    : null;
  const release = releaseVersion(raw);
  return { release, fullVersion: release ? String(raw).trim() : null };
}
