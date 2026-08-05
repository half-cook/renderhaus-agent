"use client";

import { useEffect, useRef } from "react";
import { formatTime } from "@/lib/timeline/format";
import type { TimelineDocument } from "@/lib/timeline/types";
import { RULER_HEIGHT, TRACK_GAP, TRACK_HEIGHT } from "./constants";
import { toRenderClips } from "./render";
import { usePanZoom } from "./usePanZoom";

const PLAYHEAD_COLOR = "#ff3b5c";
const RULER_TICK_COLOR = "#404040"; // neutral-700
const RULER_LABEL_COLOR = "#a3a3a3"; // neutral-400
const RULER_BORDER_COLOR = "#262626"; // neutral-800

// "Nice" tick spacings, in seconds, from sub-second up to an hour — pickTickIntervalSec
// walks this list to find the smallest one that keeps labels from crowding at the
// current zoom level.
const NICE_TICK_INTERVALS_SEC = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600];
const TARGET_PX_PER_LABEL = 80;

function pickTickIntervalSec(pxPerSec: number): number {
  const raw = TARGET_PX_PER_LABEL / pxPerSec;
  return (
    NICE_TICK_INTERVALS_SEC.find((step) => step >= raw) ??
    NICE_TICK_INTERVALS_SEC[NICE_TICK_INTERVALS_SEC.length - 1]
  );
}

/**
 * Single <canvas>, imperative draw, culled to the visible time range —
 * ported from spikes/timeline-render's validated approach (flat 60fps
 * regardless of clip count; see that spike's README for the measurements).
 * Click (not drag) seeks the playhead; drag pans; wheel zooms.
 */
export function CanvasTimeline({
  document: doc,
  playheadSec,
  onSeek,
}: {
  document: TimelineDocument;
  playheadSec: number;
  onSeek: (timeSec: number) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const { clips, duration, trackCount } = toRenderClips(doc);

  function draw() {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const targetW = Math.round(w * dpr);
    const targetH = Math.round(h * dpr);
    if (canvas.width !== targetW || canvas.height !== targetH) {
      canvas.width = targetW;
      canvas.height = targetH;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const offset = offsetRef.current;
    const px = pxRef.current;
    const visStart = offset;
    const visEnd = offset + w / px;

    // Time ruler — ticks + labels for the visible range, spaced at whatever
    // "nice" interval keeps labels legible at the current zoom level.
    ctx.fillStyle = RULER_BORDER_COLOR;
    ctx.fillRect(0, RULER_HEIGHT - 1, w, 1);
    const interval = pickTickIntervalSec(px);
    const firstTick = Math.floor(visStart / interval) * interval;
    ctx.font = "10px system-ui, sans-serif";
    ctx.textBaseline = "top";
    for (let t = firstTick; t <= visEnd; t += interval) {
      const x = (t - offset) * px;
      ctx.strokeStyle = RULER_TICK_COLOR;
      ctx.beginPath();
      ctx.moveTo(x + 0.5, RULER_HEIGHT - 6);
      ctx.lineTo(x + 0.5, RULER_HEIGHT - 1);
      ctx.stroke();
      ctx.fillStyle = RULER_LABEL_COLOR;
      ctx.fillText(formatTime(Math.max(0, t)), x + 3, 3);
    }

    for (const clip of clips) {
      if (clip.start + clip.duration < visStart || clip.start > visEnd) continue;
      const x = (clip.start - offset) * px;
      const width = clip.duration * px;
      const y = RULER_HEIGHT + clip.track * (TRACK_HEIGHT + TRACK_GAP);
      ctx.fillStyle = clip.color;
      ctx.fillRect(x, y, Math.max(width, 1), TRACK_HEIGHT);
      if (width > 32) {
        ctx.fillStyle = "rgba(0,0,0,0.7)";
        ctx.font = "11px system-ui, sans-serif";
        ctx.fillText(clip.label, x + 4, y + 16, Math.max(width - 8, 0));
      }
    }

    const playheadX = (playheadSec - offset) * px;
    if (playheadX >= -1 && playheadX <= w + 1) {
      ctx.fillStyle = PLAYHEAD_COLOR;
      ctx.fillRect(playheadX, 0, 2, h);
    }
  }

  const { offsetRef, pxRef, onPointerDown, onPointerMove, onPointerUp, onWheel } = usePanZoom({
    duration,
    containerWidth: () => wrapRef.current?.clientWidth ?? 800,
    onPan: draw,
    onZoom: draw,
    onSeek,
  });

  useEffect(() => {
    draw();
    // Redraw whenever the document, playhead, or container changes — pan/zoom
    // redraw themselves imperatively via the onPan/onZoom callbacks above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc, playheadSec]);

  return (
    <div
      ref={wrapRef}
      style={{ height: RULER_HEIGHT + trackCount * (TRACK_HEIGHT + TRACK_GAP) }}
      className="w-full touch-none"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onWheel={onWheel}
    >
      <canvas ref={canvasRef} className="block h-full w-full" />
    </div>
  );
}
