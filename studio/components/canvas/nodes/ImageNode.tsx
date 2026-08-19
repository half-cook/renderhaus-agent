"use client";

import type { NodeProps } from "@xyflow/react";
import type { CanvasNodeData } from "@/lib/canvas/types";
import { BaseNode } from "./BaseNode";

export function ImageNode({ id, data, selected }: NodeProps) {
  const nodeData = data as CanvasNodeData;
  return (
    <BaseNode id={id} data={nodeData} selected={selected} widthClass="node-media">
      {nodeData.output?.url ? (
        <img className="media-preview" src={nodeData.output.url} alt={nodeData.title} />
      ) : (
        <div className="media-placeholder">Image</div>
      )}
    </BaseNode>
  );
}
