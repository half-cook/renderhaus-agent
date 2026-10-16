/** Activity labels use the same local calendar and clock as the rest of Home. */
export function formatActivityTime(timeMs: number, now = new Date()): string {
  const date = new Date(timeMs);
  if (Number.isNaN(date.getTime())) return "Time unavailable";
  const day = date.toDateString() === now.toDateString()
    ? "Today"
    : date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  return `${day} ${date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`;
}
