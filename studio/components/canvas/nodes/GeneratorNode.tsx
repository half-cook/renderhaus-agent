"use client";

import type { NodeProps } from "@xyflow/react";
import type { CanvasNodeData } from "@/lib/canvas/types";
import { BaseNode } from "./BaseNode";

export function GeneratorNode({ id, data, selected }: NodeProps) {
  const nodeData = data as CanvasNodeData;
  const output = nodeData.output;
  return (
    <BaseNode id={id} data={nodeData} selected={selected} widthClass="node-media">
      {output?.kind === "image" && output.url ? (
        <img className="media-preview" src={output.url} alt={nodeData.title} />
      ) : output?.kind === "video" && output.url ? (
        <video className="media-preview" src={output.url} controls playsInline />
      ) : output?.kind === "audio" && output.url ? (
        <audio className="nodrag" src={output.url} controls />
      ) : (
        <div className="media-placeholder">Output</div>
      )}
    </BaseNode>
  );
}
