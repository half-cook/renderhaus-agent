"use client";

import { ReactFlowProvider, useReactFlow } from "@xyflow/react";
import { useEffect, useState } from "react";
import { useCanvasStore } from "@/lib/canvas/store";
import { FIT_VIEW_PADDING } from "@/lib/canvas/safe-area";
import type { CreativeNodeKind, DockPosition } from "@/lib/canvas/types";
import { AgentDock } from "./AgentDock";
import { AsciiPanel } from "./AsciiPanel";
import { CanvasHeader } from "./CanvasHeader";
import { NodeInspector } from "./NodeInspector";
import { SceneList } from "./SceneList";
import { StudioCanvas } from "./StudioCanvas";
import { ToolRail } from "./ToolRail";
import "@xyflow/react/dist/style.css";

const DOCK_STORAGE_KEY = "renderhaus.studio.dock.v2";

type DockState = { dock: DockPosition; x: number; y: number };

function isDockPosition(value: unknown): value is DockPosition {
  return value === "top" || value === "bottom" || value === "left" || value === "right" || value === "free";
}

function Workspace() {
  const [dockState, setDockState] = useState<DockState>({ dock: "bottom", x: 0, y: 0 });
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
  const agentOpen = useCanvasStore((state) => state.agentOpen);
  const setAgentOpen = useCanvasStore((state) => state.setAgentOpen);
  const { screenToFlowPosition, fitView } = useReactFlow();

  useEffect(() => {
    hydrate();
    void loadCatalog();
  }, [hydrate, loadCatalog]);

  useEffect(() => {
    // Wait for `hydrated`: until then Workspace renders the loading div in
    // place of the real layout, so .workspace/.flow-host/.tool-rail don't
    // exist yet and the clamp below would silently no-op on a fresh load.
    if (!hydrated) {
      return;
    }
    const raw = localStorage.getItem(DOCK_STORAGE_KEY);
    if (!raw) {
      return;
    }
    try {
      const parsed = JSON.parse(raw);
      if (isDockPosition(parsed?.dock) && typeof parsed?.x === "number" && typeof parsed?.y === "number") {
        if (parsed.dock === "free") {
          // A free position saved on a larger window (or before the safe
          // area narrowed, e.g. the inspector opening) can land outside
          // the current viewport -- the dock picker to drag it back lives
          // on the rail itself, so an off-screen rail would be
          // unreachable without clearing localStorage. Clamp against the
          // same safe area ToolRail's own drag already confines it to.
          const workspaceEl = document.querySelector(".workspace");
          const flowHostEl = workspaceEl?.querySelector(".flow-host");
          const railEl = workspaceEl?.querySelector(".tool-rail");
          if (workspaceEl && flowHostEl && railEl) {
            const workspaceRect = workspaceEl.getBoundingClientRect();
            const flowRect = flowHostEl.getBoundingClientRect();
            const railRect = railEl.getBoundingClientRect();
            const minX = flowRect.left - workspaceRect.left;
            const minY = flowRect.top - workspaceRect.top;
            const maxX = Math.max(flowRect.right - workspaceRect.left - railRect.width, minX);
            const maxY = Math.max(workspaceRect.height - railRect.height, minY);
            parsed.x = Math.min(Math.max(parsed.x, minX), maxX);
            parsed.y = Math.min(Math.max(parsed.y, minY), maxY);
          }
        }
        setDockState(parsed);
      }
    } catch {
      // Ignore a corrupt/old-format value and fall back to the default.
    }
  }, [hydrated]);

  const changeDock = (next: DockState) => {
    setDockState(next);
    localStorage.setItem(DOCK_STORAGE_KEY, JSON.stringify(next));
  };

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
      if (meta && event.key.toLowerCase() === "j") {
        event.preventDefault();
        if (agentOpen) {
          setAgentOpen(false);
        } else {
          setActiveTool("agent");
        }
        return;
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
  }, [agentOpen, redo, setActiveTool, setAgentOpen, undo]);

  useEffect(() => {
    if (!selectedNodeId || (!inspectorVisible && !agentOpen)) return;
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
  }, [agentOpen, fitView, inspectorVisible, selectedNodeId]);

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
        agentOpen ? "agent-open" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      data-dock={dockState.dock}
    >
      <a className="skip-link" href="#canvas">
        Skip to canvas
      </a>
      <CanvasHeader />
      <SceneList />
      <ToolRail
        dock={dockState.dock}
        freeX={dockState.x}
        freeY={dockState.y}
        onDockChange={(next) => changeDock({ ...dockState, dock: next })}
        onFreeMove={(x, y) => changeDock({ dock: "free", x, y })}
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
      <AgentDock />
      <AsciiPanel />
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
