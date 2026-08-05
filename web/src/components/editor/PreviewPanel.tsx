"use client";

import { Player, type PlayerRef } from "@remotion/player";
import { type DragEvent, useCallback, useEffect, useRef, useState } from "react";
import { importVideoFiles, useFilePicker, VIDEO_TRACK_ID } from "@/lib/timeline/import";
import { getTimelineDuration, findClipAtTime } from "@/lib/timeline/query";
import { useTimelineStore } from "@/lib/timeline/store";
import { COMPOSITION_FPS, COMPOSITION_HEIGHT, COMPOSITION_WIDTH } from "./remotion/constants";
import { type ClipDecodeStatus, TimelineComposition } from "./remotion/TimelineComposition";

export function PreviewPanel() {
  const document = useTimelineStore((s) => s.document);
  const playheadSec = useTimelineStore((s) => s.playheadSec);
  const isPlaying = useTimelineStore((s) => s.isPlaying);
  const setPlayhead = useTimelineStore((s) => s.setPlayhead);
  const pause = useTimelineStore((s) => s.pause);

  const clipCount = document.tracks.reduce((n, t) => n + t.items.length, 0);
  const [importing, setImporting] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const playerRef = useRef<PlayerRef>(null);
  // Last frame *we* reported via the frameupdate listener below — lets the
  // seek effect tell "Player just told us this" apart from "user scrubbed
  // the timeline". Needed because Player's seekTo() pauses-then-resumes
  // internally on every call (see PlayerUI's seekTo), so calling it once per
  // frame during normal playback stalls playback almost entirely.
  const lastReportedFrameRef = useRef<number | null>(null);

  const durationInFrames = Math.max(1, Math.round(getTimelineDuration(document) * COMPOSITION_FPS));

  // Per-asset decode status (ARCHITECTURE.md §11 — ProRes-in-Chrome etc.),
  // reported by each <Video> inside the composition via onVideoFrame/onError
  // (TimelineComposition.tsx) — this is the same signal the old
  // requestVideoFrameCallback check used, now sourced from Remotion directly
  // instead of a raw <video> ref.
  const [clipStatus, setClipStatus] = useState<Record<string, ClipDecodeStatus>>({});
  const onClipStatusChange = useCallback((assetId: string, status: ClipDecodeStatus) => {
    setClipStatus((prev) => (prev[assetId] === status ? prev : { ...prev, [assetId]: status }));
  }, []);

  const activeClip = findClipAtTime(document, VIDEO_TRACK_ID, playheadSec);
  const activeStatus = activeClip ? clipStatus[activeClip.assetId] : undefined;

  // Store playhead -> Player, but only for playhead changes that *didn't*
  // originate from the Player itself (a real scrub, e.g. dragging the
  // timeline). Skipping self-reported frames avoids fighting the frameupdate
  // listener below during normal playback.
  useEffect(() => {
    const player = playerRef.current;
    if (!player || clipCount === 0) return;
    const targetFrame = Math.round(playheadSec * COMPOSITION_FPS);
    if (targetFrame === lastReportedFrameRef.current) return;
    if (player.getCurrentFrame() !== targetFrame) player.seekTo(targetFrame);
  }, [playheadSec, clipCount]);

  // Store isPlaying -> Player.
  useEffect(() => {
    const player = playerRef.current;
    if (!player || clipCount === 0) return;
    if (isPlaying) player.play();
    else player.pause();
  }, [isPlaying, clipCount]);

  // Player -> store playhead, and end-of-timeline -> pause. Unlike the old
  // single-<video> approach, one Player plays continuously through every
  // clip on the video track — no manual "cue the next clip" needed.
  useEffect(() => {
    const player = playerRef.current;
    if (!player || clipCount === 0) return;

    function onFrameUpdate(event: { detail: { frame: number } }) {
      lastReportedFrameRef.current = event.detail.frame;
      setPlayhead(event.detail.frame / COMPOSITION_FPS);
    }
    function onEnded() {
      pause();
    }
    player.addEventListener("frameupdate", onFrameUpdate);
    player.addEventListener("ended", onEnded);
    return () => {
      player.removeEventListener("frameupdate", onFrameUpdate);
      player.removeEventListener("ended", onEnded);
    };
  }, [clipCount, setPlayhead, pause]);

  async function handleFiles(files: File[]) {
    setImporting(true);
    try {
      await importVideoFiles(files);
    } catch (err) {
      console.error("Import failed:", err);
    } finally {
      setImporting(false);
    }
  }

  const { inputRef, open, onChange } = useFilePicker(handleFiles);

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(false);
    const files = Array.from(event.dataTransfer.files);
    if (files.length) void handleFiles(files);
  }

  return (
    <div
      className={`flex min-h-0 flex-1 items-center justify-center p-8 transition-colors ${
        dragActive ? "bg-indigo-950/40" : "bg-neutral-900"
      }`}
      onDragOver={(event) => {
        event.preventDefault();
        setDragActive(true);
      }}
      onDragLeave={() => setDragActive(false)}
      onDrop={onDrop}
    >
      <input ref={inputRef} type="file" accept="video/*" multiple hidden onChange={onChange} />
      <div
        onClick={clipCount === 0 && !importing ? open : undefined}
        className={`relative flex aspect-[9/16] h-full max-h-full items-center justify-center overflow-hidden rounded-lg border px-6 text-center text-sm text-neutral-600 ${
          dragActive ? "border-indigo-500" : "border-neutral-800"
        } bg-black ${clipCount === 0 ? "cursor-pointer hover:border-neutral-700" : ""}`}
      >
        {/*
          Player stays mounted continuously, even with zero clips (duration
          clamped to >=1 frame) — @remotion/player's ref is captured once on
          first mount and never re-evaluated afterwards, so conditionally
          mounting/unmounting Player around the empty state left playerRef
          permanently null after the empty->first-clip transition. The empty
          state renders as an overlay on top instead of swapping Player out.
        */}
        <Player
          ref={playerRef}
          component={TimelineComposition}
          inputProps={{ document, onClipStatusChange }}
          durationInFrames={durationInFrames}
          fps={COMPOSITION_FPS}
          compositionWidth={COMPOSITION_WIDTH}
          compositionHeight={COMPOSITION_HEIGHT}
          controls={false}
          clickToPlay={false}
          // EditorShell already owns the Space shortcut (app-wide undo/redo/play
          // handling) — without this, Player's own internal spacebar listener
          // double-toggles play/pause on the same keypress and it net-cancels.
          spaceKeyToPlayOrPause={false}
          style={{ width: "100%", height: "100%" }}
          acknowledgeRemotionLicense
        />
        {importing ? (
          <div className="absolute inset-0 flex items-center justify-center bg-black">
            <span>Importing & transcoding…</span>
          </div>
        ) : clipCount === 0 ? (
          <div className="absolute inset-0 flex items-center justify-center bg-black">
            <span>Drop a video file here, or click to browse</span>
          </div>
        ) : (
          activeStatus === "unsupported" && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/80 px-6 text-center text-xs text-neutral-400">
              Preview isn&apos;t available for this file&apos;s video codec (often ProRes or HEVC
              exports). Audio still plays and the timeline is unaffected. Renderhaus will
              transcode a web-playable proxy on import in a later build.
            </div>
          )
        )}
      </div>
    </div>
  );
}
