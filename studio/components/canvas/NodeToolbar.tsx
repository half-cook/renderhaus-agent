"use client";

import { NodeToolbar as FlowToolbar, Position } from "@xyflow/react";
import { Copy, Download, LayoutGrid, Pencil, RefreshCw, Trash2, Video } from "lucide-react";
import type { CanvasNodeData } from "@/lib/canvas/types";
import { useCanvasStore } from "@/lib/canvas/store";

type Props = {
  id: string;
  data: CanvasNodeData;
};

export function NodeToolbar({ id, data }: Props) {
  const runNode = useCanvasStore((state) => state.runNode);
  const setInspectorOpen = useCanvasStore((state) => state.setInspectorOpen);
  const duplicateSelected = useCanvasStore((state) => state.duplicateSelected);
  const deleteSelected = useCanvasStore((state) => state.deleteSelected);
  const connectImageToVideo = useCanvasStore((state) => state.connectImageToVideo);
  const addToStoryboard = useCanvasStore((state) => state.addToStoryboard);
  const canVideo = data.kind === "image" && Boolean(data.output?.url);
  const canDownload = Boolean(data.output?.url);
  const canStoryboard = Boolean(data.output) && (data.kind === "image" || data.kind === "video");

  return (
    <FlowToolbar isVisible position={Position.Top} align="end" offset={8} className="node-toolbar">
      <button type="button" title="Edit prompt" onClick={() => setInspectorOpen(true)}>
        <Pencil size={14} />
      </button>
      {data.toolId ? (
        <button
          type="button"
          title="Regenerate"
          disabled={data.status === "running"}
          onClick={() => {
            void runNode(id);
          }}
        >
          <RefreshCw size={14} />
        </button>
      ) : null}
      {canVideo ? (
        <button type="button" title="Create video from image" onClick={() => connectImageToVideo(id)}>
          <Video size={14} />
        </button>
      ) : null}
      {canStoryboard ? (
        <button type="button" title="Add to storyboard" onClick={() => addToStoryboard(id)}>
          <LayoutGrid size={14} />
        </button>
      ) : null}
      {canDownload ? (
        <a className="toolbar-link" href={data.output?.url} download title="Download">
          <Download size={14} />
        </a>
      ) : null}
      <button type="button" title="Duplicate" onClick={duplicateSelected}>
        <Copy size={14} />
      </button>
      <button type="button" title="Delete" onClick={deleteSelected}>
        <Trash2 size={14} />
      </button>
    </FlowToolbar>
  );
}
