"use client";

import { ChevronDown, ChevronRight, FileText, Focus, LoaderCircle, Sparkles } from "lucide-react";
import type { NodeProps } from "@xyflow/react";
import { useCanvasStore } from "@/lib/canvas/store";
import type { CanvasNodeData } from "@/lib/canvas/types";
import { NodeTag } from "./NodeTag";

function eventClass(status: string): string {
  const normalized = status.toLowerCase();
  if (["failed", "error", "cancelled", "canceled"].includes(normalized)) return "failed";
  if (["queued", "running", "pending"].includes(normalized)) return "running";
  return "completed";
}

export function AgentRunNode({ id, data, selected }: NodeProps) {
  const nodeData = data as CanvasNodeData;
  const run = nodeData.agentRun;
  const updateNodeData = useCanvasStore((state) => state.updateNodeData);
  const toggleAgentRun = useCanvasStore((state) => state.toggleAgentRun);
  const focusNode = useCanvasStore((state) => state.focusNode);
  const nodes = useCanvasStore((state) => state.nodes);

  if (!run) return null;
  const primaryNodeId = run.primaryNodeId || run.finalNodeId;
  const outputCount = run.artifactNodeIds.length + (primaryNodeId ? 1 : 0);

  return (
    <div className="flow-node-wrap node-agent-run">
      <NodeTag
        title={nodeData.title}
        status={nodeData.status}
        selected={selected}
        badge="AG-UI Run"
        onRename={(title) => updateNodeData(id, { title })}
      />
      <article className={`flow-node agent-run-card ${selected ? "selected" : ""}`}>
        <button
          className="agent-run-toggle nodrag"
          type="button"
          aria-expanded={!run.collapsed}
          onClick={() => toggleAgentRun(id)}
        >
          {run.collapsed ? <ChevronRight size={15} /> : <ChevronDown size={15} />}
          <span className="agent-run-kicker"><Sparkles size={14} /> AG-UI Agent Trace</span>
          <span className="agent-run-count">
            {nodeData.status === "running" && run.toolEvents.length === 0
              ? "Live"
              : `${run.toolEvents.length} ${run.toolEvents.length === 1 ? "step" : "steps"}`}
          </span>
        </button>
        <div className="agent-run-summary-row">
          <p>{run.summary}</p>
          {primaryNodeId ? (
            <button
              className="agent-run-focus nodrag"
              type="button"
              title="Focus primary result"
              aria-label="Focus primary result"
              onClick={() => focusNode(primaryNodeId)}
            >
              <Focus size={14} />
            </button>
          ) : null}
        </div>
        {run.collapsed ? (
          <p className="agent-run-collapsed-note">{outputCount} media outputs · click to view execution trace</p>
        ) : (
          <div className="agent-run-details">
            <div className="agent-run-trace" role="table" aria-label="Agent generation trace">
              <div className="agent-run-trace-head" role="row">
                <span role="columnheader">Step</span>
                <span role="columnheader">Status</span>
                <span role="columnheader">Output</span>
              </div>
              {nodeData.status === "running" && run.toolEvents.length === 0 ? (
                <div className="agent-run-trace-row agent-run-trace-waiting" role="row">
                  <span role="cell"><LoaderCircle className="spin" size={13} />Planning request</span>
                  <span role="cell">running</span>
                  <span role="cell">—</span>
                </div>
              ) : null}
              {run.toolEvents.map((event) => {
                const target = event.assets
                  .map((asset) => nodes.find((node) => node.data.output?.versionId === asset.versionId)?.id)
                  .find(Boolean);
                return (
                  <button
                    className="agent-run-trace-row nodrag"
                    key={event.id}
                    type="button"
                    role="row"
                    disabled={!target}
                    onClick={() => target && focusNode(target)}
                  >
                    <span role="cell"><i className={`agent-tool-status ${eventClass(event.status)}`} />{event.label}</span>
                    <span role="cell">{event.status}</span>
                    <span role="cell">{event.assets.length ? `${event.assets.length} media` : "—"}</span>
                  </button>
                );
              })}
            </div>
            {run.markdown ? (
              <details className="agent-run-notes nodrag">
                <summary><FileText size={14} /> Generation notes</summary>
                <pre>{run.markdown}</pre>
              </details>
            ) : null}
          </div>
        )}
      </article>
    </div>
  );
}
