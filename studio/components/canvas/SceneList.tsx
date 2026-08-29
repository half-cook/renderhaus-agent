"use client";

import { useReactFlow } from "@xyflow/react";
import {
  Bot,
  FileText,
  Image as ImageIcon,
  LayoutGrid,
  Music,
  Sparkles,
  Type,
  Video,
} from "lucide-react";
import { FIT_VIEW_PADDING } from "@/lib/canvas/safe-area";
import { isUntitledSceneTitle, sceneBadge } from "@/lib/canvas/story";
import { useCanvasStore } from "@/lib/canvas/store";
import type { CreativeNodeKind } from "@/lib/canvas/types";

const KIND_ICON: Record<CreativeNodeKind, typeof Type> = {
  text: Type,
  image: ImageIcon,
  video: Video,
  audio: Music,
  generator: Sparkles,
  storyboard: LayoutGrid,
  agentResult: FileText,
  agentRun: Bot,
};

export function SceneList() {
  const nodes = useCanvasStore((state) => state.nodes);
  const selectedNodeIds = useCanvasStore((state) => state.selectedNodeIds);
  const focusNode = useCanvasStore((state) => state.focusNode);
  const { fitView } = useReactFlow();

  // Nodes are always appended on creation (see store.ts), so array order
  // already is creation order -- number untitled scenes off that, the same
  // way Figma numbers unnamed layers "Rectangle 1", "Rectangle 2" ...
  let untitledCount = 0;
  // Every node on the canvas, not just scene-kind ones -- mirrors Figma's
  // own layers panel, which lists every layer regardless of type rather
  // than filtering down to one kind.
  const layers = nodes.map((node) => {
    const untitled = isUntitledSceneTitle(node.data.title);
    const displayName = untitled ? `Untitled ${++untitledCount}` : node.data.title || "Untitled";
    return { node, displayName, untitled };
  });

  return (
    <nav className="scene-rail" aria-label="Layers">
      <p className="scene-rail-head">Layers</p>
      {layers.length === 0 ? (
        <p className="scene-rail-empty">Nodes you add will show up here.</p>
      ) : (
        <ul className="scene-rail-list">
          {layers.map(({ node, displayName, untitled }) => {
            const badge = sceneBadge(node.data);
            const selected = selectedNodeIds.includes(node.id);
            const Icon = KIND_ICON[node.data.kind];
            return (
              <li key={node.id}>
                <button
                  type="button"
                  className={selected ? "scene-rail-item active" : "scene-rail-item"}
                  onClick={() => {
                    focusNode(node.id);
                    void fitView({
                      nodes: [{ id: node.id }],
                      padding: FIT_VIEW_PADDING,
                      maxZoom: 1,
                      duration: 300,
                    });
                  }}
                >
                  <Icon className="scene-rail-icon" size={14} />
                  <span className={untitled ? "scene-rail-name untitled" : "scene-rail-name"}>
                    {displayName}
                  </span>
                  {badge ? <span className="scene-rail-badge">{badge}</span> : null}
                  <span className={`scene-rail-dot status-${node.data.status}`} />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );
}
