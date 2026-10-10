import { ShieldCheck } from "lucide-react";
import { ApprovalCard } from "@/components/rh/ApprovalCard";
import { pendingCard } from "@/lib/rh/fixtures";

export const TRUST_LINE = "The approval card shows an estimate and a hard cap before anything paid runs.";

/** The real approval component, in its pending state, on example figures (labelled as an example). */
export function ExampleCard() {
  return (
    <div className="rh-example">
      <div className="rh-example-live"><span className="rh-dot rh-dot-run" aria-hidden="true" />The agent is asking before it spends. Shot 1 of 2.</div>
      <ApprovalCard model={pendingCard()} actions={{}} className="rh-example-card" />
      <p className="rh-example-note"><span className="rh-sample">Example</span>Figures on this card are an example, not a quote.</p>
      <p className="rh-trust"><ShieldCheck size={14} aria-hidden="true" /><span>{TRUST_LINE}</span></p>
    </div>
  );
}
