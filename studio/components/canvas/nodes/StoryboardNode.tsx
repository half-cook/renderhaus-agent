"use client";

import type { NodeProps } from "@xyflow/react";
import { useCanvasStore } from "@/lib/canvas/store";
import type { CanvasNodeData } from "@/lib/canvas/types";
import { BaseNode } from "./BaseNode";
import { AssetMedia } from "../AssetMedia";

export function StoryboardNode({ id, data, selected }: NodeProps) {
  const nodeData = data as CanvasNodeData;
  const nodes = useCanvasStore((state) => state.nodes);
  const edges = useCanvasStore((state) => state.edges);
  const connected = edges
    .filter((edge) => edge.target === id)
    .map((edge) => nodes.find((node) => node.id === edge.source))
    .filter((node): node is NonNullable<typeof node> => Boolean(node));
  return (
    <BaseNode id={id} data={nodeData} selected={selected} widthClass="node-media">
      <div className="storyboard-grid">
        {connected.length === 0 ? (
          <div className="media-placeholder">Connect shots here</div>
        ) : (
          connected.map((node) =>
            node.data.output ? (
              <AssetMedia
                key={node.id}
                asset={node.data.output}
                className="storyboard-shot"
                alt={node.data.title}
                muted
              />
            ) : (
              <div key={node.id} className="storyboard-shot empty">
                {node.data.title}
              </div>
            ),
          )
        )}
      </div>
    </BaseNode>
  );
}
