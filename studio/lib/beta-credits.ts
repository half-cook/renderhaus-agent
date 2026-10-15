import { studioFetch } from "./authenticated-fetch";
import { OUT_OF_CREDIT, topupsEnabled } from "./launch";
import type { StudioAccount } from "./types";

export type BetaStatus = {
  enabled: boolean;
  wave: number;
  wave_size: number;
  spots_left: number;
  programme_full: boolean;
  message: string;
};

export type VerificationKind = "email" | "phone";

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? { ...value } : {};
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

async function betaPost(path: string, body: Record<string, string>): Promise<Record<string, unknown>> {
  const response = await studioFetch(`/api/beta/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = record(await response.json().catch(() => null));
  if (!response.ok) {
    throw new Error(typeof payload.detail === "string" ? payload.detail : "Could not complete the free beta credit request.");
  }
  return payload;
}

function responseMessage(payload: Record<string, unknown>): string {
  if (typeof payload.message !== "string") throw new Error("Unexpected free beta credit response. Please try again.");
  return payload.message;
}

export async function fetchBetaStatus(): Promise<BetaStatus> {
  const response = await fetch("/api/beta/status", { cache: "no-store" });
  const payload = record(await response.json().catch(() => null));
  if (
    !response.ok || typeof payload.enabled !== "boolean" ||
    typeof payload.programme_full !== "boolean" || typeof payload.message !== "string" ||
    !isCount(payload.wave) || !isCount(payload.wave_size) || !isCount(payload.spots_left)
  ) {
    throw new Error("Could not load free beta credit status.");
  }
  return {
    enabled: payload.enabled, wave: payload.wave, wave_size: payload.wave_size,
    spots_left: payload.spots_left, programme_full: payload.programme_full, message: payload.message,
  };
}

export async function startBetaVerification(kind: VerificationKind, identifier: string): Promise<{ challengeId: string; message: string }> {
  const payload = await betaPost(`verify/${kind}/start`, { [kind]: identifier });
  if (typeof payload.challenge_id !== "string" || !payload.challenge_id || typeof payload.dry_run !== "boolean") {
    throw new Error("Could not start verification. Please try again.");
  }
  return { challengeId: payload.challenge_id, message: responseMessage(payload) };
}

export async function confirmBetaVerification(kind: VerificationKind, challengeId: string, code: string): Promise<string> {
  const payload = await betaPost(`verify/${kind}/confirm`, {
    challenge_id: challengeId, [kind === "email" ? "token" : "code"]: code,
  });
  if (payload.verified !== true) throw new Error("Verification failed. Please try again.");
  return responseMessage(payload);
}

export async function claimBetaCredit(): Promise<{ balanceCents: number; message: string }> {
  const payload = await betaPost("claim", {});
  const grant = record(payload.grant);
  if (!isCount(payload.balance_cents) || !isCount(grant.amount_cents) || !isCount(grant.wave)) {
    throw new Error("Could not confirm your free beta credit. Please try again.");
  }
  return { balanceCents: payload.balance_cents, message: responseMessage(payload) };
}

export async function joinBetaWaitlist(email: string): Promise<string> {
  return responseMessage(await betaPost("waitlist", { email }));
}

export function emptyWalletMessage(account: StudioAccount): string | null {
  if (account.balance_cents > 0) return null;
  if (account.subscription?.status === "active" && account.subscription.daily_allowance_remaining_cents > 0) return null;
  if (!topupsEnabled()) return OUT_OF_CREDIT;
  return account.beta_credit && account.beta_credit.remaining_cents === 0
    ? "Your free beta credit is used up. Top up to keep creating."
    : "Your wallet is empty. Top up to keep creating.";
}

/** Live wave counter (public). Counters only; no identities. */
export type WaveState = {
  capacity: number;
  claimed: number;
  remaining: number;
  held: number;
  status: "open" | "full" | "closed";
  holdSeconds: number;
  updatedAt: number;
};

export async function fetchWave(): Promise<WaveState> {
  const response = await fetch("/api/beta/wave", { cache: "no-store" });
  const payload = record(await response.json().catch(() => null));
  const status = payload.status;
  if (
    !response.ok || (status !== "open" && status !== "full" && status !== "closed") ||
    !isCount(payload.capacity) || !isCount(payload.claimed) || !isCount(payload.remaining) ||
    !isCount(payload.hold_seconds) || !isCount(payload.updated_at)
  ) {
    throw new Error("Could not load the live spot counter.");
  }
  return {
    capacity: payload.capacity, claimed: payload.claimed, remaining: payload.remaining,
    held: isCount(payload.held) ? payload.held : 0, status, holdSeconds: payload.hold_seconds, updatedAt: payload.updated_at,
  };
}

/** Holds one wave spot for 15 minutes once the email is verified. */
export async function holdBetaSpot(): Promise<{ held: boolean; expiresAt: number | null; holdSeconds: number }> {
  const payload = await betaPost("hold", {});
  return {
    held: payload.held === true,
    expiresAt: isCount(payload.expires_at) ? payload.expires_at : null,
    holdSeconds: isCount(payload.hold_seconds) ? payload.hold_seconds : 900,
  };
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
