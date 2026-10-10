import type { Metadata } from "next";
import Link from "next/link";
import { ApprovalCard } from "@/components/rh/ApprovalCard";
import { approvedCard, doneCard, failedCard, lowCreditCard, pausedCard, pendingCard, runningCard } from "@/lib/rh/fixtures";

export const metadata: Metadata = { title: "Approval states · Renderhaus", robots: { index: false, follow: false } };

const states = [
  ["Pending", pendingCard, "Review the estimate and hard cap before any paid work starts."],
  ["Approved", approvedCard, "The cap is reserved while the step waits for a slot."],
  ["Running", runningCard, "The hold and spend so far stay visible."],
  ["Done", doneCard, "The receipt shows the final charge and remaining balance."],
  ["Failed", failedCard, "Retry starts with a fresh estimate."],
  ["Cap reached", pausedCard, "Raise the cap or stop with what was made."],
  ["Low credit", lowCreditCard, "Add credit or use the lower cap offered by the server."],
] as const;

export default function ApprovalStatesPage() {
  return <main className="rh-app rh-state-board" data-shot="approval-states-ready">
    <header><div><p className="rh-eyebrow">Component · Approval card</p><h1 className="rh-h1">Every state, one estimate, one cap</h1></div><Link href="/home" className="rh-brand"><span className="rh-mark" aria-hidden="true" /><span className="rh-wordmark">Renderhaus</span></Link></header>
    <p className="rh-fg3 rh-small">Sample data for design review. These controls do not start a run.</p>
    <div className="rh-state-grid">{states.map(([title, fixture, note], index) => <section key={title}>
      <h2 className="rh-h3"><span className="rh-mono rh-fg3">{String(index + 1).padStart(2, "0")}</span>{title}<span className="rh-chip rh-chip-mono">Sample</span></h2>
      <ApprovalCard model={fixture()} />
      <p className="rh-fg2 rh-small">{note}</p>
    </section>)}</div>
  </main>;
}
