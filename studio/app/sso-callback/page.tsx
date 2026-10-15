"use client";

import { AuthenticateWithRedirectCallback } from "@clerk/nextjs";
import { useClerkConfigured } from "@/components/StudioAuth";

export default function SsoCallbackPage() {
  const configured = useClerkConfigured();
  return (
    <main className="rh-page rh-signup" data-surface="beta">
      <p className="rh-fg3" role="status" style={{ padding: 32 }}>Signing you in…</p>
      {configured ? <AuthenticateWithRedirectCallback /> : null}
    </main>
  );
}
