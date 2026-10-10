"use client";

import { SignUpButton, useAuth } from "@clerk/nextjs";
import { Check } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";
import { Meter } from "@/components/rh/Meter";
import { useWave } from "@/components/rh/useWave";
import { useClerkConfigured } from "@/components/StudioAuth";
import {
  claimBetaCredit, confirmBetaVerification, holdBetaSpot, joinBetaWaitlist, openDemoProject, startBetaVerification,
  type WaveState,
} from "@/lib/beta-credits";
import { CodeCells } from "./CodeCells";

const ALMOST_FULL = 10;
const RESEND_SECONDS = 30;
const WRONG_CODE = "That code didn’t match. Check the text we sent, or resend.";

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

function friendly(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

type Step = "email" | "phone";
type Challenge = { id: string; hint: string } | null;

function Gate({ children }: { children: (signedIn: boolean) => ReactNode }) {
  const { isLoaded, isSignedIn } = useAuth();
  if (!isLoaded) return <div className="rh-fg3">Checking your account…</div>;
  return <>{children(Boolean(isSignedIn))}</>;
}

function SignedInGate({ children }: { children: (signedIn: boolean) => ReactNode }) {
  const configured = useClerkConfigured();
  return configured ? <Gate>{children}</Gate> : <>{children(true)}</>;
}

export function BetaSignup() {
  const wave = useWave();
  const live: WaveState | null = wave && wave !== "unavailable" ? wave : null;
  const closed = live?.status === "full" || live?.status === "closed";
  const almost = live?.status === "open" && live.remaining <= ALMOST_FULL;
  const updated = live ? new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(live.updatedAt * 1000) : null;
  const chip = !live ? null : closed
    ? <span className="rh-chip rh-chip-mono">CLOSED</span>
    : almost ? <span className="rh-chip rh-chip-accent"><span className="rh-dot rh-dot-run" aria-hidden="true" />Almost full</span>
    : <span className="rh-chip rh-chip-ok"><span className="rh-dot rh-dot-ok" aria-hidden="true" />Wave 1 is open</span>;

  return (
    <main className="rh-page rh-signup" data-surface="beta" data-shot="beta-ready">
      <header className="rh-nav">
        <Link href="/" className="rh-brand"><span className="rh-mark" aria-hidden="true" /><span className="rh-wordmark" style={{ fontSize: 24 }}>Renderhaus</span></Link>
        <Link href="/sign-in" className="rh-btn rh-btn-quiet" style={{ marginLeft: "auto", fontSize: 14 }}>Sign in</Link>
      </header>
      <div className="rh-signup-grid">
        <section className="rh-signup-left" aria-labelledby="beta-title">
          <div className="rh-signup-eyebrow"><span className="rh-eyebrow">Renderhaus beta · wave 1</span>{chip}</div>
          {closed ? (
            <h1 id="beta-title" className="rh-display rh-signup-title" data-full="true">Wave 1 is <em>full.</em></h1>
          ) : (
            <h1 id="beta-title" className="rh-display rh-signup-title">First 50 people get <em>$10</em> in credit.</h1>
          )}
          <p className="rh-signup-body">
            {closed
              ? "Every spot in the first wave is claimed. Leave your email and we’ll tell you when the next wave opens."
              : "Verify your email, then your phone, and you’re straight into the demo project. $10 is enough for a few runs. You approve every paid step, and see an estimate and a hard cap first."}
          </p>
          {live ? (
            <div className="rh-signup-meter" data-shot={closed ? "wave-full" : almost ? "wave-spots-left" : "wave-open"}>
              <div className="rh-signup-count">
                <span className="rh-mono rh-num"><b data-low={almost || undefined}>{live.remaining}</b> of {live.capacity} spots left</span>
                <span className="rh-mono rh-fg3 rh-stamp">LIVE · UPDATED {updated}</span>
              </div>
              <Meter wave={live} height={32} />
              <div className="rh-legend"><span><i className="rh-on" />Claimed</span><span><i className="rh-open" />Open</span></div>
            </div>
          ) : null}
        </section>
        <section className="rh-signup-right">
          {wave === null ? <div className="rh-card rh-form" aria-busy="true"><div className="rh-fg3">Checking spots…</div></div>
            : closed ? <WaitlistForm /> : <SignedInGate>{(signedIn) => signedIn ? <ClaimFlow wave={live} /> : <AccountGateCard />}</SignedInGate>}
        </section>
      </div>
      <footer className="rh-foot"><span>© 2026 Renderhaus</span><span className="rh-foot-links"><Link href="/">Home</Link></span></footer>
    </main>
  );
}

function AccountGateCard() {
  return (
    <div className="rh-card rh-form">
      <div className="rh-form-title">Claim your credit</div>
      <p className="rh-form-sub">Create your account first, then two quick checks and you’re in the demo project. One claim per person.</p>
      <SignUpButton mode="modal" fallbackRedirectUrl="/beta">
        <button type="button" className="rh-btn rh-btn-primary rh-btn-lg rh-btn-block">Create your account</button>
      </SignUpButton>
    </div>
  );
}

function WaitlistForm() {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  const [error, setError] = useState<string | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setState("busy"); setError(null);
    try { await joinBetaWaitlist(email); setState("done"); } catch (cause) { setError(friendly(cause, "Could not save your email. Try again.")); setState("idle"); }
  };
  return (
    <form className="rh-card rh-form rh-form-stack" onSubmit={(event) => void submit(event)} data-shot="waitlist-form">
      <div className="rh-form-title">Wave 2 notification</div>
      <p className="rh-form-sub">We’ll use this email once, to tell you when the next wave opens. Nothing else.</p>
      {state === "done" ? <p role="status" className="rh-ok-line"><Check size={14} aria-hidden="true" />You’re on the list for wave 2.</p> : (
        <>
          <label className="rh-label" htmlFor="waitlist-email">Email</label>
          <input id="waitlist-email" className="rh-input" type="email" autoComplete="email" placeholder="you@example.com" value={email} onChange={(event) => setEmail(event.target.value)} required />
          {error ? <p className="rh-err" role="alert">{error}</p> : null}
          <button type="submit" className="rh-btn rh-btn-primary rh-btn-lg rh-btn-block" disabled={state === "busy" || !email.trim()}>Notify me</button>
        </>
      )}
    </form>
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

function ClaimFlow({ wave }: { wave: WaveState | null }) {
  const router = useRouter();
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [emailChallenge, setEmailChallenge] = useState<Challenge>(null);
  const [emailCode, setEmailCode] = useState("");
  const [emailDone, setEmailDone] = useState(false);
  const [phone, setPhone] = useState("");
  const [phoneChallenge, setPhoneChallenge] = useState<Challenge>(null);
  const [code, setCode] = useState("");
  const [wrong, setWrong] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [holdUntil, setHoldUntil] = useState<number | null>(null);
  const [resendAt, setResendAt] = useState<number | null>(null);
  const holdLeft = useCountdown(holdUntil);
  const resendLeft = useCountdown(resendAt);
  const busyRef = useRef(false);

  const run = useCallback(async (action: () => Promise<void>) => {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setError(null);
    try { await action(); } catch (cause) { setError(friendly(cause, "Something went wrong. Try again.")); } finally { busyRef.current = false; setBusy(false); }
  }, []);

  const sendEmail = (event?: FormEvent) => { event?.preventDefault(); void run(async () => {
    const started = await startBetaVerification("email", email);
    setEmailChallenge({ id: started.challengeId, hint: started.message }); setEmailCode("");
  }); };
  const confirmEmail = (event?: FormEvent) => { event?.preventDefault(); void run(async () => {
    if (!emailChallenge) return;
    await confirmBetaVerification("email", emailChallenge.id, emailCode.trim());
    const held = await holdBetaSpot();
    setHoldUntil(held.expiresAt ? held.expiresAt * 1000 : Date.now() + held.holdSeconds * 1000);
    setEmailDone(true); setStep("phone");
  }); };
  const sendPhone = (event?: FormEvent) => { event?.preventDefault(); void run(async () => {
    const started = await startBetaVerification("phone", phone);
    setPhoneChallenge({ id: started.challengeId, hint: started.message }); setCode(""); setWrong(false);
    setResendAt(Date.now() + RESEND_SECONDS * 1000);
  }); };
  const finish = (event?: FormEvent) => { event?.preventDefault(); void run(async () => {
    if (!phoneChallenge) return;
    setWrong(false);
    try {
      await confirmBetaVerification("phone", phoneChallenge.id, code);
    } catch {
      setWrong(true); setCode(""); return;
    }
    await claimBetaCredit();
    await openDemoProject();
    toast.success("Phone verified. Opening your demo project.");
    router.push("/demo?welcome=1");
  }); };

  const remaining = wave?.remaining;
  return (
    <div className="rh-card rh-form" data-shot="claim-form">
      <div className="rh-form-head">
        <div className="rh-form-title">Claim your credit</div>
        {remaining != null ? <span className="rh-mono rh-fg3 rh-num" style={{ fontSize: 11.5 }}>{remaining} spots left</span> : null}
      </div>
      <p className="rh-form-sub">Two quick checks, then you’re in the demo project. One claim per person.</p>

      <div className="rh-steps-form">
        <StepHead n={1} done={emailDone} active={step === "email"} title="Verify your email">
          {emailDone ? <div className="rh-mono rh-fg3" style={{ fontSize: 12 }}>{email}</div> : null}
        </StepHead>
        {emailDone ? <span className="rh-chip rh-chip-ok rh-verified">Verified</span> : null}
        {step === "email" && !emailChallenge ? (
          <form onSubmit={sendEmail} className="rh-step-body">
            <label className="rh-label" htmlFor="beta-email">Email</label>
            <input id="beta-email" className="rh-input" type="email" autoComplete="email" placeholder="you@example.com" value={email} onChange={(event) => setEmail(event.target.value)} />
            <button type="submit" className="rh-btn rh-btn-solid rh-btn-lg rh-btn-block" disabled={busy || !email.trim()}>Send code</button>
          </form>
        ) : null}
        {step === "email" && emailChallenge ? (
          <form onSubmit={confirmEmail} className="rh-step-body">
            <p className="rh-hint">{emailChallenge.hint}</p>
            <label className="rh-label" htmlFor="beta-email-code">Email code</label>
            <input id="beta-email-code" className="rh-input" autoComplete="one-time-code" value={emailCode} onChange={(event) => setEmailCode(event.target.value)} />
            <button type="submit" className="rh-btn rh-btn-solid rh-btn-lg rh-btn-block" disabled={busy || !emailCode.trim()}>Verify email</button>
          </form>
        ) : null}
      </div>

      <div className="rh-steps-form rh-steps-second" data-muted={step !== "phone" || undefined}>
        <StepHead n={2} done={false} active={step === "phone"} title="Verify your phone">
          {step === "phone" && phoneChallenge ? <div className="rh-fg3" style={{ fontSize: 12 }}>Code sent to <b className="rh-mono" style={{ color: "var(--rh-fg)" }}>{phone}</b></div> : null}
        </StepHead>
        {step === "phone" && !phoneChallenge ? (
          <form onSubmit={sendPhone} className="rh-step-body">
            <label className="rh-label" htmlFor="beta-phone">Phone, with country code</label>
            <input id="beta-phone" className="rh-input" type="tel" autoComplete="tel" placeholder="+14165550123" value={phone} onChange={(event) => setPhone(event.target.value)} />
            <button type="submit" className="rh-btn rh-btn-solid rh-btn-lg rh-btn-block" disabled={busy || !phone.trim()}>Send code</button>
          </form>
        ) : null}
        {step === "phone" && phoneChallenge ? (
          <form onSubmit={finish} className="rh-step-body">
            <p className="rh-hint">{phoneChallenge.hint}</p>
            <CodeCells value={code} onChange={(next) => { setCode(next); setWrong(false); }} invalid={wrong} disabled={busy} label="Phone code" />
            {wrong ? <p className="rh-err" role="alert">{WRONG_CODE}</p> : null}
            <div className="rh-resend">
              {resendLeft > 0 ? <span>Resend in {mmss(resendLeft)}</span> : <button type="button" className="rh-linkbtn" onClick={() => sendPhone()}>Resend code</button>}
              <button type="button" className="rh-linkbtn" onClick={() => { setPhoneChallenge(null); setCode(""); setWrong(false); }}>Change number</button>
            </div>
            <button type="submit" className={`rh-btn rh-btn-lg rh-btn-block ${code.length < 6 ? "" : "rh-btn-primary"}`} disabled={busy || code.length < 6}>
              {code.length < 6 ? "Enter the 6-digit code to continue" : "Verify and open the demo project"}
            </button>
          </form>
        ) : null}
      </div>

      {error ? <p className="rh-err" role="alert">{error}</p> : null}
      {holdUntil && holdLeft > 0 ? <p className="rh-hold rh-mono rh-num" role="status">Your spot is held for {mmss(holdLeft)}.</p> : null}
      {holdUntil && holdLeft === 0 && !busy ? <p className="rh-err" role="alert">Your spot hold ended. Reload to try again.</p> : null}
      <p className="rh-form-fine">Your $10 credit is added when your phone is verified. It pays for generation and agent orchestration. Every paid step shows an estimate and a hard cap, and waits for your approval.</p>
    </div>
  );
}
