import type { Metadata } from "next";
import { InviteSignup } from "@/components/beta/InviteSignup";

export const metadata: Metadata = { title: "Renderhaus beta · invite only" };

export default function BetaPage() {
  return <InviteSignup />;
}
