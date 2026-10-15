// Inline chat failure line shown where the agent reply would go when Renderhaus
// can't be reached (network failure or a 5xx). Never shows codes or service names.
export const SEND_FAILED_LINE = "Couldn't reach Renderhaus · nothing charged";
export const SEND_FAILED_RETRY = "Try again";
export const SEND_FAILED_AGAIN_LINE = "We're on it, your credit is untouched";

/** note: a plain server message (e.g. credit held) shown instead of the unreachable line. */
export type FailedTurn = { prompt: string; attempts: number; note?: string };

export function isUnreachableStatus(status: number): boolean {
  return status === 0 || status >= 500;
}

export function nextFailedTurn(previous: FailedTurn | null, prompt: string, note?: string): FailedTurn {
  return { prompt, attempts: previous && previous.prompt === prompt ? previous.attempts + 1 : 1, ...(note ? { note } : {}) };
}

export function failureLines(turn: FailedTurn): string[] {
  if (turn.note) return [turn.note];
  return turn.attempts > 1 ? [SEND_FAILED_LINE, SEND_FAILED_AGAIN_LINE] : [SEND_FAILED_LINE];
}
