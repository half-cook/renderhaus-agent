"use client";

import {
  ChevronDown, GripVertical, Mic, Pause, Play, SkipBack, SkipForward, Trash2, ZoomIn, ZoomOut, Magnet, EyeOff, Eye, Film,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { useCanvasStore } from "@/lib/canvas/store";
import {
  FRAME_SECONDS, PX_PER_SECOND, clipLength, clipsFromNodes, dropIndex, moveClip, secondsLabel, timecode, totalSeconds,
  trimEdge, type TimelineClip,
} from "@/lib/rh/timeline";


type Drag =
  | { kind: "trim"; id: string; edge: "in" | "out"; startX: number; delta: number }
  | { kind: "move"; id: string; startX: number; delta: number; index: number };

const RULER_MIN_SECONDS = 10;

/** Clips, order and trims for the current project, plus the actions that edit them (trim and reorder only). */
export function useTimelineModel() {
  const nodes = useCanvasStore((state) => state.nodes);
  const trim = useCanvasStore((state) => state.trimSequenceClip);
  const reorder = useCanvasStore((state) => state.reorderSequence);
  const remove = useCanvasStore((state) => state.removeFromSequence);
  const clips = useMemo(() => clipsFromNodes(nodes), [nodes]);
  const voiceover = useMemo(() => {
    const node = nodes.find((candidate) => candidate.data.kind === "audio" && (candidate.data.output || typeof candidate.data.config.duration_seconds === "number"));
    const seconds = node && typeof node.data.config.duration_seconds === "number" ? node.data.config.duration_seconds : undefined;
    return node ? { title: node.data.title, seconds } : null;
  }, [nodes]);
  const mediaFor = useCallback((id: string) => nodes.find((node) => node.id === id)?.data.output, [nodes]);
  const move = useCallback((id: string, offset: number) => reorder(moveClip(clips.map((clip) => clip.id), id, offset)), [clips, reorder]);
  return { clips, voiceover, mediaFor, trim, reorder, remove, move };
}

export type TimelineModel = ReturnType<typeof useTimelineModel>;

/** Playhead, selection and transport. Shared by the dock and the full view so both show the same state. */
export function useTransport(clips: TimelineClip[]) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
  const total = totalSeconds(clips);
  const selected = clips.find((clip) => clip.id === selectedId) ?? clips[0] ?? null;

  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const elapsed = (now - last) / 1000;
      last = now;
      let reachedEnd = false;
      setPlayhead((current) => {
        const next = current + elapsed;
        if (next >= total) { reachedEnd = true; return total; }
        return next;
      });
      if (reachedEnd) setPlaying(false);
      else frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, total]);

  const startOf = useCallback((id: string) => {
    let cursor = 0;
    for (const clip of clips) { if (clip.id === id) return cursor; cursor += clipLength(clip); }
    return 0;
  }, [clips]);

  const select = useCallback((id: string) => { setSelectedId(id); setPlayhead(startOf(id)); }, [startOf]);
  const step = useCallback((direction: 1 | -1) => {
    const index = Math.max(0, clips.findIndex((clip) => clip.id === selected?.id));
    const target = clips[Math.min(clips.length - 1, Math.max(0, index + direction))];
    if (target) select(target.id);
  }, [clips, select, selected?.id]);

  return { selected, selectedId: selected?.id ?? null, select, playhead, setPlayhead, playing, setPlaying, total, startOf, step };
}

export type Transport = ReturnType<typeof useTransport>;

function Ruler({ seconds, pxPerSecond }: { seconds: number; pxPerSecond: number }) {
  const marks = Array.from({ length: Math.ceil(seconds) + 1 }, (_, index) => index);
  return (
    <div className="rh-tl-ruler" style={{ width: seconds * pxPerSecond }} aria-hidden="true">
      {marks.map((second) => (
        <span key={second} className="rh-tl-mark" style={{ left: second * pxPerSecond }}>
          <i>{`0:${String(second).padStart(2, "0")}`}</i>
          {[1, 2, 3].map((quarter) => <b key={quarter} style={{ left: (quarter * pxPerSecond) / 4 }} />)}
        </span>
      ))}
    </div>
  );
}

export function TimelineTrack({ model, transport, pxPerSecond, snapOn, height, changesRow, clipDecoration, clipClassName, thumbnailMode, readOnly = false }: {
  model: TimelineModel;
  transport: Transport;
  pxPerSecond: number;
  snapOn: boolean;
  height: number;
  changesRow?: ReactNode;
  clipDecoration?: (clip: TimelineClip) => ReactNode;
  clipClassName?: (clip: TimelineClip) => string;
  thumbnailMode?: "repeat-cover";
  readOnly?: boolean;
}) {
  const { clips, trim, reorder, remove, move } = model;
  const { selectedId, select, playhead, setPlayhead, total } = transport;
  const [drag, setDrag] = useState<Drag | null>(null);
  const [hidden, setHidden] = useState(false);
  const rulerSeconds = Math.max(RULER_MIN_SECONDS, Math.ceil(total) + 1);

  const live = (clip: TimelineClip): TimelineClip => {
    if (drag?.kind === "trim" && drag.id === clip.id) {
      return { ...clip, ...trimEdge(clip, drag.edge, drag.delta / pxPerSecond, snapOn ? undefined : 0) };
    }
    return clip;
  };
  const shown = clips.map(live);

  const beginTrim = (event: ReactPointerEvent, clip: TimelineClip, edge: "in" | "out") => {
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    select(clip.id);
    setDrag({ kind: "trim", id: clip.id, edge, startX: event.clientX, delta: 0 });
  };
  const beginMove = (event: ReactPointerEvent, clip: TimelineClip) => {
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    select(clip.id);
    setDrag({ kind: "move", id: clip.id, startX: event.clientX, delta: 0, index: clips.findIndex((candidate) => candidate.id === clip.id) });
  };
  const onMove = (event: ReactPointerEvent) => {
    if (!drag) return;
    const delta = event.clientX - drag.startX;
    if (drag.kind === "move") {
      const start = clips.slice(0, clips.findIndex((clip) => clip.id === drag.id)).reduce((sum, clip) => sum + clipLength(clip) * pxPerSecond, 0);
      setDrag({ ...drag, delta, index: dropIndex(clips, drag.id, start + delta + (clipLength(clips.find((clip) => clip.id === drag.id)!) * pxPerSecond) / 2, pxPerSecond) });
    } else setDrag({ ...drag, delta });
  };
  const endDrag = () => {
    if (!drag) return;
    if (drag.kind === "trim") {
      const clip = clips.find((candidate) => candidate.id === drag.id);
      if (clip && drag.delta !== 0) {
        const next = trimEdge(clip, drag.edge, drag.delta / pxPerSecond, snapOn ? undefined : 0);
        if (next.trimIn !== clip.trimIn || next.trimOut !== clip.trimOut) trim(clip.id, next.trimIn, next.trimOut);
      }
    } else {
      const ids = clips.map((clip) => clip.id).filter((id) => id !== drag.id);
      ids.splice(drag.index, 0, drag.id);
      if (ids.join() !== clips.map((clip) => clip.id).join()) reorder(ids);
    }
    setDrag(null);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (readOnly) return;
    const clip = clips.find((candidate) => candidate.id === selectedId);
    if (!clip) return;
    const edge = event.altKey ? "in" : "out";
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      const next = trimEdge(clip, edge, (event.key === "ArrowLeft" ? -1 : 1) * FRAME_SECONDS, 0);
      trim(clip.id, next.trimIn, next.trimOut);
    } else if (event.key === "[" || event.key === "]") {
      event.preventDefault();
      move(clip.id, event.key === "[" ? -1 : 1);
    } else if (event.key === "Backspace" || event.key === "Delete") {
      event.preventDefault();
      remove(clip.id);
    }
  };

  let cursor = 0;
  const gapAt = drag?.kind === "move" ? drag.index : -1;
  return (
    <div className="rh-tl-scroll" data-shot="timeline-track">
      <div className="rh-tl-canvas" style={{ width: rulerSeconds * pxPerSecond + 120 }}>
        {changesRow ? <div className="rh-tl-changes-row"><div className="rh-tl-gutter rh-eyebrow">Changes</div>{changesRow}</div> : null}
        <div className="rh-tl-timed-region">
        <div className="rh-tl-rulerrow">
          <div className="rh-tl-gutter rh-eyebrow">Shots · {clips.length}</div>
          <Ruler seconds={rulerSeconds} pxPerSecond={pxPerSecond} />
        </div>
        <div className="rh-tl-row" style={{ height: height + 28 }}>
          <div className="rh-tl-gutter rh-tl-trackname">
            <Film size={13} aria-hidden="true" /><span>Video</span>
            <button type="button" className="rh-icon-btn rh-tl-eye" aria-label={hidden ? "Show video track" : "Hide video track"} aria-pressed={hidden} onClick={() => setHidden((value) => !value)}>{hidden ? <EyeOff size={13} /> : <Eye size={13} />}</button>
          </div>
          <div
            className="rh-tl-lane"
            role="listbox"
            aria-label={readOnly ? "Video track with proposed changes. Select a shot to preview. Switch to Current cut to edit." : "Video track. Drag a clip to reorder, drag an end to trim. Arrow keys trim by a frame, brackets reorder, Backspace removes."}
            aria-orientation="horizontal"
            tabIndex={0}
            onKeyDown={onKeyDown}
            onPointerMove={onMove}
            onPointerUp={endDrag}
            onPointerCancel={() => setDrag(null)}
            style={{ height, opacity: hidden ? 0.35 : 1 }}
          >
            {clips.length === 0 ? <p className="rh-tl-empty">No shots on the timeline yet. Approve a clip on the canvas, or ask the agent.</p> : null}
            {shown.map((clip, position) => {
              const width = clipLength(clip) * pxPerSecond;
              const left = cursor;
              cursor += width;
              const moving = drag?.kind === "move" && drag.id === clip.id;
              const selected = clip.id === selectedId;
              return (
                <div
                  key={clip.id}
                  role="option"
                  aria-selected={selected}
                  aria-label={`${String(clip.order).padStart(2, "0")} ${clip.title}, ${secondsLabel(clipLength(clip))}`}
                  className={`rh-tl-clip rh-ticks${clipClassName ? ` ${clipClassName(clip)}` : ""}`}
                  data-selected={selected}
                  data-moving={moving}
                  style={{ left: left + (gapAt >= 0 && position >= gapAt && !moving ? 0 : 0), width, transform: moving ? `translateX(${drag.delta}px)` : undefined, zIndex: moving ? 5 : undefined }}
                  onPointerDown={() => select(clip.id)}
                >
                  {thumbnailMode === "repeat-cover" ? <div className="rh-tl-strip rh-tl-strip-cover" aria-hidden="true">
                    {clip.thumbUrl ? Array.from({ length: Math.ceil(width / (height * 16 / 9)) + 1 }, (_, index) => <img key={index} src={clip.thumbUrl} alt="" draggable={false} />) : null}
                  </div> : <div className="rh-tl-strip" style={clip.thumbUrl ? { backgroundImage: `url(${clip.thumbUrl})`, backgroundSize: `${Math.max(60, height * 1.7)}px 100%` } : undefined} />}
                  {!readOnly ? <><span className="rh-tl-grip" aria-hidden="true" onPointerDown={(event) => beginMove(event, clip)}><GripVertical size={11} /></span>
                  <span className="rh-tl-handle" data-edge="in" role="presentation" onPointerDown={(event) => beginTrim(event, clip, "in")} />
                  <span className="rh-tl-handle" data-edge="out" role="presentation" onPointerDown={(event) => beginTrim(event, clip, "out")} /></> : null}
                  <span className="rh-tl-cliplabel rh-mono"><b>{String(clip.order).padStart(2, "0")}</b> · {clip.title}</span>
                  <span className="rh-tl-cliplen rh-mono rh-num">{secondsLabel(clipLength(clip))}</span>
                  {clipDecoration?.(clip)}
                  <span className="rh-tk" />
                </div>
              );
            })}
            {drag?.kind === "move" ? <span className="rh-tl-drop" style={{ left: clips.filter((clip) => clip.id !== drag.id).slice(0, drag.index).reduce((sum, clip) => sum + clipLength(clip) * pxPerSecond, 0) }} aria-hidden="true" /> : null}
          </div>
        </div>
        <div className="rh-tl-playhead" style={{ left: 112 + playhead * pxPerSecond }} aria-hidden="true"><i /></div>
        <button type="button" className="rh-tl-seek" style={{ left: 112, width: rulerSeconds * pxPerSecond }} aria-label="Move the playhead" tabIndex={-1} onClick={(event) => { const rect = event.currentTarget.getBoundingClientRect(); setPlayhead(Math.min(total, Math.max(0, (event.clientX - rect.left) / pxPerSecond))); }} />
        </div>
      </div>
    </div>
  );
}

export function TransportBar({ model, transport, snapOn, onSnap, zoom, onZoom, children, playbackAvailable = true }: {
  model: TimelineModel; transport: Transport; snapOn: boolean; onSnap: () => void; zoom: number; onZoom: (value: number) => void;
  children?: ReactNode;
  playbackAvailable?: boolean;
}) {
  const { playing, setPlaying, playhead, total, step } = transport;
  return (
    <div className="rh-tl-bar">
      <span className="rh-tl-title">Timeline</span>
      <span className="rh-chip rh-chip-mono">Single track · trim and reorder</span>
      <div className="rh-tl-transport">
        <button type="button" className="rh-icon-btn" aria-label="Previous shot" onClick={() => step(-1)}><SkipBack size={14} /></button>
        <button type="button" className="rh-icon-btn rh-tl-play" disabled={!playbackAvailable} aria-label={!playbackAvailable ? "Playback unavailable for still preview" : playing ? "Pause" : "Play"} aria-pressed={playing} onClick={() => { if (!playing && playhead >= total) transport.setPlayhead(0); setPlaying(!playing); }}>{playing ? <Pause size={15} /> : <Play size={15} />}</button>
        <button type="button" className="rh-icon-btn" aria-label="Next shot" onClick={() => step(1)}><SkipForward size={14} /></button>
      </div>
      <span className="rh-tl-time rh-mono rh-num"><b>{timecode(playhead)}</b> / {timecode(total)}</span>
      {children}
      <span className="rh-tl-spacer" />
      {model.voiceover ? <span className="rh-chip"><Mic size={12} aria-hidden="true" />Voiceover attached{model.voiceover.seconds ? ` · 0:${String(Math.round(model.voiceover.seconds)).padStart(2, "0")}` : ""}</span> : null}
      <button type="button" className="rh-btn rh-btn-quiet rh-btn-sm" aria-pressed={snapOn} onClick={onSnap}><Magnet size={13} aria-hidden="true" />Snap <span className="rh-kbd">S</span></button>
      <ZoomOut size={13} className="rh-fg3" aria-hidden="true" />
      <input className="rh-tl-zoom" type="range" min={60} max={220} step={4} value={zoom} aria-label="Timeline zoom" onChange={(event) => onZoom(Number(event.target.value))} />
      <ZoomIn size={13} className="rh-fg3" aria-hidden="true" />
    </div>
  );
}

export function TimelineHints({ onRemove, canRemove }: { onRemove: () => void; canRemove: boolean }) {
  return (
    <div className="rh-tl-hints">
      <span>Drag to reorder</span><span>Drag an end to trim</span>
      <button type="button" className="rh-btn rh-btn-quiet rh-btn-sm" disabled={!canRemove} onClick={onRemove}><Trash2 size={12} aria-hidden="true" />Remove shot</button>
      <span className="rh-tl-spacer" />
      <span>Multi-track editing is not in v1. Add a shot from the media bin or ask the agent.</span>
    </div>
  );
}

/** The 250px dock under the canvas. */
export function TimelineDock() {
  const open = useCanvasStore((state) => state.timelineDockOpen);
  const setOpen = useCanvasStore((state) => state.setTimelineDockOpen);
  const model = useTimelineModel();
  const transport = useTransport(model.clips);
  const [snapOn, setSnapOn] = useState(true);
  const [zoom, setZoom] = useState(PX_PER_SECOND);
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key.toLowerCase() !== "s" || event.metaKey || event.ctrlKey) return;
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      if (open) setSnapOn((value) => !value);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  if (!open) return null;
  return (
    <section className="rh-tl-dock" aria-label="Timeline">
      <TransportBar model={model} transport={transport} snapOn={snapOn} onSnap={() => setSnapOn((value) => !value)} zoom={zoom} onZoom={setZoom} />
      <TimelineTrack model={model} transport={transport} pxPerSecond={zoom} snapOn={snapOn} height={56} />
      <TimelineHints canRemove={Boolean(transport.selectedId)} onRemove={() => transport.selectedId && model.remove(transport.selectedId)} />
      <button type="button" className="rh-icon-btn rh-tl-collapse" aria-label="Collapse timeline" onClick={() => setOpen(false)}><ChevronDown size={15} /></button>
    </section>
  );
}
