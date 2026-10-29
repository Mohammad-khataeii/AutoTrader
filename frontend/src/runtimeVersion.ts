// The running API is authoritative: display the release without its build suffix.
export function releaseVersion(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const match = /^(\d+\.\d+\.\d+)(?:[.+-][0-9A-Za-z.-]+)?$/.exec(value.trim());
  return match?.[1] ?? null;
}
