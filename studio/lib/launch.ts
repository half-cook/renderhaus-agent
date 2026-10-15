/** Quiet-beta launch copy and switches (spec 4.12). */
export const INVITE_LINE = "Invite only · $10 credit to start";
export const TOPUPS_COMING_SOON = "Top-ups are coming soon.";
export const OUT_OF_CREDIT = "You've used your beta credit. Top-ups are coming soon.";
export const OUT_OF_CREDIT_FULL = `${OUT_OF_CREDIT} Reply and tell us what you'd make next.`;

/** Top-ups stay hidden unless explicitly enabled at build time; the server blocks them too. */
export function topupsEnabled(): boolean {
  return typeof process !== "undefined" && process.env.NEXT_PUBLIC_TOPUPS_ENABLED === "true";
}
