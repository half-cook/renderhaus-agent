import { studioFetch } from "./authenticated-fetch";
import { OUT_OF_CREDIT } from "./launch";
import type { StudioAccount } from "./types";

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? { ...value } : {};
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

export function emptyWalletMessage(account: StudioAccount): string | null {
  if (account.balance_cents > 0) return null;
  return OUT_OF_CREDIT;
}

export async function openDemoProject(): Promise<{ projectId: string; name: string }> {
  const response = await studioFetch("/api/studio/demo-project", { method: "POST" });
  const payload = record(await response.json().catch(() => null));
  if (!response.ok || typeof payload.project_id !== "string" || typeof payload.name !== "string") {
    throw new Error("Could not open the demo project. Please try again.");
  }
  return { projectId: payload.project_id, name: payload.name };
}

/** Invite-only beta (spec 4.12). */
export type InviteError = "invalid" | "used" | "rate_limited" | "other";

export class InviteCheckError extends Error {
  constructor(message: string, readonly kind: InviteError) {
    super(message);
  }
}

const RESERVATION_KEY = "renderhaus.beta.invite";

export type InviteReservation = { code: string; reservation: string; reservedUntil: number; creditCents: number };

export function savedInvite(): InviteReservation | null {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(RESERVATION_KEY) || "null");
    return parsed && typeof parsed.code === "string" && typeof parsed.reservation === "string" ? parsed as InviteReservation : null;
  } catch {
    return null;
  }
}

export function forgetInvite(): void {
  try { sessionStorage.removeItem(RESERVATION_KEY); } catch { /* storage unavailable */ }
}

async function invitePost(path: "check" | "redeem", body: Record<string, string>): Promise<Record<string, unknown>> {
  const response = await studioFetch(`/api/beta/invite/${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const payload = record(await response.json().catch(() => null));
  if (!response.ok) {
    const detail = typeof payload.detail === "string" ? payload.detail : "Could not check that code. Try again.";
    const kind: InviteError = response.status === 400 ? "invalid" : response.status === 409 ? "used" : response.status === 429 ? "rate_limited" : "other";
    throw new InviteCheckError(detail, kind);
  }
  return payload;
}

/** Validates and reserves (never burns) a code. Burned only by redeemInvite after the email is confirmed. */
export async function checkInvite(code: string): Promise<InviteReservation> {
  const previous = savedInvite();
  const sameCode = previous && previous.code.replace(/[^A-Z0-9]/gi, "").toUpperCase() === code.replace(/[^A-Z0-9]/gi, "").toUpperCase();
  const payload = await invitePost("check", { code, reservation: sameCode ? previous.reservation : "" });
  const reservation: InviteReservation = {
    code: code.trim().toUpperCase(),
    reservation: typeof payload.reservation === "string" ? payload.reservation : "",
    reservedUntil: isCount(payload.reserved_until) ? payload.reserved_until : 0,
    creditCents: isCount(payload.credit_cents) ? payload.credit_cents : 1000,
  };
  try { sessionStorage.setItem(RESERVATION_KEY, JSON.stringify(reservation)); } catch { /* storage unavailable */ }
  return reservation;
}

export async function redeemInvite(invite: InviteReservation): Promise<{ balanceCents: number }> {
  const payload = await invitePost("redeem", { code: invite.code, reservation: invite.reservation });
  forgetInvite();
  return { balanceCents: isCount(payload.balance_cents) ? payload.balance_cents : 0 };
}
