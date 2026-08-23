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

export default function RootLayout({ children }: { children: ReactNode }) {
  const publishableKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  return (
    <html lang="en" className={`${geist.variable} ${geistMono.variable}`}>
      <body>
        <StudioClerkBootstrap publishableKey={publishableKey}>
          {children}
        </StudioClerkBootstrap>
      </body>
    </html>
  );
}
