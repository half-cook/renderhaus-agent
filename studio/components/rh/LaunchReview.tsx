"use client";

import { useSearchParams } from "next/navigation";
import { InviteSignup } from "@/components/beta/InviteSignup";
import { ApprovalCard } from "@/components/rh/ApprovalCard";
import { LaunchReviewV4 } from "@/components/rh/LaunchReviewV4";
import { UploadRow } from "@/components/rh/UploadRow";
import { OUT_OF_CREDIT_FULL, TOPUPS_COMING_SOON } from "@/lib/launch";
import type { ApprovalCardModel } from "@/lib/rh/billing";

const LINES: ApprovalCardModel["lines"] = [
  { kind: "media", label: "Video clip · 5 s", priceCents: 120, basis: "estimate" },
  { kind: "orchestration", label: "Agent orchestration", priceCents: 6, basis: "estimate" },
];
const base: ApprovalCardModel = {
  id: "sample", status: "pending", title: "Shot 1 · push-in on the handle", tier: "Standard quality",
  prompt: "Slow push-in on the handle and the matte texture. Soft morning window light.", specs: ["5 s", "1080p", "16:9"],
  lines: LINES, estimateCents: 126, capCents: 150, stepIndex: 2, stepCount: 4,
};

function Frame({ children, title }: { children: React.ReactNode; title: string }) {
  return (
    <main className="rh-page" data-surface="beta" style={{ padding: 40, minHeight: "100vh" }}>
      <div className="rh-eyebrow" style={{ marginBottom: 16 }}>{title} · sample data</div>
      <div style={{ maxWidth: 460 }}>{children}</div>
    </main>
  );
}

export function LaunchReview() {
  const screen = useSearchParams().get("screen") ?? "49";
  if (screen.startsWith("v4-")) return <LaunchReviewV4 screen={screen} />;
  if (screen === "46") return <InviteSignup initialPhase={{ kind: "welcome", balanceCents: 1000 }} />;
  if (screen === "47") return (
    <Frame title="47 · paused at cap, credit used up">
      <ApprovalCard focusOnMount={false} model={{ ...base, status: "paused_cap", chargedCents: 150, balanceCents: 0, walletTotalCents: 1000 }} />
    </Frame>
  );
  if (screen === "48") return (
    <Frame title="48 · out of credit">
      <section className="rh-betacard" data-low aria-label="Beta credit">
        <div className="rh-betacard-head"><span className="rh-eyebrow">Beta credit</span><span className="rh-chip rh-chip-mono">Invite</span></div>
        <p className="rh-betacard-amt"><b className="rh-mono rh-num">$0.00</b> <span className="rh-fg3">of $10.00</span></p>
        <div className="rh-bar rh-bar-acc"><b style={{ width: "0%" }} /></div>
        <p className="rh-betacard-note">{TOPUPS_COMING_SOON}</p>
      </section>
      <div className="rh-card" style={{ padding: 18, marginTop: 16 }}>
        <p style={{ margin: 0 }}>{OUT_OF_CREDIT_FULL}</p>
        <div className="rh-appr-ft" style={{ padding: "14px 0 0" }}>
          <button type="button" className="rh-btn rh-btn-solid" style={{ flex: 1 }}>Trim</button>
          <button type="button" className="rh-btn">Keep as is</button>
        </div>
        <label className="rh-label" htmlFor="reply" style={{ marginTop: 14, display: "block" }}>Reply to the team</label>
        <textarea id="reply" className="rh-input" rows={3} placeholder="What would you make next?" />
        <p className="rh-fg3" style={{ fontSize: 12 }}>Free edits (trim, reorder, export) still work.</p>
      </div>
    </Frame>
  );
  if (screen === "49") return (
    <Frame title="49 · estimate fits, cap doesn't">
      <ApprovalCard focusOnMount={false} model={{ ...base, balanceCents: 120, lowerCapOptionCents: null, estimateCents: 110, lines: [{ ...LINES[0], priceCents: 104 }, LINES[1]] }} approveEnabled={false} />
    </Frame>
  );
  if (screen === "49b") return (
    <Frame title="49b · estimate doesn't fit">
      <ApprovalCard focusOnMount={false} model={{ ...base, balanceCents: 90, estimateCents: 126, cheaperOption: { label: "Same shot, 3 s instead of 5 s", estimateCents: 78, capCents: 90 } }} approveEnabled={false} />
    </Frame>
  );
  if (screen === "49c") return (
    <Frame title="49 · nothing fits">
      <ApprovalCard focusOnMount={false} model={{ ...base, balanceCents: 20 }} approveEnabled={false} />
    </Frame>
  );
  return (
    <Frame title="50 · upload rows">
      <div style={{ display: "flex", flexDirection: "column", gap: 8, width: 560 }}>
        <UploadRow state={{ kind: "uploading", name: "launch-broll-a.mov", confirmedBytes: 2.98e9, totalBytes: 4.8e9, secondsLeft: 120 }} />
        <UploadRow state={{ kind: "resuming", name: "interview-cam2.mp4", confirmedBytes: 0.8e9, totalBytes: 2.1e9, chunk: 37, chunks: 98 }} />
        <UploadRow state={{ kind: "failed", name: "drone-pass-03.mov", confirmedBytes: 0.71e9, totalBytes: 3.4e9 }} />
        <UploadRow state={{ kind: "waiting", name: "product-closeups.mp4", totalBytes: 1.2e9 }} />
        <UploadRow state={{ kind: "done", name: "logo-sting.mov", totalBytes: 0.24e9 }} />
      </div>
    </Frame>
  );
}
