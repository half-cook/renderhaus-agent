"use client";

import { useAuth } from "@clerk/nextjs";
import { ArrowRight, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { ExampleCard } from "@/components/beta/ExampleCard";
import { HeroClip } from "@/components/beta/HeroClip";
import { LandingDemo } from "@/components/landing/LandingDemo";
import { Meter, SpotsLeft } from "@/components/rh/Meter";
import { useWave } from "@/components/rh/useWave";
import { useClerkConfigured } from "@/components/StudioAuth";

function SignedInRedirect() {
  const { isLoaded, isSignedIn } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (isLoaded && isSignedIn) router.replace("/home");
  }, [isLoaded, isSignedIn, router]);
  return null;
}

const FAQ = [
  ["Will I see the price before anything is charged?", "Yes. Every paid step arrives as a card with an estimate and a hard cap. Nothing runs until you approve it, and rejecting it costs nothing."],
  ["How much does a film cost?", "It depends on the shots. Every paid step shows an estimate and a hard cap first, and the receipt shows exactly what was charged, including agent orchestration. What you see is what you pay. Every price you see includes a small platform fee."],
  ["What does the $10 credit cover?", "Enough for a few runs. Media and agent orchestration both come out of your credit, and each card shows an estimate and a hard cap first."],
  ["Can I change what the agent makes?", "Yes. Reorder and trim the shots on a single timeline, or rewire them on the canvas. Regenerating any step shows a new price card first."],
  ["Is the video labelled as AI-generated?", "Clips on this page are, and we recommend you label yours too when you publish."],
] as const;

const STEPS = [
  ["01", "Describe it", "Start from a photo and a sentence. The agent plans the shots and shows the plan with a running estimate."],
  ["02", "Approve the price", "Every paid step arrives as a card with an estimate and a hard cap. You approve it, edit it or reject it."],
  ["03", "Trim and ship", "Reorder and trim the shots on a single timeline, or rewire them on the canvas. Export when it's right."],
] as const;

function ClaimButton({ size = "xl" }: { size?: "xl" | "lg" }) {
  return (
    <Link href="/beta" className={`rh-btn rh-btn-primary ${size === "xl" ? "rh-btn-xl" : "rh-btn-lg"}`}>
      Claim your $10 credit <ArrowRight size={size === "xl" ? 18 : 16} aria-hidden="true" />
    </Link>
  );
}

export default function MarketingPage() {
  const clerkConfigured = useClerkConfigured();
  const wave = useWave();
  const live = wave && wave !== "unavailable" && wave.status !== "closed" ? wave : null;
  const full = live?.status === "full";

  return (
    <main className="rh-page" data-surface="beta" data-shot="landing-ready">
      {clerkConfigured ? <SignedInRedirect /> : null}
      <header className="rh-nav">
        <Link href="/" className="rh-brand"><span className="rh-mark" aria-hidden="true" /><span className="rh-wordmark" style={{ fontSize: 24 }}>Renderhaus</span></Link>
        <nav aria-label="Primary" className="rh-nav-links"><a href="#how">Product</a><a href="#faq">Pricing</a></nav>
        <Link href="/sign-in" className="rh-btn rh-btn-quiet" style={{ marginLeft: "auto", fontSize: 14 }}>Sign in</Link>
      </header>

      <section className="rh-hero">
        <div className="rh-hero-head">
          <h1 className="rh-display">Direct the video.<br /><em>Approve every dollar.</em></h1>
          <p className="rh-hero-sub">A chat-first studio for product and ad video. The agent plans the shots, and you see the price of each paid step before anything runs.</p>
        </div>
        <div className="rh-hero-row">
          <HeroClip />
          <ExampleCard />
        </div>
        <div className="rh-cta-row">
          {full ? (
            <Link href="/beta" className="rh-btn rh-btn-primary rh-btn-xl">Notify me about wave 2 <ArrowRight size={18} aria-hidden="true" /></Link>
          ) : <ClaimButton />}
          <div className="rh-offer">
            <div>
              <div className="rh-offer-line">First 50 people get $10 in credit · <SpotsLeft wave={wave} /></div>
              <div className="rh-offer-sub">Verify email, then phone, then you’re in the demo project. $10 is enough for a few runs.</div>
            </div>
            {live ? <div className="rh-offer-meter"><Meter wave={live} /></div> : null}
          </div>
        </div>
      </section>

      <section id="how" className="rh-section">
        <div className="rh-eyebrow">How it works</div>
        <h2 className="rh-h1" style={{ fontSize: 56, marginTop: 12 }}>One conversation. <em>Three decisions.</em></h2>
        <div className="rh-steps">
          {STEPS.map(([n, title, text]) => (
            <div key={n} className="rh-step-col">
              <div className="rh-step-n">{n}</div>
              <h3 className="rh-h3" style={{ fontSize: 17 }}>{title}</h3>
              <p>{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="rh-section" aria-label="Interactive canvas demo">
        <div className="rh-eyebrow">The canvas</div>
        <div className="rh-demo-head">
          <h2 className="rh-h1" style={{ fontSize: 56 }}>Build on one canvas.</h2>
          <p className="rh-fg2">Wire up image, video, voice, and music. Wherever there’s a paid step, the button tells you the price first.</p>
        </div>
        <div className="rh-demo-wrap"><LandingDemo /></div>
      </section>

      <section id="faq" className="rh-section">
        <div className="rh-faq">
          <div className="rh-faq-title">
            <div className="rh-eyebrow">FAQ</div>
            <h2 className="rh-h1" style={{ fontSize: 56, marginTop: 12 }}>Short answers, <em>no fine print.</em></h2>
          </div>
          <div className="rh-faq-list">
            {FAQ.map(([question, answer], index) => (
              <details key={question} className="rh-faq-item" open={index === 0}>
                <summary><h3>{question}</h3><Plus size={16} aria-hidden="true" /></summary>
                <p>{answer}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      <section className="rh-section">
        <div className="rh-card rh-band">
          <div style={{ flex: 1 }}>
            <div className="rh-eyebrow">Beta · wave 1</div>
            <h2 className="rh-h1" style={{ fontSize: 64, lineHeight: 1, marginTop: 12 }}>The first 50 get <em>$10.</em></h2>
            <p className="rh-fg2 rh-band-text">Verify your email, then your phone, and you’re in the demo project. $10 is enough for a few runs. You approve every paid step.</p>
            <div style={{ marginTop: 28 }}><ClaimButton size="lg" /></div>
          </div>
          {live ? (
            <div style={{ width: 520 }}>
              <div className="rh-band-count rh-mono rh-num"><b>{live.remaining}</b> of {live.capacity} spots left</div>
              <Meter wave={live} height={56} />
            </div>
          ) : null}
        </div>
      </section>

      <footer className="rh-foot">
        <span className="rh-brand"><span className="rh-mark" aria-hidden="true" /><span className="rh-wordmark" style={{ fontSize: 20 }}>Renderhaus</span></span>
        <span style={{ marginLeft: 24 }}>© 2026</span>
        <span className="rh-foot-links"><Link href="/sign-in">Sign in</Link></span>
      </footer>
    </main>
  );
}
