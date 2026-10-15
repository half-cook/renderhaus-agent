"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Pause, Play, RotateCcw } from "lucide-react";
import type { AgentApprovalRequest } from "@/lib/api";
import { useStudioAssetPlayback } from "@/lib/assets";
import { finishingComparison, type FinishingComparison } from "@/lib/rh/finishing-preview";
import { formatCents } from "@/lib/rh/money";
import styles from "./FinishingPreviewReview.module.css";

type Props = {
  approval: AgentApprovalRequest;
  active: boolean;
  busy: boolean;
  onDecision: (approval: AgentApprovalRequest, decision: "approve" | "reject") => void;
};

export function FinishingPreviewReview(props: Props) {
  const comparison = finishingComparison(props.approval.arguments);
  if (!comparison) return <article className={styles.card}>
    <h3>Preview unavailable</h3>
    <p>The saved comparison is incomplete. A new preview is needed before the full finish.</p>
    {props.active && !props.approval.decision ? <button type="button" className="rh-btn" disabled={props.busy}
      onClick={() => props.onDecision(props.approval, "reject")}>Keep original</button> : null}
  </article>;
  return <Comparison {...props} comparison={comparison} />;
}

type Side = "before" | "after";
type View = "side-by-side" | "before" | "after";

function Comparison({ approval, comparison, active, busy, onDecision }: Props & { comparison: FinishingComparison }) {
  const [attempt, setAttempt] = useState(0);
  const beforePlayback = useStudioAssetPlayback(comparison.before, attempt);
  const afterPlayback = useStudioAssetPlayback(comparison.after, attempt);
  const beforeUrl = beforePlayback.status === "ready" ? beforePlayback.url : undefined;
  const afterUrl = afterPlayback.status === "ready" ? afterPlayback.url : undefined;
  const before = useRef<HTMLVideoElement>(null);
  const after = useRef<HTMLVideoElement>(null);
  const [ready, setReady] = useState<Set<Side>>(new Set());
  const [watched, setWatched] = useState<Set<Side>>(new Set());
  const [playing, setPlaying] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [mediaError, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("side-by-side");
  const descriptionId = useId();
  const pending = active && !approval.decision;
  const error = mediaError ?? (beforePlayback.status === "error" ? beforePlayback.message
    : afterPlayback.status === "error" ? afterPlayback.message : null);
  const canPlay = ready.size === 2 && beforeUrl !== undefined && afterUrl !== undefined && !error;
  const canApprove = pending && !busy && canPlay && watched.size === 2;
  const lastFrameTime = Math.max(0, comparison.duration - 1 / comparison.sourceFps);

  useEffect(() => () => { before.current?.pause(); after.current?.pause(); }, []);

  function pause() {
    before.current?.pause();
    after.current?.pause();
    setPlaying(false);
  }

  function seek(value: number) {
    pause();
    const next = Math.max(0, Math.min(value, lastFrameTime));
    if (before.current) before.current.currentTime = next;
    if (after.current) after.current.currentTime = next;
    setSeconds(next);
  }

  async function play() {
    if (!canPlay || !before.current || !after.current) return;
    if (before.current.ended || before.current.currentTime >= lastFrameTime) seek(0);
    after.current.currentTime = before.current.currentTime;
    try {
      await Promise.all([before.current.play(), after.current.play()]);
      setPlaying(true);
    } catch {
      pause();
      setError("Playback failed. Reopen this review to reload both saved previews.");
    }
  }

  function loaded(side: Side, video: HTMLVideoElement) {
    if (!Number.isFinite(video.duration) || video.duration <= 0 || !video.videoWidth || !video.videoHeight) {
      fail();
      return;
    }
    setReady((previous) => new Set([...previous, side]));
  }

  function fail() {
    pause();
    setError("A saved preview could not be played. Keep the original and request a new preview.");
  }

  function timeUpdate(side: Side, video: HTMLVideoElement) {
    if (side !== "before") return;
    setSeconds(Math.min(video.currentTime, comparison.duration));
    if (after.current && Math.abs(after.current.currentTime - video.currentTime) > Math.max(.08, 2 / comparison.outputFps)) {
      after.current.currentTime = video.currentTime;
    }
  }

  function playingPreview(side: Side) {
    setWatched((previous) => previous.has(side) ? previous : new Set([...previous, side]));
  }

  const views: Array<{ id: View; label: string }> = [
    { id: "side-by-side", label: "Side by side" }, { id: "before", label: "A · Original" }, { id: "after", label: "B · Enhanced" },
  ];
  return <article className={styles.card} aria-label="Review finishing preview" aria-describedby={descriptionId}>
    <h3>Compare the preview</h3>
    <p id={descriptionId}>{comparison.duration.toFixed(2)} s sample starting at {comparison.sourceStart.toFixed(2)} s. Review detail, faces, and motion before finishing the full clip.</p>
    <div className={styles.views} role="group" aria-label="Comparison view">
      {views.map((item) => <button type="button" className="rh-btn rh-btn-sm" key={item.id}
        aria-pressed={view === item.id} onClick={() => setView(item.id)}>{item.label}</button>)}
    </div>
    <div className={styles.frames} data-view={view}>
      <figure hidden={view === "after"}>
        <figcaption>Original · {comparison.sourceWidth} × {comparison.sourceHeight} · {comparison.sourceFps} fps</figcaption>
        <video ref={before} src={beforeUrl} aria-label="Original preview" playsInline muted preload="auto"
          onLoadedData={(event) => loaded("before", event.currentTarget)} onError={fail}
          onPlaying={() => playingPreview("before")}
          onTimeUpdate={(event) => timeUpdate("before", event.currentTarget)} onEnded={pause}
          onWaiting={() => { if (playing) pause(); }} />
      </figure>
      <figure hidden={view === "before"}>
        <figcaption>Enhanced · {comparison.outputWidth} × {comparison.outputHeight} · {comparison.outputFps} fps</figcaption>
        <video ref={after} src={afterUrl} aria-label="Enhanced preview" playsInline muted preload="auto"
          onLoadedData={(event) => loaded("after", event.currentTarget)} onError={fail}
          onPlaying={() => playingPreview("after")}
          onTimeUpdate={(event) => timeUpdate("after", event.currentTarget)}
          onWaiting={() => { if (playing) pause(); }} />
      </figure>
    </div>
    <div className={styles.transport}>
      <button type="button" className="rh-btn rh-btn-sm" disabled={!canPlay} onClick={() => { if (playing) pause(); else void play(); }}>
        {playing ? <Pause size={14} aria-hidden="true" /> : <Play size={14} aria-hidden="true" />}{playing ? "Pause" : "Play both"}
      </button>
      <button type="button" className="rh-btn rh-btn-sm" disabled={!canPlay} onClick={() => seek(0)}><RotateCcw size={14} aria-hidden="true" />Restart</button>
      <span className="rh-mono">{seconds.toFixed(2)} / {comparison.duration.toFixed(2)} s</span>
    </div>
    <input type="range" className={styles.scrubber} min={0} max={lastFrameTime}
      step={1 / Math.max(comparison.sourceFps, comparison.outputFps)} value={seconds}
      disabled={!canPlay} aria-label="Comparison position" onChange={(event) => seek(Number(event.target.value))} />
    <p role="status">{error ?? (!canPlay ? "Loading both saved previews…" : watched.size < 2 ? "Play both previews before continuing." : "Both previews played. Review this sample before continuing.")}</p>
    {error ? <button type="button" className="rh-btn rh-btn-sm" onClick={() => {
      pause(); setError(null); setReady(new Set()); setWatched(new Set()); setSeconds(0); setAttempt((value) => value + 1);
    }}>Reload previews</button> : null}
    <p>{comparison.coversFullSource ? "This sample covers the entire source. Accepting keeps this finished clip and starts no additional processing."
      : <>{comparison.fullEstimateCents === null ? "Full finish estimate unknown." : `Full finish estimate ${formatCents(comparison.fullEstimateCents)}.`} Continuing shows a separate spending approval. Preview cost is separate from full processing.</>}</p>
    {pending ? <footer className={styles.actions}>
      <button type="button" className="rh-btn" disabled={busy} onClick={() => { pause(); onDecision(approval, "reject"); }}>Keep original</button>
      <button type="button" className="rh-btn rh-btn-primary" disabled={!canApprove}
        onClick={() => { pause(); onDecision(approval, "approve"); }}>{comparison.coversFullSource ? "Accept finished clip" : "Continue to full estimate"}</button>
    </footer> : <p>{approval.decision === "approve" ? comparison.coversFullSource ? "Finished clip accepted." : "Preview accepted. Full processing has its own spending approval." : approval.decision === "reject" ? "Original kept. Full processing was not approved." : "This review is closed."}</p>}
  </article>;
}
