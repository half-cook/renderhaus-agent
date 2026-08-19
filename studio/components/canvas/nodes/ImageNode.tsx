"use client";

import type { NodeProps } from "@xyflow/react";
import type { CanvasNodeData } from "@/lib/canvas/types";
import { SceneCard } from "./SceneCard";

export function ImageNode({ id, data, selected }: NodeProps) {
  return <SceneCard id={id} data={data as CanvasNodeData} selected={selected} />;
}
