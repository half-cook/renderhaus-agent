"use client";

import { useEffect, useRef, useState } from "react";
import {
  claimBetaCredit, confirmBetaVerification, fetchBetaStatus, joinBetaWaitlist, startBetaVerification,
  type BetaStatus, type VerificationKind,
} from "@/lib/beta-credits";
import type { StudioAccount } from "@/lib/types";
import styles from "./BetaCredits.module.css";

type VerificationState =
  | { kind: "unverified" }
  | { kind: "challenge"; challengeId: string; message: string }
  | { kind: "verified"; message: string };

type Verification = { identifier: string; code: string; state: VerificationState };
const blankVerification = (): Verification => ({ identifier: "", code: "", state: { kind: "unverified" } });
const verificationFields = [
  { kind: "email", label: "Email", type: "email", placeholder: "you@example.com", codeLabel: "Email verification token", codeButton: "Confirm email" },
  { kind: "phone", label: "Phone", type: "tel", placeholder: "+14165550123", codeLabel: "Phone verification code", codeButton: "Confirm phone" },
] satisfies Array<{ kind: VerificationKind; label: string; type: string; placeholder: string; codeLabel: string; codeButton: string }>;

export function BetaCredits({ account, onClaimed, compact = false }: {
  account: StudioAccount | null;
  onClaimed?: () => Promise<void> | void;
  compact?: boolean;
}) {
  const [status, setStatus] = useState<BetaStatus | null>(null);
  const [verification, setVerification] = useState<Record<VerificationKind, Verification>>(() => ({ email: blankVerification(), phone: blankVerification() }));
  const [waitlistEmail, setWaitlistEmail] = useState("");
  const [pending, setPending] = useState(false);
  const pendingRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchBetaStatus().then((next) => {
      if (!cancelled) setStatus(next);
    }).catch((err) => {
      if (!cancelled) setError(err instanceof Error ? err.message : "Could not load free beta credit status.");
    });
    return () => { cancelled = true; };
  }, []);

  const run = async (action: () => Promise<void>) => {
    if (pendingRef.current) return;
    pendingRef.current = true;
    setPending(true);
    setError(null);
    setMessage(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not complete the free beta credit request.");
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  };

  const updateVerification = (kind: VerificationKind, next: Verification) => {
    setVerification((current) => ({ ...current, [kind]: next }));
  };

  const start = (kind: VerificationKind) => run(async () => {
    const current = verification[kind];
    updateVerification(kind, { ...current, code: "", state: { kind: "unverified" } });
    const challenge = await startBetaVerification(kind, current.identifier);
    updateVerification(kind, { ...current, code: "", state: { kind: "challenge", ...challenge } });
  });

  const confirm = (kind: VerificationKind) => run(async () => {
    const current = verification[kind];
    if (current.state.kind !== "challenge") return;
    const verifiedMessage = await confirmBetaVerification(kind, current.state.challengeId, current.code);
    updateVerification(kind, { ...current, code: "", state: { kind: "verified", message: verifiedMessage } });
  });

  const claim = () => run(async () => {
    const result = await claimBetaCredit();
    setMessage(result.message);
    setVerification({ email: blankVerification(), phone: blankVerification() });
    await Promise.all([fetchBetaStatus().then(setStatus), onClaimed?.()]);
  });

  const grant = account?.beta_credit;
  const waveOpen = Boolean(status?.enabled && !status.programme_full && status.spots_left > 0);
  const waveFull = Boolean(status?.enabled && !status.programme_full && status.spots_left === 0);
  const bothVerified = verification.email.state.kind === "verified" && verification.phone.state.kind === "verified";

  return (
    <div id={compact ? undefined : "beta-credits"} className={styles["beta-credits"]}>
      <p className={styles.heading}>Free beta credit</p>
      {status ? <p className="inspector-note" role="status">{status.message}</p> : error ? null : <p className="inspector-note">Loading free beta credit…</p>}
      {grant ? <p className="inspector-note">${(grant.remaining_cents / 100).toFixed(2)} of your free beta credit remains.</p> : null}
      {compact ? (
        status?.enabled ? <a className={styles.link} href="/home#beta-credits">{grant ? "View free beta credit" : "Verify and claim free credit"}</a> : null
      ) : !grant && account && waveOpen ? (
        <>
          <p className="inspector-note">Verify both your email and phone to claim your free credit.</p>
          {verificationFields.map((field) => {
            const current = verification[field.kind];
            return (
              <div key={field.kind} className={styles.verification}>
                <label>
                  {field.label}
                  <input
                    type={field.type} aria-label={`Beta ${field.kind}`} autoComplete={field.kind === "email" ? "email" : "tel"}
                    placeholder={field.placeholder} value={current.identifier} disabled={pending}
                    onChange={(event) => {
                      updateVerification(field.kind, { identifier: event.target.value, code: "", state: { kind: "unverified" } });
                      setMessage(null);
                      setError(null);
                    }}
                  />
                </label>
                {current.state.kind === "verified" ? <p className="inspector-note">{field.label} verified.</p> : (
                  <button type="button" className={styles.button} disabled={pending || !current.identifier.trim()} onClick={() => start(field.kind)}>Verify {field.kind}</button>
                )}
                {current.state.kind === "challenge" ? (
                  <>
                    <p className="inspector-note">{current.state.message}</p>
                    <label>
                      {field.codeLabel}
                      <input aria-label={field.codeLabel} value={current.code} disabled={pending} autoComplete="one-time-code" onChange={(event) => updateVerification(field.kind, { ...current, code: event.target.value })} />
                    </label>
                    <button type="button" className={styles.button} disabled={pending || !current.code.trim()} onClick={() => confirm(field.kind)}>{field.codeButton}</button>
                  </>
                ) : null}
              </div>
            );
          })}
          <button type="button" className={styles.button} disabled={pending || !bothVerified} onClick={claim}>Claim free credit</button>
        </>
      ) : !grant && account && waveFull ? (
        <div className={styles.verification}>
          <label>
            Email for the next wave
            <input type="email" aria-label="Waitlist email" autoComplete="email" value={waitlistEmail} disabled={pending} onChange={(event) => setWaitlistEmail(event.target.value)} />
          </label>
          <button type="button" className={styles.button} disabled={pending || !waitlistEmail.trim()} onClick={() => run(async () => {
            setMessage(await joinBetaWaitlist(waitlistEmail));
            setWaitlistEmail("");
          })}>Join waitlist</button>
        </div>
      ) : null}
      {pending ? <p className="inspector-note" role="status">Working…</p> : null}
      {message ? <p className="inspector-note" role="status">{message}</p> : null}
      {error ? <p className="generate-hint" role="alert">{error}</p> : null}
    </div>
  );
}
