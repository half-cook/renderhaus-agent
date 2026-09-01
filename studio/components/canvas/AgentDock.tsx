"use client";

import { useReactFlow } from "@xyflow/react";
import {
  Archive,
  AtSign,
  Check,
  ChevronRight,
  CircleAlert,
  Download,
  LoaderCircle,
  PanelRightClose,
  Paperclip,
  Pencil,
  Plus,
  Send,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AGENT_PROMPT_MAX_CHARS,
  decideAgentApproval,
  submitAgentPrompt,
  type AgentApprovalRequest,
  type AgentProgress,
  type StudioExecution,
} from "@/lib/api";
import { useCanvasStore } from "@/lib/canvas/store";
import type { AgentProgressEvent, AgentToolEvent } from "@/lib/canvas/types";
import type { StudioAsset } from "@/lib/types";
import { AssetDownloadLink, AssetMedia } from "./AssetMedia";

type LiveRun = {
  prompt: string;
  progress: AgentProgress;
};

function normalizedStatus(status: string): "running" | "completed" | "failed" {
  const value = status.toLowerCase();
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
  return <Check size={14} />;
}

function IntermediateSteps({
  events,
  progressEvents,
  status,
  message,
  duration,
}: {
  events: AgentToolEvent[];
  progressEvents: AgentProgressEvent[];
  status: string;
  message: string;
  duration?: string | null;
}) {
  const state = normalizedStatus(status);
  const progressToolIds = new Set(
    progressEvents.map((event) => event.toolCallId).filter(Boolean),
  );
  const steps = [
    ...progressEvents
      .filter((event) => !["RUN_STARTED", "RUN_FINISHED", "RUN_ERROR"].includes(event.type))
      .map((event) => ({
        id: event.id,
        title: event.title,
        message: event.message,
        status:
          state === "failed" && normalizedStatus(event.status) === "running"
            ? "failed"
            : event.status,
        kind:
          event.type === "REASONING_MESSAGE_CONTENT"
            ? "Reasoning"
            : event.type === "MODEL_UPDATE"
              ? "Update"
              : event.type === "TOOL_APPROVAL_REQUIRED"
                ? "Approval"
            : event.type.startsWith("TOOL_CALL")
              ? "Tool"
              : event.type === "TEXT_MESSAGE_CONTENT"
                ? "Response"
                : "Step",
      })),
    ...events
      .filter((event) => !progressToolIds.has(event.id))
      .map((event) => ({
        id: `tool-event-${event.id}`,
        title: event.label,
        message: event.summary,
        status:
          state === "failed" && normalizedStatus(event.status) === "running"
            ? "failed"
            : event.status,
        kind: "Tool",
      })),
  ];
  const label =
    status === "awaiting_approval"
      ? "Waiting for approval"
      : state === "running"
      ? progressEvents.filter((event) => event.type === "MODEL_UPDATE").at(-1)?.message
        || (steps.length ? "In progress" : message || "Queued")
      : state === "failed"
        ? "Stopped"
        : `Completed${duration ? ` in ${duration}` : ""}`;

  return (
    <details className={`agent-progress-group ${state}`} open={state === "running"}>
      <summary>
        <span className="agent-progress-leading">
          <StepIcon status={status} />
          <span>{label}</span>
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
  );
}

function ApprovalCards({
  approvals,
  onDecision,
  busyCallId,
}: {
  approvals: AgentApprovalRequest[];
  onDecision: (approval: AgentApprovalRequest, decision: "approve" | "reject") => void;
  busyCallId: string | null;
}) {
  if (!approvals.length) return null;
  return (
    <div className="agent-approvals" aria-label="Tool approvals">
      {approvals.map((approval) => (
        <article className="agent-approval" key={approval.callId}>
          <header>
            <span><ShieldCheck size={14} /> Tool approval</span>
            {approval.provider ? <em>{approval.provider}</em> : null}
          </header>
          <strong>{approval.label}</strong>
          <pre>{JSON.stringify(approval.arguments, null, 2)}</pre>
          {approval.decision ? (
            <p className={`agent-approval-decision ${approval.decision}`}>
              {approval.decision === "approve" ? "Approved" : "Rejected"}
            </p>
          ) : (
            <footer>
              <button
                type="button"
                className="agent-approval-reject"
                disabled={busyCallId !== null}
                onClick={() => onDecision(approval, "reject")}
              >
                Reject
              </button>
              <button
                type="button"
                className="agent-approval-approve"
                disabled={busyCallId !== null}
                onClick={() => onDecision(approval, "approve")}
              >
                {busyCallId === approval.callId ? <LoaderCircle className="spin" size={13} /> : null}
                Approve once
              </button>
            </footer>
          )}
        </article>
      ))}
    </div>
  );
}

function ArtifactCard({
  asset,
  placed,
  onPlace,
}: {
  asset: StudioAsset;
  placed: boolean;
  onPlace: () => void;
}) {
  return (
    <article className="agent-artifact">
      <AssetMedia
        asset={asset}
        alt={asset.filename}
        className="agent-artifact-media"
        controls={asset.kind !== "image"}
        muted={asset.kind === "video"}
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
          <button
            className="agent-artifact-place"
            type="button"
            disabled={placed}
            onClick={onPlace}
          >
            {placed ? <Check size={13} /> : <Plus size={13} />}
            {placed ? "On canvas" : "Place & edit"}
          </button>
        </div>
      </div>
    </article>
  );
}

function ExecutionTurn({
  execution,
  placedVersionIds,
  onPlace,
  onApproval,
  busyApproval,
}: {
  execution: StudioExecution;
  placedVersionIds: Set<string>;
  onPlace: (asset: StudioAsset, execution: StudioExecution, event?: AgentToolEvent) => void;
  onApproval: (
    execution: StudioExecution,
    approval: AgentApprovalRequest,
    decision: "approve" | "reject",
  ) => void;
  busyApproval: string | null;
}) {
  const state = normalizedStatus(execution.status);
  const assets = execution.assets;
  return (
    <section className="agent-turn" aria-label={`Agent run ${execution.title || execution.status}`}>
      {execution.prompt ? <p className="agent-user-message">{execution.prompt}</p> : null}
      <div className="agent-response">
        <IntermediateSteps
          events={execution.toolEvents}
          progressEvents={execution.progressEvents}
          status={execution.status}
          message={execution.message}
          duration={runDuration(execution)}
        />
        <ApprovalCards
          approvals={execution.approvals}
          busyCallId={busyApproval}
          onDecision={(approval, decision) => onApproval(execution, approval, decision)}
        />
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
            <pre>{execution.result.markdown}</pre>
          </details>
        ) : null}
        <footer>
          <span>{runTime(execution.createdAt)}</span>
          {execution.result?.partial ? <span>Partial result</span> : null}
        </footer>
      </div>
    </section>
  );
}

function LiveExecutionTurn({ run }: { run: LiveRun }) {
  return (
    <section className="agent-turn agent-turn-live" aria-live="polite">
      <p className="agent-user-message">{run.prompt}</p>
      <div className="agent-response">
        <IntermediateSteps
          events={run.progress.toolEvents}
          progressEvents={run.progress.progressEvents}
          status={run.progress.status}
          message={run.progress.message}
        />
        {run.progress.result?.summary ? (
          <p className="agent-response-summary">{run.progress.result.summary}</p>
        ) : null}
      </div>
    </section>
  );
}

export function AgentDock() {
  const nodes = useCanvasStore((state) => state.nodes);
  const projectId = useCanvasStore((state) => state.projectId);
  const projectName = useCanvasStore((state) => state.projectName);
  const selectedNodeIds = useCanvasStore((state) => state.selectedNodeIds);
  const executions = useCanvasStore((state) => state.executions);
  const conversations = useCanvasStore((state) => state.conversations);
  const conversationId = useCanvasStore((state) => state.conversationId);
  const agentMessage = useCanvasStore((state) => state.agentMessage);
  const agentOpen = useCanvasStore((state) => state.agentOpen);
  const setAgentMessage = useCanvasStore((state) => state.setAgentMessage);
  const setAgentOpen = useCanvasStore((state) => state.setAgentOpen);
  const setActiveTool = useCanvasStore((state) => state.setActiveTool);
  const placeAgentAsset = useCanvasStore((state) => state.placeAgentAsset);
  const refreshConversations = useCanvasStore((state) => state.refreshConversations);
  const refreshExecutions = useCanvasStore((state) => state.refreshExecutions);
  const createAgentConversation = useCanvasStore((state) => state.createAgentConversation);
  const switchAgentConversation = useCanvasStore((state) => state.switchAgentConversation);
  const renameAgentConversation = useCanvasStore((state) => state.renameAgentConversation);
  const archiveAgentConversation = useCanvasStore((state) => state.archiveAgentConversation);
  const status = useCanvasStore((state) => state.status);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [liveRun, setLiveRun] = useState<LiveRun | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [archivePending, setArchivePending] = useState(false);
  const [autonomous, setAutonomous] = useState(false);
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
  const activeConversation = conversations.find((item) => item.id === conversationId);
  const activeExecution = conversationExecutions.find(
    (execution) => normalizedStatus(execution.status) === "running",
  );
  const runInFlight = busy || Boolean(activeExecution);
  const placedVersionIds = useMemo(
    () => new Set(
      nodes
        .map((node) => node.data.output?.versionId)
        .filter((versionId): versionId is string => Boolean(versionId)),
    ),
    [nodes],
  );

  useEffect(() => {
    if (agentOpen) inputRef.current?.focus();
  }, [agentOpen]);

  useEffect(() => {
    setAutonomous(window.localStorage.getItem("renderhaus.agent.autonomous") === "true");
  }, []);

  useEffect(() => {
    setRenaming(null);
    setArchivePending(false);
  }, [conversationId]);

  useEffect(() => {
    const transcript = transcriptRef.current;
    if (transcript) transcript.scrollTop = transcript.scrollHeight;
  }, [agentOpen, liveRun, conversationExecutions.length]);

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
      void renameAgentConversation(activeConversation.id, title);
    }
    setRenaming(null);
  };

  const submit = async () => {
    const prompt = value.trim();
    if (!prompt || runInFlight || !conversationId) return;
    setBusy(true);
    setAgentMessage(null);
    setLiveRun({
      prompt,
      progress: {
        status: "queued",
        message: "Queued",
        toolEvents: [],
        progressEvents: [],
        autonomous,
        approvals: [],
      },
    });
    setValue("");
    const refs = mentions.map((node) => node.id);
    const ids = refs.length ? refs : selectedNodeIds;
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
        autonomous,
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
            autonomous,
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
          autonomous,
          approvals: [],
        },
      });
    } finally {
      await refreshConversations();
      setLiveRun(null);
      setBusy(false);
    }
  };

  const onApproval = async (
    execution: StudioExecution,
    approval: AgentApprovalRequest,
    decision: "approve" | "reject",
  ) => {
    setBusyApproval(approval.callId);
    try {
      const progress = await decideAgentApproval(execution.jobId, approval.callId, decision);
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
    placeAgentAsset({
      asset,
      executionId: execution.jobId,
      prompt: execution.prompt,
      toolEvent,
      position: placementPosition(),
    });
  };

  if (!agentOpen) {
    const activeRuns = conversationExecutions.filter(
      (execution) => normalizedStatus(execution.status) === "running",
    ).length;
    return (
      <button
        className="agent-dock-toggle"
        id="agent-composer"
        type="button"
        aria-label="Open agent"
        onClick={() => {
          setAgentOpen(true);
          setActiveTool("agent");
        }}
      >
        <Sparkles size={16} />
        <span>Agent</span>
        {activeRuns ? <i>{activeRuns}</i> : null}
      </button>
    );
  }

  return (
    <aside className="agent-dock" id="agent-composer" aria-label="Agent conversation">
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
                      void archiveAgentConversation(activeConversation.id);
                    }
                    setArchivePending(false);
                  }}
                >
                  Archive
                </button>
              </>
            ) : (
              <>
                <select
                  value={conversationId || ""}
                  disabled={busy || conversations.length === 0}
                  aria-label="Agent conversation"
                  onChange={(event) => void switchAgentConversation(event.target.value)}
                >
                  {conversations.map((conversation) => (
                    <option value={conversation.id} key={conversation.id}>
                      {conversation.title}
                    </option>
                  ))}
                </select>
                <button
                  className="icon-btn"
                  type="button"
                  disabled={busy}
                  aria-label="New conversation"
                  title="New conversation"
                  onClick={() => void createAgentConversation()}
                >
                  <Plus size={15} />
                </button>
                <button
                  className="icon-btn"
                  type="button"
                  disabled={busy || !activeConversation}
                  aria-label="Rename conversation"
                  title="Rename conversation"
                  onClick={() => setRenaming(activeConversation?.title || "")}
                >
                  <Pencil size={14} />
                </button>
                <button
                  className="icon-btn"
                  type="button"
                  disabled={busy || !activeConversation}
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
        <button
          className="icon-btn"
          type="button"
          aria-label="Close agent"
          title="Close agent"
          onClick={() => setAgentOpen(false)}
        >
          <PanelRightClose size={16} />
        </button>
      </header>

      <div className="agent-transcript" ref={transcriptRef}>
        {conversationExecutions.length === 0 && !liveRun ? (
          <div className="agent-empty">
            <Sparkles size={18} />
            <h3>Work across this project</h3>
            <p>Ask for ideas, edits or generated media. Runs and intermediate steps stay here.</p>
          </div>
        ) : null}
        {conversationExecutions.map((execution) => (
          <ExecutionTurn
            key={execution.jobId}
            execution={execution}
            placedVersionIds={placedVersionIds}
            onPlace={onPlace}
            onApproval={onApproval}
            busyApproval={busyApproval}
          />
        ))}
        {liveRun ? <LiveExecutionTurn run={liveRun} /> : null}
      </div>

      <div className="agent-composer">
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
                disabled
                aria-label="Attachments are not connected yet"
                title="Attachments are not connected yet"
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
                <span>{autonomous ? "Autonomous" : "Ask before tools"}</span>
              </label>
            </div>
            <button
              className="send-btn"
              type="button"
              aria-label={runInFlight ? "Agent is working" : "Send to agent"}
              disabled={runInFlight || !value.trim() || !status?.agent || !conversationId}
              onClick={() => void submit()}
            >
              {runInFlight ? <LoaderCircle className="spin" size={14} /> : <Send size={14} />}
            </button>
          </div>
        </div>
        <div className="agent-composer-meta">
          <span>{selectedNodeIds.length ? `${selectedNodeIds.length} selected` : "Project context"}</span>
          <span>
            {agentMessage || activeExecution?.message || (status?.agent ? "Agent ready" : "Agent unavailable")}
          </span>
        </div>
      </div>
    </aside>
  );
}
