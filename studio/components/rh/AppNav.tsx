"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { ThemeToggle } from "@/components/canvas/ThemeToggle";

export function Avatar({ name }: { name?: string }) {
  const initials = (name || "").split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]!.toUpperCase()).join("") || "·";
  return <span className="rh-avatar" role="img" aria-label={name ? `Signed in as ${name}` : "Account"}>{initials}</span>;
}

const LINKS: Array<{ href: string; label: string }> = [
  { href: "/home", label: "Home" },
  { href: "/home#projects", label: "Projects" },
  { href: "/home#library", label: "Library" },
  { href: "/home#credit", label: "Credits" },
];

/** App-surface top bar for the home screen. The canvas has its own header (CanvasHeader). */
export function AppNav({ active = "Home", credit, name }: { active?: string; credit?: ReactNode; name?: string }) {
  return (
    <header className="rh-appnav">
      <Link href="/home" className="rh-brand"><span className="rh-mark" aria-hidden="true" /><span className="rh-wordmark">Renderhaus</span></Link>
      <nav aria-label="Main" className="rh-appnav-links">
        {LINKS.map((link) => (
          <Link key={link.label} href={link.href} aria-current={link.label === active ? "page" : undefined}>{link.label}</Link>
        ))}
      </nav>
      <div className="rh-appnav-right">
        {credit}
        <ThemeToggle />
        <Avatar name={name} />
      </div>
    </header>
  );
}
