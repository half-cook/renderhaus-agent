"use client";

import { ArrowLeft, ArrowRight, Mic } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { AssetMedia } from "@/components/canvas/AssetMedia";
import { useCanvasStore } from "@/lib/canvas/store";
import { PX_PER_SECOND, clipLength, setTrimField, timecode, type TimelineClip } from "@/lib/rh/timeline";
import { TimelineHints, TimelineTrack, TransportBar, useTimelineModel, useTransport } from "./Timeline";

/** "4.2", "0:04.2" and "4,2" all mean 4.2 seconds. Anything else is rejected, not guessed. */
export function parseSeconds(value: string): number | null {
  const text = value.trim().replace(",", ".");
  const match = /^(?:(\d+):)?(\d+(?:\.\d+)?)$/.exec(text);
  if (!match) return null;
  return Number(match[1] ?? 0) * 60 + Number(match[2]);
}
const fieldText = (seconds: number) => `${Math.floor(seconds / 60)}:${(seconds % 60).toFixed(1).padStart(4, "0")}`;

function TrimField({ label, seconds, onCommit }: { label: string; seconds: number; onCommit: (seconds: number) => void }) {
  const [draft, setDraft] = useState<string | null>(null);
  const [invalid, setInvalid] = useState(false);
  const commit = () => {
    if (draft == null) return;
    const parsed = parseSeconds(draft);
    if (parsed == null) { setInvalid(true); return; }
    setInvalid(false); onCommit(parsed); setDraft(null);
  };
  return (
    <label className="rh-tl-field">
      <span className="rh-fg2">{label}</span>
      <input
        className="rh-input rh-mono rh-num" inputMode="decimal" aria-invalid={invalid}
        value={draft ?? fieldText(seconds)}
        onChange={(event) => { setDraft(event.target.value); setInvalid(false); }}
        onBlur={commit}
        onKeyDown={(event) => { if (event.key === "Enter") commit(); if (event.key === "Escape") { setDraft(null); setInvalid(false); } }}
      />
    </label>
  );
}

function Inspector({ clip, count, onTrim, onMove }: { clip: TimelineClip | null; count: number; onTrim: (trimIn: number, trimOut: number) => void; onMove: (offset: number) => void }) {
  if (!clip) return <aside className="rh-tl-inspector" aria-label="Clip inspector"><p className="rh-fg3 rh-small">Select a shot on the track to trim or reorder it.</p></aside>;
  const apply = (field: "in" | "out" | "length") => (seconds: number) => { const next = setTrimField(clip, field, seconds); onTrim(next.trimIn, next.trimOut); };
  return (
    <aside className="rh-tl-inspector" aria-label="Clip inspector">
      <h2 className="rh-h3" style={{ fontSize: 16 }}>{clip.title}</h2>
      <h3 className="rh-eyebrow">Trim</h3>
      <div className="rh-tl-fields">
        <TrimField label="In" seconds={clip.trimIn} onCommit={apply("in")} />
        <TrimField label="Out" seconds={clip.trimOut} onCommit={apply("out")} />
        <TrimField label="Length" seconds={clipLength(clip)} onCommit={apply("length")} />
      </div>
      <h3 className="rh-eyebrow">Order</h3>
      <div className="rh-tl-order">
        <span className="rh-fg2">{clip.order} of {count}</span>
        <span className="rh-tl-spacer" />
        <button type="button" className="rh-btn" disabled={clip.order <= 1} onClick={() => onMove(-1)}><ArrowLeft size={13} aria-hidden="true" />Earlier</button>
        <button type="button" className="rh-btn" disabled={clip.order >= count} onClick={() => onMove(1)}>Later<ArrowRight size={13} aria-hidden="true" /></button>
      </div>
    </aside>
  );
}

/** Third segment of the header capsule: media bin, monitor, inspector and the single track at its larger size. */
export function TimelineView() {
  const nodes = useCanvasStore((state) => state.nodes);
  const model = useTimelineModel();
  const transport = useTransport(model.clips);
  const [snapOn, setSnapOn] = useState(true);
  const [safeArea, setSafeArea] = useState(true);
  const [zoom, setZoom] = useState(PX_PER_SECOND);
  const selected = transport.selected;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== "s" || event.metaKey || event.ctrlKey) return;
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      setSnapOn((value) => !value);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const bin = useMemo(() => nodes.filter((node) => (node.data.kind === "image" || node.data.kind === "video") && (node.data.output || typeof node.data.config.thumbnail_url === "string")), [nodes]);
  const audio = nodes.filter((node) => node.data.kind === "audio");
  const asset = selected ? model.mediaFor(selected.id) : undefined;
  const aspect = selected ? String(nodes.find((node) => node.id === selected.id)?.data.config.aspect_ratio ?? "16:9") : "16:9";

  return (
    <div className="rh-tl-view" data-shot="timeline-ready">
      <div className="rh-tl-top">
        <aside className="rh-tl-bin" aria-label="Media bin">
          <h2 className="rh-eyebrow">Media bin</h2>
          <ul>
            {bin.map((node) => {
              const clip = model.clips.find((candidate) => candidate.id === node.id);
              const thumb = typeof node.data.config.thumbnail_url === "string" ? node.data.config.thumbnail_url : undefined;
              const seconds = typeof node.data.config.duration_seconds === "number" ? node.data.config.duration_seconds : undefined;
              return (
                <li key={node.id}>
                  <button type="button" className="rh-tl-bin-item" aria-current={selected?.id === node.id ? "true" : undefined} onClick={() => clip && transport.select(clip.id)} disabled={!clip}>
                    <span className="rh-thumb rh-tl-bin-thumb" style={thumb ? { backgroundImage: `url(${thumb})` } : undefined} />
                    <span><b>{node.data.title}</b><i className="rh-mono">{seconds ? `0:${String(Math.round(seconds)).padStart(2, "0")}` : aspectOf(node.data.config.aspect_ratio)}</i></span>
                  </button>
                </li>
              );
            })}
          </ul>
          {audio.length ? (
            <>
              <h2 className="rh-eyebrow" style={{ marginTop: 18 }}>Audio</h2>
              <ul>
                {audio.map((node) => (
                  <li key={node.id} className="rh-tl-audio"><Mic size={13} aria-hidden="true" /><span>{node.data.title}</span>{typeof node.data.config.duration_seconds === "number" ? <i className="rh-mono">{`0:${String(Math.round(node.data.config.duration_seconds)).padStart(2, "0")}`}</i> : null}</li>
                ))}
              </ul>
            </>
          ) : null}
        </aside>
        <section className="rh-tl-monitorwrap" aria-label="Monitor">
          <div className="rh-tl-monitor rh-ticks" data-aspect={aspect}>
            {asset && asset.kind === "video" ? <AssetMedia asset={asset} alt={selected?.title ?? "Preview"} className="rh-tl-media" muted />
              : selected?.thumbUrl ? <div className="rh-tl-media rh-thumb" style={{ backgroundImage: `url(${selected.thumbUrl})` }} role="img" aria-label={selected.title} />
                : <div className="rh-tl-media rh-tl-nomedia rh-fg3">Nothing to preview yet</div>}
            {safeArea ? <span className="rh-tl-safe" aria-hidden="true" /> : null}
            <span className="rh-tk" />
          </div>
          <div className="rh-tl-caption rh-mono">
            {selected ? <>{selected.title.split(" · ")[0]} · {timecode(transport.playhead)} · {aspect} preview · </> : null}
            <button type="button" className="rh-linkbtn" aria-pressed={safeArea} onClick={() => setSafeArea((value) => !value)}>Safe area {safeArea ? "on" : "off"}</button>
          </div>
        </section>
        <Inspector clip={selected} count={model.clips.length} onTrim={(trimIn, trimOut) => selected && useCanvasStore.getState().trimSequenceClip(selected.id, trimIn, trimOut)} onMove={(offset) => selected && model.move(selected.id, offset)} />
      </div>
      <section className="rh-tl-bottom" aria-label="Timeline">
        <TransportBar model={model} transport={transport} snapOn={snapOn} onSnap={() => setSnapOn((value) => !value)} zoom={zoom} onZoom={setZoom} />
        <TimelineTrack model={model} transport={transport} pxPerSecond={zoom} snapOn={snapOn} height={72} />
        <TimelineHints canRemove={Boolean(transport.selectedId)} onRemove={() => transport.selectedId && model.remove(transport.selectedId)} />
      </section>
    </div>
  );
}

function aspectOf(value: unknown): string {
  return typeof value === "string" ? value : "";
}
