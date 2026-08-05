import { useCallback, useRef } from "react";
import type React from "react";
import { MAX_PX_PER_SEC, MIN_PX_PER_SEC } from "./constants";

const CLICK_MOVE_THRESHOLD_PX = 4;

interface PanZoomOptions {
  duration: number;
  containerWidth: () => number;
  initialPx?: number;
  onPan?: () => void;
  onZoom?: () => void;
  /** Fires on pointerup if the pointer barely moved — a click/tap, not a drag. */
  onSeek?: (timeSec: number) => void;
}

/**
 * Owns pan (drag) + zoom (wheel) interaction state as refs, so the canvas
 * renderer can read current offset/scale imperatively inside its own draw
 * call instead of re-rendering React on every pointermove. Ported near
 * verbatim from spikes/timeline-render — this piece was already validated
 * there, no reason to redesign it.
 */
export function usePanZoom({
  duration,
  containerWidth,
  initialPx = 60,
  onPan,
  onZoom,
  onSeek,
}: PanZoomOptions) {
  const offsetRef = useRef(0); // seconds, leftmost visible time
  const pxRef = useRef(initialPx);
  const draggingRef = useRef<{ startX: number; startOffset: number } | null>(null);

  const clamp = useCallback(() => {
    const maxOffset = Math.max(0, duration - containerWidth() / pxRef.current);
    offsetRef.current = Math.min(Math.max(offsetRef.current, 0), maxOffset);
  }, [duration, containerWidth]);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    draggingRef.current = { startX: e.clientX, startOffset: offsetRef.current };
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  }, []);

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!draggingRef.current) return;
      const dx = e.clientX - draggingRef.current.startX;
      offsetRef.current = draggingRef.current.startOffset - dx / pxRef.current;
      clamp();
      onPan?.();
    },
    [clamp, onPan],
  );

  const onPointerUp = useCallback(
    (e: React.PointerEvent) => {
      const drag = draggingRef.current;
      if (drag && onSeek) {
        const moved = Math.abs(e.clientX - drag.startX);
        if (moved < CLICK_MOVE_THRESHOLD_PX) {
          const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
          const localX = e.clientX - rect.left;
          onSeek(Math.max(0, offsetRef.current + localX / pxRef.current));
        }
      }
      draggingRef.current = null;
    },
    [onSeek],
  );

  const onWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault();
      const zoomFactor = Math.exp(-e.deltaY * 0.001);
      pxRef.current = Math.min(MAX_PX_PER_SEC, Math.max(MIN_PX_PER_SEC, pxRef.current * zoomFactor));
      clamp();
      onZoom?.();
    },
    [clamp, onZoom],
  );

  return { offsetRef, pxRef, onPointerDown, onPointerMove, onPointerUp, onWheel };
}
