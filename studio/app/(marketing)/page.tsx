"use client";

import { useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { LogoMark } from "@/components/Logo";
import { LandingDemo } from "@/components/landing/LandingDemo";
import { useClerkConfigured } from "@/components/StudioAuth";
import styles from "./page.module.css";

function SignedInRedirect() {
  const { isLoaded, isSignedIn } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isLoaded && isSignedIn) {
      router.replace("/dashboard");
    }
  }, [isLoaded, isSignedIn, router]);

  return null;
}

export default function MarketingPage() {
  const clerkConfigured = useClerkConfigured();
  const primaryHref = clerkConfigured ? "/sign-up" : "/dashboard";

  return (
    <main className={styles["landing"]}>
      {clerkConfigured ? <SignedInRedirect /> : null}
      <header className={styles["landing-header"]}>
        <span className={styles["landing-mark"]}>
          <LogoMark />
          Renderhaus
        </span>
        {clerkConfigured ? (
          <Link href="/sign-in" className="text-btn">
            Sign in
          </Link>
        ) : null}
      </header>
      <div className={styles["landing-eyebrow"]}>
        <div>
          <h1>Build on one canvas</h1>
          <p>Wire up image, video, voice, and music, and watch it come together — try it below.</p>
        </div>
        <Link href={primaryHref} className={`${styles["landing-cta"]} ${styles["landing-cta-primary"]}`}>
          Start creating
        </Link>
      </div>
      <LandingDemo />
    </main>
  );
}
