"use client";

import { useReactFlow } from "@xyflow/react";
import {
  Archive,
  BookmarkCheck,
  Captions,
  Clapperboard,
  FileText,
  Layers,
  Clock3,
  RotateCcw,
  Square,
  AtSign,
  Check,
  ChevronRight,
  CircleAlert,
  Download,
  LoaderCircle,
  Paperclip,
  Pencil,
  Plus,
  Send,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AGENT_PROMPT_MAX_CHARS,
  answerAgentCap,
  decideAgentApproval,
  resumeAgentRun,
  stopAgentRun,
  submitAgentPrompt,
  type AgentApprovalRequest,
  type AgentProgress,
  type StudioExecution,
} from "@/lib/api";
import { useCanvasStore } from "@/lib/canvas/store";
import { useChangesStore } from "@/lib/rh/changes-store";
import { ChangesetCard } from "@/components/changes/ChangesetCard";
import type { AgentProgressEvent, AgentToolEvent } from "@/lib/canvas/types";
import type { StudioAsset } from "@/lib/types";
import { AssetDownloadLink, AssetMedia } from "./AssetMedia";
import { ApprovalCard } from "@/components/rh/ApprovalCard";
import { RunReceipt } from "@/components/rh/RunBilling";
import { approvalCardModel, visibleParameters } from "@/lib/rh/approval-model";
import { toRunReceiptModel, toApprovalCardModel } from "@/lib/rh/billing";
import { useCreditContext } from "@/lib/rh/credit-store";
import { RH_ADD_CREDIT_EVENT } from "@/lib/rh/events";

type LiveRun = {
  prompt: string;
  progress: AgentProgress;
};

function normalizedStatus(status: string): "running" | "completed" | "failed" | "incomplete" {
  const value = status.toLowerCase();
  if (["incomplete", "not_run", "rejected"].includes(value)) return "incomplete";
  if (["failed", "error", "cancelled", "canceled"].includes(value)) return "failed";
  if (["queued", "running", "pending", "awaiting_approval"].includes(value)) return "running";
  return "completed";
}

function runDuration(execution: StudioExecution): string | null {
  if (!execution.createdAt || !execution.updatedAt) return null;
  const seconds = Math.max(1, execution.updatedAt - execution.createdAt);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function runTime(timestamp?: number): string | null {
  if (!timestamp) return null;
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(timestamp * 1000);
}

function isFollowUpToolEvent(event: AgentToolEvent): boolean {
  const name = event.name.toLowerCase();
  return (
    name.includes("get_video_task") ||
    name.includes("get_runway_task") ||
    name.includes("query_music_task") ||
    name.includes("get_render_progress") ||
    name.includes("poll")
  );
}

function sourceEventForAsset(
  execution: StudioExecution,
  asset: StudioAsset,
): AgentToolEvent | undefined {
  const eventIndex = execution.toolEvents.findIndex((event) =>
    event.assets.some((candidate) => candidate.versionId === asset.versionId),
  );
  const assetEvent = execution.toolEvents[eventIndex];
  if (!assetEvent || !isFollowUpToolEvent(assetEvent)) return assetEvent;

  const earlier = execution.toolEvents.slice(0, eventIndex).reverse();
  if (assetEvent.providerJobId) {
    const matchingJob = earlier.find(
      (event) =>
        !isFollowUpToolEvent(event) && event.providerJobId === assetEvent.providerJobId,
    );
    if (matchingJob) return matchingJob;
  }
  return earlier.find(
    (event) => !isFollowUpToolEvent(event) && event.provider === assetEvent.provider,
  ) || assetEvent;
}

function StepIcon({ status }: { status: string }) {
  const state = normalizedStatus(status);
  if (state === "running") return <LoaderCircle className="spin" size={14} />;
  if (state === "failed") return <CircleAlert size={14} />;
  if (state === "incomplete") return <Clock3 size={14} />;
  return <Check size={14} />;
}

function IntermediateSteps({
  events,
  progressEvents,
  status,
  message,
  duration,
  recoveryAvailable = false,
}: {
  events: AgentToolEvent[];
  progressEvents: AgentProgressEvent[];
  status: string;
  message: string;
  duration?: string | null;
  recoveryAvailable?: boolean;
}) {
  const state = normalizedStatus(status);
  const visible = progressEvents.filter((event) =>
    ["MODEL_UPDATE", "CONTEXT_COMPACTION"].includes(event.type),
  );
  const steps = [
    ...visible.map((event) => ({id: event.id, title: event.title, message: event.message,
      status: event.status, kind: "Update"})),
    ...events.map((event) => ({id: event.id, title: event.label, message: event.summary,
      status: state !== "running" && normalizedStatus(event.status) === "running" ? "incomplete" : event.status,
      kind: event.status === "awaiting_approval" ? "Approval" : "Tool"})),
  ];
  const currentWait = progressEvents.filter((event) => event.type === "MEDIA_WAIT" && event.status === "running").at(-1);
  const currentUpdate = progressEvents.filter((event) => event.type === "MODEL_UPDATE").at(-1);
  const label = status === "awaiting_approval" ? "Your approval is needed"
    : state === "running" ? currentWait?.message || currentUpdate?.message || message || "Starting…"
    : state === "incomplete" ? `Export incomplete${recoveryAvailable ? " · progress saved" : ""}`
    : state === "failed" ? (recoveryAvailable ? "Stopped · progress saved" : "Run failed")
    : `Completed${duration ? ` in ${duration}` : ""}`;

  return (
    <div className={`agent-progress-group ${state}`}>
      <div className="agent-run-status" role="status"><StepIcon status={status} /><span>{label}</span></div>
    <details>
      <summary>
        <span className="agent-progress-leading">
          <span>{events.length} tool {events.length === 1 ? "step" : "steps"} · Updates & history</span>
        </span>
        {steps.length ? <ChevronRight className="agent-progress-chevron" size={14} /> : null}
      </summary>
      {steps.length ? (
        <ol className="agent-step-list">
          {steps.map((step) => (
            <li className={normalizedStatus(step.status)} key={step.id}>
              <span className="agent-step-icon"><StepIcon status={step.status} /></span>
              <span>
                <em>{step.kind}</em>
                <strong>{step.title}</strong>
                {step.message ? <small>{step.message}</small> : null}
              </span>
            </li>
          ))}
        </ol>
      ) : null}
    </details>
    </div>
  );
}

function ApprovalCards({
  approvals,
  onDecision,
  busyCallId,
  active,
  disabled,
}: {
  approvals: AgentApprovalRequest[];
  onDecision: (approval: AgentApprovalRequest, decision: "approve" | "reject", capCents?: number) => void;
  busyCallId: string | null;
  active: boolean;
  disabled: boolean;
}) {
  if (!approvals.length) return null;
  return (
    <div className="agent-approvals" aria-label="Tool approvals">
      {approvals.map((approval) => {
        const model = approvalCardModel(approval);
        if (model && active && approval.decision !== "reject") {
          return <PricedApproval key={approval.callId} approval={approval} model={model} busy={disabled || busyCallId !== null} onDecision={onDecision} />;
        }
        return approval.decision || !active ? <details className="agent-approval-record" key={approval.callId}>
          <summary>{approval.decision === "approve" ? "Approved" : approval.decision === "reject" ? "Rejected" : "Not run · closed"} · {approval.label}</summary>
          <ApprovalSummary approval={approval}/>
          <div className="agent-approval-details"><Parameters args={approval.arguments} bare /></div>
        </details> :
        <article className="agent-approval" key={approval.callId}>
          <header>
            <span><ShieldCheck size={14} /> Tool approval</span>
          </header>
          <strong>{approval.label}</strong>
          <ApprovalSummary approval={approval}/>
          <p className="rh-fg3 rh-small">This step needs a server estimate and hard cap before you can approve.</p>
          <details className="agent-approval-details"><summary>Review parameters</summary><Parameters args={approval.arguments} bare /></details>
            <footer>
              <button
                type="button"
                className="agent-approval-reject"
                disabled={disabled || busyCallId !== null}
                onClick={() => onDecision(approval, "reject")}
              >
                Reject
              </button>
              <button
                type="button"
                className="agent-approval-approve"
                disabled
                aria-label="Approval unavailable until an estimate and hard cap arrive"
              >
                {busyCallId === approval.callId ? <LoaderCircle className="spin" size={13} /> : null}
                Estimate unavailable
              </button>
            </footer>
        </article>;
      })}
    </div>
  );
}

/** A step with a server-sent price: the full approval card. Edit reveals the parameters; Approve is never auto-focused. */
function PricedApproval({ approval, model, busy, onDecision }: {
  approval: AgentApprovalRequest;
  model: ReturnType<typeof approvalCardModel> & object;
  busy: boolean;
  onDecision: (approval: AgentApprovalRequest, decision: "approve" | "reject", capCents?: number) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [loweredCap, setLoweredCap] = useState<number | null>(null);
  // Lowering the cap is the user's own choice, sent as cap_cents on approve. The server re-checks it against the estimate and credit.
  const shown = loweredCap == null ? model : { ...model, capCents: loweredCap, balanceCents: undefined, balanceAfterCapCents: undefined };
  return (
    <div className="rh-appr-wrap">
      <ApprovalCard
        model={shown}
        approveEnabled={model.approveEnabled !== false || loweredCap != null}
        busy={busy}
        actions={{
          onApprove: () => onDecision(approval, "approve", loweredCap ?? undefined),
          onReject: () => onDecision(approval, "reject"),
          onEdit: () => setEditing((value) => !value),
          onAddCredit: () => window.dispatchEvent(new CustomEvent(RH_ADD_CREDIT_EVENT)),
          onLowerCap: (cap) => setLoweredCap(cap),
        }}
      />
      {editing ? <Parameters args={approval.arguments} /> : null}
    </div>
  );
}

/** The step's settings as plain label/value rows. Model and provider fields and machine ids are never shown. */
function Parameters({ args, bare = false }: { args: Record<string, unknown>; bare?: boolean }) {
  const rows = visibleParameters(args);
  const body = rows.length ? <dl className="rh-params">{rows.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl> : <p className="rh-fg3 rh-small">No adjustable settings for this step.</p>;
  return bare ? body : <details className="agent-approval-details rh-appr-params" open><summary>Parameters</summary>{body}</details>;
}

/** Starter prompts. Chips say what to expect, never a price: prices only ever come from the server's approval card. */
const AGENT_STARTERS = [
  { id: "film", Icon: Clapperboard, title: "Product film from one photo", detail: "Upload a still, get a 10 s film with voiceover.", chip: "Shows estimate", free: false,
    prompt: "From the product photo in this project, plan a 10 second product film with a warm voiceover. Show me the plan and ask before every paid step." },
  { id: "variants", Icon: Layers, title: "Ad variants in 9:16, 1:1, 4:5", detail: "One master cut, every placement.", chip: "Shows estimate", free: false,
    prompt: "Take the master cut and propose ad variants in 9:16, 1:1 and 4:5. Show the plan and ask before every paid step." },
  { id: "captions", Icon: Captions, title: "Captions and a punchier hook", detail: "Edit what you already have. Free to preview.", chip: "Free to preview", free: true,
    prompt: "Add captions to the existing cut and suggest a punchier opening hook. Preview the edit before anything paid runs." },
  { id: "explainer", Icon: FileText, title: "Explainer from a document", detail: "Drop a PDF; I'll storyboard and ask first.", chip: "Shows estimate", free: false,
    prompt: "I'll upload a document. Storyboard a short explainer from it and ask me before any paid step." },
] as const;

function ApprovalSummary({approval}: {approval: AgentApprovalRequest}) {
  if (approval.message) return <p className="agent-approval-summary">{approval.message}</p>;
  const args = approval.arguments;
  if (Array.isArray(args.visuals)) {
    const ends = new Map<number, number>();
    for (const clip of args.visuals as Array<Record<string, unknown>>) {
      const track = Number(clip.track || 0);
      ends.set(track, Math.max(ends.get(track) || 0, Number(clip.start_seconds ?? ends.get(track) ?? 0) + Number(clip.duration_seconds || 0)));
    }
    const duration = Math.max(...ends.values());
    const audio = Array.isArray(args.audio_tracks) ? args.audio_tracks as Array<Record<string, unknown>> : [];
    return <p className="agent-approval-summary">Export {duration}s · {String(args.aspect_ratio || "9:16")} · {String(args.fps || 30)} fps<br/>{args.visuals.length} visual {args.visuals.length === 1 ? "clip" : "clips"}{audio.length ? ` · ${audio.length} audio ${audio.length === 1 ? "track" : "tracks"}` : ""}
      {audio.map((clip, index) => <span className="agent-audio-timing" key={index}>Audio {index + 1}: plays at {Number(clip.start_seconds || 0)}–{Math.min(duration, Number(clip.start_seconds || 0) + Number(clip.duration_seconds || 0))}s · source starts at {Number(clip.source_in_seconds || 0)}s</span>)}
    </p>;
  }
  if (args.job_id || args.render_id) return <p className="agent-approval-summary">Check the existing job and wait for its result. This does not start another generation.</p>;
  return typeof args.prompt === "string" ? <p className="agent-approval-summary">{args.prompt.slice(0,220)}{args.prompt.length > 220 ? "…" : ""}</p> : null;
}

function ArtifactCard({
  asset,
  placed,
  onPlace,
  disabled = false,
}: {
  asset: StudioAsset;
  placed: boolean;
  onPlace?: () => void;
  disabled?: boolean;
}) {
  return (
    <article className={`agent-artifact ${asset.kind === "video" ? "agent-artifact-video" : ""}`}>
      <AssetMedia
        asset={asset}
        alt={asset.filename}
        className="agent-artifact-media"
        controls={asset.kind !== "image"}
        muted={false}
      />
      <div className="agent-artifact-meta">
        <span title={asset.filename}>{asset.filename}</span>
        <div>
          <AssetDownloadLink
            asset={asset}
            className="agent-artifact-action"
            ariaLabel={`Download ${asset.filename}`}
          >
            <Download size={13} />
          </AssetDownloadLink>
          {onPlace ? <button
            className="agent-artifact-place"
            type="button"
            disabled={placed || disabled}
            onClick={onPlace}
          >
            {placed ? <Check size={13} /> : <Plus size={13} />}
            {placed ? "On canvas" : "Place & edit"}
          </button> : null}
        </div>
      </div>
    </article>
  );
}

/** Run-level billing from the server: the paused-at-cap card and the whole-run receipt. All figures are cents it sent. */
function RunBillingBlocks({ execution, disabled, onCap }: {
  execution: StudioExecution;
  disabled: boolean;
  onCap: (execution: StudioExecution, action: "raise" | "stop", capCents?: number) => void;
}) {
  const paused = execution.pausedCap;
  const receipt = toRunReceiptModel(execution.receipt);
  const finished = execution.updatedAt ? new Date(execution.updatedAt * 1000).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }) : "";
  return (
    <>
      {paused ? (
        <ApprovalCard
          model={toApprovalCardModel({
            id: `${execution.jobId}:paused`,
            status: "paused_cap",
            title: "Paused at your cap",
            walletTotalCents: undefined,
          }, paused)}
          busy={disabled}
          actions={{
            onRaise: (cap) => onCap(execution, "raise", cap),
            onStop: () => onCap(execution, "stop"),
            onAddCredit: () => window.dispatchEvent(new CustomEvent(RH_ADD_CREDIT_EVENT)),
          }}
        />
      ) : null}
      {receipt && !paused ? (
        <RunReceipt
          receipt={{ ...receipt, title: execution.title || "Run receipt", finishedLabel: finished ? `Finished ${finished}` : "" }}
          onOpen={() => window.dispatchEvent(new CustomEvent("rh:open-film"))}
          onTimeline={() => useCanvasStore.getState().setWorkspaceView("timeline")}
          onExport={() => window.dispatchEvent(new CustomEvent("rh:open-export"))}
        />
      ) : null}
    </>
  );
}

function ExecutionTurn({
  execution,
  placedVersionIds,
  onPlace,
  onApproval,
  onCap,
  busyApproval,
  onResume,
  canResume,
  recovering,
  actionsDisabled,
}: {
  execution: StudioExecution;
  placedVersionIds: Set<string>;
  onPlace: (asset: StudioAsset, execution: StudioExecution, event?: AgentToolEvent) => void;
  onApproval: (
    execution: StudioExecution,
    approval: AgentApprovalRequest,
    decision: "approve" | "reject",
    capCents?: number,
  ) => void;
  onCap: (execution: StudioExecution, action: "raise" | "stop", capCents?: number) => void;
  busyApproval: string | null;
  onResume: () => void;
  canResume: boolean;
  recovering: boolean;
  actionsDisabled: boolean;
}) {
  const displayStatus = execution.progressEvents.some((event) => event.id === "video-delivery" && event.status === "failed")
    || execution.errorType === "VideoExportIncomplete" ? "incomplete" : execution.status;
  const state = normalizedStatus(displayStatus);
  const assets = execution.assets;
  return (
    <section className="agent-turn" aria-label={`Agent run ${execution.title || execution.status}`}>
      {execution.prompt ? <UserMessage text={execution.prompt} /> : null}
      <div className="agent-response">
        <IntermediateSteps
          events={execution.toolEvents}
          progressEvents={execution.progressEvents}
          status={displayStatus}
          message={execution.message}
          duration={runDuration(execution)}
          recoveryAvailable={execution.recoveryAvailable}
        />
        <ApprovalCards
          approvals={execution.approvals}
          active={execution.status === "awaiting_approval"}
          busyCallId={busyApproval}
          disabled={actionsDisabled}
          onDecision={(approval, decision, capCents) => onApproval(execution, approval, decision, capCents)}
        />
        <RunBillingBlocks execution={execution} disabled={actionsDisabled} onCap={onCap} />
        {execution.title ? <h3 className="agent-result-title">{execution.title}</h3> : null}
        {execution.summary ? <p className="agent-response-summary">{execution.summary}</p> : null}
        {state === "failed" ? (
          <p className="agent-response-error">{execution.message}</p>
        ) : null}
        {assets.length ? (
          <div className="agent-artifacts" aria-label="Run artifacts">
            {assets.map((asset) => (
              <ArtifactCard
                key={asset.versionId}
                asset={asset}
                placed={placedVersionIds.has(asset.versionId)}
                disabled={actionsDisabled}
                onPlace={() => onPlace(
                  asset,
                  execution,
                  sourceEventForAsset(execution, asset),
                )}
              />
            ))}
          </div>
        ) : null}
        {execution.result?.markdown ? (
          <details className="agent-response-notes">
            <summary>View full response</summary>
            <div className="agent-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{execution.result.markdown}</ReactMarkdown></div>
          </details>
        ) : null}
        {canResume && ["failed", "incomplete"].includes(state) ? <button className="agent-resume" type="button" disabled={actionsDisabled || recovering || !execution.canResume} onClick={onResume}
          title={execution.canResume ? undefined : "No durable recovery data is available for this run."}>
          {recovering ? <LoaderCircle size={14} className="spin" /> : <RotateCcw size={14} />} {execution.canResume ? "Resume saved progress" : "Resume unavailable"}
        </button> : null}
        <footer>
          <span>{runTime(execution.createdAt)}</span>
          {execution.checkpointAt ? <span className="agent-checkpoint"><BookmarkCheck size={12}/> Checkpoint saved</span> : null}
          {execution.result?.partial ? <span>Partial result</span> : null}
        </footer>
      </div>
    </section>
  );
}

function LiveExecutionTurn({ run }: { run: LiveRun }) {
  const assets = [...new Map(run.progress.toolEvents.flatMap((event) => event.assets).map((asset) => [asset.versionId, asset])).values()];
  return (
    <section className="agent-turn agent-turn-live" aria-live="polite">
      <UserMessage text={run.prompt} />
      <div className="agent-response">
        <IntermediateSteps
          events={run.progress.toolEvents}
          progressEvents={run.progress.progressEvents}
          status={run.progress.status}
          message={run.progress.message}
        />
        {assets.length ? <div className="agent-artifacts" aria-label="Completed assets while working">{assets.map((asset) => <ArtifactCard key={asset.versionId} asset={asset} placed={false}/>)}</div> : null}
        {run.progress.result?.summary ? (
          <p className="agent-response-summary">{run.progress.result.summary}</p>
        ) : null}
      </div>
    </section>
  );
}

function UserMessage({text}: {text: string}) {
  const [expanded, setExpanded] = useState(false);
  return <div className="agent-user-message">
    <p className={!expanded && text.length > 400 ? "agent-prompt-collapsed" : ""}>{text}</p>
    {text.length > 400 ? <button type="button" onClick={() => setExpanded(!expanded)}>{expanded ? "Collapse brief" : "Read full brief"}</button> : null}
  </div>;
}

export function AgentDock({ navigationBusy: externalBusy, onBusyChange, suggestion, onSuggestionUsed, onAttach }: {
  navigationBusy: boolean;
  onBusyChange: (busy: boolean) => void;
  suggestion: string | null;
  onSuggestionUsed: () => void;
  onAttach: () => void;
}) {
  const nodes = useCanvasStore((state) => state.nodes);
  const projectId = useCanvasStore((state) => state.projectId);
  const changesDocument = useChangesStore((state) => state.document);
  const frameMessage = useChangesStore((state) => state.frameMessage);
  const composerInsertion = useChangesStore((state) => state.composerInsertion);
  const projectName = useCanvasStore((state) => state.projectName);
  const selectedNodeIds = useCanvasStore((state) => state.selectedNodeIds);
  const executions = useCanvasStore((state) => state.executions);
  const conversations = useCanvasStore((state) => state.conversations);
  const conversationId = useCanvasStore((state) => state.conversationId);
  const agentMessage = useCanvasStore((state) => state.agentMessage);
  const agentOpen = useCanvasStore((state) => state.agentOpen);
  const setAgentMessage = useCanvasStore((state) => state.setAgentMessage);
  const setActiveTool = useCanvasStore((state) => state.setActiveTool);
  const placeAgentAsset = useCanvasStore((state) => state.placeAgentAsset);
  const refreshConversations = useCanvasStore((state) => state.refreshConversations);
  const refreshExecutions = useCanvasStore((state) => state.refreshExecutions);
  const createAgentConversation = useCanvasStore((state) => state.createAgentConversation);
  const renameAgentConversation = useCanvasStore((state) => state.renameAgentConversation);
  const archiveAgentConversation = useCanvasStore((state) => state.archiveAgentConversation);
  const status = useCanvasStore((state) => state.status);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const draftKey = `${projectId}:${conversationId || "new"}`;
  const value = drafts[draftKey] || "";
  const setValue = (next: string | ((current: string) => string)) => setDrafts((current) => ({
    ...current, [draftKey]: typeof next === "function" ? next(current[draftKey] || "") : next,
  }));
  const [busy, setBusy] = useState(false);
  const [liveRun, setLiveRun] = useState<LiveRun | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [archivePending, setArchivePending] = useState(false);
  const [autonomous, setAutonomous] = useState(false);
  const [recovering, setRecovering] = useState(false);
  const [changingTask, setChangingTask] = useState(false);
  const stickToBottom = useRef(true);
  const [busyApproval, setBusyApproval] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const { screenToFlowPosition } = useReactFlow();
  const mentions = useMemo(
    () => nodes.filter((node) => value.includes(`@${node.data.title.replaceAll(" ", "")}`)),
    [nodes, value],
  );
  const conversationExecutions = useMemo(
    () => executions
      .filter((execution) => execution.conversationId === conversationId)
      .sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0)),
    [executions, conversationId],
  );
  // The credit chip needs the hard cap of the step waiting for approval, and any credit held for a running step.
  const setPendingCap = useCreditContext((state) => state.setPendingCap);
  const setHeld = useCreditContext((state) => state.setHeld);
  useEffect(() => {
    const waiting = conversationExecutions.flatMap((execution) => execution.status === "awaiting_approval" ? execution.approvals.filter((approval) => !approval.decision) : []);
    const cap = waiting.map((approval) => approval.billing?.cap_cents).find((value): value is number => typeof value === "number");
    setPendingCap(cap ?? null);
    const held = conversationExecutions.map((execution) => execution.pausedCap?.held_cents ?? execution.approvals.find((approval) => approval.billing?.status === "running")?.billing?.held_cents).find((value): value is number => typeof value === "number");
    setHeld(held ?? 0);
  }, [conversationExecutions, setHeld, setPendingCap]);
  const activeConversation = conversations.find((item) => item.id === conversationId);
  const activeExecution = conversationExecutions.find(
    (execution) => normalizedStatus(execution.status) === "running",
  );
  const runInFlight = busy || Boolean(activeExecution);
  const navigationBusy = busy || recovering || busyApproval !== null || changingTask;
  useEffect(() => {
    onBusyChange(navigationBusy);
    return () => onBusyChange(false);
  }, [navigationBusy, onBusyChange]);

  useEffect(() => {
    if (!suggestion) return;
    setDrafts((current) => ({ ...current, [draftKey]: current[draftKey] ? `${current[draftKey]}\n\n${suggestion}` : suggestion }));
    onSuggestionUsed();
    inputRef.current?.focus();
  }, [suggestion, draftKey, onSuggestionUsed]);
  useEffect(() => {
    if (!composerInsertion) return;
    const text = useChangesStore.getState().consumeComposerInsertion();
    if (!text) return;
    const at = inputRef.current?.selectionStart ?? value.length;
    const separator = at && !/\s$/.test(value.slice(0, at)) ? " " : "";
    setValue((current) => `${current.slice(0, at)}${separator}${text} ${current.slice(at)}`);
    const caret = at + separator.length + text.length + 1;
    requestAnimationFrame(() => { inputRef.current?.focus(); inputRef.current?.setSelectionRange(caret, caret); });
  }, [composerInsertion, draftKey]);
  const placedVersionIds = useMemo(
    () => new Set(
      nodes
        .map((node) => node.data.output?.versionId)
        .filter((versionId): versionId is string => Boolean(versionId)),
    ),
    [nodes],
  );

  const awaitingApproval = conversationExecutions.some((execution) => execution.status === "awaiting_approval" && execution.approvals.some((approval) => !approval.decision));
  useEffect(() => {
    if (agentOpen && !awaitingApproval) inputRef.current?.focus();
  }, [agentOpen, awaitingApproval]);

  useEffect(() => {
    setAutonomous(window.localStorage.getItem("renderhaus.agent.autonomous") === "true");
  }, []);

  useEffect(() => {
    setRenaming(null);
    setArchivePending(false);
    stickToBottom.current = true;
    setAgentMessage(null);
  }, [conversationId, setAgentMessage]);

  useEffect(() => {
    const transcript = transcriptRef.current;
    if (transcript && stickToBottom.current) transcript.scrollTop = transcript.scrollHeight;
  }, [agentOpen, liveRun, conversationExecutions]);

  useEffect(() => {
    if (!activeExecution || liveRun) return;
    const timer = window.setInterval(() => void refreshExecutions(), 1_000);
    return () => window.clearInterval(timer);
  }, [activeExecution?.jobId, liveRun, refreshExecutions]);

  const placementPosition = () => {
    const selected = nodes.filter((node) => selectedNodeIds.includes(node.id));
    if (selected.length) {
      return {
        x: Math.max(...selected.map((node) => node.position.x)) + 440,
        y: Math.min(...selected.map((node) => node.position.y)),
      };
    }
    const pane = document.querySelector(".react-flow");
    const rect = pane?.getBoundingClientRect();
    const center = screenToFlowPosition({
      x: (rect?.left || 0) + (rect?.width || 800) / 2,
      y: (rect?.top || 0) + (rect?.height || 600) / 2,
    });
    return { x: center.x - 180, y: center.y - 120 };
  };

  const commitRename = () => {
    const title = renaming?.trim();
    if (title && activeConversation) {
      void changeTask(() => renameAgentConversation(activeConversation.id, title));
    }
    setRenaming(null);
  };

  const changeTask = async (action: () => Promise<void>) => {
    if (externalBusy || navigationBusy) return;
    setChangingTask(true);
    onBusyChange(true);
    try { await action(); }
    finally { setChangingTask(false); onBusyChange(false); }
  };

  const submit = async (frameText?: string, frameSlotId?: string) => {
    const prompt = (frameText ?? value).trim();
    const allowAutonomous = frameText ? false : autonomous;
    if (!prompt || runInFlight || externalBusy || !conversationId) return;
    setBusy(true);
    stickToBottom.current = true;
    setAgentMessage(null);
    setLiveRun({
      prompt,
      progress: {
        status: "queued",
        message: "Queued",
        toolEvents: [],
        progressEvents: [],
        autonomous: allowAutonomous,
        approvals: [],
      },
    });
    if (!frameText) setValue("");
    const refs = mentions.map((node) => node.id);
    const ids = frameText ? frameSlotId ? [frameSlotId] : [] : refs.length ? refs : selectedNodeIds;
    const referencedNodes = nodes.filter((node) => ids.includes(node.id));
    const contexts = referencedNodes.map((node) => {
      const promptValue = ["prompt", "text", "script", "lyrics"]
        .map((key) => node.data.config[key])
        .find((item): item is string => typeof item === "string" && item.trim().length > 0);
      return {
        id: node.id,
        title: node.data.title,
        kind: node.data.kind,
        prompt: promptValue || node.data.agentResult?.markdown || "",
        ...(node.data.output
          ? {
              asset_id: node.data.output.assetId,
              version_id: node.data.output.versionId,
            }
          : {}),
      };
    });

    try {
      const result = await submitAgentPrompt(
        prompt,
        projectId,
        conversationId,
        ids,
        contexts,
        allowAutonomous,
        (progress) => {
          setAgentMessage(progress.message);
          setLiveRun({ prompt, progress });
        },
      );
      setAgentMessage(result.message);
      if ("result" in result && result.result) {
        setLiveRun({
          prompt,
          progress: {
            jobId: result.result.executionId,
            status: result.status,
            message: result.message,
            toolEvents: result.result.toolEvents,
            progressEvents: liveRun?.progress.progressEvents || [],
            result: result.result,
            autonomous: allowAutonomous,
            approvals: [],
          },
        });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "The agent could not run.";
      setAgentMessage(message);
      setLiveRun({
        prompt,
        progress: {
          status: "error",
          message,
          toolEvents: [],
          progressEvents: [],
          autonomous: allowAutonomous,
          approvals: [],
        },
      });
    } finally {
      await refreshConversations();
      setLiveRun(null);
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!frameMessage || runInFlight || externalBusy || !conversationId) return;
    const message = useChangesStore.getState().consumeFrameMessage();
    if (!message) return;
    if (message.projectId !== projectId || message.conversationId !== conversationId) {
      setAgentMessage("The task changed before the frame note could be sent. Return to the original task to send it.");
      return;
    }
    void submit(message.text, message.slotId);
  }, [frameMessage, runInFlight, externalBusy, projectId, conversationId]);

  const onCap = async (execution: StudioExecution, action: "raise" | "stop", capCents?: number) => {
    if (externalBusy || navigationBusy) return;
    setBusyApproval(execution.jobId);
    try {
      const progress = await answerAgentCap(execution.jobId, action, capCents);
      setAgentMessage(progress.message);
      await refreshExecutions();
    } catch (error) {
      setAgentMessage(error instanceof Error ? error.message : "The cap could not be changed. Nothing more has been charged.");
    } finally {
      setBusyApproval(null);
    }
  };

  const onApproval = async (
    execution: StudioExecution,
    approval: AgentApprovalRequest,
    decision: "approve" | "reject",
    capCents?: number,
  ) => {
    if (externalBusy || navigationBusy) return;
    setBusyApproval(approval.callId);
    try {
      const progress = await decideAgentApproval(execution.jobId, approval.callId, decision, capCents);
      setAgentMessage(progress.message);
      await refreshExecutions();
    } catch (error) {
      setAgentMessage(error instanceof Error ? error.message : "The approval could not be saved.");
    } finally {
      setBusyApproval(null);
    }
  };

  const onPlace = (
    asset: StudioAsset,
    execution: StudioExecution,
    toolEvent?: AgentToolEvent,
  ) => {
    if (externalBusy || navigationBusy) return;
    placeAgentAsset({
      asset,
      executionId: execution.jobId,
      prompt: execution.prompt,
      toolEvent,
      position: placementPosition(),
    });
  };

  return (
    <section className="agent-dock rh-agent-dock" id="agent-composer" aria-label="Agent conversation">
      <header className="agent-dock-head">
        <div className="agent-dock-title">
          <span className="agent-dock-kicker"><Sparkles size={14} /> {projectName}</span>
          <div className="agent-conversation-controls">
            {renaming !== null ? (
              <>
                <input
                  autoFocus
                  value={renaming}
                  aria-label="Conversation name"
                  onChange={(event) => setRenaming(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") commitRename();
                    if (event.key === "Escape") setRenaming(null);
                  }}
                />
                <button
                  className="icon-btn"
                  type="button"
                  aria-label="Save conversation name"
                  title="Save conversation name"
                  onClick={commitRename}
                >
                  <Check size={14} />
                </button>
                <button
                  className="icon-btn"
                  type="button"
                  aria-label="Cancel rename"
                  title="Cancel rename"
                  onClick={() => setRenaming(null)}
                >
                  <X size={14} />
                </button>
              </>
            ) : archivePending ? (
              <>
                <span className="agent-conversation-confirm">Archive this conversation?</span>
                <button
                  className="agent-conversation-action"
                  type="button"
                  onClick={() => setArchivePending(false)}
                >
                  Cancel
                </button>
                <button
                  className="agent-conversation-action danger"
                  type="button"
                  onClick={() => {
                    if (activeConversation) {
                      void changeTask(() => archiveAgentConversation(activeConversation.id));
                    }
                    setArchivePending(false);
                  }}
                >
                  Archive
                </button>
              </>
            ) : (
              <>
                <h2 className="agent-task-title">{activeConversation?.title || "New task"}</h2>
                <button
                  className="icon-btn"
                  type="button"
                  disabled={navigationBusy || externalBusy}
                  aria-label="New task"
                  title="New task"
                  onClick={() => void changeTask(createAgentConversation)}
                >
                  <Plus size={15} />
                </button>
                <button
                  className="icon-btn"
                  type="button"
                  disabled={navigationBusy || externalBusy || !activeConversation}
                  aria-label="Rename conversation"
                  title="Rename conversation"
                  onClick={() => setRenaming(activeConversation?.title || "")}
                >
                  <Pencil size={14} />
                </button>
                <button
                  className="icon-btn"
                  type="button"
                  disabled={runInFlight || navigationBusy || externalBusy || !activeConversation}
                  aria-label="Archive conversation"
                  title="Archive conversation"
                  onClick={() => setArchivePending(true)}
                >
                  <Archive size={14} />
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      <div className="agent-memory-bar"><BookmarkCheck size={13}/><span>Conversation saved · {conversationExecutions.length} {conversationExecutions.length === 1 ? "run" : "runs"}</span></div>
      <div className="agent-transcript" ref={transcriptRef} onScroll={(event) => {
        const el = event.currentTarget;
        stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
      }}>
        {conversationExecutions.length === 0 && !liveRun && !changesDocument ? (
          <div className="agent-empty">
            <p className="rh-eyebrow">Project · {projectName}</p>
            <h3>What are we <em>making</em>?</h3>
            <p>Describe the video, or drop in a still. I&apos;ll plan the shots and show you the price of every paid step before it runs.</p>
            <div className="rh-starters" role="list">
              {AGENT_STARTERS.map(({ id, Icon, title, detail, chip, prompt, free }) => (
                <button key={id} type="button" role="listitem" className="rh-starter" onClick={() => { setValue(prompt); inputRef.current?.focus(); }}>
                  <span className="rh-starter-top"><Icon size={16} aria-hidden="true" /><span className={`rh-chip rh-chip-mono ${free ? "rh-chip-ok" : "rh-chip-money"}`}>{chip}</span></span>
                  <b>{title}</b>
                  <span>{detail}</span>
                </button>
              ))}
            </div>
            {!conversationId ? <button type="button" className="agent-conversation-action" disabled={externalBusy || navigationBusy} onClick={() => void changeTask(createAgentConversation)}>Start a task</button> : null}
          </div>
        ) : null}
        {conversationExecutions.filter((execution) => execution.jobId !== liveRun?.progress.jobId).map((execution) => (
          <ExecutionTurn
            key={execution.jobId}
            execution={execution}
            placedVersionIds={placedVersionIds}
            onPlace={onPlace}
            onApproval={onApproval}
            onCap={onCap}
            busyApproval={busyApproval}
            actionsDisabled={externalBusy || navigationBusy}
            canResume={!runInFlight && execution.jobId === conversationExecutions.at(-1)?.jobId}
            recovering={recovering}
            onResume={() => {
              if (externalBusy || navigationBusy) return;
              setRecovering(true);
              void resumeAgentRun(execution.jobId).then(() => refreshExecutions()).catch((error) => setAgentMessage(String(error))).finally(() => setRecovering(false));
            }}
          />
        ))}
        {liveRun ? <LiveExecutionTurn run={liveRun} /> : null}
        {changesDocument ? <ChangesetCard document={changesDocument} onInsert={(n) => useChangesStore.getState().setComposerInsertion(`change ${n}`)} onOpen={() => { const store = useChangesStore.getState(); store.setTab("changes"); const take = changesDocument.changes.find((change) => change.kind === "take"); if (take) store.openCompare(take.n); }} /> : null}
      </div>

      <div className="agent-composer">
        {activeExecution || liveRun?.progress.jobId ? <button className="agent-stop" type="button" onClick={() => {
          void stopAgentRun(activeExecution?.jobId || liveRun!.progress.jobId!).then(() => refreshExecutions()).catch((error) => setAgentMessage(String(error)));
        }}><Square size={12}/> Stop & save progress</button> : null}
        {nodes.length > 0 && value.includes("@") ? (
          <div className="mention-list">
            {nodes.slice(0, 6).map((node) => (
              <button
                key={node.id}
                type="button"
                onClick={() => setValue((current) => `${current.replace(/@$/, "")}@${node.data.title.replaceAll(" ", "")} `)}
              >
                {node.data.title}
              </button>
            ))}
          </div>
        ) : null}
        <div className="agent-composer-input">
          <textarea
            aria-label="Ask the project agent"
            ref={inputRef}
            value={value}
            maxLength={AGENT_PROMPT_MAX_CHARS}
            placeholder="Ask the project agent"
            rows={3}
            onFocus={() => setActiveTool("agent")}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void submit();
              }
            }}
          />
          <div className="agent-composer-actions">
            <div>
              <button
                className="icon-btn"
                type="button"
                disabled={externalBusy || runInFlight}
                aria-label="Upload media to project"
                title="Upload media to project"
                onClick={onAttach}
              >
                <Paperclip size={15} />
              </button>
              <button
                className="icon-btn"
                type="button"
                aria-label="Mention a canvas object"
                title="Mention a canvas object"
                onClick={() => setValue((current) => `${current}@`)}
              >
                <AtSign size={15} />
              </button>
              {value.length >= 4_000 ? (
                <span className="agent-prompt-size" aria-live="polite">
                  {value.length.toLocaleString()} / {AGENT_PROMPT_MAX_CHARS.toLocaleString()}
                </span>
              ) : null}
              <label className={`agent-autonomy-toggle ${autonomous ? "active" : ""}`}>
                <input
                  type="checkbox"
                  checked={autonomous}
                  disabled={runInFlight}
                  onChange={(event) => {
                    const enabled = event.target.checked;
                    setAutonomous(enabled);
                    window.localStorage.setItem("renderhaus.agent.autonomous", String(enabled));
                  }}
                />
                <ShieldCheck size={14} />
                <span>{autonomous ? "Autonomous" : "Ask before every paid step"}</span>
              </label>
            </div>
            <button
              className="send-btn"
              type="button"
              aria-label={runInFlight ? "Agent is working" : "Send to agent"}
              disabled={runInFlight || externalBusy || !value.trim() || !status?.agent || !conversationId}
              onClick={() => void submit()}
            >
              {runInFlight ? <LoaderCircle className="spin" size={14} /> : <Send size={14} />}
            </button>
          </div>
        </div>
        <div className="agent-composer-meta">
          <span>{selectedNodeIds.length ? `${selectedNodeIds.length} selected` : "Project context"}</span>
          <span>
            {activeExecution ? "Estimate and hard cap shown on every paid step" : agentMessage?.startsWith("Error") ? agentMessage : "Estimate and hard cap shown on every paid step"}
          </span>
        </div>
      </div>
    </section>
  );
}
