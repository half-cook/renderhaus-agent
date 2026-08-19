"use client";

import { SchemaForm } from "./SchemaForm";
import type { StudioAsset, ToolNode } from "@/lib/types";

type Props = {
  node: ToolNode;
  selected: boolean;
  options?: Record<string, Array<string | number>>;
  onSelect: () => void;
  onMove: (dx: number, dy: number) => void;
  onChange: (name: string, value: unknown) => void;
  onRun: () => void;
  onDelete: () => void;
};

function AssetPreview({ asset }: { asset: StudioAsset }) {
  if (asset.kind === "image") {
    return <img className="asset-media" src={asset.url} alt="" />;
  }
  if (asset.kind === "video") {
    return <video className="asset-media" src={asset.url} controls playsInline />;
  }
  return <audio className="asset-audio" src={asset.url} controls />;
}

export function ToolNodeCard({
  node,
  selected,
  options,
  onSelect,
  onMove,
  onChange,
  onRun,
  onDelete,
}: Props) {
  return (
    <article
      className={selected ? "node selected" : "node"}
      style={{ left: node.x, top: node.y }}
      onPointerDown={(event) => {
        if ((event.target as HTMLElement).closest("input, textarea, select, button, label, video, audio")) {
          return;
        }
        onSelect();
        const originX = event.clientX;
        const originY = event.clientY;
        const move = (next: PointerEvent) => {
          onMove(next.clientX - originX, next.clientY - originY);
        };
        const up = () => {
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", up);
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
      }}
    >
      <header className="node-head">
        <div>
          <h3>{node.tool.name}</h3>
          <div className="meta">{node.providerName}</div>
        </div>
        <div className={`status ${node.status}`}>{node.status}</div>
      </header>
      {node.assets.length > 0 ? (
        <div className="asset-stage">
          {node.assets.map((asset) => (
            <AssetPreview key={asset.url} asset={asset} />
          ))}
        </div>
      ) : null}
      <div className="node-body">
        <SchemaForm
          schema={node.tool.inputSchema}
          values={node.args}
          options={options}
          onChange={onChange}
        />
        <div className="actions">
          <button className="run" type="button" disabled={node.status === "running"} onClick={onRun}>
            {node.status === "running" ? "Running" : "Run tool"}
          </button>
          <button className="delete" type="button" onClick={onDelete}>
            Remove
          </button>
        </div>
        {node.error ? <div className="status error">{node.error}</div> : null}
        {node.result !== null && node.result !== undefined ? (
          <pre className="result">{JSON.stringify(node.result, null, 2)}</pre>
        ) : null}
      </div>
    </article>
  );
}
