"use client";

import { Handle, Position } from "@xyflow/react";
import type { ReactNode } from "react";
import { NodeToolbar } from "../NodeToolbar";
import { statusLabel, useCanvasStore } from "@/lib/canvas/store";
import { portsForNode } from "@/lib/canvas/tool-registry";
import type { CanvasNodeData } from "@/lib/canvas/types";

type Props = {
  id: string;
  data: CanvasNodeData;
  selected?: boolean;
  widthClass: string;
  children: ReactNode;
};

function promptSummary(data: CanvasNodeData): string {
  const value = data.config.prompt ?? data.config.text ?? data.config.script ?? data.config.lyrics;
  return typeof value === "string" ? value : "";
}

function metaBits(data: CanvasNodeData): string[] {
  const bits: string[] = [];
  for (const key of ["model", "aspect_ratio", "resolution", "size", "duration_seconds", "voice"]) {
    const value = data.config[key];
    if (value !== undefined && value !== null && value !== "") {
      bits.push(String(value));
    }
  }
  return bits.slice(0, 4);
}

export function BaseNode({ id, data, selected, widthClass, children }: Props) {
  const runNode = useCanvasStore((state) => state.runNode);
  const updateNodeData = useCanvasStore((state) => state.updateNodeData);
  const ports = portsForNode(data.toolId, data.kind);
  const summary = promptSummary(data);
  const meta = metaBits(data);
  const canGenerate = Boolean(data.toolId);

  return (
    <article className={`flow-node ${widthClass} ${selected ? "selected" : ""} status-${data.status}`}>
      {selected ? <NodeToolbar id={id} data={data} /> : null}
      {ports.inputs.map((port, index) => (
        <Handle
          key={port.id}
          id={port.id}
          type="target"
          position={Position.Left}
          className={`port port-${port.dataType}`}
          style={{ top: 48 + index * 22 }}
          title={port.label}
        />
      ))}
      {ports.outputs.map((port, index) => (
        <Handle
          key={port.id}
          id={port.id}
          type="source"
          position={Position.Right}
          className={`port port-${port.dataType}`}
          style={{ top: 48 + index * 22 }}
          title={port.label}
        />
      ))}
      <header className="flow-node-head">
        <input
          className="nodrag nopan node-title"
          value={data.title}
          aria-label="Node title"
          onChange={(event) => updateNodeData(id, { title: event.target.value })}
        />
        <span className={`node-status ${data.status}`}>{statusLabel(data.status)}</span>
      </header>
      <div className="flow-node-stage">{children}</div>
      {summary ? <p className="node-prompt">{summary}</p> : null}
      {meta.length > 0 ? <div className="node-meta">{meta.join(" · ")}</div> : null}
      {canGenerate ? (
        <div className="node-actions">
          <button
            className="generate nodrag"
            type="button"
            disabled={data.status === "running" || data.status === "queued"}
            onClick={() => {
              void runNode(id);
            }}
          >
            {data.output ? "Regenerate" : "Generate"}
          </button>
        </div>
      ) : null}
      {data.error ? <p className="node-error">{data.error}</p> : null}
    </article>
  );
}
