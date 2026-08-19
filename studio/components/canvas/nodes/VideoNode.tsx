"use client";

import type { NodeProps } from "@xyflow/react";
import type { CanvasNodeData } from "@/lib/canvas/types";
import { BaseNode } from "./BaseNode";

export function VideoNode({ id, data, selected }: NodeProps) {
  const nodeData = data as CanvasNodeData;
  return (
    <BaseNode id={id} data={nodeData} selected={selected} widthClass="node-media">
      {nodeData.output?.url ? (
        <video className="media-preview" src={nodeData.output.url} controls playsInline />
      ) : (
        <div className="media-placeholder">Video</div>
      )}
    </BaseNode>
  );
}
