"use client";

import { ReactFlowProvider, useReactFlow } from "@xyflow/react";
import { useEffect } from "react";
import { useCanvasStore } from "@/lib/canvas/store";
import { FIT_VIEW_PADDING } from "@/lib/canvas/safe-area";
import type { CreativeNodeKind } from "@/lib/canvas/types";
import { AgentComposer } from "./AgentComposer";
import { CanvasHeader } from "./CanvasHeader";
import { NodeInspector } from "./NodeInspector";
import { SequenceStrip } from "./SequenceStrip";
import { StudioCanvas } from "./StudioCanvas";
import { ToolRail } from "./ToolRail";
import "@xyflow/react/dist/style.css";

function Workspace() {
  const hydrate = useCanvasStore((state) => state.hydrate);
  const loadCatalog = useCanvasStore((state) => state.loadCatalog);
  const hydrated = useCanvasStore((state) => state.hydrated);
  const addCreativeNode = useCanvasStore((state) => state.addCreativeNode);
  const addUploadNode = useCanvasStore((state) => state.addUploadNode);
  const undo = useCanvasStore((state) => state.undo);
  const redo = useCanvasStore((state) => state.redo);
  const setActiveTool = useCanvasStore((state) => state.setActiveTool);
  const inspectorVisible = useCanvasStore(
    (state) => state.inspectorOpen && state.selectedNodeIds.length === 1,
  );
  const selectedNodeId = useCanvasStore((state) =>
    state.selectedNodeIds.length === 1 ? state.selectedNodeIds[0] : undefined,
  );
  const composerOpen = useCanvasStore((state) => state.composerOpen);
  const { screenToFlowPosition, fitView } = useReactFlow();

  useEffect(() => {
    hydrate();
    void loadCatalog();
  }, [hydrate, loadCatalog]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const meta = event.metaKey || event.ctrlKey;
      if (meta && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) {
          redo();
        } else {
          undo();
        }
      }
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
        return;
      }
      if (event.key.toLowerCase() === "v") {
        setActiveTool("select");
      }
      if (event.key.toLowerCase() === "h") {
        setActiveTool("hand");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [redo, setActiveTool, undo]);

  useEffect(() => {
    if (!selectedNodeId || (!inspectorVisible && !composerOpen)) return;
    // Only refocus after a selection or panel transition. Camera movement
    // updates the store too, and must remain under the user's control.
    const timer = window.setTimeout(() => {
      void fitView({
        nodes: [{ id: selectedNodeId }],
        padding: FIT_VIEW_PADDING,
        maxZoom: 1,
        duration: 180,
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [composerOpen, fitView, inspectorVisible, selectedNodeId]);

  const center = () => {
    const pane = document.querySelector(".react-flow");
    const rect = pane?.getBoundingClientRect();
    return screenToFlowPosition({
      x: (rect?.left || 0) + (rect?.width || 800) / 2,
      y: (rect?.top || 0) + (rect?.height || 600) / 2,
    });
  };

  if (!hydrated) {
    return <div className="workspace-loading">Loading canvas</div>;
  }

  return (
    <div
      className={[
        "workspace",
        inspectorVisible ? "inspector-open" : "",
        composerOpen ? "composer-open" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <a className="skip-link" href="#canvas">
        Skip to canvas
      </a>
      <CanvasHeader />
      <ToolRail
        onPlace={(kind: CreativeNodeKind, toolId?: string) => {
          addCreativeNode({ kind, toolId, position: center() });
        }}
        onUpload={(file) => {
          void addUploadNode(file, center());
        }}
      />
      <main id="canvas" className="workspace-main">
        <StudioCanvas />
      </main>
      <NodeInspector />
      <AgentComposer />
      <SequenceStrip />
    </div>
  );
}

export function CanvasShell() {
  return (
    <ReactFlowProvider>
      <Workspace />
    </ReactFlowProvider>
  );
}
