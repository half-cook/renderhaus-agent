"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState, type PointerEvent, type RefObject } from "react";
import { ArrowLeft, ArrowLeftRight, Check, Columns2, GripVertical, Link2, MapPin, Pause, Play, Repeat2, RotateCw, Send, SkipBack, SkipForward, SplitSquareVertical, X, ZoomIn } from "lucide-react";
import { type ApprovalCardModel } from "@/lib/rh/billing";
import { cutClips, isPaidChange, withChangesCut, type ChangeItem, type ChangesDocument, type Cut, type Take } from "@/lib/rh/changes";
import { compareFrames, compareTimecode, stepCompareFrame, type CompareAlignment, type CompareFrame } from "@/lib/rh/compare-clock";
import { formatCents } from "@/lib/rh/money";
import { clamp, clipLength } from "@/lib/rh/timeline";
import { CutRibbon } from "./CutRibbon";

export type CompareMode = "swipe" | "side-by-side" | "flicker";
export type CompareViewProps = {
  document: ChangesDocument;
  change: ChangeItem;
  onBack: () => void;
  onAcceptTake: (takeId: string) => void;
  onKeepTake: () => void;
  onNewTake?: () => void;
  onAskFrame?: (text: string) => void;
  newTakeApproval?: ApprovalCardModel;
  initialMode?: CompareMode;
  initialTimeSeconds?: number;
  onModeChange?: (mode: CompareMode) => void;
};

const STATE_LABEL: Record<ChangeItem["state"], string> = {
  proposed: "Needs you", awaiting_approval: "Waiting for approval", running: "Running", ready: "Needs you",
  accepted: "Accepted", rejected: "Rejected", reverted: "Reverted", out_of_date: "Out of date", failed: "Failed", paused_at_cap: "Paused at cap",
};

function takeForFrame(document: ChangesDocument, cut: Cut, frame: CompareFrame | null): Take | undefined {
  const takeId = cut.slots.find((slot) => slot.slotId === frame?.clipId)?.takeId;
  return document.takes.find((take) => take.id === takeId);
}

function editingTarget(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && Boolean(target.closest("input, textarea, select, [contenteditable='true'], [role='dialog']"));
}

function seekVideo(video: HTMLVideoElement | null, frame: CompareFrame | null) {
  if (video && frame && video.readyState >= 1 && Math.abs(video.currentTime - frame.sourceSeconds) > 0.02) video.currentTime = frame.sourceSeconds;
}

export function CompareView({ document, change, onBack, onAcceptTake, onKeepTake, onNewTake, onAskFrame, newTakeApproval, initialMode = "swipe", initialTimeSeconds = 2.4, onModeChange }: CompareViewProps) {
  const formId = useId();
  const quote = newTakeApproval ?? document.newTakeApproval;
  const titleRef = useRef<HTMLHeadingElement>(null);
  const playbackRun = useRef(0);
  const slotId = change.slotId ?? document.checkpointCut.order[0] ?? "";
  const takes = useMemo(() => document.takes.filter((take) => take.slotId === slotId).sort((a, b) => a.n - b.n), [document.takes, slotId]);
  const proposal = useMemo(() => withChangesCut(document), [document]);
  const beforeTakeId = change.kind === "take" ? change.beforeRef.takeId : document.checkpointCut.slots.find((slot) => slot.slotId === slotId)?.takeId;
  const proposedTakeId = change.kind === "take" ? change.afterRef.takeId : proposal.slots.find((slot) => slot.slotId === slotId)?.takeId;
  const [selectedTakeId, setSelectedTakeId] = useState(proposedTakeId ?? takes[0]?.id ?? "");
  const selectedTake = takes.find((take) => take.id === selectedTakeId) ?? takes.find((take) => take.id === proposedTakeId) ?? takes[0];
  const beforeCut = useMemo(() => ({ ...document.checkpointCut, slots: document.checkpointCut.slots.map((slot) => slot.slotId === slotId && beforeTakeId ? { ...slot, takeId: beforeTakeId } : slot) }), [document.checkpointCut, slotId, beforeTakeId]);
  const afterCut = useMemo(() => ({ ...proposal, slots: proposal.slots.map((slot) => slot.slotId === slotId && selectedTake ? { ...slot, takeId: selectedTake.id, outMs: Math.min(slot.outMs, selectedTake.durationMs) } : slot) }), [proposal, slotId, selectedTake]);
  const beforeClips = useMemo(() => cutClips(document, beforeCut), [document, beforeCut]);
  const afterClips = useMemo(() => cutClips(document, afterCut), [document, afterCut]);
  const shotIndex = beforeClips.findIndex((clip) => clip.id === slotId);
  const shot = beforeClips.find((clip) => clip.id === slotId);
  const shotStart = beforeClips.slice(0, Math.max(0, shotIndex)).reduce((seconds, clip) => seconds + clipLength(clip), 0);
  const duration = shot ? clipLength(shot) : 0;
  const lastFrameSeconds = Math.max(0, Math.ceil(duration * 24) - 1) / 24;
  const [mode, setMode] = useState<CompareMode>(initialMode);
  const [alignment, setAlignment] = useState<CompareAlignment>("shot");
  const [seconds, setSeconds] = useState(Math.min(initialTimeSeconds, lastFrameSeconds));
  const [playing, setPlaying] = useState(false);
  const [loop, setLoop] = useState(true);
  const [swipe, setSwipe] = useState(55);
  const [peekBefore, setPeekBefore] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [note, setNote] = useState("");
  const [noteSent, setNoteSent] = useState(false);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [ready, setReady] = useState({ before: false, after: false });
  const beforeVideo = useRef<HTMLVideoElement>(null);
  const afterVideo = useRef<HTMLVideoElement>(null);
  const swipeFrame = useRef<HTMLDivElement>(null);
  const swipePointer = useRef<number | null>(null);
  const panPointer = useRef<{ id: number; x: number; y: number; origin: { x: number; y: number } } | null>(null);
  const frames = compareFrames({ before: beforeClips, after: afterClips, seconds: shotStart + seconds, alignment });
  const beforeTake = takeForFrame(document, beforeCut, frames.before);
  const afterTake = takeForFrame(document, afterCut, frames.after);
  const videosAvailable = beforeTake?.mediaKind === "video" && afterTake?.mediaKind === "video";
  const playable = videosAvailable && ready.before && ready.after && !mediaError && duration > 0;
  const currentTakeId = document.currentCut.slots.find((slot) => slot.slotId === slotId)?.takeId;
  const candidatePending = document.changes.some((item) => item.kind === "take" && item.afterRef.takeId === selectedTake?.id && isPaidChange(item) && !item.taken);
  const candidateTooShort = Boolean(selectedTake && selectedTake.durationMs < (document.currentCut.slots.find((slot) => slot.slotId === slotId)?.outMs ?? 0));
  const acceptEnabled = !candidatePending && !candidateTooShort && Boolean(selectedTake && selectedTake.id !== currentTakeId && (!isPaidChange(change) || change.taken) && ["proposed", "ready", "rejected", "reverted", "accepted"].includes(change.state));
  const held = frames.after?.held;
  const timecode = compareTimecode(seconds);
  const transform = `translate(${pan.x}%, ${pan.y}%) scale(${zoom})`;

  const pause = useCallback(() => {
    playbackRun.current += 1;
    beforeVideo.current?.pause();
    afterVideo.current?.pause();
    setPlaying(false);
  }, []);

  const seek = useCallback((nextSeconds: number) => {
    pause();
    const next = clamp(nextSeconds, 0, lastFrameSeconds);
    const nextFrames = compareFrames({ before: beforeClips, after: afterClips, seconds: shotStart + next, alignment });
    seekVideo(beforeVideo.current, nextFrames.before);
    seekVideo(afterVideo.current, nextFrames.after);
    setSeconds(next);
  }, [pause, lastFrameSeconds, beforeClips, afterClips, shotStart, alignment]);

  const pickTake = useCallback((takeId: string) => {
    pause();
    setSelectedTakeId(takeId);
    setPeekBefore(false);
  }, [pause]);

  const step = useCallback((direction: -1 | 1) => seek(stepCompareFrame({ seconds, direction, durationSeconds: duration })), [seek, seconds, duration]);

  const togglePlayback = useCallback(async () => {
    if (playing) { pause(); return; }
    if (!playable) return;
    const start = seconds >= lastFrameSeconds ? 0 : seconds;
    const startFrames = compareFrames({ before: beforeClips, after: afterClips, seconds: shotStart + start, alignment });
    seekVideo(beforeVideo.current, startFrames.before);
    seekVideo(afterVideo.current, startFrames.after);
    setSeconds(start);
    const run = ++playbackRun.current;
    setPlaying(true);
    try {
      await Promise.all([beforeVideo.current?.play(), afterVideo.current?.play()]);
    } catch {
      if (run !== playbackRun.current) return;
      pause();
      setMediaError("Playback could not start. Try opening the take again.");
    }
  }, [playing, pause, playable, seconds, lastFrameSeconds, beforeClips, afterClips, shotStart, alignment]);

  useEffect(() => {
    titleRef.current?.focus({ preventScroll: true });
  }, [change.id]);

  useEffect(() => () => {
    playbackRun.current += 1;
    beforeVideo.current?.pause();
    afterVideo.current?.pause();
  }, []);

  useEffect(() => {
    pause();
    setReady({ before: (beforeVideo.current?.readyState ?? 0) >= 2, after: (afterVideo.current?.readyState ?? 0) >= 2 });
    setMediaError(null);
  }, [beforeTake?.mediaRef, afterTake?.mediaRef, pause]);

  useEffect(() => {
    if (!playing) {
      seekVideo(beforeVideo.current, frames.before);
      seekVideo(afterVideo.current, frames.after);
    }
  }, [playing, frames.before, frames.after, ready]);

  useEffect(() => {
    if (!playing) return;
    let request = 0;
    const tick = () => {
      const video = beforeVideo.current;
      if (!video || !shot) { pause(); return; }
      const localSeconds = video.currentTime - shot.trimIn;
      if (localSeconds >= duration - 1 / 24 || video.ended) {
        if (!loop) { setSeconds(lastFrameSeconds); pause(); return; }
        const first = compareFrames({ before: beforeClips, after: afterClips, seconds: shotStart, alignment });
        seekVideo(video, first.before);
        seekVideo(afterVideo.current, first.after);
        setSeconds(0);
        void video.play().catch(() => { pause(); setMediaError("Playback stopped. Try opening the take again."); });
      } else {
        const next = clamp(Math.round(localSeconds * 24) / 24, 0, lastFrameSeconds);
        setSeconds(next);
        const nextFrames = compareFrames({ before: beforeClips, after: afterClips, seconds: shotStart + next, alignment });
        const other = afterVideo.current;
        if (other && nextFrames.after) {
          if (nextFrames.after.held) other.pause();
          if (Math.abs(other.currentTime - nextFrames.after.sourceSeconds) > 0.08) seekVideo(other, nextFrames.after);
          if (!nextFrames.after.held && other.paused) void other.play().catch(() => { pause(); setMediaError("The second take could not play. Try opening it again."); });
        }
      }
      request = requestAnimationFrame(tick);
    };
    request = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(request);
  }, [playing, shot, duration, loop, lastFrameSeconds, beforeClips, afterClips, shotStart, alignment, pause]);

  useEffect(() => {
    const down = (event: KeyboardEvent) => {
      if (editingTarget(event.target) || event.altKey || event.ctrlKey || event.metaKey) return;
      const take = takes.find((item) => item.n === Number(event.key));
      if (take && /^[123]$/.test(event.key)) { event.preventDefault(); pickTake(take.id); }
      if (event.key.toLowerCase() === "b" && mode === "flicker") { event.preventDefault(); setPeekBefore(true); }
      if (event.key.toLowerCase() === "a" && acceptEnabled && selectedTake) { event.preventDefault(); onAcceptTake(selectedTake.id); }
      if (event.key.toLowerCase() === "r" && ["ready", "proposed", "reverted"].includes(change.state)) { event.preventDefault(); onKeepTake(); }
      if (event.key === "ArrowLeft") { event.preventDefault(); step(-1); }
      if (event.key === "ArrowRight") { event.preventDefault(); step(1); }
      if (event.code === "Space" && !(event.target instanceof HTMLElement && event.target.closest("button"))) { event.preventDefault(); void togglePlayback(); }
    };
    const up = (event: KeyboardEvent) => { if (event.key.toLowerCase() === "b") setPeekBefore(false); };
    const blur = () => { setPeekBefore(false); pause(); };
    const visibility = () => { if (window.document.hidden) blur(); };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    window.document.addEventListener("visibilitychange", visibility);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
      window.document.removeEventListener("visibilitychange", visibility);
    };
  }, [takes, pickTake, mode, step, togglePlayback, pause, acceptEnabled, selectedTake, onAcceptTake, onKeepTake, change.state]);

  const setCompareMode = (next: CompareMode) => { setPeekBefore(false); setMode(next); onModeChange?.(next); };
  const moveSwipe = (clientX: number) => {
    const bounds = swipeFrame.current?.getBoundingClientRect();
    if (bounds) setSwipe(clamp(((clientX - bounds.left) / bounds.width) * 100, 0, 100));
  };
  const beginPan = (event: PointerEvent<HTMLDivElement>) => {
    if (mode !== "side-by-side" || zoom <= 1 || panPointer.current || event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    panPointer.current = { id: event.pointerId, x: event.clientX, y: event.clientY, origin: pan };
  };
  const movePan = (event: PointerEvent<HTMLDivElement>) => {
    const pointer = panPointer.current;
    if (!pointer || pointer.id !== event.pointerId) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const limit = (zoom - 1) * 50;
    setPan({ x: clamp(pointer.origin.x + ((event.clientX - pointer.x) / bounds.width) * 100, -limit, limit), y: clamp(pointer.origin.y + ((event.clientY - pointer.y) / bounds.height) * 100, -limit, limit) });
  };
  const endPan = (event: PointerEvent<HTMLDivElement>) => { if (panPointer.current?.id === event.pointerId) panPointer.current = null; };
  const takeState = (take: Take) => {
    if (take.id === currentTakeId) return "in cut";
    const review = document.changes.find((item) => item.kind === "take" && item.afterRef.takeId === take.id);
    if (review?.state === "rejected") return "rejected";
    if (take.id === proposedTakeId) return "new";
    return !review && take.reviewState === "rejected" ? "rejected" : "retained";
  };

  return (
    <section className="rh-compare" aria-label={`Compare change ${change.n}, ${change.title}`} data-shot={`compare-${mode}`}>
      <header className="rh-compare-header">
        <div className="rh-compare-title"><button type="button" className="rh-btn rh-btn-quiet rh-btn-sm" onClick={onBack}><ArrowLeft size={14} aria-hidden="true" />Changes</button><span className="rh-fg3" aria-hidden="true">/</span><span className="rh-compare-number rh-mono">{change.n}</span><h2 ref={titleRef} tabIndex={-1}>{change.title}</h2><span className={`rh-chip ${change.state === "accepted" ? "rh-chip-ok" : change.state === "failed" ? "rh-chip-danger" : "rh-chip-accent"}`}>{STATE_LABEL[change.state]}</span></div>
        <div className="rh-compare-modes"><div className="rh-compare-seg" role="group" aria-label="Compare view"><button type="button" aria-pressed={mode === "swipe"} onClick={() => setCompareMode("swipe")}><ArrowLeftRight size={13} aria-hidden="true" />Swipe</button><button type="button" aria-pressed={mode === "side-by-side"} onClick={() => setCompareMode("side-by-side")}><Columns2 size={13} aria-hidden="true" />Side by side</button><button type="button" aria-pressed={mode === "flicker"} onClick={() => setCompareMode("flicker")}><SplitSquareVertical size={13} aria-hidden="true" />Flicker</button></div><span className="rh-compare-shortcuts" title="Number keys select a take">{takes.filter((take) => take.n <= 3).map((take) => <kbd className="rh-kbd" key={take.id}>{take.n}</kbd>)}</span></div>
        <div className="rh-compare-align"><span><Link2 size={14} aria-hidden="true" />Align</span><div className="rh-compare-seg" role="group" aria-label="Align comparison"><button type="button" aria-pressed={alignment === "shot"} onClick={() => { pause(); setAlignment("shot"); }}>By shot</button><button type="button" aria-pressed={alignment === "time"} onClick={() => { pause(); setAlignment("time"); }}>By time</button></div><button type="button" className="rh-icon-btn" aria-label="Close compare and return to Changes" onClick={onBack}><X size={16} aria-hidden="true" /></button></div>
      </header>
      <div className="rh-compare-main">
        <div className="rh-compare-workspace">
          <div className="rh-compare-player" data-mode={mode}>
            <div className="rh-compare-frames" ref={swipeFrame}>
              <CompareMedia side="before" take={beforeTake} videoRef={beforeVideo} transform={mode === "side-by-side" ? transform : undefined} clipPath={mode === "swipe" ? `inset(0 ${100 - swipe}% 0 0)` : mode === "flicker" ? `inset(0 ${peekBefore ? 0 : 100}% 0 0)` : undefined} subtitle={`in your cut · ${(beforeTake?.durationMs ?? 0) / 1000} s`} onReady={() => setReady((current) => ({ ...current, before: true }))} onError={() => { pause(); setMediaError("The before take could not load. Open another take or try again."); }} onPointerDown={beginPan} onPointerMove={movePan} onPointerUp={endPan} />
              <CompareMedia side="after" take={afterTake} videoRef={afterVideo} transform={mode === "side-by-side" ? transform : undefined} subtitle={`${selectedTake ? takeState(selectedTake) : "unavailable"}${held ? " · last frame held after trim" : ""}`} onReady={() => setReady((current) => ({ ...current, after: true }))} onError={() => { pause(); setMediaError("The after take could not load. Open another take or try again."); }} onPointerDown={beginPan} onPointerMove={movePan} onPointerUp={endPan} />
              {mode === "swipe" ? <div className="rh-compare-swipe-line" style={{ left: `${swipe}%` }}><button type="button" className="rh-compare-swipe-handle" role="slider" aria-label="Before and after divider" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(swipe)} aria-valuetext={`${Math.round(swipe)} percent before`} onKeyDown={(event) => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.stopPropagation(); event.preventDefault(); setSwipe((value) => clamp(value + (event.key === "ArrowLeft" ? -2 : 2), 0, 100)); } if (event.key === "Home" || event.key === "End") { event.preventDefault(); setSwipe(event.key === "Home" ? 0 : 100); } }} onPointerDown={(event) => { if (swipePointer.current !== null) return; event.currentTarget.setPointerCapture(event.pointerId); swipePointer.current = event.pointerId; moveSwipe(event.clientX); }} onPointerMove={(event) => { if (swipePointer.current === event.pointerId) moveSwipe(event.clientX); }} onPointerUp={(event) => { if (swipePointer.current === event.pointerId) swipePointer.current = null; }} onLostPointerCapture={() => { swipePointer.current = null; }}><GripVertical size={15} aria-hidden="true" /></button></div> : null}
            </div>
            {mode === "side-by-side" ? <div className="rh-compare-link-note"><span><Link2 size={13} aria-hidden="true" />Playback and zoom linked</span><label><ZoomIn size={13} aria-hidden="true" /><span className="rh-mono">{Math.round(zoom * 100)}%</span><input type="range" min="1" max="3" step="0.1" value={zoom} aria-label="Linked frame zoom" onChange={(event) => { const next = Number(event.target.value); const limit = (next - 1) * 50; setZoom(next); setPan((value) => ({ x: clamp(value.x, -limit, limit), y: clamp(value.y, -limit, limit) })); }} /></label><span>Drag either frame to pan both</span></div> : null}
            {mode === "flicker" ? <div className="rh-compare-link-note"><span>Hold <kbd className="rh-kbd">B</kbd> to see before</span><button type="button" className="rh-btn rh-btn-quiet rh-btn-sm" aria-pressed={peekBefore} onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); setPeekBefore(true); }} onPointerUp={() => setPeekBefore(false)} onPointerCancel={() => setPeekBefore(false)} onLostPointerCapture={() => setPeekBefore(false)} onBlur={() => setPeekBefore(false)} onKeyDown={(event) => { if (event.code === "Space" || event.key === "Enter") { event.preventDefault(); setPeekBefore(true); } }} onKeyUp={() => setPeekBefore(false)}>Hold to see before</button></div> : null}
            <div className="rh-compare-transport"><div className="rh-compare-transport-buttons"><button type="button" className="rh-icon-btn" aria-label="Previous frame" disabled={!duration} onClick={() => step(-1)}><SkipBack size={15} aria-hidden="true" /></button><button type="button" className="rh-icon-btn rh-compare-play" aria-label={playing ? "Pause comparison" : "Play both takes"} disabled={!playable} onClick={() => void togglePlayback()}>{playing ? <Pause size={14} aria-hidden="true" /> : <Play size={14} aria-hidden="true" />}</button><button type="button" className="rh-icon-btn" aria-label="Next frame" disabled={!duration} onClick={() => step(1)}><SkipForward size={15} aria-hidden="true" /></button><span className="rh-mono rh-num"><span className="rh-ember">{timecode}</span><span className="rh-fg3"> / {compareTimecode(duration)}</span></span></div><div className="rh-compare-transport-options"><button type="button" className="rh-btn rh-btn-quiet rh-btn-sm" aria-pressed={loop} onClick={() => setLoop((value) => !value)}><Repeat2 size={13} aria-hidden="true" />Loop</button><span><kbd className="rh-kbd">←</kbd><kbd className="rh-kbd">→</kbd> frame</span></div></div>
            <input type="range" className="rh-compare-scrubber" aria-label="Comparison frame" aria-valuetext={`${timecode} of ${compareTimecode(duration)}`} min="0" max={lastFrameSeconds} step={1 / 24} value={Math.min(seconds, lastFrameSeconds)} disabled={!duration} onChange={(event) => seek(Number(event.target.value))} />
            <p className="rh-compare-media-note" role="status">{mediaError ?? (!videosAvailable ? "Still preview. Scrubbing changes the frame reference; these posters do not play." : !ready.before || !ready.after ? "Loading both takes…" : held ? "The after take is trimmed. Its last available frame is held." : "Both takes share one playback clock.")}</p>
          </div>
        </div>
        <aside className="rh-compare-sidebar" aria-label="Take comparison and actions">
          <h3 className="rh-eyebrow">Compare</h3>
          <div className="rh-compare-take-pair"><span className="rh-compare-baseline"><span className="rh-dot rh-dot-ok" aria-hidden="true" />Take {document.takes.find((take) => take.id === beforeTakeId)?.n ?? 1} · before</span><ArrowLeftRight size={14} aria-hidden="true" /><label className="rh-sr-only" htmlFor={`${formId}-take`}>After take</label><select id={`${formId}-take`} className="rh-input" value={selectedTake?.id ?? ""} onChange={(event) => pickTake(event.target.value)}>{takes.map((take) => <option key={take.id} value={take.id}>Take {take.n} · {takeState(take)}</option>)}</select></div>
          <p className="rh-compare-description">{change.description}</p>
          {selectedTake ? <div className="rh-compare-specs"><span className="rh-chip rh-chip-mono">{selectedTake.durationMs / 1000} s</span>{selectedTake.height ? <span className="rh-chip rh-chip-mono">{selectedTake.height}p</span> : null}<span className="rh-chip rh-chip-mono">16:9 preview</span></div> : null}
          <div className="rh-compare-takes" aria-label="Retained takes">{takes.map((take) => <button type="button" key={take.id} className="rh-compare-take" data-selected={take.id === selectedTake?.id || undefined} data-state={takeState(take)} aria-pressed={take.id === selectedTake?.id} onClick={() => pickTake(take.id)}><span className="rh-compare-take-thumb" style={{ backgroundImage: take.posterUrl || take.mediaKind === "still" ? `url("${take.posterUrl ?? take.mediaRef}")` : undefined }} /><span><b>Take {take.n}</b><small>{takeState(take)}</small></span><span className="rh-money rh-mono">{formatCents(take.costCents)}</span></button>)}</div>
          {selectedTake ? <div className="rh-compare-price"><dl><div><dt>Take {selectedTake.n} · {selectedTake.mediaKind === "video" ? "video clip" : "still preview"}</dt><dd className="rh-mono rh-money">{formatCents(selectedTake.costCents)}</dd></div></dl><p>{candidatePending ? "No result has been taken yet. Review its estimate and approval in Changes." : "Already charged. Accepting or rejecting adds no cost, and the take you don’t pick stays in Takes."}</p></div> : null}
          {candidateTooShort ? <p className="rh-compare-action-note" role="status">This take is shorter than your cut. Trim the cut before accepting it.</p> : null}
          <div className="rh-compare-actions"><button type="button" className="rh-btn rh-btn-primary" disabled={!acceptEnabled} onClick={() => { if (selectedTake) onAcceptTake(selectedTake.id); }}><Check size={15} aria-hidden="true" />{selectedTake?.id === currentTakeId ? `Take ${selectedTake.n} is in your cut` : `Accept take ${selectedTake?.n ?? 2}`}</button><button type="button" className="rh-btn" disabled={!["ready", "proposed", "reverted"].includes(change.state)} onClick={onKeepTake}>Keep take {document.takes.find((take) => take.id === beforeTakeId)?.n ?? 1}</button><button type="button" className="rh-btn rh-btn-quiet rh-compare-new-take" disabled={!onNewTake} onClick={onNewTake}><RotateCw size={14} aria-hidden="true" /><span>New take{quote ? ` · est. ${formatCents(quote.estimateCents)}` : ""}</span>{quote ? <small>cap {formatCents(quote.capCents)}</small> : null}</button>{!quote ? <p className="rh-compare-action-note">A new take shows its estimate and hard cap before it runs.</p> : null}{change.state === "out_of_date" ? <p className="rh-compare-action-note">This change is out of date. Re-check it in Changes before accepting.</p> : null}</div>
          <form className="rh-compare-frame-form" onSubmit={(event) => { event.preventDefault(); if (!note.trim() || !onAskFrame) return; onAskFrame(`About ${change.title}, take ${selectedTake?.n ?? 1}, frame ${timecode}: ${note.trim()}`); setNote(""); setNoteSent(true); }}><label className="rh-eyebrow" htmlFor={`${formId}-note`}>Ask about this frame</label><div className="rh-compare-note-input"><span className="rh-chip rh-chip-mono"><MapPin size={11} aria-hidden="true" />{timecode}</span><input id={`${formId}-note`} value={note} onChange={(event) => { setNote(event.target.value); setNoteSent(false); }} placeholder="Keep the window less blown out…" /><button type="submit" className="rh-icon-btn" aria-label={`Send note about frame ${timecode}`} disabled={!note.trim() || !onAskFrame}><Send size={13} aria-hidden="true" /></button></div><p>Sends your note and timecode to the agent. A new take shows its price before it runs.</p><span className="rh-sr-only" role="status" aria-live="polite">{noteSent ? `Frame note queued for the agent at ${timecode}.` : ""}</span></form>
        </aside>
      </div>
      <CutRibbon document={document} beforeCut={beforeCut} afterCut={afterCut} />
    </section>
  );
}

function CompareMedia({ side, take, videoRef, transform, clipPath, subtitle, onReady, onError, onPointerDown, onPointerMove, onPointerUp }: {
  side: "before" | "after";
  take: Take | undefined;
  videoRef: RefObject<HTMLVideoElement | null>;
  transform?: string;
  clipPath?: string;
  subtitle: string;
  onReady: () => void;
  onError: () => void;
  onPointerDown: (event: PointerEvent<HTMLDivElement>) => void;
  onPointerMove: (event: PointerEvent<HTMLDivElement>) => void;
  onPointerUp: (event: PointerEvent<HTMLDivElement>) => void;
}) {
  return <div className="rh-compare-frame" data-side={side} style={{ clipPath }}><div className="rh-compare-frame-label"><span className="rh-mono">{side === "before" ? "Before" : "After"} · Take {take?.n ?? "unavailable"}</span><small className="rh-mono">{subtitle}</small></div><div className={`rh-compare-media-viewport rh-ticks ${side === "after" ? "rh-acc" : ""}`} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp} onLostPointerCapture={onPointerUp}><div className="rh-compare-media-crop"><div className="rh-compare-media" style={{ transform }}>{take?.mediaKind === "video" ? <video ref={videoRef} src={take.mediaRef} poster={take.posterUrl} muted playsInline preload="auto" onLoadedData={onReady} onError={onError} aria-label={`${side === "before" ? "Before" : "After"}, take ${take.n}`} /> : take ? <img src={take.posterUrl ?? take.mediaRef} alt={`${side === "before" ? "Before" : "After"}, take ${take.n}, still preview`} onError={onError} /> : <div className="rh-compare-unavailable">No take available for this frame.</div>}</div></div><span className="rh-tk" /></div></div>;
}
