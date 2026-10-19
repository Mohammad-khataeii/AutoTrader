// Presentation labels only. Network paths, persisted identifiers and exports retain their schema.
export function personalText(value: unknown): string {
  return String(value ?? "")
    .replace(/autotrader/gi, "Personal Plan")
    .replace(/revolut(?:[ -]x)?/gi, "Connected provider")
    .replace(/paper trading/gi, "Simulated Mode")
    .replace(/trade gate/gi, "decision")
    .replace(/trading/gi, "portfolio activity")
    .replace(/trader/gi, "participant")
    .replace(/trades/gi, "positions")
    .replace(/trade/gi, "position");
}
