"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Bot, Download } from "lucide-react";
import {
  agentResultDownloadFilename,
  agentResultDownloadUrl,
} from "@/lib/canvas/download";
import { useCanvasStore } from "@/lib/canvas/store";
import type { CanvasNodeData } from "@/lib/canvas/types";
import { NodeToolbar } from "../NodeToolbar";
import { AssetDownloadLink, AssetMedia } from "../AssetMedia";
import { NodeTag } from "./NodeTag";

function eventClass(status: string): string {
  const normalized = status.toLowerCase();
  if (["failed", "error", "cancelled", "canceled"].includes(normalized)) {
    return "failed";
  }
  if (["queued", "running", "pending"].includes(normalized)) {
    return "running";
  }
  return "completed";
}

export function AgentResultNode({ id, data, selected }: NodeProps) {
  const nodeData = data as CanvasNodeData;
  const result = nodeData.agentResult;
  const updateNodeData = useCanvasStore((state) => state.updateNodeData);

  if (!result) {
    return null;
  }

  return (
    <div className="flow-node-wrap node-agent-result">
      <NodeTag
        title={nodeData.title}
        status={nodeData.status}
        selected={selected}
        onRename={(title) => updateNodeData(id, { title })}
      />
      {selected ? <NodeToolbar id={id} data={nodeData} /> : null}
      <article className={`flow-node agent-result-card ${selected ? "selected" : ""}`}>
        <header className="agent-result-head">
          <span className="agent-result-kicker">
            <Bot size={15} aria-hidden="true" />
            Agent result
          </span>
          {result.primaryAsset ? (
            <AssetDownloadLink
              className="agent-result-download nodrag"
              asset={result.primaryAsset}
              ariaLabel={`Download ${result.primaryAsset.filename}`}
            >
              <Download size={14} aria-hidden="true" />
              Download
            </AssetDownloadLink>
          ) : (
            <a
              className="agent-result-download nodrag"
              href={agentResultDownloadUrl(result)}
              download={agentResultDownloadFilename(result)}
              aria-label={`Download ${agentResultDownloadFilename(result)}`}
            >
              <Download size={14} aria-hidden="true" />
              Download
            </a>
          )}
        </header>
        <p className="agent-result-summary">{result.summary}</p>
        {result.assets.length > 0 ? (
          <div className="agent-result-assets" aria-label="Created media">
            {result.assets.map((asset, index) => {
              const key = asset.versionId || asset.assetId || `${asset.kind}-${index}`;
              return (
                <AssetMedia
                  key={key}
                  asset={asset}
                  className="agent-result-media"
                  alt="Agent-created result"
                  controls={asset.kind !== "image"}
                />
              );
            })}
          </div>
        ) : null}
        {result.toolEvents.length > 0 ? (
          <ul className="agent-tool-events" aria-label="Tools used">
            {result.toolEvents.map((event, index) => (
              <li key={`${event.name}-${index}`}>
                <span className={`agent-tool-status ${eventClass(event.status)}`} aria-hidden="true" />
                <span>
                  <strong>{event.label}</strong>
                  <small>{event.summary}</small>
                </span>
              </li>
            ))}
          </ul>
        ) : null}
        <pre className="agent-result-content">{result.markdown}</pre>
        <footer className="agent-result-footer">
          <span>{result.filename}</span>
          <span>{result.toolEvents.length} tools used</span>
        </footer>
        <Handle
          id="text"
          type="source"
          position={Position.Right}
          className="port port-text"
          title="Result text"
        />
      </article>
    </div>
  );
}
