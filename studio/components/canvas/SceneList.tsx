"use client";

import { useReactFlow } from "@xyflow/react";
import { FIT_VIEW_PADDING } from "@/lib/canvas/safe-area";
import { isSceneNode, isUntitledSceneTitle, sceneBadge } from "@/lib/canvas/story";
import { useCanvasStore } from "@/lib/canvas/store";

export function SceneList() {
  const nodes = useCanvasStore((state) => state.nodes);
  const selectedNodeIds = useCanvasStore((state) => state.selectedNodeIds);
  const focusNode = useCanvasStore((state) => state.focusNode);
  const { fitView } = useReactFlow();

  // Nodes are always appended on creation (see store.ts), so array order
  // already is creation order -- number untitled scenes off that, the same
  // way Figma numbers unnamed layers "Rectangle 1", "Rectangle 2" ...
  let untitledCount = 0;
  const scenes = nodes
    .filter((node) => isSceneNode(node.data))
    .map((node) => {
      const untitled = isUntitledSceneTitle(node.data.title);
      const displayName = untitled ? `Untitled ${++untitledCount}` : node.data.title || "Untitled";
      return { node, displayName, untitled };
    });

  return (
    <nav className="scene-rail" aria-label="Scenes">
      <p className="scene-rail-head">Scenes</p>
      {scenes.length === 0 ? (
        <p className="scene-rail-empty">Scenes you add will show up here.</p>
      ) : (
        <ul className="scene-rail-list">
          {scenes.map(({ node, displayName, untitled }) => {
            const badge = sceneBadge(node.data);
            const selected = selectedNodeIds.includes(node.id);
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
                  <span className={`scene-rail-dot status-${node.data.status}`} />
                  <span className={untitled ? "scene-rail-name untitled" : "scene-rail-name"}>
                    {displayName}
                  </span>
                  {badge ? <span className="scene-rail-badge">{badge}</span> : null}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );
}
