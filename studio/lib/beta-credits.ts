import { studioFetch } from "./authenticated-fetch";
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
  return account.beta_credit && account.beta_credit.remaining_cents === 0
    ? "Your free beta credit is used up. Top up to keep creating."
    : "Your wallet is empty. Top up to keep creating.";
}
