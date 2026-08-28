import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Geist, Geist_Mono } from "next/font/google";
import { StudioClerkBootstrap } from "@/components/StudioAuth";
import "./globals.css";

const geist = Geist({
  subsets: ["latin"],
  variable: "--font-geist",
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono",
});

export const metadata: Metadata = {
  title: "Renderhaus",
  description: "An agentic video production canvas.",
};

const THEME_INIT_SCRIPT = `
try {
  var theme = localStorage.getItem("renderhaus.studio.theme");
  if (theme === "light") {
    document.documentElement.setAttribute("data-theme", "light");
  }
} catch (e) {}
`;

export default function RootLayout({ children }: { children: ReactNode }) {
  const publishableKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  return (
    <html lang="en" className={`${geist.variable} ${geistMono.variable}`}>
      <head>
        {/* Runs before paint so a saved light-mode preference doesn't
            flash dark-then-light on load. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>
        <StudioClerkBootstrap publishableKey={publishableKey}>
          {children}
        </StudioClerkBootstrap>
      </body>
    </html>
  );
}
