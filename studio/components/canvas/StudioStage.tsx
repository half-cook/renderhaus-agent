"use client";

/* Revamp v4 Studio stage (01/01b): one dominant frame (~976×576) with the shot title in
   Instrument Serif, player controls only on hover or focus, and a slim 48 px film strip of the
   project's shots below. Clips dim while one is hovered; the selected clip gets the ember ring. */
import { Film } from "lucide-react";
import { useMemo, useState } from "react";
import { AssetMedia } from "./AssetMedia";
import { useCanvasStore } from "@/lib/canvas/store";

export function StudioStage({ onOpenReview }: { onOpenReview?: () => void }) {
  const nodes = useCanvasStore((state) => state.nodes);
  const selectedNodeIds = useCanvasStore((state) => state.selectedNodeIds);
  const [hot, setHot] = useState(false);
  const shots = useMemo(
    () => nodes.filter((node) => node.data.output && (node.data.output.kind === "video" || node.data.output.kind === "image")),
    [nodes],
  );
  const selected = shots.find((node) => selectedNodeIds.includes(node.id))
    ?? [...shots].reverse().find((node) => node.data.output?.kind === "video")
    ?? shots.at(-1);
  const index = selected ? shots.indexOf(selected) : -1;

  return (
    <section className="rh-stage" aria-label="Preview" data-shot="studio-stage">
      <div className="rh-stage-frame" data-hot={hot || undefined}
        onMouseEnter={() => setHot(true)} onMouseLeave={() => setHot(false)} onFocus={() => setHot(true)} onBlur={() => setHot(false)}>
        {selected?.data.output ? (
          <AssetMedia key={selected.data.output.versionId} asset={selected.data.output} alt={selected.data.title} className="rh-stage-media" controls={hot} preload="metadata" />
        ) : (
          <div className="rh-stage-empty"><Film size={22} aria-hidden="true" /><p>Your film shows up here. Ask for a change, or start from the demo.</p></div>
        )}
        {selected ? (
          <div className="rh-stage-caption" aria-hidden={hot || undefined}>
            <span className="rh-num">Shot {index + 1} of {shots.length}</span>
            <b>{selected.data.title}</b>
          </div>
        ) : null}
        {onOpenReview ? <button type="button" className="rh-stage-review rh-hover-only" onClick={onOpenReview}>Review changes</button> : null}
      </div>
      <div className="rh-strip" role="list" aria-label="Timeline">
        {shots.map((node, i) => (
          <button key={node.id} type="button" role="listitem" className="rh-strip-clip" data-sel={node.id === selected?.id || undefined}
            aria-label={`Shot ${i + 1}: ${node.data.title}`} aria-current={node.id === selected?.id || undefined}
            onClick={() => useCanvasStore.getState().onSelectionChange([node.id])}>
            <AssetMedia asset={node.data.output} alt="" className="rh-strip-media" muted preload="metadata" startTime={1} />
            <span className="rh-strip-label">{node.data.title}</span>
          </button>
        ))}
        {shots.length === 0 ? <div className="rh-strip-empty" aria-hidden="true" /> : null}
      </div>
    </section>
  );
}
