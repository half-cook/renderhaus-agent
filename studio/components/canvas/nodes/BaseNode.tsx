"use client";

import { Handle, Position } from "@xyflow/react";
import type { ReactNode } from "react";
import { NodeToolbar } from "../NodeToolbar";
import { NodeTag } from "./NodeTag";
import { generateBlockers } from "@/lib/canvas/generate-readiness";
import { choiceLabel } from "@/lib/canvas/model-labels";
import { schemaFor, type CanvasNodeData } from "@/lib/canvas/types";
import { useCanvasStore } from "@/lib/canvas/store";
import { portsForNode } from "@/lib/canvas/tool-registry";

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
      bits.push(key === "model" ? choiceLabel("model", String(value)) : String(value));
    }
  }
  return bits.slice(0, 4);
}

export function BaseNode({ id, data, selected, widthClass, children }: Props) {
  const runNode = useCanvasStore((state) => state.runNode);
  const updateNodeData = useCanvasStore((state) => state.updateNodeData);
  const providers = useCanvasStore((state) => state.providers);
  const edges = useCanvasStore((state) => state.edges);
  const ports = portsForNode(data.toolId, data.kind);
  const summary = promptSummary(data);
  const meta = metaBits(data);
  const canGenerate = Boolean(data.toolId);
  const schema = schemaFor(providers, data.providerId, data.toolName);
  const connectedFields = edges
    .filter((edge) => edge.target === id)
    .map((edge) => edge.data?.targetField)
    .filter((field): field is string => Boolean(field));
  const blockers = generateBlockers(data, schema, connectedFields);
  const generateDisabled =
    data.status === "running" || data.status === "queued" || blockers.length > 0;

  return (
    <div className={`flow-node-wrap ${widthClass}`}>
      <NodeTag
        title={data.title}
        status={data.status}
        selected={selected}
        onRename={(title) => updateNodeData(id, { title })}
      />
      {selected ? <NodeToolbar id={id} data={data} /> : null}
      <article className={`flow-node ${selected ? "selected" : ""} status-${data.status}`}>
        {ports.inputs.map((port, index) => (
          <Handle
            key={port.id}
            id={port.id}
            type="target"
            position={Position.Left}
            className={`port port-${port.dataType}`}
            style={{ top: 28 + index * 22 }}
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
            style={{ top: 28 + index * 22 }}
            title={port.label}
          />
        ))}
        <div className="flow-node-stage">{children}</div>
        {summary ? <p className="node-prompt">{summary}</p> : null}
        {meta.length > 0 ? <div className="node-meta">{meta.join(" · ")}</div> : null}
        {canGenerate ? (
          <div className="node-actions">
            <button
              className="generate nodrag"
              type="button"
              disabled={generateDisabled}
              title={blockers[0]}
              onClick={() => {
                void runNode(id);
              }}
            >
              {data.output ? "Regenerate" : "Generate"}
            </button>
            {blockers.length > 0 ? <p className="generate-hint">{blockers[0]}</p> : null}
          </div>
        ) : null}
        {data.error ? <p className="node-error">{data.error}</p> : null}
      </article>
    </div>
  );
}
