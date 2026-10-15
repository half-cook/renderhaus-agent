"use client";

import Link from "next/link";
import { useState } from "react";
import { ChangeRow } from "./ChangeRow";
import { changesStateVariants } from "@/lib/rh/fixtures";
import { transitionChange } from "@/lib/rh/changes";

export function ChangeStatesBoard() {
  const [fixtures, setFixtures] = useState(changesStateVariants);
  const [notice, setNotice] = useState("Design review. Static previews. Paid controls cannot start a run.");
  return <main className="rh-app rh-change-state-board" data-shot="change-states-ready">
    <header><div><p className="rh-eyebrow">Component · Change row</p><h1 className="rh-h1">Changes, every state</h1></div><Link href="/home" className="rh-brand"><span className="rh-mark" aria-hidden="true" /><span className="rh-wordmark">Renderhaus</span></Link></header>
    <p className="rh-fg2 rh-small" role="status">{notice}</p>
    <div className="rh-change-state-grid">{fixtures.map((fixture, index) => {
      const change = fixture.document.changes.find((item) => item.n === fixture.changeN);
      if (!change) return null;
      return <section key={fixture.id} aria-label={fixture.title}><h2><span className="rh-mono rh-fg3">{String(index + 1).padStart(2, "0")}</span>{fixture.title}</h2>
        <ChangeRow document={fixture.document} change={change} selected={fixture.id === "ready"} approvalEnabled={false}
          onInsert={() => setNotice(`Use “change ${change.n}” in an agent message.`)}
          onAction={(action) => { setFixtures((current) => current.map((item) => item.id === fixture.id ? { ...item, document: transitionChange(item.document, item.changeN, action) } : item)); setNotice(`Change ${change.n} updated in this design review.`); }}
          onCompare={() => setNotice("Open the project’s Changes tab to compare its takes.")}
          onPrice={() => setNotice("A paid step needs its own connected approval. This design review cannot start a run.")}
          onRecheck={() => setNotice("Ask the agent to re-check the change against the current cut.")}
          approvalActions={{ onCancel: () => setNotice("There is no connected run to cancel in this design review."), onStop: () => setNotice("There is no connected run to stop in this design review."), onRaise: () => setNotice("A connected run is needed to raise the cap.") }} />
      </section>;
    })}</div>
  </main>;
}
