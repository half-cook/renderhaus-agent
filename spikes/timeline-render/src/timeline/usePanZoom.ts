import { useCallback, useRef } from 'react';
import type React from 'react';
import { MAX_PX_PER_SEC, MIN_PX_PER_SEC } from './constants';

interface PanZoomOptions {
  duration: number;
  containerWidth: () => number;
  initialPx?: number;
  onPan?: (offsetSeconds: number, pxPerSecond: number) => void;
  onZoom?: (offsetSeconds: number, pxPerSecond: number) => void;
}

/**
 * Owns pan (drag) + zoom (wheel) interaction state as refs, so consumers can
 * read current offset/scale imperatively inside their own render loop instead
 * of re-rendering on every pointermove.
 */
export function usePanZoom({ duration, containerWidth, initialPx = 60, onPan, onZoom }: PanZoomOptions) {
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

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!draggingRef.current) return;
    const dx = e.clientX - draggingRef.current.startX;
    offsetRef.current = draggingRef.current.startOffset - dx / pxRef.current;
    clamp();
    onPan?.(offsetRef.current, pxRef.current);
  }, [clamp, onPan]);

  const onPointerUp = useCallback(() => {
    draggingRef.current = null;
  }, []);

  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const zoomFactor = Math.exp(-e.deltaY * 0.001);
    pxRef.current = Math.min(MAX_PX_PER_SEC, Math.max(MIN_PX_PER_SEC, pxRef.current * zoomFactor));
    clamp();
    onZoom?.(offsetRef.current, pxRef.current);
  }, [clamp, onZoom]);

  return { offsetRef, pxRef, onPointerDown, onPointerMove, onPointerUp, onWheel };
}
