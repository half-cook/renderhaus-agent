"use client";

import type { NodeProps } from "@xyflow/react";
import type { CanvasNodeData } from "@/lib/canvas/types";
import { AssetMedia } from "../AssetMedia";
import { BaseNode } from "./BaseNode";

export function GeneratorNode({ id, data, selected }: NodeProps) {
  const nodeData = data as CanvasNodeData;
  const output = nodeData.output;
  return (
    <BaseNode id={id} data={nodeData} selected={selected} widthClass="node-media">
      {output?.kind === "image" ? (
        <AssetMedia asset={output} className="media-preview" alt={nodeData.title} />
      ) : output?.kind === "video" ? (
        <AssetMedia asset={output} className="media-preview" alt={nodeData.title} controls />
      ) : output?.kind === "audio" ? (
        <AssetMedia asset={output} className="nodrag" alt={nodeData.title} controls />
      ) : (
        <div className="media-placeholder">Output</div>
      )}
    </BaseNode>
  );
}
