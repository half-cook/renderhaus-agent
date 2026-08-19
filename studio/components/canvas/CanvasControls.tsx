"use client";

import { MiniMap, Panel, useReactFlow } from "@xyflow/react";
import { Maximize2, Minus, Plus } from "lucide-react";
import { FIT_VIEW_PADDING } from "@/lib/canvas/safe-area";
import { useCanvasStore } from "@/lib/canvas/store";

export function CanvasControls() {
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  const zoom = useCanvasStore((state) => state.viewport.zoom);
  return (
    <>
      <MiniMap pannable zoomable position="bottom-right" className="minimap" />
      <Panel position="bottom-right" className="canvas-controls">
        <div className="zoombar">
          <button type="button" aria-label="Zoom out" onClick={() => void zoomOut()}>
            <Minus size={14} />
          </button>
          <span>{Math.round(zoom * 100)}%</span>
          <button type="button" aria-label="Zoom in" onClick={() => void zoomIn()}>
            <Plus size={14} />
          </button>
          <button
            type="button"
            aria-label="Fit view"
            onClick={() => void fitView({ padding: FIT_VIEW_PADDING })}
          >
            <Maximize2 size={14} />
          </button>
        </div>
      </Panel>
    </>
  );
}
