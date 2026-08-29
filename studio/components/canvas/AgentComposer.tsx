"use client";

import { useReactFlow } from "@xyflow/react";
import {
  AtSign,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Focus,
  LoaderCircle,
  Paperclip,
  Radio,
  Send,
  Sparkles,
  Wand2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { submitAgentPrompt, type AgentToolEvent } from "@/lib/api";
import { useCanvasStore } from "@/lib/canvas/store";
import type { StudioAsset } from "@/lib/types";
import { AssetMedia } from "./AssetMedia";

function eventStatusBadge(status: string) {
  const norm = status.toLowerCase();
  if (["failed", "error", "cancelled"].includes(norm)) return "failed";
  if (["queued", "running", "pending"].includes(norm)) return "running";
  return "completed";
}

export function AgentComposer() {
  const nodes = useCanvasStore((state) => state.nodes);
  const projectId = useCanvasStore((state) => state.projectId);
  const selectedNodeIds = useCanvasStore((state) => state.selectedNodeIds);
  const composerMessage = useCanvasStore((state) => state.composerMessage);
  const composerOpen = useCanvasStore((state) => state.composerOpen);
  const setComposerMessage = useCanvasStore((state) => state.setComposerMessage);
  const setComposerOpen = useCanvasStore((state) => state.setComposerOpen);
  const setActiveTool = useCanvasStore((state) => state.setActiveTool);
  const addAgentResult = useCanvasStore((state) => state.addAgentResult);
  const startAgentRun = useCanvasStore((state) => state.startAgentRun);
  const updateAgentRun = useCanvasStore((state) => state.updateAgentRun);
  const completeAgentRun = useCanvasStore((state) => state.completeAgentRun);
  const failAgentRun = useCanvasStore((state) => state.failAgentRun);
  const focusNode = useCanvasStore((state) => state.focusNode);
  const refreshExecutions = useCanvasStore((state) => state.refreshExecutions);
  const status = useCanvasStore((state) => state.status);

  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [streamStep, setStreamStep] = useState<string | null>(null);
  const [streamTools, setStreamTools] = useState<AgentToolEvent[]>([]);
  const [streamAssets, setStreamAssets] = useState<StudioAsset[]>([]);
  const [streamText, setStreamText] = useState("");
  const [completedNodeId, setCompletedNodeId] = useState<string | null>(null);
  const [panelExpanded, setPanelExpanded] = useState(true);

  const inputRef = useRef<HTMLTextAreaElement>(null);
  const textEndRef = useRef<HTMLDivElement>(null);
  const streamToolsRef = useRef<AgentToolEvent[]>([]);
  const streamAssetsRef = useRef<StudioAsset[]>([]);
  const { fitView, screenToFlowPosition } = useReactFlow();

  const mentions = useMemo(
    () => nodes.filter((node) => value.includes(`@${node.data.title.replaceAll(" ", "")}`)),
    [nodes, value],
  );

  useEffect(() => {
    if (composerOpen) {
      inputRef.current?.focus();
    }
  }, [composerOpen]);

  useEffect(() => {
    if (busy && textEndRef.current) {
      textEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [busy, streamText]);

  const submit = async () => {
    const prompt = value.trim();
    if (!prompt || busy) {
      return;
    }
    setBusy(true);
    setComposerMessage(null);
    setStreamStep("Initiating AG-UI stream...");
    setStreamTools([]);
    setStreamAssets([]);
    streamToolsRef.current = [];
    streamAssetsRef.current = [];
    setStreamText("");
    setCompletedNodeId(null);
    setPanelExpanded(true);

    const refs = mentions.map((node) => node.id);
    const ids = refs.length > 0 ? refs : selectedNodeIds;
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
    const position = referencedNodes.length
      ? {
          x: Math.max(...referencedNodes.map((node) => node.position.x)) + 440,
          y: Math.min(...referencedNodes.map((node) => node.position.y)),
        }
      : (() => {
          const pane = document.querySelector(".react-flow");
          const rect = pane?.getBoundingClientRect();
          const center = screenToFlowPosition({
            x: (rect?.left || 0) + (rect?.width || 800) / 2,
            y: (rect?.top || 0) + (rect?.height || 600) / 2,
          });
          return { x: center.x - 190, y: center.y - 120 };
        })();
    let liveRunNodeId: string | null = null;

    try {
      const result = await submitAgentPrompt(
        prompt,
        projectId,
        ids,
        contexts,
        (progress) => {
          setStreamStep(progress);
          if (liveRunNodeId) {
            updateAgentRun(liveRunNodeId, { summary: progress });
          }
        },
        (_delta, fullText) => {
          setStreamText(fullText);
          if (liveRunNodeId) {
            updateAgentRun(liveRunNodeId, { markdown: fullText });
          }
        },
        {
          onRunStarted: (runId) => {
            if (liveRunNodeId) return;
            liveRunNodeId = startAgentRun(runId, prompt, position);
            setCompletedNodeId(liveRunNodeId);
            window.setTimeout(() => {
              if (!liveRunNodeId) return;
              focusNode(liveRunNodeId);
              void fitView({
                nodes: [{ id: liveRunNodeId }],
                padding: 0.35,
                maxZoom: 1,
                duration: 350,
              });
            }, 0);
          },
          onToolEvent: (toolEv) => {
            const next = [...streamToolsRef.current];
            const index = next.findIndex((event) => event.id === toolEv.id);
            if (index >= 0) next[index] = toolEv;
            else next.push(toolEv);
            streamToolsRef.current = next;
            setStreamTools(next);
            if (liveRunNodeId) {
              updateAgentRun(liveRunNodeId, {
                toolEvents: next,
                summary: toolEv.summary || `${toolEv.label}: ${toolEv.status}`,
              });
            }
          },
          onAsset: (asset) => {
            if (streamAssetsRef.current.some((item) => item.versionId === asset.versionId)) return;
            const next = [...streamAssetsRef.current, asset];
            streamAssetsRef.current = next;
            setStreamAssets(next);
            if (liveRunNodeId) {
              updateAgentRun(liveRunNodeId, { assets: next, primaryAsset: asset });
            }
          },
          onRunError: (message) => {
            if (liveRunNodeId) failAgentRun(liveRunNodeId, message);
          },
        },
      );

      setComposerMessage(result.message);
      const completedResult = result.result;
      if (completedResult) {
        const newTargetId = liveRunNodeId
          ? completeAgentRun(liveRunNodeId, completedResult)
          : addAgentResult(completedResult, position);
        if (result.status === "error" && liveRunNodeId) {
          failAgentRun(liveRunNodeId, result.message);
        }
        setCompletedNodeId(newTargetId || null);
        setValue("");
      } else if (result.status === "error" && liveRunNodeId) {
        failAgentRun(liveRunNodeId, result.message);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "The agent could not run.";
      setComposerMessage(message);
      if (liveRunNodeId) failAgentRun(liveRunNodeId, message);
    } finally {
      await refreshExecutions();
      setBusy(false);
      setStreamStep(null);
    }
  };

  const hasLiveActivity = busy || streamTools.length > 0 || streamAssets.length > 0 || streamText.length > 0;

  if (!composerOpen) {
    return (
      <div className="composer collapsed" id="agent-composer">
        <button
          className="composer-open-btn"
          type="button"
          onClick={() => {
            setComposerOpen(true);
            setActiveTool("agent");
          }}
        >
          <Sparkles size={14} className="inline-block mr-1.5 text-amber-400" />
          Ask the agent
        </button>
      </div>
    );
  }

  return (
    <div className={`composer ${hasLiveActivity ? "composer-active" : ""}`} id="agent-composer">
      {/* AG-UI Live Streaming Activity Panel */}
      {hasLiveActivity ? (
        <div className="composer-live-panel">
          <div className="composer-live-head">
            <div className="composer-live-badge-group">
              <span className="composer-agui-badge">
                <Radio size={12} className={busy ? "composer-pulse-icon text-cyan-400" : "text-emerald-400"} />
                AG-UI Protocol {busy ? "Streaming" : "Ready"}
              </span>
              {streamStep ? (
                <span className="composer-step-badge">
                  <Sparkles size={12} />
                  {streamStep}
                </span>
              ) : null}
            </div>

            <div className="composer-live-actions">
              {completedNodeId ? (
                <button
                  className="composer-focus-cluster-btn nodrag"
                  type="button"
                  title="Focus result on canvas"
                  onClick={() => {
                    focusNode(completedNodeId);
                    void fitView({
                      nodes: [{ id: completedNodeId }],
                      padding: 0.35,
                      maxZoom: 1,
                      duration: 350,
                    });
                  }}
                >
                  <Focus size={13} />
                  <span>View on Canvas</span>
                </button>
              ) : null}
              <button
                className="composer-panel-toggle"
                type="button"
                aria-label={panelExpanded ? "Collapse activity" : "Expand activity"}
                onClick={() => setPanelExpanded(!panelExpanded)}
              >
                {panelExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </button>
              {!busy ? (
                <button
                  className="composer-panel-close"
                  type="button"
                  aria-label="Dismiss stream activity"
                  onClick={() => {
                    setStreamTools([]);
                    setStreamAssets([]);
                    setStreamText("");
                    setCompletedNodeId(null);
                  }}
                >
                  <X size={13} />
                </button>
              ) : null}
            </div>
          </div>

          {panelExpanded ? (
            <div className="composer-live-body">
              {/* Tool Execution Pipeline */}
              {streamTools.length > 0 ? (
                <div className="composer-live-tools" role="list" aria-label="Agent execution trace">
                  {streamTools.map((tool) => {
                    const badge = eventStatusBadge(tool.status);
                    return (
                      <div key={tool.id} role="listitem" className={`composer-tool-chip ${badge}`}>
                        {badge === "running" ? (
                          <LoaderCircle size={12} className="spin" />
                        ) : badge === "completed" ? (
                          <CheckCircle2 size={12} />
                        ) : (
                          <Wand2 size={12} />
                        )}
                        <span className="composer-tool-label">{tool.label}</span>
                        {tool.assets.length > 0 ? (
                          <span className="composer-tool-media-count">{tool.assets.length} media</span>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              ) : null}

              {/* Real-time Generated Media Tray */}
              {streamAssets.length > 0 ? (
                <div className="composer-live-assets" aria-label="Streaming media outputs">
                  {streamAssets.map((asset) => (
                    <div key={asset.versionId} className="composer-live-asset-card">
                      <AssetMedia asset={asset} alt={asset.filename} className="composer-asset-thumb" />
                      <span className="composer-asset-tag">{asset.kind}</span>
                    </div>
                  ))}
                </div>
              ) : null}

              {/* Streaming Reasoning Text */}
              {streamText ? (
                <div className="composer-live-text-wrap">
                  <div className="composer-live-text">
                    <pre>{streamText}</pre>
                    {busy ? <span className="composer-live-cursor">▋</span> : null}
                  </div>
                  <div ref={textEndRef} />
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Input Form */}
      <div className="composer-row">
        <button
          className="icon-btn"
          type="button"
          disabled
          aria-label="Attachments are not connected yet"
          title="Attachments are not connected yet"
        >
          <Paperclip size={16} />
        </button>
        <textarea
          ref={inputRef}
          value={value}
          placeholder="Describe a change, generate video/audio, or @ a node"
          rows={2}
          onFocus={() => setActiveTool("agent")}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void submit();
            }
          }}
        />
        <button
          className="icon-btn"
          type="button"
          aria-label="Mention a node"
          title="Mention a node"
          onClick={() => setValue((current) => `${current}@`)}
        >
          <AtSign size={16} />
        </button>
        <button
          className="send-btn"
          type="button"
          aria-label={busy ? "Agent is streaming" : "Send to agent"}
          disabled={busy || !status?.agent}
          onClick={() => {
            void submit();
          }}
        >
          {busy ? <LoaderCircle className="spin" size={14} /> : <Send size={14} />}
        </button>
      </div>

      {nodes.length > 0 && value.includes("@") ? (
        <div className="mention-list">
          {nodes.slice(0, 6).map((node) => (
            <button
              key={node.id}
              type="button"
              onClick={() =>
                setValue((current) => `${current.replace(/@$/, "")}@${node.data.title.replaceAll(" ", "")} `)
              }
            >
              {node.data.title}
            </button>
          ))}
        </div>
      ) : null}

      <div className="composer-meta">
        <span>
          {busy
            ? "AG-UI Protocol streaming response..."
            : status?.agent
              ? "OpenAI agent ready (AG-UI protocol)"
              : "OpenAI agent unavailable"}
        </span>
        {composerMessage ? <span className="composer-status">{composerMessage}</span> : null}
        <button
          className="composer-collapse"
          type="button"
          aria-label="Collapse agent"
          onClick={() => setComposerOpen(false)}
        >
          <ChevronDown size={14} />
        </button>
      </div>
    </div>
  );
}
