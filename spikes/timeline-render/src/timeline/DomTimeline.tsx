import { useEffect, useMemo, useRef, useState } from 'react';
import type { RendererProps } from './types';
import { SCRUB_SPEED, TRACK_GAP, TRACK_HEIGHT } from './constants';
import { usePanZoom } from './usePanZoom';
import { useFpsReporter } from './useFps';

// Naive-but-realistic React DOM approach: one absolutely-positioned <div> per
// clip. Pan is a transform on a single wrapper (cheap, compositor-only).
// Zoom recomputes every clip's left/width and re-renders the full list —
// this is the expensive path we're deliberately testing.
export function DomTimeline({ data, autoScrub, onFps, onDrawCalls }: RendererProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const worldRef = useRef<HTMLDivElement>(null);
  const playheadRef = useRef<HTMLDivElement>(null);
  const [zoomTick, setZoomTick] = useState(0);
  const reportFps = useFpsReporter(onFps);

  const applyPanTransform = (offset: number, px: number) => {
    if (worldRef.current) {
      worldRef.current.style.transform = `translateX(${-offset * px}px)`;
    }
  };

  const { offsetRef, pxRef, onPointerDown, onPointerMove, onPointerUp, onWheel } = usePanZoom({
    duration: data.duration,
    containerWidth: () => wrapRef.current?.clientWidth ?? 800,
    onPan: (offset, px) => {
      applyPanTransform(offset, px);
      reportFps();
    },
    onZoom: (offset, px) => {
      applyPanTransform(offset, px);
      setZoomTick((t) => t + 1);
      reportFps();
    },
  });

  const layout = useMemo(() => {
    const px = pxRef.current;
    return data.clips.map((c) => ({
      ...c,
      left: c.start * px,
      width: Math.max(c.duration * px, 1),
      top: c.track * (TRACK_HEIGHT + TRACK_GAP),
    }));
    // pxRef.current is read intentionally on zoomTick change, not tracked as a dep
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.clips, zoomTick]);

  useEffect(() => {
    onDrawCalls(layout.length);
  }, [layout, onDrawCalls]);

  useEffect(() => {
    if (!autoScrub) return;
    let raf: number;
    const loop = (t: number) => {
      const time = ((t / 1000) * SCRUB_SPEED) % data.duration;
      if (playheadRef.current) {
        playheadRef.current.style.transform = `translateX(${(time - offsetRef.current) * pxRef.current}px)`;
      }
      reportFps();
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoScrub, data.duration]);

  return (
    <div
      ref={wrapRef}
      className="timeline-surface"
      style={{ height: data.trackCount * (TRACK_HEIGHT + TRACK_GAP) }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onWheel={onWheel}
    >
      <div ref={worldRef} className="dom-world">
        {layout.map((c) => (
          <div
            key={c.id}
            className="dom-clip"
            style={{ left: c.left, top: c.top, width: c.width, height: TRACK_HEIGHT, background: c.color }}
          >
            {c.width > 40 && <span className="dom-clip-label">{c.label}</span>}
          </div>
        ))}
      </div>
      {autoScrub && <div ref={playheadRef} className="playhead" />}
    </div>
  );
}
