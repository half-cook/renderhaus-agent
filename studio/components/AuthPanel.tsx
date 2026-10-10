"use client";

import { SignIn, SignUp } from "@clerk/nextjs";
import Link from "next/link";
import { useClerkConfigured } from "@/components/StudioAuth";

/**
 * Sign-in / sign-up screen. Clerk's components throw outside a <ClerkProvider>, so they only render
 * when this environment has Clerk keys; otherwise a plain panel explains why (local dev runs open).
 */
export function AuthPanel({ mode }: { mode: "sign-in" | "sign-up" }) {
  const configured = useClerkConfigured();
  return (
    <main className="rh-page rh-auth" data-surface="beta" data-shot="sign-in-ready">
      {configured ? (
        mode === "sign-in" ? <SignIn fallbackRedirectUrl="/home" /> : <SignUp fallbackRedirectUrl="/home" />
      ) : (
        <div className="rh-card rh-auth-card">
          <span className="rh-eyebrow">{mode === "sign-in" ? "Sign in" : "Create account"}</span>
          <h1 className="rh-h1" style={{ fontSize: 34, marginTop: 10 }}>Auth isn’t configured <em>here.</em></h1>
          <p className="rh-fg2" style={{ fontSize: 14, lineHeight: 1.55, margin: "12px 0 20px" }}>
            This environment runs without sign-in, so there is nothing to sign in to. You can go straight to your projects.
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <Link href="/home" className="rh-btn rh-btn-primary rh-btn-lg">Open projects</Link>
            <Link href="/" className="rh-btn rh-btn-lg">Back to home</Link>
          </div>
        </div>
      )}
    </main>
  );
}
