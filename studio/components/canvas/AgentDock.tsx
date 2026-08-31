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
  Sparkles,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  submitAgentPrompt,
  type AgentProgress,
  type StudioExecution,
} from "@/lib/api";
import { useCanvasStore } from "@/lib/canvas/store";
import type { AgentToolEvent } from "@/lib/canvas/types";
import type { StudioAsset } from "@/lib/types";
import { AssetDownloadLink, AssetMedia } from "./AssetMedia";

type LiveRun = {
  prompt: string;
  progress: AgentProgress;
};

function normalizedStatus(status: string): "running" | "completed" | "failed" {
  const value = status.toLowerCase();
  if (["failed", "error", "cancelled", "canceled"].includes(value)) return "failed";
  if (["queued", "running", "pending"].includes(value)) return "running";
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
  status,
  message,
  duration,
}: {
  events: AgentToolEvent[];
  status: string;
  message: string;
  duration?: string | null;
}) {
  const state = normalizedStatus(status);
  const label =
    state === "running"
      ? message || "Working on the request"
      : state === "failed"
        ? `Stopped${events.length ? ` after ${events.length} ${events.length === 1 ? "step" : "steps"}` : ""}`
        : events.length
          ? `Worked through ${events.length} ${events.length === 1 ? "step" : "steps"}${duration ? ` in ${duration}` : ""}`
          : `Completed${duration ? ` in ${duration}` : ""}`;

  return (
    <details className={`agent-progress-group ${state}`} open={state === "running"}>
      <summary>
        <span className="agent-progress-leading">
          <StepIcon status={status} />
          <span>{label}</span>
        </span>
        {events.length ? <ChevronRight className="agent-progress-chevron" size={14} /> : null}
      </summary>
      {events.length ? (
        <ol className="agent-step-list">
          {events.map((event) => (
            <li className={normalizedStatus(event.status)} key={event.id}>
              <span className="agent-step-icon"><StepIcon status={event.status} /></span>
              <span>
                <strong>{event.label}</strong>
                {event.summary ? <small>{event.summary}</small> : null}
              </span>
            </li>
          ))}
        </ol>
      ) : null}
    </details>
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
}: {
  execution: StudioExecution;
  placedVersionIds: Set<string>;
  onPlace: (asset: StudioAsset, execution: StudioExecution, event?: AgentToolEvent) => void;
}) {
  const state = normalizedStatus(execution.status);
  const assets = execution.assets;
  return (
    <section className="agent-turn" aria-label={`Agent run ${execution.title || execution.status}`}>
      {execution.prompt ? <p className="agent-user-message">{execution.prompt}</p> : null}
      <div className="agent-response">
        <IntermediateSteps
          events={execution.toolEvents}
          status={execution.status}
          message={execution.message}
          duration={runDuration(execution)}
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
    setRenaming(null);
    setArchivePending(false);
  }, [conversationId]);

  useEffect(() => {
    const transcript = transcriptRef.current;
    if (transcript) transcript.scrollTop = transcript.scrollHeight;
  }, [agentOpen, liveRun, conversationExecutions.length]);

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
    if (!prompt || busy || !conversationId) return;
    setBusy(true);
    setAgentMessage(null);
    setLiveRun({
      prompt,
      progress: {
        status: "queued",
        message: "Starting the agent",
        toolEvents: [],
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
        (progress) => {
          setAgentMessage(progress.message);
          setLiveRun({ prompt, progress });
        },
      );
      setAgentMessage(result.message);
      if (result.result) {
        setLiveRun({
          prompt,
          progress: {
            jobId: result.result.executionId,
            status: result.status,
            message: result.message,
            toolEvents: result.result.toolEvents,
            result: result.result,
          },
        });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "The agent could not run.";
      setAgentMessage(message);
      setLiveRun({
        prompt,
        progress: { status: "error", message, toolEvents: [] },
      });
    } finally {
      await refreshConversations();
      setLiveRun(null);
      setBusy(false);
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
            </div>
            <button
              className="send-btn"
              type="button"
              aria-label={busy ? "Agent is working" : "Send to agent"}
              disabled={busy || !value.trim() || !status?.agent || !conversationId}
              onClick={() => void submit()}
            >
              {busy ? <LoaderCircle className="spin" size={14} /> : <Send size={14} />}
            </button>
          </div>
        </div>
        <div className="agent-composer-meta">
          <span>{selectedNodeIds.length ? `${selectedNodeIds.length} selected` : "Project context"}</span>
          <span>{agentMessage || (status?.agent ? "Agent ready" : "Agent unavailable")}</span>
        </div>
      </div>
    </aside>
  );
}
