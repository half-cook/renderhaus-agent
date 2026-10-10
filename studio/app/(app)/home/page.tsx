"use client";

import { ArrowRight, Check, Plus, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useUser } from "@clerk/nextjs";
import { AppNav } from "@/components/rh/AppNav";
import { CreditChip } from "@/components/rh/CreditChip";
import { useClerkConfigured } from "@/components/StudioAuth";
import { createStudioProject, fetchAccount, fetchStudioProjects, type StudioProject } from "@/lib/api";
import { creditState } from "@/lib/rh/credit-store";
import { formatCents } from "@/lib/rh/money";
import { safeCopy } from "@/lib/rh/billing";
import type { StudioAccount } from "@/lib/types";

const DEMO_THUMBS = ["/beta/still-mug-wide.jpg", "/beta/shot-macro.jpg", "/beta/shot-lift.jpg", "/beta/shot-window.jpg"];

function isDemo(project: StudioProject): boolean {
  return project.id.startsWith("demo-");
}

function greeting(now: Date): string {
  const hour = now.getHours();
  return hour < 5 ? "Good evening" : hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

function ago(unixSeconds?: number): string {
  if (!unixSeconds) return "";
  const minutes = Math.max(0, Math.floor((Date.now() - unixSeconds * 1000) / 60000));
  if (minutes < 2) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

function clock(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

/** Ledger reasons arrive as snake_case ids. Show a plain label; never an id and never a provider. */
function reasonLabel(reason: string, delta: number): string {
  if (/beta/.test(reason)) return "Beta credit · wave 1";
  if (/top.?up|purchase/.test(reason)) return "Credit added";
  if (/refund|release/.test(reason)) return "Released hold";
  if (/image|still/.test(reason)) return "Product still · Studio Image";
  if (/video|clip|shot/.test(reason)) return "Video clip · Studio Video";
  if (/orchestrat|agent/.test(reason)) return "Agent orchestration";
  return delta < 0 ? "Studio step" : "Credit added";
}

function ClerkName({ onName }: { onName: (name: string) => void }) {
  const { user } = useUser();
  const name = user?.firstName || user?.fullName || "";
  useEffect(() => { if (name) onName(name); }, [name, onName]);
  return null;
}

function ProjectCard({ project, onOpen }: { project: StudioProject; onOpen: () => void }) {
  const demo = isDemo(project);
  const thumbs = project.thumbs?.length ? project.thumbs : demo ? DEMO_THUMBS : [];
  const meta = demo ? `Demo project · edited ${ago(project.updated_at)}` : project.file_count ? `${project.file_count} files · edited ${ago(project.updated_at)}` : `${project.updated_at ? "Edited " + ago(project.updated_at) : "New"}`;
  return (
    <button type="button" className="rh-pcard" onClick={onOpen} aria-label={`Open ${project.name}`}>
      {thumbs.length ? (
        <span className="rh-mosaic" aria-hidden="true">
          {thumbs.slice(0, 3).map((src, index) => <span key={src + index} style={{ backgroundImage: `url(${src})` }} />)}
        </span>
      ) : (
        <span className="rh-mosaic rh-mosaic-empty" aria-hidden="true"><Plus size={18} /></span>
      )}
      <span className="rh-pcard-row">
        <b>{project.name}</b>
        {demo ? <span className="rh-chip rh-chip-mono">DEMO</span> : null}
      </span>
      <span className="rh-pcard-meta">{meta}</span>
    </button>
  );
}

export default function HomePage() {
  const router = useRouter();
  const clerkConfigured = useClerkConfigured();
  const [account, setAccount] = useState<StudioAccount | null | undefined>(undefined);
  const [projects, setProjects] = useState<StudioProject[] | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void fetchAccount().then((data) => { if (!cancelled) setAccount(data); }).catch(() => { if (!cancelled) setAccount(null); });
    void fetchStudioProjects().then((items) => { if (!cancelled) setProjects(items); }).catch(() => { if (!cancelled) { setProjects([]); setError("Could not load your projects."); } });
    return () => { cancelled = true; };
  }, []);

  const displayName = name || account?.display_name || "";
  const open = (id: string) => router.push(`/canvas?project=${encodeURIComponent(id)}`);
  const newProject = async () => {
    setCreating(true);
    setError(null);
    try { open((await createStudioProject("Untitled")).id); } catch { setError("Could not create the project."); setCreating(false); }
  };

  const today = new Date();
  const dateLine = today.toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" }).replace(",", " ·").toUpperCase();
  const ledger = account?.recent_ledger ?? [];
  const lastCharge = ledger.find((entry) => entry.delta < 0);
  const hasDemo = (projects ?? []).some(isDemo);
  const checklist = useMemo(() => [
    { title: "Open the demo project", body: "Look around the storyboard and timeline.", done: hasDemo },
    { title: "Try one paid step", body: "You'll see the estimate and the hard cap first.", done: Boolean(lastCharge) },
    { title: "Watch the price card", body: "Approve it, or reject it. Nothing runs without you.", done: false },
  ], [hasDemo, lastCharge]);
  const currentStep = checklist.findIndex((step) => !step.done);
  const granted = account?.beta_credit?.granted_cents ?? 0;
  const spent = account?.beta_credit?.spent_cents ?? 0;
  const state = account ? creditState(account.balance_cents, null, 0) : "normal";

  return (
    <div className="rh-app rh-home" data-shot="home-ready">
      {clerkConfigured ? <ClerkName onName={setName} /> : null}
      <AppNav credit={account ? <CreditChip balanceCents={account.balance_cents} state={state} /> : null} name={displayName} />
      <main className="rh-home-main" id="main">
        <div className="rh-home-head">
          <div>
            <p className="rh-eyebrow">{dateLine}</p>
            <h1 className="rh-h1 rh-home-title">{greeting(today)}{displayName ? <>, <em>{displayName}.</em></> : "."}</h1>
          </div>
          <button type="button" className="rh-btn rh-btn-primary rh-btn-lg" onClick={() => void newProject()} disabled={creating}><Plus size={15} aria-hidden="true" />{creating ? "Creating…" : "New project"}</button>
        </div>

        <div className="rh-home-cols">
          <div className="rh-home-left">
            <section aria-labelledby="continue-h" id="projects">
              <div className="rh-sec-head"><h2 className="rh-eyebrow" id="continue-h">Continue</h2><Link href="/home#projects" className="rh-sec-link">All projects <ArrowRight size={12} aria-hidden="true" /></Link></div>
              {projects === null ? <p className="rh-fg3 rh-small">Loading projects…</p> : projects.length === 0 ? (
                <p className="rh-fg3 rh-small">No projects yet. Start one with the button above.</p>
              ) : (
                <div className="rh-pgrid">
                  {projects.slice(0, 3).map((project) => <ProjectCard key={project.id} project={project} onOpen={() => open(project.id)} />)}
                </div>
              )}
              {error ? <p className="rh-err" role="alert">{error}</p> : null}
            </section>

            <section className="rh-askbar" aria-label="Start a task with the agent">
              <Sparkles size={16} className="rh-ember" aria-hidden="true" />
              <div><b>Start a task with the agent</b><span>Describe the video. You&apos;ll see every price before it runs.</span></div>
              <button type="button" className="rh-btn" onClick={() => { const first = projects?.find(isDemo) ?? projects?.[0]; if (first) router.push(`/canvas?project=${encodeURIComponent(first.id)}&workspace=agent`); else void newProject(); }}>Open agent <ArrowRight size={13} aria-hidden="true" /></button>
            </section>
          </div>

          <aside className="rh-home-right">
            <section aria-labelledby="credit-h" id="credit">
              <h2 className="rh-eyebrow" id="credit-h">Credit</h2>
              <div className="rh-card rh-credit-card">
                {account === undefined ? <p className="rh-fg3 rh-small">Loading…</p> : account === null ? <p className="rh-fg3 rh-small">Balance unavailable.</p> : (
                  <>
                    <p className="rh-credit-big"><span className="rh-mono rh-num rh-money">{formatCents(account.balance_cents)}</span>{granted ? <span className="rh-fg3"> of {formatCents(granted)} beta credit</span> : null}</p>
                    {granted ? <div className="rh-bar rh-bar-money" role="img" aria-label={`${formatCents(spent)} of ${formatCents(granted)} used`}><b style={{ width: `${Math.min(100, Math.max(0, (account.balance_cents / granted) * 100))}%` }} /></div> : null}
                    <ul className="rh-ledger-list">
                      {ledger.slice(0, 2).map((entry) => (
                        <li key={entry.id}>
                          <span><b>{safeCopy(reasonLabel(entry.reason, entry.delta), "Studio step")}</b><i>{`Today ${clock(entry.created_at)}`}</i></span>
                          <span className={`rh-mono rh-num ${entry.delta < 0 ? "" : "rh-ok-text"}`}>{entry.delta < 0 ? "−" : "+"}{formatCents(Math.abs(entry.delta))}</span>
                        </li>
                      ))}
                      {ledger.length === 0 ? <li><span className="rh-fg3">No activity yet.</span></li> : null}
                    </ul>
                  </>
                )}
              </div>
            </section>
            <section aria-labelledby="start-h">
              <h2 className="rh-eyebrow" id="start-h">Start here</h2>
              <ol className="rh-card rh-checklist">
                {checklist.map((step, index) => (
                  <li key={step.title} data-state={step.done ? "done" : index === currentStep ? "current" : "todo"}>
                    <span className="rh-check" aria-hidden="true">{step.done ? <Check size={12} /> : null}</span>
                    <span><b>{step.title}</b><i>{step.body}</i></span>
                    <span className="rh-sr-only">{step.done ? "Done" : index === currentStep ? "Next" : "Not started"}</span>
                  </li>
                ))}
              </ol>
            </section>
          </aside>
        </div>

        {hasDemo ? (
          <section aria-labelledby="recent-h" id="library" className="rh-recent">
            <div className="rh-sec-head"><h2 className="rh-eyebrow" id="recent-h">Recent outputs</h2><span className="rh-fg3 rh-small">Last 24 hours</span></div>
            <ul className="rh-recent-grid">
              {[
                { title: lastCharge ? "Product still" : "Matte mug · wide", src: DEMO_THUMBS[0]!, meta: lastCharge ? clock(lastCharge.created_at) : "Demo project", price: lastCharge ? formatCents(Math.abs(lastCharge.delta)) : "demo" },
                { title: "Shot 1 · macro", src: DEMO_THUMBS[1]!, meta: "included", price: "demo" },
                { title: "Shot 2 · lift", src: DEMO_THUMBS[2]!, meta: "included", price: "demo" },
                { title: "Window tilt", src: DEMO_THUMBS[3]!, meta: "included", price: "demo" },
              ].map((item) => (
                <li key={item.title}>
                  <span className="rh-recent-img" style={{ backgroundImage: `url(${item.src})` }} role="img" aria-label={item.title} />
                  <span className="rh-pcard-row"><b>{item.title}</b><span className="rh-mono rh-num rh-money">{item.price}</span></span>
                  <span className="rh-pcard-meta">{item.meta}</span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </main>
    </div>
  );
}
