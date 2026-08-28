"use client";

import {
  ClerkProvider,
  OrganizationSwitcher,
  SignInButton,
  UserButton,
  useAuth,
} from "@clerk/nextjs";
import { Fragment, type ReactNode, useEffect, useState } from "react";
import { configureStudioTokenGetter } from "@/lib/authenticated-fetch";

export function StudioAuth({ children }: { children: ReactNode }) {
  const { getToken, isLoaded, isSignedIn, orgId, userId } = useAuth();
  configureStudioTokenGetter(getToken);

  if (!isLoaded) {
    return <div className="workspace-loading">Loading account</div>;
  }
  if (!isSignedIn) {
    return (
      <main className="workspace-loading studio-sign-in">
        <p>Sign in to open your Renderhaus workspace.</p>
        <SignInButton mode="modal">
          <button className="send-btn" type="button">
            Sign in
          </button>
        </SignInButton>
      </main>
    );
  }
  return (
    <Fragment key={orgId || userId || "personal"}>
      {children}
      <div className="studio-account-controls" aria-label="Account and workspace">
        <OrganizationSwitcher />
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
    return <LocalStudioAuth>{children}</LocalStudioAuth>;
  }
  return (
    <ClerkProvider publishableKey={configuration.key} dynamic>
      <StudioAuth>{children}</StudioAuth>
    </ClerkProvider>
  );
}
