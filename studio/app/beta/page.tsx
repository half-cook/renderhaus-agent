import type { Metadata } from "next";
import { BetaSignup } from "@/components/beta/BetaSignup";

export const metadata: Metadata = { title: "Renderhaus beta" };

export default function BetaPage() {
  return <BetaSignup />;
}
