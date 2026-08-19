"use client";

import { Handle, Position } from "@xyflow/react";
import { NodeToolbar } from "../NodeToolbar";
import { NodeTag } from "./NodeTag";
import { generateBlockers } from "@/lib/canvas/generate-readiness";
import { aspectLabel, durationLabel, sceneBadge, variantPosition } from "@/lib/canvas/story";
import { schemaFor, type CanvasNodeData } from "@/lib/canvas/types";
import { useCanvasStore } from "@/lib/canvas/store";
import { portsForNode } from "@/lib/canvas/tool-registry";

type Props = {
  id: string;
  data: CanvasNodeData;
  selected?: boolean;
};

export function SceneCard({ id, data, selected }: Props) {
  const runNode = useCanvasStore((state) => state.runNode);
  const updateNodeData = useCanvasStore((state) => state.updateNodeData);
  const setInspectorOpen = useCanvasStore((state) => state.setInspectorOpen);
  const setApproved = useCanvasStore((state) => state.setApproved);
  const cycleVariant = useCanvasStore((state) => state.cycleVariant);
  const providers = useCanvasStore((state) => state.providers);
  const edges = useCanvasStore((state) => state.edges);
  const ports = portsForNode(data.toolId, data.kind);
  const schema = schemaFor(providers, data.providerId, data.toolName);
  const connectedFields = edges
    .filter((edge) => edge.target === id)
    .map((edge) => edge.data?.targetField)
    .filter((field): field is string => Boolean(field));
  const blockers = generateBlockers(data, schema, connectedFields);
  const busy = data.status === "running" || data.status === "queued";
  const generateDisabled = busy || blockers.length > 0;
  const variants = variantPosition(data);
  const duration = durationLabel(data);
  const aspect = aspectLabel(data);
  const meta = [duration, aspect].filter(Boolean).join(" · ");

  return (
    <div className="flow-node-wrap node-media">
      <NodeTag
        title={data.title}
        status={data.status}
        selected={selected}
        badge={sceneBadge(data)}
        onRename={(title) => updateNodeData(id, { title })}
      />
      {selected ? <NodeToolbar id={id} data={data} /> : null}
      <article
        className={`flow-node scene-card ${selected ? "selected" : ""} ${data.approved ? "approved" : ""} status-${data.status}`}
      >
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
        <div className="scene-stage">
          {data.kind === "video" && data.output?.url ? (
            <video className="media-preview" src={data.output.url} controls playsInline />
          ) : data.output?.url ? (
            <img className="media-preview" src={data.output.url} alt={data.title} />
          ) : (
            <div className="media-placeholder">
              <span>{data.kind === "video" ? "No clip yet" : "No still yet"}</span>
              {data.toolId ? (
                <button
                  className="generate nodrag"
                  type="button"
                  disabled={generateDisabled}
                  title={blockers[0]}
                  onClick={() => {
                    void runNode(id);
                  }}
                >
                  {busy ? "Generating" : "Generate"}
                </button>
              ) : null}
              {blockers.length > 0 ? <p className="generate-hint">{blockers[0]}</p> : null}
            </div>
          )}
        </div>
        <footer className="scene-footer">
          <p className="scene-meta">{meta || "Scene"}</p>
          <div className="scene-actions">
            <button
              className="text-btn nodrag"
              type="button"
              onClick={() => setInspectorOpen(true)}
            >
              Edit
            </button>
            {variants.total > 1 ? (
              <button
                className="text-btn nodrag"
                type="button"
                aria-label="Show next variant"
                onClick={() => cycleVariant(id, 1)}
              >
                {variants.current} of {variants.total}
              </button>
            ) : null}
            <button
              className={`text-btn nodrag ${data.approved ? "approved" : ""}`}
              type="button"
              onClick={() => setApproved(id, !data.approved)}
            >
              {data.approved ? "Approved" : "Approve"}
            </button>
          </div>
        </footer>
        {data.error ? <p className="node-error">{data.error}</p> : null}
      </article>
    </div>
  );
}
