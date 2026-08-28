"use client";

import { NodeToolbar as FlowToolbar, Position } from "@xyflow/react";
import { Check, Copy, Download, LayoutGrid, Pencil, RefreshCw, Trash2, Video } from "lucide-react";
import { agentResultDownloadUrl } from "@/lib/canvas/download";
import type { CanvasNodeData } from "@/lib/canvas/types";
import { useCanvasStore } from "@/lib/canvas/store";
import { AssetDownloadLink } from "./AssetMedia";

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
  const setApproved = useCanvasStore((state) => state.setApproved);
  const canVideo = data.kind === "image" && Boolean(data.output);
  const canStoryboard = Boolean(data.output) && (data.kind === "image" || data.kind === "video");
  const canApprove = data.kind === "image" || data.kind === "video" || data.kind === "storyboard";

  return (
    <FlowToolbar isVisible position={Position.Top} align="end" offset={8} className="node-toolbar">
      <button type="button" aria-label="Edit" title="Edit" onClick={() => setInspectorOpen(true)}>
        <Pencil size={14} />
      </button>
      {data.toolId ? (
        <button
          type="button"
          title="Regenerate"
          aria-label="Regenerate"
          disabled={data.status === "running"}
          onClick={() => {
            void runNode(id);
          }}
        >
          <RefreshCw size={14} />
        </button>
      ) : null}
      {canApprove ? (
        <button
          type="button"
          className={data.approved ? "approved" : ""}
          aria-label={data.approved ? "Remove from sequence" : "Approve"}
          title={data.approved ? "Remove from sequence" : "Approve"}
          onClick={() => setApproved(id, !data.approved)}
        >
          <Check size={14} />
        </button>
      ) : null}
      {canVideo ? (
        <button type="button" aria-label="Create video from image" title="Create video from image" onClick={() => connectImageToVideo(id)}>
          <Video size={14} />
        </button>
      ) : null}
      {canStoryboard ? (
        <button type="button" aria-label="Add to storyboard" title="Add to storyboard" onClick={() => addToStoryboard(id)}>
          <LayoutGrid size={14} />
        </button>
      ) : null}
      {data.output || data.agentResult?.primaryAsset ? (
        <AssetDownloadLink
          className="toolbar-link"
          asset={data.output || data.agentResult?.primaryAsset}
          ariaLabel="Download"
        >
          <Download size={14} />
        </AssetDownloadLink>
      ) : data.agentResult ? (
        <a
          className="toolbar-link"
          href={agentResultDownloadUrl(data.agentResult)}
          download={data.agentResult.filename}
          aria-label={`Download ${data.agentResult.filename}`}
          title="Download"
        >
          <Download size={14} />
        </a>
      ) : null}
      <button type="button" aria-label="Duplicate" title="Duplicate" onClick={duplicateSelected}>
        <Copy size={14} />
      </button>
      <button type="button" aria-label="Delete" title="Delete" onClick={deleteSelected}>
        <Trash2 size={14} />
      </button>
    </FlowToolbar>
  );
}
