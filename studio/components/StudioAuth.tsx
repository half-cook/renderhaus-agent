"use client";

import { ClerkProvider, SignInButton, SignUpButton, UserButton, useAuth } from "@clerk/nextjs";
import { createContext, Fragment, useContext, type ReactNode, useEffect, useState } from "react";
import { configureStudioTokenGetter } from "@/lib/authenticated-fetch";
import styles from "./StudioAuth.module.css";

// Clerk's own default theme is a self-contained light/indigo UI that
// ignores the host page's CSS -- left alone, the sign-in/sign-up screens
// and the UserButton/OrganizationSwitcher popovers look like a generic
// SaaS auth widget dropped onto Renderhaus rather than part of it. Every
// color below is one of the studio's own custom properties (globals.css),
// so this automatically follows the light/dark toggle instead of needing
// its own theme switch.
const CLERK_APPEARANCE = {
  variables: {
    colorPrimary: "var(--active)",
    colorBackground: "var(--node)",
    colorInputBackground: "var(--bg)",
    colorInputText: "var(--text)",
    colorText: "var(--text)",
    colorTextSecondary: "var(--muted)",
    colorTextOnPrimaryBackground: "var(--bg)",
    colorDanger: "var(--danger)",
    colorSuccess: "var(--ok)",
    colorWarning: "var(--warn)",
    colorNeutral: "var(--text)",
    colorShimmer: "var(--line)",
    fontFamily: "var(--font-geist), 'Segoe UI', system-ui, sans-serif",
    borderRadius: "8px",
  },
  elements: {
    card: {
      backgroundColor: "var(--node)",
      border: "1px solid var(--line)",
      boxShadow: "none",
      borderRadius: "16px",
    },
    headerTitle: { color: "var(--text)" },
    headerSubtitle: { color: "var(--muted)" },
    socialButtonsBlockButton: {
      backgroundColor: "var(--bg)",
      borderColor: "var(--line)",
      color: "var(--text)",
      "&:hover": { backgroundColor: "var(--line)" },
    },
    dividerLine: { backgroundColor: "var(--line)" },
    dividerText: { color: "var(--muted)" },
    formFieldLabel: { color: "var(--text)" },
    formFieldInput: {
      backgroundColor: "var(--bg)",
      borderColor: "var(--line)",
      color: "var(--text)",
      "&:focus": { borderColor: "var(--active)" },
    },
    formButtonPrimary: {
      backgroundColor: "var(--active)",
      color: "var(--bg)",
      textTransform: "uppercase",
      fontSize: "11px",
      fontWeight: 700,
      letterSpacing: "0.08em",
      "&:hover": { backgroundColor: "var(--active)", opacity: 0.85 },
      "&:focus": { backgroundColor: "var(--active)" },
    },
    footer: { backgroundColor: "transparent" },
    footerActionLink: { color: "var(--selected)" },
    identityPreviewText: { color: "var(--text)" },
    identityPreviewEditButton: { color: "var(--selected)" },
    formResendCodeLink: { color: "var(--selected)" },
    otpCodeFieldInput: { color: "var(--text)", borderColor: "var(--line)" },
    badge: { backgroundColor: "var(--line)", color: "var(--muted)" },
    userButtonPopoverCard: {
      backgroundColor: "var(--node)",
      border: "1px solid var(--line)",
      boxShadow: "none",
    },
    userButtonPopoverActionButtonText: { color: "var(--text)" },
    userButtonPopoverFooter: { display: "none" },
  },
} as const;

// Whether Clerk is actually configured in this environment -- read by any
// route that needs to know before calling Clerk hooks itself, since those
// throw outside a <ClerkProvider> and local dev without Clerk keys is a
// real supported mode (see README's "Clerk authentication" section).
const ClerkConfiguredContext = createContext(false);

export function useClerkConfigured(): boolean {
  return useContext(ClerkConfiguredContext);
}

// The blocking "sign in to continue" gate + account controls. Used only by
// the (app) route group's layout, not at the root -- a public marketing
// page at / needs to render without hitting this wall first.
export function StudioAppGate({ children }: { children: ReactNode }) {
  const { getToken, isLoaded, isSignedIn, userId } = useAuth();
  configureStudioTokenGetter(getToken);

  if (!isLoaded) {
    return <div className="workspace-loading">Loading account</div>;
  }
  if (!isSignedIn) {
    return (
      <main className={`workspace-loading ${styles["studio-sign-in"]}`}>
        <p>Sign in to open your Renderhaus workspace.</p>
        <div className={styles["studio-auth-actions"]}>
          {/* mode="modal" keeps this in-app (styled by CLERK_APPEARANCE
              below) instead of the default behavior of bouncing out to
              Clerk's own hosted, unthemed Account Portal domain. */}
          <SignInButton mode="modal" fallbackRedirectUrl="/dashboard">
            <button className={`${styles["studio-auth-button"]} ${styles.primary}`} type="button">
              Sign in
            </button>
          </SignInButton>
          <SignUpButton mode="modal" fallbackRedirectUrl="/dashboard">
            <button className={styles["studio-auth-button"]} type="button">
              Create account
            </button>
          </SignUpButton>
        </div>
      </main>
    );
  }
  return (
    <Fragment key={userId || "personal"}>
      {children}
      <div className={styles["studio-account-controls"]} aria-label="Account">
        <UserButton />
      </div>
    </Fragment>
  );
}

export function LocalStudioAuth({ children }: { children: ReactNode }) {
  configureStudioTokenGetter(async () => null);
  return children;
}

export function StudioClerkBootstrap({
  children,
  publishableKey,
}: {
  children: ReactNode;
  publishableKey?: string;
}) {
  const [configuration, setConfiguration] = useState<{
    loaded: boolean;
    key?: string;
  }>({ loaded: Boolean(publishableKey), key: publishableKey });

  useEffect(() => {
    if (configuration.loaded) return;
    void fetch("/api/config")
      .then(async (response) => {
        const payload = await response.json();
        const key =
          payload.clerk_enabled && typeof payload.clerk_publishable_key === "string"
            ? payload.clerk_publishable_key
            : undefined;
        setConfiguration({ loaded: true, key });
      })
      .catch(() => setConfiguration({ loaded: true }));
  }, [configuration.loaded]);

  if (!configuration.loaded) {
    return <div className="workspace-loading">Loading workspace</div>;
  }
  if (!configuration.key) {
    return (
      <ClerkConfiguredContext.Provider value={false}>
        <LocalStudioAuth>{children}</LocalStudioAuth>
      </ClerkConfiguredContext.Provider>
    );
  }
  return (
    <ClerkConfiguredContext.Provider value={true}>
      <ClerkProvider publishableKey={configuration.key} dynamic appearance={CLERK_APPEARANCE}>
        {children}
      </ClerkProvider>
    </ClerkConfiguredContext.Provider>
  );
}
