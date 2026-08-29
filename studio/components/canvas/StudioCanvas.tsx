"use client";

import {
  Background,
  BackgroundVariant,
  ReactFlow,
  SelectionMode,
  useReactFlow,
  type Connection,
  type Edge,
  type OnMove,
} from "@xyflow/react";
import { useCallback, useRef, useState } from "react";
import { isCompatibleConnection } from "@/lib/canvas/connection-validation";
import { FIT_VIEW_PADDING } from "@/lib/canvas/safe-area";
import { useCanvasStore } from "@/lib/canvas/store";
import type { CreativeNodeKind } from "@/lib/canvas/types";
import { CanvasControls } from "./CanvasControls";
import { nodeTypes } from "./nodes";

type MenuState = { x: number; y: number; flowX: number; flowY: number } | null;

const QUICK_ADD: Array<{ label: string; kind: CreativeNodeKind; toolId?: string }> = [
  { label: "Text", kind: "text" },
  { label: "Scene", kind: "image", toolId: "image.generate" },
  { label: "Video", kind: "video", toolId: "video.generate" },
  { label: "Music", kind: "audio", toolId: "music.generate" },
  { label: "Voiceover", kind: "audio", toolId: "voice.generate" },
  { label: "Storyboard", kind: "storyboard" },
];

const FIT_VIEW_OPTIONS = { padding: FIT_VIEW_PADDING };
const DEFAULT_EDGE_OPTIONS = { type: "smoothstep" as const };
const CONNECTION_LINE_STYLE = { stroke: "#5eead4", strokeWidth: 1.5 };
const PAN_ON_DRAG_SELECT: number[] = [1, 2];
const PRO_OPTIONS = { hideAttribution: true };
const DELETE_KEY_CODE = ["Backspace", "Delete"];
const MULTI_SELECTION_KEY_CODE = ["Meta", "Control"];

const EMPTY_ACTIONS: Array<{
  label: string;
  hint: string;
  kind?: CreativeNodeKind;
  toolId?: string;
  upload?: boolean;
  sequence?: boolean;
}> = [
  { label: "Add scene", hint: "Start from a still", kind: "image", toolId: "image.generate" },
  { label: "Start sequence", hint: "Three empty scenes in a row", sequence: true },
  { label: "Upload reference", hint: "Drop in a still or clip", upload: true },
  { label: "Add text", hint: "Write a prompt or script", kind: "text" },
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
  const addUploadNode = useCanvasStore((state) => state.addUploadNode);
  const startSequence = useCanvasStore((state) => state.startSequence);
  const pushHistory = useCanvasStore((state) => state.pushHistory);
  const persist = useCanvasStore((state) => state.persist);
  const { screenToFlowPosition } = useReactFlow();
  const [menu, setMenu] = useState<MenuState>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const isValidConnection = useCallback(
    (connection: Connection | Edge) => isCompatibleConnection(connection, useCanvasStore.getState().nodes).ok,
    [],
  );

  const handleSelectionChange = useCallback(
    ({ nodes: selected }: { nodes: Array<{ id: string }> }) => {
      onSelectionChange(selected.map((node) => node.id));
    },
    [onSelectionChange],
  );

  const handleMoveEnd: OnMove = useCallback(
    (_event, viewport) => {
      setViewport(viewport);
    },
    [setViewport],
  );

  const center = () => {
    const pane = document.querySelector(".react-flow");
    const rect = pane?.getBoundingClientRect();
    return screenToFlowPosition({
      x: (rect?.left || 0) + (rect?.width || 800) / 2,
      y: (rect?.top || 0) + (rect?.height || 600) / 2,
    });
  };

  return (
    <div className="flow-host" data-tool={activeTool}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        isValidConnection={isValidConnection}
        onSelectionChange={handleSelectionChange}
        onMoveEnd={handleMoveEnd}
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
        fitViewOptions={FIT_VIEW_OPTIONS}
        selectionOnDrag={activeTool === "select"}
        panOnDrag={activeTool === "hand" ? true : PAN_ON_DRAG_SELECT}
        selectionMode={SelectionMode.Partial}
        deleteKeyCode={DELETE_KEY_CODE}
        multiSelectionKeyCode={MULTI_SELECTION_KEY_CODE}
        panOnScroll
        minZoom={0.2}
        maxZoom={2.2}
        defaultEdgeOptions={DEFAULT_EDGE_OPTIONS}
        connectionLineStyle={CONNECTION_LINE_STYLE}
        proOptions={PRO_OPTIONS}
      >
        <Background id="grid" variant={BackgroundVariant.Dots} gap={24} size={1.5} color="var(--grid)" />
        <CanvasControls />
      </ReactFlow>
      {nodes.length === 0 ? (
        <div className="empty-canvas">
          <h1>Start the storyboard</h1>
          <p>Scenes run left to right. Approve the ones that belong in the final sequence.</p>
          <div className="empty-actions">
            {EMPTY_ACTIONS.map((action) => (
              <button
                key={action.label}
                className="empty-action"
                type="button"
                onClick={() => {
                  if (action.upload) {
                    fileRef.current?.click();
                    return;
                  }
                  if (action.sequence) {
                    startSequence(center());
                    return;
                  }
                  if (action.kind) {
                    addCreativeNode({ kind: action.kind, toolId: action.toolId, position: center() });
                  }
                }}
              >
                <span>{action.label}</span>
                <small>{action.hint}</small>
              </button>
            ))}
          </div>
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
      <input
        ref={fileRef}
        type="file"
        hidden
        accept="image/*,video/*,audio/*"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) {
            void addUploadNode(file, center());
          }
        }}
      />
    </div>
  );
}
