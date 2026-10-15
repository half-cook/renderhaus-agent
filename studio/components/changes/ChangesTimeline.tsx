"use client";

import { AlertTriangle, GitCompareArrows, Mic, Plus } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  TimelineHints, TimelineTrack, TransportBar, useTransport, type TimelineModel,
} from "@/components/timeline/Timeline";
import {
  cutClips, cutDurationMs, needYou, withChangesCut, type ChangeItem, type ChangesDocument, type Cut, type Take,
} from "@/lib/rh/changes";
import { formatCents } from "@/lib/rh/money";
import type { ApprovalCardModel } from "@/lib/rh/billing";
import { clipLength, moveClip, PX_PER_SECOND, timecode, totalSeconds, type TimelineClip } from "@/lib/rh/timeline";

const kindLabels: Record<ChangeItem["kind"], string> = {
  take: "New take", trim: "Trim", reorder: "Reorder", voice: "Voiceover", still: "Still image",
};
const stateLabels: Record<ChangeItem["state"], string> = {
  proposed: "Needs you", awaiting_approval: "Needs approval", running: "Running", ready: "Needs you",
  accepted: "Accepted", rejected: "Rejected", reverted: "Reverted", out_of_date: "Out of date",
  failed: "Failed", paused_at_cap: "Paused at the cap",
};
const lengthText = (seconds: number) => `${seconds.toFixed(1)} s`;
const voiceTime = (ms: number) => `${Math.floor(ms / 60000)}:${(ms / 1000 % 60).toFixed(1).padStart(4, "0")}`;
const isPending = (change: ChangeItem) => change.state === "proposed" || change.state === "ready" || change.state === "awaiting_approval";

type ChangeMarker = { change: ChangeItem; left: number; row: number; width: number; missingShot: boolean };

export function changeTimelineMarkers(changes: ChangeItem[], clips: TimelineClip[], pxPerSecond: number): ChangeMarker[] {
  const positions = new Map<string, { start: number; clip: TimelineClip }>();
  let cursor = 0;
  for (const clip of clips) {
    positions.set(clip.id, { start: cursor, clip });
    cursor += clipLength(clip);
  }
  const sameShot = new Map<string, number>();
  const markers: ChangeMarker[] = [];
  for (const change of changes) {
    const position = change.slotId ? positions.get(change.slotId) : undefined;
    const key = change.slotId ?? change.kind;
    const index = sameShot.get(key) ?? 0;
    sameShot.set(key, index + 1);
    let seconds = position?.start ?? (change.kind === "voice" ? cursor * 0.68 : 0);
    if (change.kind === "trim" && position) seconds += Math.max(0, (change.afterRef.outMs - change.afterRef.inMs) / 1000);
    const left = Math.round((seconds * pxPerSecond + (change.kind === "trim" ? 0 : index * 32)) * 1000) / 1000;
    const width = 168;
    let row = 0;
    while (markers.some((marker) => marker.row === row && left < marker.left + marker.width && left + width > marker.left)) row += 1;
    markers.push({ change, left, row, width, missingShot: Boolean(change.slotId && !position) });
  }
  return markers;
}

function ChangeFlags({ changes, clips, zoom, selectedN, onSelect }: {
  changes: ChangeItem[]; clips: TimelineClip[]; zoom: number; selectedN: number; onSelect: (n: number) => void;
}) {
  const markers = changeTimelineMarkers(changes, clips, zoom);
  const height = Math.max(1, ...markers.map((marker) => marker.row + 1)) * 30 + 8;
  return <div className="rh-ch-timeline-flags" style={{ height }} aria-label="Changes on this cut">
    {markers.map(({ change, left, row, width, missingShot }) => {
      const shot = clips.find((clip) => clip.id === change.slotId);
      const shotName = shot ? `Shot ${shot.order}` : missingShot ? "Shot unavailable" : "Cut";
      const label = `Change ${change.n}, ${shotName}, ${kindLabels[change.kind].toLowerCase()}, ${stateLabels[change.state].toLowerCase()}`;
      return <button key={change.id} type="button" className="rh-ch-timeline-flag" data-state={change.state}
        data-selected={change.n === selectedN} aria-pressed={change.n === selectedN} aria-label={label} title={label}
        style={{ left, top: 4 + row * 30, width }} onClick={() => onSelect(change.n)}>
        <b className="rh-ch-timeline-number rh-mono">{change.n}</b>
        <span>{kindLabels[change.kind]} <small>{stateLabels[change.state]}</small></span>
      </button>;
    })}
  </div>;
}

function TakeCard({ take, state, charged, onSelect }: { take: Take; state: "current" | "proposed" | "rejected" | "kept"; charged: boolean; onSelect: () => void }) {
  const label = state === "current" ? "In your cut" : state === "proposed" ? "Proposed" : state === "rejected" ? "Rejected" : "Kept in Takes";
  return <button type="button" className="rh-ch-timeline-take" data-state={state}
    onClick={onSelect} aria-label={`Take ${take.n}, ${label.toLowerCase()}, ${formatCents(take.costCents)} ${charged ? "charged" : "waiting for approval"}`}>
    <div className="rh-ch-timeline-take-image">
      {take.posterUrl ? <img src={take.posterUrl} alt="" draggable={false} /> : <span>No preview yet</span>}
      <span className="rh-ch-timeline-take-state">{label}</span>
      <span className="rh-ch-timeline-take-n rh-mono">Take {take.n}</span>
      <span className="rh-ch-timeline-take-price rh-mono rh-num">{formatCents(take.costCents)}</span>
    </div>
  </button>;
}

export type ChangesTimelineProps = {
  document: ChangesDocument;
  selectedN: number;
  monitorMode: "current" | "changes";
  onMonitorModeChange: (mode: "current" | "changes") => void;
  onSelectChange: (n: number) => void;
  onCompare: (n: number) => void;
  onNewTake: (quote: ApprovalCardModel) => void;
  actions: Pick<TimelineModel, "trim" | "reorder" | "remove">;
  reviewPanel?: ReactNode;
  onTrimVoiceover?: (cut: Cut) => void;
  onKeepVoiceover?: () => void;
};

export function ChangesTimeline({ document, selectedN, monitorMode, onMonitorModeChange, onSelectChange,
  onCompare, onNewTake, actions, reviewPanel, onTrimVoiceover, onKeepVoiceover }: ChangesTimelineProps) {
  const [zoom, setZoom] = useState(PX_PER_SECOND);
  const [snapOn, setSnapOn] = useState(true);
  const [safeArea, setSafeArea] = useState(false);
  const [beforeHeld, setBeforeHeld] = useState(false);
  const [previewTakeId, setPreviewTakeId] = useState<string | null>(null);
  const [keepLongVoice, setKeepLongVoice] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const proposedCut = useMemo(() => withChangesCut(document), [document]);
  const visibleMode = beforeHeld ? "current" : monitorMode;
  const cut = visibleMode === "current" ? document.currentCut : proposedCut;
  const clips = useMemo(() => cutClips(document, cut), [document, cut]);
  const transport = useTransport(clips);
  const selectRef = useRef(transport.select);
  selectRef.current = transport.select;
  const selectedChange = document.changes.find((change) => change.n === selectedN);
  const model: TimelineModel = {
    clips, voiceover: null, mediaFor: () => undefined,
    trim: actions.trim, reorder: actions.reorder, remove: actions.remove,
    move: (id, offset) => actions.reorder(moveClip(clips.map((clip) => clip.id), id, offset)),
  };
  const currentSlot = document.currentCut.slots.find((slot) => slot.slotId === transport.selectedId);
  let monitorSlotId = transport.selectedId;
  if (transport.playing) {
    let start = 0;
    for (const clip of clips) {
      if (transport.playhead >= start && transport.playhead < start + clipLength(clip)) { monitorSlotId = clip.id; break; }
      start += clipLength(clip);
    }
  }
  const selectedSlot = cut.slots.find((slot) => slot.slotId === monitorSlotId);
  const previewTake = document.takes.find((take) => take.id === previewTakeId && take.slotId === transport.selectedId)
    ?? document.takes.find((take) => take.id === selectedSlot?.takeId);
  const selectedTakes = document.takes.filter((take) => take.slotId === transport.selectedId);
  const selectedTakeChange = document.changes.find((change) => change.slotId === transport.selectedId && change.kind === "take" && isPending(change));
  const videoUrl = previewTake?.mediaKind === "video" ? previewTake.mediaRef : undefined;
  const sourceClock = selectedSlot ? Math.max(0, transport.playhead - transport.startOf(selectedSlot.slotId)) + selectedSlot.inMs / 1000 : 0;
  const voiceDuration = cut.voiceDurationMs;
  const voiceTooLong = cut.voiceRef && voiceDuration !== undefined && voiceDuration > cutDurationMs(cut);
  const quote = document.newTakeApproval;

  useEffect(() => {
    if (selectedChange?.slotId) selectRef.current(selectedChange.slotId);
    setPreviewTakeId(null);
  }, [selectedN, selectedChange?.slotId]);

  useEffect(() => { transport.setPlayhead((value) => Math.min(value, transport.total)); }, [transport.total, transport.setPlayhead]);

  useEffect(() => { setKeepLongVoice(false); }, [cut.voiceRef, voiceDuration, transport.total]);

  useEffect(() => {
    const keyDown = (event: KeyboardEvent) => {
      if (event.target instanceof Element && event.target.closest("select,[role='dialog']")) return;
      if (event.metaKey || event.ctrlKey || event.altKey || event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || (event.target instanceof HTMLElement && event.target.isContentEditable)) return;
      if (event.key.toLowerCase() === "b") { event.preventDefault(); setBeforeHeld(true); }
      if (event.key.toLowerCase() === "s" && !event.repeat) setSnapOn((value) => !value);
    };
    const release = (event: KeyboardEvent) => { if (event.key.toLowerCase() === "b") setBeforeHeld(false); };
    const blur = () => setBeforeHeld(false);
    window.addEventListener("keydown", keyDown);
    window.addEventListener("keyup", release);
    window.addEventListener("blur", blur);
    return () => { window.removeEventListener("keydown", keyDown); window.removeEventListener("keyup", release); window.removeEventListener("blur", blur); };
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (Number.isFinite(video.duration) && Math.abs(video.currentTime - sourceClock) > 0.15) video.currentTime = Math.min(video.duration, sourceClock);
    if (transport.playing) void video.play().catch(() => transport.setPlaying(false));
    else video.pause();
  }, [sourceClock, transport.playing, transport.setPlaying, videoUrl]);

  const selectChange = (n: number) => { setPreviewTakeId(null); onSelectChange(n); };
  const decoration = (clip: TimelineClip) => {
    const slot = cut.slots.find((candidate) => candidate.slotId === clip.id);
    const take = document.takes.find((candidate) => candidate.id === slot?.takeId);
    const takes = document.takes.filter((candidate) => candidate.slotId === clip.id);
    const trim = document.changes.find((change) => change.kind === "trim" && change.slotId === clip.id && (isPending(change) || change.state === "accepted"));
    const removed = trim?.kind === "trim" ? Math.max(0, trim.beforeRef.outMs - trim.beforeRef.inMs - (trim.afterRef.outMs - trim.afterRef.inMs)) / 1000 : 0;
    const sourceLength = trim?.kind === "trim" ? (trim.beforeRef.outMs - trim.beforeRef.inMs) / 1000 : clipLength(clip);
    return <>
      {take && takes.length > 1 ? <span className="rh-ch-timeline-take-label rh-mono" data-tail={clip.order === clips.length} title={`Take ${take.n} of ${takes.length}`}>Take {take.n} of {takes.length}</span> : null}
      {removed > 0 ? <span className="rh-ch-timeline-trim" style={{ width: `${Math.min(100, removed / sourceLength * 100)}%` }} title={`${lengthText(removed)} removed`}><b className="rh-mono">−{lengthText(removed)}</b></span> : null}
    </>;
  };

  return <div className="rh-ch-timeline" data-shot="timeline-changes">
    <div className="rh-ch-timeline-top">
      <section className="rh-ch-timeline-monitorwrap" aria-label="Cut monitor">
        <div className="rh-ch-timeline-monitor rh-ticks" data-mode={visibleMode}>
          {videoUrl ? <video key={previewTake?.id} ref={videoRef} src={videoUrl} poster={previewTake?.posterUrl} muted playsInline preload="metadata" onLoadedMetadata={(event) => { event.currentTarget.currentTime = Math.min(event.currentTarget.duration, sourceClock); }} aria-label={`${transport.selected?.title ?? "Shot"}, Take ${previewTake?.n}`} />
            : previewTake?.posterUrl ? <img src={previewTake.posterUrl} alt={`${transport.selected?.title ?? "Shot"}, Take ${previewTake.n} preview`} />
              : <div className="rh-ch-timeline-no-preview">Select a shot with a preview.</div>}
          <span className="rh-ch-timeline-preview-label rh-mono">{previewTakeId && previewTake?.id !== selectedSlot?.takeId ? "Take preview" : visibleMode === "changes" ? "With changes" : "Current cut"}{previewTake ? ` · Take ${previewTake.n}` : ""}</span>
          {safeArea ? <span className="rh-tl-safe" aria-hidden="true" /> : null}<span className="rh-tk" />
        </div>
        <div className="rh-ch-timeline-caption">
          <div className="rh-seg" role="group" aria-label="Monitor cut">
            <button type="button" aria-pressed={visibleMode === "current"} onClick={() => { setPreviewTakeId(null); onMonitorModeChange("current"); }}>Current cut</button>
            <button type="button" aria-pressed={visibleMode === "changes"} onClick={() => { setPreviewTakeId(null); onMonitorModeChange("changes"); }}>With changes</button>
          </div>
          <span className="rh-mono rh-fg3">{transport.selected?.title ?? "Cut"} · {timecode(transport.playhead)} · 16:9 preview</span>
          {selectedTakeChange ? <button type="button" className="rh-btn rh-btn-sm" onClick={() => onCompare(selectedTakeChange.n)}><GitCompareArrows size={13} aria-hidden="true" />Compare</button> : null}
          <button type="button" className="rh-linkbtn rh-small" aria-pressed={safeArea} onClick={() => setSafeArea((value) => !value)}>Safe area {safeArea ? "on" : "off"}</button>
        </div>
        {!videoUrl ? <p className="rh-ch-timeline-preview-note">Still preview. Playback is not available for this take.</p> : null}
      </section>
      {reviewPanel}
    </div>
    <section className="rh-ch-timeline-dock" aria-label="Timeline with changes">
      <TransportBar model={model} transport={transport} snapOn={snapOn} onSnap={() => setSnapOn((value) => !value)} zoom={zoom} onZoom={setZoom} playbackAvailable={Boolean(videoUrl)}>
        <span className="rh-chip rh-chip-accent rh-ch-timeline-count"><GitCompareArrows size={12} aria-hidden="true" />{document.changes.length} {document.changes.length === 1 ? "change" : "changes"} · {needYou(document)} need you</span>
        {cut.voiceRef ? <span className="rh-chip rh-ch-timeline-voice"><Mic size={12} aria-hidden="true" />Voiceover attached{document.currentCut.voiceDurationMs !== undefined && voiceDuration !== undefined ? ` · ${voiceTime(document.currentCut.voiceDurationMs)} to ${voiceTime(voiceDuration)}` : voiceDuration !== undefined ? ` · ${voiceTime(voiceDuration)}` : ""}</span> : null}
      </TransportBar>
      {voiceTooLong ? <div className="rh-ch-timeline-audio-warning" role="status"><AlertTriangle size={14} aria-hidden="true" /><span>Voiceover is longer than this cut.{keepLongVoice ? " Kept at its full length." : ""}</span>
        {onTrimVoiceover ? <button type="button" className="rh-btn rh-btn-sm" onClick={() => onTrimVoiceover(cut)}>Trim to fit</button> : null}
        {!keepLongVoice ? <button type="button" className="rh-btn rh-btn-quiet rh-btn-sm" onClick={() => { setKeepLongVoice(true); onKeepVoiceover?.(); }}>Keep</button> : null}
      </div> : null}
      <TimelineTrack model={model} transport={transport} pxPerSecond={zoom} snapOn={snapOn} height={84} readOnly={visibleMode === "changes"}
        thumbnailMode="repeat-cover" clipDecoration={decoration}
        clipClassName={(clip) => document.changes.some((change) => change.slotId === clip.id && isPending(change)) ? "rh-ch-timeline-pending" : ""}
        changesRow={<ChangeFlags changes={document.changes} clips={clips} zoom={zoom} selectedN={selectedN} onSelect={selectChange} />} />
      <div className="rh-ch-timeline-takes">
        <div className="rh-ch-timeline-takes-heading"><span className="rh-eyebrow">Takes{transport.selected ? ` · Shot ${transport.selected.order}` : ""}</span><span>Pick a take to preview. Unused takes stay here.</span></div>
        <div className="rh-ch-timeline-takes-strip">
          {selectedTakes.map((take) => {
            const change = document.changes.find((candidate) => candidate.kind === "take" && candidate.afterRef.takeId === take.id);
            const state = take.id === currentSlot?.takeId ? "current" : change?.state === "rejected" || take.reviewState === "rejected" ? "rejected" : change && isPending(change) ? "proposed" : "kept";
            return <TakeCard key={take.id} take={take} state={state} charged={!change || change.taken} onSelect={() => setPreviewTakeId(take.id)} />;
          })}
          <button type="button" className="rh-ch-timeline-new-take" onClick={() => quote && onNewTake(quote)} disabled={!quote}>
            <Plus size={16} aria-hidden="true" /><span>New take</span>
            <span className="rh-mono rh-num">{quote ? `est. ${formatCents(quote.estimateCents)} · cap ${formatCents(quote.capCents)}` : "Ask the agent for a price"}</span>
          </button>
        </div>
      </div>
      {visibleMode === "current" ? <TimelineHints canRemove={Boolean(transport.selectedId)} onRemove={() => transport.selectedId && actions.remove(transport.selectedId)} />
        : <p className="rh-ch-timeline-edit-note">With changes is a preview. Switch to Current cut to trim or reorder.</p>}
      <span className="rh-ch-timeline-length rh-mono" aria-label="Cut length comparison">Current cut {lengthText(totalSeconds(cutClips(document, document.currentCut)))} · With changes {lengthText(totalSeconds(cutClips(document, proposedCut)))}</span>
    </section>
  </div>;
}
