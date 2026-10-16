"use client";

/* Revamp v4 Studio stage: dominant ~976×576 frame with the shot title in Instrument Serif.
   While the agent works, overlays its status and explicit frame progress. Film-strip timeline and
   hover-only chrome are deferred until after launch. */
import { Film } from "lucide-react";
import { useMemo, useState } from "react";
import { AssetMedia } from "./AssetMedia";
import { useCanvasStore } from "@/lib/canvas/store";

export function StudioStage({ onOpenReview }: { onOpenReview?: () => void }) {
  const nodes = useCanvasStore((state) => state.nodes);
  const selectedNodeIds = useCanvasStore((state) => state.selectedNodeIds);
  const executions = useCanvasStore((state) => state.executions);
  const conversationId = useCanvasStore((state) => state.conversationId);
  const [hot, setHot] = useState(false);
  const shots = useMemo(
    () => nodes.filter((node) => node.data.output && (node.data.output.kind === "video" || node.data.output.kind === "image")),
    [nodes],
  );
  const selected = shots.find((node) => selectedNodeIds.includes(node.id))
    ?? [...shots].reverse().find((node) => node.data.output?.kind === "video")
    ?? shots.at(-1);
  const index = selected ? shots.indexOf(selected) : -1;
  const live = executions.find((execution) => execution.conversationId === conversationId && ["running", "queued", "pending"].includes(execution.status.toLowerCase()));
  const frameMatch = [
    ...(live?.toolEvents.filter((event) => /^(running|pending)$/i.test(event.status)).map((event) => event.summary) || []),
    ...(live?.progressEvents.filter((event) => event.type === "MEDIA_WAIT" && event.status === "running").map((event) => event.message) || []),
  ].reverse().map((message) => message.match(/\b(\d+)\s*(?:of|\/)\s*(\d+)\s+frames?\b/i))
    .find((match) => match && Number.isSafeInteger(Number(match[1])) && Number.isSafeInteger(Number(match[2]))
      && Number(match[2]) > 0 && Number(match[1]) <= Number(match[2]));
  const frames = frameMatch ? `${frameMatch[1]} of ${frameMatch[2]} frames` : "";
  const shooting = live ? {
    title: frames ? "Rendering…" : "Working…",
    meta: frames ? [index >= 0 ? `Shot ${index + 1}` : null, frames].filter(Boolean).join(" · ") : "",
  } : null;

  return (
    <section className="rh-stage" aria-label="Preview" data-shot="studio-stage">
      <div className="rh-stage-frame" data-hot={hot || undefined} data-shooting={shooting ? "" : undefined}
        onMouseEnter={() => setHot(true)} onMouseLeave={() => setHot(false)} onFocus={() => setHot(true)} onBlur={() => setHot(false)}>
        {selected?.data.output ? (
          <AssetMedia key={selected.data.output.versionId} asset={selected.data.output} alt={selected.data.title} className="rh-stage-media" controls={hot && !shooting} preload="metadata" />
        ) : (
          <div className="rh-stage-empty"><Film size={22} aria-hidden="true" /><p>Your film shows up here. Ask for a change, or start from the demo.</p></div>
        )}
        {shooting ? (
          <div className="rh-shooting" role="status">
            <span className="rh-shooting-title">{shooting.title}</span>
            {shooting.meta ? <span className="rh-shooting-meta rh-num">{shooting.meta}</span> : null}
          </div>
        ) : selected ? (
          <div className="rh-stage-caption" aria-hidden={hot || undefined}>
            <span className="rh-num">Shot {index + 1} of {shots.length || 1}</span>
            <b>{selected.data.title}</b>
          </div>
        ) : null}
        {onOpenReview ? <button type="button" className="rh-stage-review" onClick={onOpenReview}>Review changes</button> : null}
        <div className="rh-stage-shade" aria-hidden="true" />
      </div>
      {shots.length ? (
        <div className="rh-strip" role="list" aria-label="Timeline" data-shot="studio-strip">
          {shots.map((node, i) => (
            <button key={node.id} type="button" role="listitem" className="rh-strip-clip" data-sel={node.id === selected?.id || undefined}
              aria-label={`Shot ${i + 1}: ${node.data.title}`} aria-current={node.id === selected?.id || undefined}
              onClick={() => useCanvasStore.getState().onSelectionChange([node.id])}>
              <AssetMedia asset={node.data.output} alt="" className="rh-strip-media" muted preload="metadata" startTime={1} />
              <span className="rh-strip-label">{node.data.title}</span>
            </button>
          ))}
        </div>
      ) : (
        // Empty project: keep the slim timeline visible with three quiet slots instead of a blank band.
        <div className="rh-strip rh-strip-placeholder" data-shot="studio-strip-empty" aria-label="Timeline, no shots yet" role="note">
          <div className="rh-strip-empty" /><div className="rh-strip-empty" /><div className="rh-strip-empty" />
          <span className="rh-strip-hint">Shots appear here as they’re made</span>
        </div>
      )}
    </section>
  );
}
