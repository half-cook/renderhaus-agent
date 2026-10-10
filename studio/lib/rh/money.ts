/** All money reaches the UI as integer cents. The UI formats them and never computes a price. */
export function formatCents(cents: number): string {
  const safe = Number.isFinite(cents) ? Math.max(0, Math.round(cents)) : 0;
  const dollars = Math.floor(safe / 100);
  return `$${dollars.toLocaleString("en-US")}.${String(safe % 100).padStart(2, "0")}`;
}

export function isCents(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}
