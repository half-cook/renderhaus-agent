"use client";

import type { ReactNode } from "react";
import { StudioAppGate, useClerkConfigured } from "@/components/StudioAuth";

export default function AppLayout({ children }: { children: ReactNode }) {
  const clerkConfigured = useClerkConfigured();
  if (!clerkConfigured) {
    // Local dev without Clerk keys stays fully open, same as before this
    // route split.
    return children;
  }
  return <StudioAppGate>{children}</StudioAppGate>;
}
