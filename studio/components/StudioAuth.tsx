"use client";

import { ClerkProvider, SignInButton, SignUpButton, UserButton, useAuth, useUser } from "@clerk/nextjs";
import { createContext, Fragment, useContext, type ReactNode, useEffect, useState } from "react";
import { configureStudioTokenGetter } from "@/lib/authenticated-fetch";
import styles from "./StudioAuth.module.css";

// Single source of truth for the UserButton avatar's size -- pinned
// explicitly below (elements.userButtonAvatarBox) rather than left to
// Clerk's own default, since UserAvatarButton's default-avatar overlay
// has to match it exactly and can't read it back out of Clerk itself.
const USER_AVATAR_SIZE = 32;

// Clerk's own default theme is a self-contained light/indigo UI that
// ignores the host page's CSS -- left alone, the sign-in/sign-up screens
// and the UserButton/OrganizationSwitcher popovers look like a generic
// SaaS auth widget dropped onto Renderhaus rather than part of it. Every
// color below is one of the studio's own custom properties (globals.css),
// so this automatically follows the light/dark toggle instead of needing
// its own theme switch.
const CLERK_APPEARANCE = {
  // v4 tokens (globals.css --rh-*). The "Secured by Clerk" footer stays: hiding it
  // requires a paid Clerk plan, so we only restyle it to sit quietly.
  variables: {
    colorPrimary: "var(--rh-accent)",
    colorBackground: "var(--rh-card)",
    colorInputBackground: "var(--rh-surface)",
    colorInputText: "var(--rh-fg)",
    colorText: "var(--rh-fg)",
    colorTextSecondary: "var(--rh-fg-2)",
    colorTextOnPrimaryBackground: "var(--rh-on-accent)",
    colorDanger: "var(--rh-danger)",
    colorSuccess: "var(--rh-ok)",
    colorWarning: "var(--rh-money)",
    colorNeutral: "var(--rh-fg)",
    colorShimmer: "var(--rh-line)",
    fontFamily: "var(--font-geist), 'Segoe UI', system-ui, sans-serif",
    fontSize: "14px",
    borderRadius: "10px",
  },
  elements: {
    rootBox: { width: "100%", maxWidth: "400px" },
    cardBox: { borderRadius: "16px", border: "1px solid var(--rh-line)", boxShadow: "var(--rh-shadow-pop)", width: "100%" },
    card: {
      backgroundColor: "var(--rh-card)",
      border: "none",
      boxShadow: "var(--rh-inset)",
      borderRadius: "16px 16px 0 0",
      padding: "32px 28px 24px",
    },
    headerTitle: {
      color: "var(--rh-fg)",
      fontFamily: "var(--font-instrument-serif), 'Instrument Serif', serif",
      fontWeight: 400,
      fontSize: "30px",
      letterSpacing: "-0.01em",
    },
    headerSubtitle: { color: "var(--rh-fg-2)", fontSize: "13px" },
    socialButtonsBlockButton: {
      backgroundColor: "var(--rh-surface)",
      borderColor: "var(--rh-line)",
      color: "var(--rh-fg)",
      borderRadius: "999px",
      height: "40px",
      "&:hover": { backgroundColor: "var(--rh-raised)", borderColor: "var(--rh-line-strong)" },
    },
    dividerLine: { backgroundColor: "var(--rh-line)" },
    dividerText: { color: "var(--rh-fg-3)", fontFamily: "var(--font-geist-mono), monospace", fontSize: "11px", textTransform: "uppercase" },
    formFieldLabel: { color: "var(--rh-fg-2)", fontSize: "12px", fontWeight: 500 },
    formFieldInput: {
      backgroundColor: "var(--rh-surface)",
      borderColor: "var(--rh-line)",
      color: "var(--rh-fg)",
      borderRadius: "10px",
      height: "40px",
      "&:focus": { borderColor: "var(--rh-accent)", boxShadow: "0 0 0 3px var(--rh-accent-soft)" },
    },
    formButtonPrimary: {
      backgroundColor: "var(--rh-accent)",
      color: "var(--rh-on-accent)",
      borderRadius: "999px",
      height: "40px",
      fontSize: "13px",
      fontWeight: 600,
      textTransform: "none",
      boxShadow: "none",
      "&:hover": { backgroundColor: "var(--rh-accent-hover)" },
      "&:focus": { backgroundColor: "var(--rh-accent)" },
    },
    footer: { background: "var(--rh-surface)", borderTop: "1px solid var(--rh-line)", borderRadius: "0 0 16px 16px" },
    footerAction: { color: "var(--rh-fg-2)" },
    footerActionText: { color: "var(--rh-fg-2)" },
    footerActionLink: { color: "var(--rh-accent-text)", fontWeight: 500 },
    identityPreviewText: { color: "var(--rh-fg)" },
    identityPreviewEditButton: { color: "var(--rh-accent-text)" },
    formResendCodeLink: { color: "var(--rh-accent-text)" },
    otpCodeFieldInput: { color: "var(--rh-fg)", borderColor: "var(--rh-line)", borderRadius: "10px" },
    formFieldErrorText: { color: "var(--rh-danger)" },
    alert: { borderRadius: "10px", borderColor: "var(--rh-line)" },
    badge: { backgroundColor: "var(--rh-raised)", color: "var(--rh-fg-2)" },
    userButtonPopoverCard: {
      backgroundColor: "var(--rh-card)",
      border: "1px solid var(--rh-line)",
      borderRadius: "12px",
      boxShadow: "var(--rh-shadow-pop)",
    },
    userButtonPopoverActionButtonText: { color: "var(--rh-fg)" },
    userButtonPopoverFooter: { display: "none" },
    userButtonAvatarBox: { width: USER_AVATAR_SIZE, height: USER_AVATAR_SIZE },
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

// Clerk has no appearance hook for the fallback image a UserButton shows
// when the account has no photo (no upload, no OAuth picture) -- it's
// baked into the trigger's own rendering, not a swappable slot. Overlaying
// our own image on top (pointer-events: none, so clicks fall through to
// Clerk's real button underneath) gets the same visual result without
// reimplementing the popover's manage-account/sign-out menu ourselves.
function UserAvatarButton() {
  const { user } = useUser();
  const showDefaultAvatar = Boolean(user) && !user!.hasImage;
  return (
    <span
      style={{ position: "relative", display: "inline-flex", width: USER_AVATAR_SIZE, height: USER_AVATAR_SIZE }}
    >
      <UserButton />
      {showDefaultAvatar ? (
        <img
          src="/default-avatar.png"
          alt=""
          aria-hidden="true"
          style={{
            position: "absolute",
            inset: 0,
            width: USER_AVATAR_SIZE,
            height: USER_AVATAR_SIZE,
            borderRadius: "50%",
            pointerEvents: "none",
          }}
        />
      ) : null}
    </span>
  );
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
          <SignInButton mode="modal" fallbackRedirectUrl="/home">
            <button className={`${styles["studio-auth-button"]} ${styles.primary}`} type="button">
              Sign in
            </button>
          </SignInButton>
          <SignUpButton mode="modal" fallbackRedirectUrl="/home">
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
        <UserAvatarButton />
      </div>
    </Fragment>
  );
}

function LocalStudioAuth({ children }: { children: ReactNode }) {
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
