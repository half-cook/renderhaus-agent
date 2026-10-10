"use client";

import Link from "next/link";
import { ArrowRight, Check, FileImage, Film, Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { fetchAccount, fetchStudioCanvas, fetchStudioConversations, type StudioCanvasDocument, type StudioConversation } from "@/lib/api";
import type { StudioAccount } from "@/lib/types";
import type { CanvasNode } from "@/lib/canvas/connection-validation";
import { clipsFromNodes, clipLength } from "@/lib/rh/timeline";
import { safeCopy, toNodeEstimate } from "@/lib/rh/billing";
import { formatCents } from "@/lib/rh/money";
import { AppNav } from "./AppNav";
import { CreditChip } from "./CreditChip";
import { CapRow, Ledger, LedgerRow, LedgerTotal, lineLabel } from "./Ledger";

export function ProjectOverview({ projectId }: { projectId: string }) {
  const query = useSearchParams();
  const [document, setDocument] = useState<StudioCanvasDocument | null>(null);
  const [account, setAccount] = useState<StudioAccount | null>(null);
  const [tasks, setTasks] = useState<StudioConversation[]>([]);
  const [error, setError] = useState(false);
  const [welcome, setWelcome] = useState(query.get("welcome") === "1");
  useEffect(() => {
    let cancelled = false;
    setDocument(null); setError(false);
    void Promise.all([fetchStudioCanvas(projectId), fetchAccount().catch(() => null), fetchStudioConversations(projectId)]).then(([canvas, credit, conversations]) => {
      if (cancelled) return;
      setDocument(canvas.document); setAccount(credit); setTasks(conversations.filter((task) => task.status !== "archived"));
    }).catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [projectId]);
  const grant = account?.beta_credit?.granted_cents;
  useEffect(() => {
    if (welcome && grant != null) toast.success("Phone verified. Your demo project is ready.", { id: `welcome-${projectId}`, duration: 8000 });
  }, [welcome, grant, projectId]);
  const canvas = `/canvas?project=${encodeURIComponent(projectId)}`;
  const nodes = (document?.nodes ?? []) as CanvasNode[];
  const clips = clipsFromNodes(nodes);
  const demo = projectId.startsWith("demo-");
  const title = safeCopy(document?.projectName, "Project");
  const still = nodes.find((node) => node.data.kind === "image");
  const estimate = toNodeEstimate(still?.data.estimate);
  const dismissWelcome = () => {
    setWelcome(false); toast.dismiss(`welcome-${projectId}`);
    const url = new URL(window.location.href); url.searchParams.delete("welcome"); window.history.replaceState(null, "", url);
  };
  return <div className="rh-app rh-project" data-shot={document ? "project-ready" : undefined}>
    <AppNav active="Projects" name={account?.display_name} credit={account ? <CreditChip balanceCents={account.balance_cents} /> : undefined} />
    <main className="rh-project-main" id="main">
      {welcome && grant != null ? <section className="rh-welcome" aria-label="Welcome to Renderhaus">
        <Check size={18} aria-hidden="true" /><div><b>You’re in. {formatCents(grant)} beta credit added.</b><p>Your demo project is ready. Explore, then try a paid step when you’re ready.</p></div>
        <Link href="/home" className="rh-btn rh-btn-sm">Back to home</Link><button type="button" className="rh-btn rh-btn-quiet rh-btn-sm" aria-label="Dismiss welcome" onClick={dismissWelcome}><X size={15} /></button>
      </section> : null}
      <nav className="rh-project-crumb" aria-label="Breadcrumb"><Link href="/home">Home</Link><span aria-hidden="true">/</span><Link href="/home#projects">Projects</Link><span aria-hidden="true">/</span><span aria-current="page">{title}</span></nav>
      {error ? <p role="alert">Could not load this project. <Link href="/home">Back to home</Link></p> : !document ? <p role="status" className="rh-fg3">Loading project…</p> : <>
        <header className="rh-project-head"><div><div className="rh-project-title"><h1 className="rh-h1">{title}</h1>{demo ? <span className="rh-chip rh-chip-mono">DEMO</span> : null}</div><p className="rh-fg2">{demo ? "A product film to explore. Every shot is included; your edits are yours." : "Your storyboard, tasks and files in one place."}</p></div><div className="rh-project-actions"><Link className="rh-btn rh-btn-solid" href={`${canvas}&workspace=timeline`}><Film size={14} aria-hidden="true" />Open timeline</Link><Link className="rh-btn" href={`${canvas}&workspace=agent`}><Sparkles size={14} aria-hidden="true" />Open agent</Link></div></header>
        {demo ? <section className="rh-tour" aria-labelledby="tour-title"><div><h2 id="tour-title" className="rh-eyebrow">Guided tour · step 2 of 3</h2><ol className="rh-tour-steps"><li data-done="true"><Check size={12} aria-hidden="true" />Explore the demo</li><li aria-current="step"><span>2</span>Try one paid step</li><li><span>3</span>Watch the price card</li></ol><h3 className="rh-h3">Try one paid step</h3><p className="rh-fg2">Ask the agent to regenerate the product still. Review its estimate and hard cap before approving.</p><Link className="rh-btn rh-btn-primary" href={`${canvas}&workspace=agent`}>Open agent{estimate ? ` · est. ${formatCents(estimate.estimateCents)}` : ""}<ArrowRight size={14} aria-hidden="true" /></Link><p className="rh-fg3 rh-small">Estimate and hard cap shown on the card first.</p></div><div>{estimate ? <Ledger heading="Estimate">{estimate.lines.map((line, index) => <LedgerRow key={index} label={lineLabel(line, "estimate")} amount={formatCents(line.priceCents)} />)}<LedgerTotal label="Estimated total" amountCents={estimate.estimateCents} /><CapRow capCents={estimate.capCents} /></Ledger> : <p className="rh-tour-note">Opening the agent is free. A current estimate appears when you request the step.</p>}</div></section> : null}
        <div className="rh-project-cols"><div>
          <section aria-labelledby="storyboard-title"><div className="rh-sec-head"><h2 id="storyboard-title" className="rh-eyebrow">Storyboard</h2><Link href={`${canvas}&workspace=canvas`} className="rh-sec-link">Open canvas <ArrowRight size={12} aria-hidden="true" /></Link></div><div className="rh-storyboard">{clips.map((clip) => <Link key={clip.id} href={`${canvas}&workspace=timeline`} className="rh-shot-card"><div className="rh-ticks"><div className="rh-shot-thumb" style={clip.thumbUrl ? { backgroundImage: `url(${clip.thumbUrl})` } : undefined} role="img" aria-label={safeCopy(clip.title, "Video shot")} /><span className="rh-tk" /></div><div className="rh-pcard-row"><b>{safeCopy(clip.title, "Video shot")}</b><span className="rh-mono rh-fg3">{clipLength(clip)} s</span></div><p className="rh-fg3 rh-small">{demo ? "Included in demo" : "On the timeline"}</p></Link>)}</div>{!clips.length ? <p className="rh-fg3 rh-small">No shots on the timeline yet.</p> : null}</section>
          <section className="rh-project-tasks" aria-labelledby="tasks-title"><div className="rh-sec-head"><h2 id="tasks-title" className="rh-eyebrow">Tasks in this project</h2><Link href={`${canvas}&workspace=agent`} className="rh-sec-link">New task <ArrowRight size={12} aria-hidden="true" /></Link></div>{tasks.length ? <ul>{tasks.map((task) => <li key={task.id}><Link href={`${canvas}&workspace=agent&task=${encodeURIComponent(task.id)}`}><Sparkles size={14} aria-hidden="true" /><b>{safeCopy(task.title, "Project task")}</b><ArrowRight size={13} aria-hidden="true" /></Link></li>)}</ul> : <p className="rh-fg3 rh-small">No tasks yet. Open the agent to start one.</p>}</section>
        </div><aside className="rh-project-details"><section><h2 className="rh-eyebrow">Details</h2><dl><div><dt>Project</dt><dd>{demo ? "Demo · your copy" : "Your project"}</dd></div><div><dt>Shots</dt><dd className="rh-mono">{clips.length}</dd></div><div><dt>Canvas</dt><dd><Link href={`${canvas}&workspace=canvas`}>Open canvas</Link></dd></div></dl></section><section><h2 className="rh-eyebrow">Files</h2><ul>{nodes.filter((node) => node.data.output || node.data.config.thumbnail_url).map((node) => <li key={node.id}>{node.data.kind === "image" ? <FileImage size={14} aria-hidden="true" /> : <Film size={14} aria-hidden="true" />}<span>{safeCopy(node.data.title, "Project media")}</span></li>)}</ul></section></aside></div>
      </>}
    </main>
  </div>;
}
