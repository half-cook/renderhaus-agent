import type { Metadata } from "next";
import { ChangeStatesBoard } from "@/components/changes/ChangeStatesBoard";

export const metadata: Metadata = { title: "Change states · Renderhaus", robots: { index: false, follow: false } };

export default function ChangeStatesPage() {
  return <ChangeStatesBoard />;
}
