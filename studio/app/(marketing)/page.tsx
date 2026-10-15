"use client";

import { useAuth } from "@clerk/nextjs";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { LandingDemo } from "@/components/landing/LandingDemo";
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
  ["How much does a film cost?", "It depends on the shots. Every paid step shows an estimate and a hard cap first, and the receipt shows exactly what was charged, including agent orchestration. What you see is what you pay."],
  ["What does the $10 credit cover?", "Enough for a few runs. Media and agent orchestration both come out of your credit, and each card shows an estimate and a hard cap first."],
  ["Can I change what the agent makes?", "Yes. Reorder and trim the shots on a single timeline, or rewire them on the canvas. Regenerating any step shows a new price card first."],
  ["Is the video labelled as AI-generated?", "Clips on this page are, and we recommend you label yours too when you publish."],
] as const;

const STEPS = [
  ["01", "Describe it", "Start from a photo and a sentence. The agent plans the shots and shows the plan with a running estimate."],
  ["02", "Approve the price", "Every paid step arrives as a card with an estimate and a hard cap. You approve it, edit it or reject it."],
  ["03", "Trim and ship", "Reorder and trim the shots on a single timeline, or rewire them on the canvas. Export when it's right."],
] as const;

export default function MarketingPage() {
  const clerkConfigured = useClerkConfigured();

  return (
    <main className="rh-page" data-surface="beta" data-shot="landing-ready">
      {clerkConfigured ? <SignedInRedirect /> : null}
      <section className="rh-bleed" aria-labelledby="landing-title" data-shot="landing-hero" style={{ backgroundImage: "url(/beta/p1-poster.jpg)", backgroundSize: "cover", backgroundPosition: "center" }}>
        <video className="rh-bleed-media" src="/beta/p1-film.mp4" poster="/beta/p1-poster.jpg" muted loop playsInline autoPlay preload="metadata"
          aria-label="Example film: a matte travel mug, made from one product photo" />
        <div className="rh-bleed-shade" aria-hidden="true" />
        <header className="rh-bleed-nav">
          <Link href="/" className="rh-brand"><span className="rh-mark" aria-hidden="true" /><span className="rh-bleed-word">Renderhaus</span></Link>
          <Link href="/sign-in" className="rh-bleed-signin">Sign in</Link>
        </header>
        <aside className="rh-glass rh-price-chip" aria-label="Sample approval line" data-shot="price-chip">
          <span className="rh-sample rh-mono">Sample</span>
          <div className="rh-price-chip-hd"><span>This shot</span><span className="rh-price-ok">Approved</span></div>
          <div className="rh-price-chip-row"><span>Video clip · 5 s</span><b className="rh-num">$0.65</b></div>
          <p>The approval card shows an estimate and a hard cap before anything paid runs.</p>
        </aside>
        <div className="rh-bleed-copy">
          <h1 id="landing-title" className="rh-bleed-title">Describe it.<br />Get the film.</h1>
          <p className="rh-bleed-sub">A chat that plans your video and shows you the price of every step before anything runs.</p>
        </div>
        <div className="rh-bleed-cta" data-shot="landing-cta">
          <Link href="/beta" className="rh-btn rh-btn-primary rh-btn-lg">Use your invite</Link>
          <span className="rh-bleed-offer rh-num">$10 credit · invite only</span>
        </div>
        <div className="rh-scrub" aria-hidden="true">
          <span className="rh-mono rh-num">00:04.6</span>
          <span className="rh-scrub-shots"><i data-done /><i data-cur /><i /><i /></span>
          <span className="rh-mono rh-num">00:09.2</span>
          <span className="rh-scrub-cap">Matte travel mug · shot 2 of 3 · AI-generated</span>
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

      <footer className="rh-foot">
        <span className="rh-brand"><span className="rh-mark" aria-hidden="true" /><span className="rh-wordmark" style={{ fontSize: 20 }}>Renderhaus</span></span>
        <span style={{ marginLeft: 24 }}>© 2026</span>
        <span className="rh-foot-links"><Link href="/sign-in">Sign in</Link></span>
      </footer>
    </main>
  );
}
