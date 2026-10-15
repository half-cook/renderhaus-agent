"use client";

/* Revamp v4 review board (sample data, noindex via /launch-review). Composes the real components
   inside the v4 Studio frame so screens can be checked without a backend. Not a live run. */
import { IntermediateSteps } from "@/components/canvas/AgentDock";
import { ApprovalCard } from "@/components/rh/ApprovalCard";
import { RunReceipt } from "@/components/rh/RunBilling";
import type { AgentProgressEvent, AgentToolEvent } from "@/lib/canvas/types";
import type { ApprovalCardModel, RunReceiptModel } from "@/lib/rh/billing";

const tool = (id: string, label: string, status: string, summary = "", cost?: string): AgentToolEvent & { costLabel?: string } =>
  ({ id, name: id, label, status, summary, arguments: {}, assets: [], costLabel: cost }) as AgentToolEvent & { costLabel?: string };

const STEPS_DONE = [
  tool("t1", "Planned the change", "completed", "", "Free"),
  tool("t2", "Approved by you", "completed", "", "Free"),
  tool("t3", "Shooting a warmer take of Shot 2", "completed", "5 s · 126 frames", "$0.65"),
  tool("t4", "Recording voiceover line 3", "completed", "", "$0.02"),
  tool("t5", "Checking its work", "completed", "", "$0.04"),
  tool("t6", "Putting the cut together", "completed", "", "$0.24"),
];
const STEPS_LIVE = STEPS_DONE.map((step, index) => (
  index < 2 ? step
    : index === 2 ? { ...step, status: "running", summary: "78 / 126 frames" }
    : { ...step, status: "pending", costLabel: undefined }
));
const NO_PROGRESS: AgentProgressEvent[] = [];

const APPROVAL: ApprovalCardModel = {
  id: "v4", status: "pending", title: "Warmer ending", tier: "2 paid · 1 free", specs: [],
  thumbUrl: "/beta/shot-lift.jpg",
  resultThumbUrl: "/beta/shot-lift-warm.jpg",
  lines: [
    { kind: "media", label: "Warmer take of Shot 2", priceCents: 65, basis: "estimate" },
    { kind: "media", label: "Voiceover line 3", priceCents: 2, basis: "estimate" },
    { kind: "media", label: "Trim Shot 2 to 4.2 s", priceCents: 0, basis: "estimate" },
    { kind: "orchestration", label: "Agent orchestration", priceCents: 30, basis: "estimate" },
  ],
  estimateCents: 97, capCents: 150,
};

const RECEIPT: RunReceiptModel = {
  title: "Delivered", finishedLabel: "9.2 s film · today 8:14 PM",
  lines: [
    { kind: "media", label: "Warmer take of Shot 2", priceCents: 65, basis: "fixed" },
    { kind: "media", label: "Voiceover line 3", priceCents: 2, basis: "fixed" },
    { kind: "media", label: "Trim Shot 2", priceCents: 0, basis: "fixed" },
    { kind: "orchestration", label: "Agent orchestration", priceCents: 28, basis: "fixed" },
  ],
  actualCents: 95, estimateCents: 97, capCents: 150, underEstimate: true,
  balanceBeforeCents: 1000, balanceAfterCents: 905, paidSteps: 3, status: "done",
  thumbStrip: ["/beta/still-mug.jpg", "/beta/shot-lift-warm.jpg", "/beta/shot-window.jpg"],
};

function StudioFrame({
  chat, balance = "$8.64", stageTitle = "Warm lift", shot, proposed, shooting,
}: {
  chat: React.ReactNode; balance?: string; stageTitle?: string; shot: string;
  proposed?: boolean; shooting?: { frames: string; shotLabel: string };
}) {
  return (
    <main className="rh-page rh-v4-studio" data-surface="beta" data-shot={shot}>
      <header className="rh-v4-top">
        <span className="rh-brand"><span className="rh-mark" aria-hidden="true" /><span className="rh-v4-project">10 s product film</span></span>
        <span className="rh-v4-credit rh-num">{balance}</span>
        <span className="rh-v4-avatar" aria-hidden="true">SN</span>
      </header>
      <section className="rh-v4-chat" aria-label="Agent conversation">
        <div className="rh-v4-earlier">2 earlier messages</div>
        <div className="rh-v4-bubble">Make the ending warmer and re-record the last line as “carry it anywhere”.</div>
        {chat}
        <div className="rh-v4-composer"><input className="rh-v4-ask" placeholder="Ask for a change" aria-label="Ask for a change" /></div>
      </section>
      <section className="rh-v4-stage" aria-label="Preview">
        <div className="rh-v4-frame" style={{ backgroundImage: `url(${shooting ? "/beta/shot-lift.jpg" : "/beta/shot-lift-warm.jpg"})` }}>
          {proposed ? (
            <aside className="rh-proposed" aria-label="Proposed look">
              <img src="/beta/shot-lift-warm.jpg" alt="" />
              <span>Proposed look</span>
            </aside>
          ) : null}
          {shooting ? (
            <div className="rh-shooting" role="status">
              <span className="rh-shooting-title">Shooting…</span>
              <span className="rh-shooting-meta rh-num">{shooting.shotLabel} · {shooting.frames}</span>
            </div>
          ) : (
            <div className="rh-v4-caption"><span>Shot 2 of 3</span><b>{stageTitle}</b></div>
          )}
          <div className="rh-stage-shade" aria-hidden="true" />
        </div>
        <div className="rh-strip" role="list" aria-label="Timeline">
          {[["/beta/still-mug.jpg","Open",2.2],["/beta/shot-lift-warm.jpg","Warm lift · 4.2 s",3.2],["/beta/shot-window.jpg","Window",1.5]].map(([url,label,flex],i)=>(
            <button key={i} type="button" role="listitem" className="rh-strip-clip" data-sel={i===1||undefined} style={{ flex: `${flex} 1 0`, backgroundImage: `url(${url})`, backgroundSize: "cover", backgroundPosition: "center" }}>
              <span className="rh-strip-label">{label}</span>
            </button>
          ))}
        </div>
      </section>
      <span className="rh-sample rh-mono rh-v4-sample">Sample</span>
    </main>
  );
}

export function LaunchReviewV4({ screen }: { screen: string }) {
  if (screen === "v4-not-now") return (
    <StudioFrame shot="v4-not-now" chat={<>
      <p className="rh-v4-agent">Here’s the plan.</p>
      <p className="rh-paused-line" role="status" data-shot="not-now-paused">Paused · nothing charged · your credit is free to use.</p>
    </>} />
  );
  if (screen === "v4-approval") return (
    <StudioFrame shot="v4-approval" stageTitle="Current take" proposed chat={<>
      <p className="rh-v4-agent">Here’s the plan.</p>
      <ApprovalCard focusOnMount={false} model={APPROVAL} />
    </>} />
  );
  if (screen === "v4-receipt") return (
    <StudioFrame shot="v4-receipt" balance="$9.05" chat={<>
      <p className="rh-v4-agent">All delivered.</p>
      <RunReceipt receipt={RECEIPT} />
    </>} />
  );
  const live = screen === "v4-trace-live" || screen === "v4-trace-expanded-live";
  const expanded = screen === "v4-trace-expanded" || screen === "v4-trace-expanded-live";
  return (
    <StudioFrame
      shot={screen}
      shooting={live ? { frames: "78 of 126 frames", shotLabel: "Shot 2" } : undefined}
      chat={<>
        <p className="rh-v4-agent">{live ? "Working on it. I’ll show you before anything touches your cut." : "Done. Shot 2 has a warmer take and the new line is in. Nothing touches your cut until you accept."}</p>
        <div className="rh-v4-trace-wrap">
          <IntermediateSteps
            defaultOpen={expanded}
            events={live ? STEPS_LIVE : STEPS_DONE}
            progressEvents={NO_PROGRESS}
            status={live ? "running" : "completed"}
            message={live ? "Shooting a warmer take of Shot 2" : ""}
            duration={live ? "0:42" : "1 min 48 s"}
            cost={live ? { cents: 48, capCents: 150, final: false } : { cents: 95, final: true }}
            stepCosts={live || expanded ? (live ? STEPS_LIVE : STEPS_DONE).map((s) => (s as { costLabel?: string }).costLabel) : undefined}
            showStop={live}
            liveFrames={live ? ["/beta/shot-lift.jpg", "/beta/shot-lift-warm.jpg", "/beta/shot-lift-cool.jpg", "/beta/shot-macro.jpg"] : undefined}
          />
        </div>
        {!live ? <span className="rh-v4-needs"><span className="rh-dot" aria-hidden="true" />2 changes need you</span> : null}
      </>}
    />
  );
}
