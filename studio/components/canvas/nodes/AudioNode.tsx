"use client";

import type { NodeProps } from "@xyflow/react";
import type { CanvasNodeData } from "@/lib/canvas/types";
import { BaseNode } from "./BaseNode";

export function AudioNode({ id, data, selected }: NodeProps) {
  const nodeData = data as CanvasNodeData;
  return (
    <BaseNode id={id} data={nodeData} selected={selected} widthClass="node-media">
      <div className="audio-stage">
        <div className="waveform" aria-hidden="true">
          {Array.from({ length: 24 }, (_, index) => (
            <span key={index} style={{ height: `${12 + ((index * 7) % 28)}px` }} />
          ))}
        </div>
        {nodeData.output?.url ? (
          <audio className="nodrag" src={nodeData.output.url} controls />
        ) : (
          <p className="media-placeholder-copy">No audio yet</p>
        )}
      </div>
    </BaseNode>
  );
}
