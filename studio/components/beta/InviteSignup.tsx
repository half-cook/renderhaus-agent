"use client";

import { useSignIn, useSignUp } from "@clerk/nextjs/legacy";
import { ArrowRight, Check } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useClerkConfigured } from "@/components/StudioAuth";
import {
  checkInvite, InviteCheckError, openDemoProject, redeemInvite, savedInvite, type InviteError, type InviteReservation,
} from "@/lib/beta-credits";
import { TOPUPS_COMING_SOON } from "@/lib/launch";
import { CodeCells } from "./CodeCells";
import { classifyConfirmError, confirmError, incompleteResult, WRONG_CODE } from "@/lib/signup-errors";

const RESEND_SECONDS = 45;
const INVALID = "We don’t recognise that code. Check for typos, or ask the person who invited you to send it again.";

function friendly(error: unknown, fallback: string): string {
  const clerk = error as { errors?: Array<{ longMessage?: string; message?: string }> };
  if (clerk?.errors?.[0]) return clerk.errors[0].longMessage || clerk.errors[0].message || fallback;
  return error instanceof Error && error.message ? error.message : fallback;
}

function mmss(seconds: number): string {
  const safe = Math.max(0, seconds);
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

function useCountdown(deadline: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (deadline === null) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [deadline]);
  return deadline === null ? 0 : Math.max(0, Math.ceil((deadline - now) / 1000));
}

/** Sends and confirms the six-digit email code. Clerk (free tier, email only) in production; a local stand-in when Clerk is off. */
type EmailCode = { start: (email: string) => Promise<string>; confirm: (code: string) => Promise<void> };

function useClerkEmailCode(): EmailCode {
  const signUp = useSignUp();
  const signIn = useSignIn();
  const mode = useRef<"up" | "in">("up");
  return {
    start: async (email) => {
      if (!signUp.isLoaded || !signIn.isLoaded) throw new Error("Still loading. Try again in a moment.");
      try {
        await signUp.signUp.create({ emailAddress: email });
        await signUp.signUp.prepareEmailAddressVerification({ strategy: "email_code" });
        mode.current = "up";
      } catch (error) {
        const code = (error as { errors?: Array<{ code?: string }> })?.errors?.[0]?.code;
        if (code !== "form_identifier_exists") throw error;
        // One account per email: an existing account signs in with the same email code.
        const attempt = await signIn.signIn.create({ identifier: email });
        const factor = attempt.supportedFirstFactors?.find((item) => item.strategy === "email_code");
        if (!factor || !("emailAddressId" in factor)) throw new Error("Email sign-in isn’t available for this account.");
        await signIn.signIn.prepareFirstFactor({ strategy: "email_code", emailAddressId: factor.emailAddressId });
        mode.current = "in";
      }
      return `Sent to ${email}. Type the code from the email.`;
    },
    confirm: async (code) => {
      if (!signUp.isLoaded || !signIn.isLoaded) throw new Error("Still loading. Try again in a moment.");
      if (mode.current === "up") {
        let result;
        try { result = await signUp.signUp.attemptEmailAddressVerification({ code }); } catch (error) { throw classifyConfirmError(error); }
        if (result.status !== "complete" || !result.createdSessionId) throw incompleteResult(result);
        await signUp.setActive({ session: result.createdSessionId });
      } else {
        let result;
        try { result = await signIn.signIn.attemptFirstFactor({ strategy: "email_code", code }); } catch (error) { throw classifyConfirmError(error); }
        if (result.status !== "complete" || !result.createdSessionId) throw incompleteResult(result);
        await signIn.setActive({ session: result.createdSessionId });
      }
    },
  };
}

const LOCAL_CODE = "424242";
function useLocalEmailCode(): EmailCode {
  return {
    start: async (email) => `Local mode: no email was sent to ${email}. Use ${LOCAL_CODE}.`,
    confirm: async (code) => { if (code !== LOCAL_CODE) throw confirmError("wrong_code"); },
  };
}

type Phase = { kind: "code" } | { kind: "email"; invite: InviteReservation } | { kind: "welcome"; balanceCents: number };

export function InviteSignup({ initialPhase }: { initialPhase?: Phase } = {}) {
  const [phase, setPhase] = useState<Phase>(initialPhase ?? { kind: "code" });
  useEffect(() => {
    if (initialPhase) return;
    const saved = savedInvite();
    if (saved && saved.reservedUntil * 1000 > Date.now()) setPhase({ kind: "email", invite: saved });
  }, [initialPhase]);
  const welcome = phase.kind === "welcome";
  return (
    <main className="rh-page rh-signup" data-surface="beta" data-shot={`invite-${phase.kind}`}>
      <div className="rh-signup-v4 rh-signup-cinema">
        <div className="rh-signup-bleed" aria-hidden="true" />
        <Link href="/" className="rh-brand rh-signup-brand"><span className="rh-mark" /><span className="rh-bleed-word">Renderhaus</span></Link>
        <p className="rh-signup-caption">Your first project opens with a demo film, so you see an approval card before you spend anything.</p>
        <section className="rh-signup-pane" aria-labelledby="beta-title">
          {welcome ? <Welcome balanceCents={phase.balanceCents} /> : (
            <div className="rh-form rh-form-v4" data-shot="invite-form">
              <div className="rh-fg3 rh-num rh-signup-step">Step {phase.kind === "code" ? 1 : 2} of 2</div>
              <h1 id="beta-title" className="rh-signup-h">{phase.kind === "code" ? "Enter your invite" : "Confirm your email"}</h1>
              <p className="rh-form-sub">One code, one account, $10 in credit.</p>
              <CodeStep phase={phase} onReserved={(invite) => setPhase({ kind: "email", invite })} onChange={() => setPhase({ kind: "code" })} />
              <EmailStepSwitch phase={phase} onDone={(balanceCents) => setPhase({ kind: "welcome", balanceCents })} />
              <p className="rh-form-fine">Already in? <Link href="/sign-in">Sign in</Link></p>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

function StepHead({ n, done, active, title, children }: { n: number; done: boolean; active: boolean; title: string; children?: ReactNode }) {
  return (
    <div className="rh-stephead" data-active={active || undefined}>
      <span className="rh-stepmark" data-done={done || undefined} aria-hidden="true">{done ? <Check size={13} /> : n}</span>
      <div style={{ flex: 1, minWidth: 0 }}><div className="rh-step-title">{title}</div>{children}</div>
    </div>
  );
}

function CodeStep({ phase, onReserved, onChange }: { phase: Phase; onReserved: (invite: InviteReservation) => void; onChange: () => void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ kind: InviteError; message: string } | null>(null);
  const reserved = phase.kind === "email" ? phase.invite : null;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true); setError(null);
    try { onReserved(await checkInvite(code)); } catch (cause) {
      setError(cause instanceof InviteCheckError ? { kind: cause.kind, message: cause.message } : { kind: "other", message: friendly(cause, "Could not check that code. Try again.") });
    } finally { setBusy(false); }
  };
  return (
    <div className="rh-steps-form">
      <StepHead n={1} done={Boolean(reserved)} active={!reserved} title={reserved ? "Invite code" : "Enter your invite code"}>
        {reserved ? <div className="rh-invite-meta rh-mono">{reserved.code} · ${(reserved.creditCents / 100).toFixed(0)} credit reserved <button type="button" className="rh-linkbtn" onClick={onChange}>Change</button></div> : null}
      </StepHead>
      {reserved ? <span className="rh-chip rh-chip-ok rh-verified">Valid</span> : (
        <form onSubmit={(event) => void submit(event)} className="rh-step-body">
          <label className="rh-label" htmlFor="invite-code">Invite code</label>
          <input id="invite-code" className="rh-input rh-invite-code" autoComplete="off" spellCheck={false} placeholder="RH-XXXX-XXXX-XXXX"
            value={code} onChange={(event) => { setCode(event.target.value); setError(null); }} aria-invalid={Boolean(error) || undefined} />
          {error?.kind === "used" ? (
            <p className="rh-err" role="alert" data-shot="invite-used">This code has already been used. Each code works once. If it was you, <Link href="/sign-in">sign in with your email</Link>. If not, ask for a new code.</p>
          ) : error?.kind === "invalid" ? (
            <p className="rh-err" role="alert" data-shot="invite-invalid">{INVALID}</p>
          ) : error ? <p className="rh-err" role="alert">{error.message}</p> : null}
          <button type="submit" className="rh-btn rh-btn-solid rh-btn-lg rh-btn-block" disabled={busy || code.trim().length < 12}>{busy ? "Checking…" : <>Continue <ArrowRight size={16} aria-hidden="true" /></>}</button>
        </form>
      )}
    </div>
  );
}

function EmailStepSwitch(props: { phase: Phase; onDone: (balanceCents: number) => void }) {
  return useClerkConfigured() ? <ClerkEmailStep {...props} /> : <LocalEmailStep {...props} />;
}
function ClerkEmailStep(props: { phase: Phase; onDone: (balanceCents: number) => void }) {
  return <EmailStep {...props} auth={useClerkEmailCode()} />;
}
function LocalEmailStep(props: { phase: Phase; onDone: (balanceCents: number) => void }) {
  return <EmailStep {...props} auth={useLocalEmailCode()} />;
}

function EmailStep({ phase, onDone, auth }: { phase: Phase; onDone: (balanceCents: number) => void; auth: EmailCode }) {
  const active = phase.kind === "email";
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [wrong, setWrong] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resendAt, setResendAt] = useState<number | null>(null);
  const resendLeft = useCountdown(resendAt);
  const busyRef = useRef(false);
  const run = useCallback(async (action: () => Promise<void>) => {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setError(null);
    try { await action(); } catch (cause) { setError(friendly(cause, "Something went wrong. Try again.")); } finally { busyRef.current = false; setBusy(false); }
  }, []);
  const send = (event?: FormEvent) => { event?.preventDefault(); void run(async () => {
    setSent(await auth.start(email.trim())); setCode(""); setWrong(false); setResendAt(Date.now() + RESEND_SECONDS * 1000);
  }); };
  const confirm = (event?: FormEvent) => { event?.preventDefault(); if (phase.kind !== "email") return; const invite = phase.invite; void run(async () => {
    try { await auth.confirm(code); } catch (cause) {
      // Only a real wrong code marks the cells wrong; everything else gets its own plain message.
      const failure = classifyConfirmError(cause);
      if (failure.kind === "wrong_code") { setWrong(true); setCode(""); return; }
      if (failure.kind === "expired") setCode("");
      setError(failure.message); return;
    }
    // The email is confirmed and the session is live: only now is the invite burned and the credit added.
    onDone((await redeemInvite(invite)).balanceCents);
  }); };
  return (
    <div className="rh-steps-form rh-steps-second" data-muted={!active || undefined}>
      <StepHead n={2} done={false} active={active} title="Confirm your email">
        {active && sent ? <div className="rh-fg3" style={{ fontSize: 12 }}>Sent to <b className="rh-mono" style={{ color: "var(--rh-fg)" }}>{email}</b>. Click the link in the email, or type the code.</div> : null}
      </StepHead>
      {active && !sent ? (
        <form onSubmit={send} className="rh-step-body">
          <label className="rh-label" htmlFor="invite-email">Email</label>
          <input id="invite-email" className="rh-input" type="email" autoComplete="email" placeholder="you@example.com" value={email} onChange={(event) => setEmail(event.target.value)} />
          <button type="submit" className="rh-btn rh-btn-solid rh-btn-lg rh-btn-block" disabled={busy || !email.trim()}>Send code</button>
        </form>
      ) : null}
      {active && sent ? (
        <form onSubmit={confirm} className="rh-step-body">
          <CodeCells value={code} onChange={(next) => { setCode(next); setWrong(false); }} invalid={wrong} disabled={busy} label="Email code" />
          {wrong ? <p className="rh-err" role="alert">{WRONG_CODE}</p> : null}
          <div className="rh-resend">
            {resendLeft > 0 ? <span>Resend in {mmss(resendLeft)}</span> : <button type="button" className="rh-linkbtn" onClick={() => send()}>Resend code</button>}
            <button type="button" className="rh-linkbtn" onClick={() => { setSent(null); setCode(""); setWrong(false); }}>Use a different email</button>
          </div>
          <button type="submit" className={`rh-btn rh-btn-lg rh-btn-block ${code.length < 6 ? "" : "rh-btn-primary"}`} disabled={busy || code.length < 6}>
            {code.length < 6 ? "Enter the 6-digit code to continue" : "Confirm and add my $10"}
          </button>
        </form>
      ) : null}
      {error ? <p className="rh-err" role="alert">{error}</p> : null}
    </div>
  );
}

function Welcome({ balanceCents }: { balanceCents: number }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const open = async () => {
    setBusy(true); setError(null);
    try {
      const demo = await openDemoProject();
      router.push(`/project/${encodeURIComponent(demo.projectId)}?welcome=1`);
    } catch (cause) { setError(friendly(cause, "Could not open the demo project. Try again.")); setBusy(false); }
  };
  return (
    <div className="rh-card rh-form" data-shot="invite-welcome">
      <span className="rh-chip rh-chip-ok"><span className="rh-dot rh-dot-ok" aria-hidden="true" />You’re in</span>
      <div className="rh-form-title" style={{ marginTop: 12 }}>${(balanceCents / 100).toFixed(0)} credit added</div>
      <div style={{ marginTop: 12 }}><span className="rh-welcome-amount rh-num">${(balanceCents / 100).toFixed(2)}</span> <span className="rh-fg3" style={{ fontSize: 13 }}>beta credit</span></div>
      <div className="rh-welcome-bar" aria-hidden="true"><b /></div>
      <p className="rh-form-sub" style={{ marginTop: 16 }}>The demo project is ready: a matte travel mug photo and a plan for a 10 s film. Nothing has been spent. Each paid step will ask you first.</p>
      {error ? <p className="rh-err" role="alert">{error}</p> : null}
      <button type="button" className="rh-btn rh-btn-primary rh-btn-lg rh-btn-block" style={{ marginTop: 16 }} disabled={busy} onClick={() => void open()}>
        Open the demo project <ArrowRight size={16} aria-hidden="true" />
      </button>
      <p className="rh-form-fine">This is a quiet beta. {TOPUPS_COMING_SOON.replace(".", ",")} so your $10 is the credit for now.</p>
    </div>
  );
}
