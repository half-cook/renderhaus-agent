"use client";

import type { NodeProps } from "@xyflow/react";
import { useCanvasStore } from "@/lib/canvas/store";
import type { CanvasNodeData } from "@/lib/canvas/types";
import { BaseNode } from "./BaseNode";

export function TextNode({ id, data, selected }: NodeProps) {
  const nodeData = data as CanvasNodeData;
  const updateNodeConfig = useCanvasStore((state) => state.updateNodeConfig);
  return (
    <BaseNode id={id} data={nodeData} selected={selected} widthClass="node-text">
      <textarea
        className="nodrag nopan text-stage"
        value={String(nodeData.config.prompt ?? "")}
        placeholder="Write a prompt or scene note"
        onChange={(event) => updateNodeConfig(id, "prompt", event.target.value)}
      />
    </BaseNode>
  );
}
