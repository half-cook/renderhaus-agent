"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { clamp, clipLength, syncTimelineVideo, timelinePosition, type TimelineClip } from "@/lib/rh/timeline";
import type { Transport } from "./Timeline";

/** Keep every timeline monitor on its real source clock, including loading and trims. */
export function useTimelinePlayback(clips: TimelineClip[], transport: Transport, {
  sourceKey,
  active,
  stopAtSourceEnd = false,
}: { sourceKey?: string; active: boolean; stopAtSourceEnd?: boolean }) {
  const video = useRef<HTMLVideoElement | null>(null);
  const playingRef = useRef(transport.playing);
  const reported = useRef<{ sourceKey?: string; clipId: string; sourceTime: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [endedEarly, setEndedEarly] = useState(false);
  const position = timelinePosition(clips, transport.playhead);
  const selected = position?.clip;
  const timelineStart = position?.timelineStart ?? 0;
  const { setPlayhead, playing, setPlaying, total } = transport;
  playingRef.current = playing && active;
  const videoRef = useCallback((next: HTMLVideoElement | null) => {
    if (video.current !== next) video.current?.pause();
    video.current = next;
  }, []);
  const fail = useCallback((message?: unknown) => {
    video.current?.pause();
    setPlaying(false);
    setError(typeof message === "string" ? message : "Preview could not play. Reload the preview or try Play again.");
  }, [setPlaying]);
  const sync = useCallback(() => {
    const current = video.current;
    if (!current || !position) return;
    if (current.readyState >= 1 && Number.isFinite(current.duration) && position.clip.trimIn >= current.duration) {
      fail("This take is too short for the selected trim. Choose another take or adjust the trim.");
      return;
    }
    if (playing && current.ended && stopAtSourceEnd && position.sourceTime >= current.duration - 0.005) {
      setEndedEarly(false);
      setPlayhead(position.timelineStart);
      return;
    }
    const last = reported.current;
    const seek = last?.sourceKey !== sourceKey || last?.clipId !== position.clip.id
      || Math.abs(last.sourceTime - position.sourceTime) > 0.001;
    const pending = syncTimelineVideo(current, position.sourceTime, playing && active, seek);
    if (pending) void pending.then(() => {
      if (video.current === current) setError(null);
    }).catch(() => {
      if (video.current === current && playingRef.current) fail();
    });
  }, [position?.sourceTime, position?.clip.id, position?.clip.trimIn, position?.timelineStart, sourceKey, playing, active, stopAtSourceEnd, setPlayhead, fail]);
  const read = useCallback(() => {
    const current = video.current;
    if (!active || !current || !selected || current.readyState < 1 || current.seeking) return;
    const early = current.ended && current.currentTime < selected.trimOut - 0.005;
    const atEnd = current.ended || current.currentTime >= selected.trimOut - 0.005;
    const next = atEnd && !(early && stopAtSourceEnd) ? timelineStart + clipLength(selected)
      : timelineStart + clamp(current.currentTime - selected.trimIn, 0, clipLength(selected));
    // Reporting the real clock must not seek back to that older frame after render.
    reported.current = { sourceKey, clipId: selected.id, sourceTime: current.currentTime };
    if (atEnd && playing) {
      current.pause();
      if (next >= total || (early && stopAtSourceEnd)) setPlaying(false);
      if (early && stopAtSourceEnd) setEndedEarly(true);
    }
    setPlayhead(Math.min(next, total));
  }, [active, selected, timelineStart, sourceKey, playing, total, stopAtSourceEnd, setPlayhead, setPlaying]);

  useEffect(sync, [sync]);
  useEffect(() => { setError(null); setEndedEarly(false); }, [sourceKey]);
  useEffect(() => {
    setPlayhead((value) => Math.min(value, total));
    if (!active || !total) { video.current?.pause(); setPlaying(false); }
  }, [active, total, setPlayhead, setPlaying]);
  useEffect(() => {
    if (!playing || !active) return;
    let frame = 0;
    const tick = () => { read(); frame = requestAnimationFrame(tick); };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, active, read]);

  return {
    sourceTime: position?.sourceTime, error, endedEarly,
    mediaProps: {
      videoRef,
      onMetadata: () => { setError(null); setEndedEarly(false); sync(); },
      onTimeUpdate: read, onEnded: read, onError: fail, onPlaybackError: fail,
    },
  };
}
