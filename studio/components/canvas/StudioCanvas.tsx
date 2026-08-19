"use client";

import {
  Background,
  BackgroundVariant,
  ReactFlow,
  SelectionMode,
  useReactFlow,
  type Connection,
  type Edge,
} from "@xyflow/react";
import { useCallback, useState } from "react";
import { isCompatibleConnection } from "@/lib/canvas/connection-validation";
import { useCanvasStore } from "@/lib/canvas/store";
import type { CreativeNodeKind } from "@/lib/canvas/types";
import { CanvasControls } from "./CanvasControls";
import { nodeTypes } from "./nodes";

type MenuState = { x: number; y: number; flowX: number; flowY: number } | null;

const QUICK_ADD: Array<{ label: string; kind: CreativeNodeKind; toolId?: string }> = [
  { label: "Text", kind: "text" },
  { label: "Image", kind: "image", toolId: "image.generate" },
  { label: "Video", kind: "video", toolId: "video.generate" },
  { label: "Music", kind: "audio", toolId: "music.generate" },
  { label: "Voiceover", kind: "audio", toolId: "voice.generate" },
  { label: "Storyboard", kind: "storyboard" },
];

export function StudioCanvas() {
  const nodes = useCanvasStore((state) => state.nodes);
  const edges = useCanvasStore((state) => state.edges);
  const activeTool = useCanvasStore((state) => state.activeTool);
  const connectionHint = useCanvasStore((state) => state.connectionHint);
  const onNodesChange = useCanvasStore((state) => state.onNodesChange);
  const onEdgesChange = useCanvasStore((state) => state.onEdgesChange);
  const onConnect = useCanvasStore((state) => state.onConnect);
  const onSelectionChange = useCanvasStore((state) => state.onSelectionChange);
  const setViewport = useCanvasStore((state) => state.setViewport);
  const addCreativeNode = useCanvasStore((state) => state.addCreativeNode);
  const pushHistory = useCanvasStore((state) => state.pushHistory);
  const persist = useCanvasStore((state) => state.persist);
  const { screenToFlowPosition } = useReactFlow();
  const [menu, setMenu] = useState<MenuState>(null);

  const isValidConnection = useCallback(
    (connection: Connection | Edge) => isCompatibleConnection(connection, useCanvasStore.getState().nodes).ok,
    [],
  );

  return (
    <div className="flow-host">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        isValidConnection={isValidConnection}
        onSelectionChange={({ nodes: selected }) => onSelectionChange(selected.map((node) => node.id))}
        onMoveEnd={(_, viewport) => setViewport(viewport)}
        onNodeDragStart={() => pushHistory()}
        onNodeDragStop={() => persist()}
        onPaneClick={(event) => {
          if (event.detail === 2) {
            const bounds = (event.currentTarget as HTMLElement).getBoundingClientRect();
            const flow = screenToFlowPosition({ x: event.clientX, y: event.clientY });
            setMenu({
              x: event.clientX - bounds.left,
              y: event.clientY - bounds.top,
              flowX: flow.x,
              flowY: flow.y,
            });
            return;
          }
          setMenu(null);
        }}
        onPaneContextMenu={(event) => {
          event.preventDefault();
          const bounds = (event.currentTarget as HTMLElement).getBoundingClientRect();
          const flow = screenToFlowPosition({ x: event.clientX, y: event.clientY });
          setMenu({
            x: event.clientX - bounds.left,
            y: event.clientY - bounds.top,
            flowX: flow.x,
            flowY: flow.y,
          });
        }}
        defaultViewport={useCanvasStore.getState().viewport}
        selectionOnDrag={activeTool === "select"}
        panOnDrag={activeTool === "hand" ? true : [1, 2]}
        selectionMode={SelectionMode.Partial}
        deleteKeyCode={["Backspace", "Delete"]}
        multiSelectionKeyCode={["Meta", "Control"]}
        panOnScroll
        minZoom={0.2}
        maxZoom={2.2}
        defaultEdgeOptions={{ type: "smoothstep" }}
        connectionLineStyle={{ stroke: "#5eead4", strokeWidth: 1.5 }}
        proOptions={{ hideAttribution: true }}
      >
        <Background id="grid" variant={BackgroundVariant.Dots} gap={24} size={1} color="#252529" />
        <CanvasControls />
      </ReactFlow>
      {nodes.length === 0 ? (
        <div className="empty-canvas">
          <h1>Start with a shot</h1>
          <p>Add text, generate an image, or upload a reference. Connect outputs into the next node.</p>
        </div>
      ) : null}
      {connectionHint ? <div className="connection-hint">{connectionHint}</div> : null}
      {menu ? (
        <div className="quick-add" style={{ left: menu.x, top: menu.y }}>
          {QUICK_ADD.map((item) => (
            <button
              key={item.label}
              type="button"
              onClick={() => {
                addCreativeNode({
                  kind: item.kind,
                  toolId: item.toolId,
                  position: { x: menu.flowX, y: menu.flowY },
                });
                setMenu(null);
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
