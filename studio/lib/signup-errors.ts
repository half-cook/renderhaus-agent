/** Email-code confirm outcomes for invite sign-up. Plain copy only: no provider names in UI text. */
export const WRONG_CODE = "That code didn’t match. Check the email we sent, or resend.";
export const EXPIRED_CODE = "That code has expired. Resend a new one and try again.";
export const NOT_FINISHED = "Your email is confirmed, but sign-up isn’t finished. Try again in a minute.";
export const CAPTCHA = "We couldn’t verify this browser. Turn off blockers or try another browser, then resend the code.";
export const TOO_MANY = "Too many tries. Wait a minute, then resend a new code.";
export const CONFIRM_FAILED = "We couldn’t confirm your email. Try again in a minute.";

export type ConfirmErrorKind = "wrong_code" | "expired" | "not_finished" | "captcha" | "too_many" | "other";

export class ConfirmError extends Error {
  constructor(public kind: ConfirmErrorKind, message: string, public missingFields: string[] = []) { super(message); this.name = "ConfirmError"; }
}

const MESSAGES: Record<ConfirmErrorKind, string> = {
  wrong_code: WRONG_CODE, expired: EXPIRED_CODE, not_finished: NOT_FINISHED, captcha: CAPTCHA, too_many: TOO_MANY, other: CONFIRM_FAILED,
};

export function confirmError(kind: ConfirmErrorKind, missingFields: string[] = []): ConfirmError {
  return new ConfirmError(kind, MESSAGES[kind], missingFields);
}

/** Map a thrown auth error (API error codes) to one of the outcomes above. */
export function classifyConfirmError(error: unknown): ConfirmError {
  if (error instanceof ConfirmError) return error;
  const codes = ((error as { errors?: Array<{ code?: string }> })?.errors ?? []).map((item) => item?.code ?? "");
  const has = (...wanted: string[]) => codes.some((code) => wanted.includes(code));
  if (has("form_code_incorrect", "verification_failed")) return confirmError("wrong_code");
  if (has("verification_expired")) return confirmError("expired");
  if (codes.some((code) => code.includes("captcha"))) return confirmError("captcha");
  if (has("too_many_requests", "verification_attempts_exhausted", "rate_limit_exceeded")) return confirmError("too_many");
  return confirmError("other");
}

/** A finished attempt that still has no session: missing_requirements means the email was confirmed but sign-up needs more. */
export function incompleteResult(result: { status?: string | null; missingFields?: string[]; unverifiedFields?: string[] }): ConfirmError {
  if (result.status === "missing_requirements") {
    const missing = result.missingFields ?? [];
    console.warn("sign-up missing_requirements", { missingFields: missing, unverifiedFields: result.unverifiedFields ?? [] });
    return confirmError("not_finished", missing);
  }
  return confirmError("other");
}
