import { useEffect, useRef } from 'react';
import type { RendererProps } from './types';
import { SCRUB_SPEED, TRACK_GAP, TRACK_HEIGHT } from './constants';
import { usePanZoom } from './usePanZoom';
import { useFpsReporter } from './useFps';

// Single <canvas>, imperative draw. Redraws only on interaction/auto-scrub
// (not every idle frame), and culls clips outside the visible time range.
export function CanvasTimeline({ data, autoScrub, onFps, onDrawCalls }: RendererProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const playheadTimeRef = useRef<number | null>(null);
  const reportFps = useFpsReporter(onFps);

  const { offsetRef, pxRef, onPointerDown, onPointerMove, onPointerUp, onWheel } = usePanZoom({
    duration: data.duration,
    containerWidth: () => wrapRef.current?.clientWidth ?? 800,
    onPan: () => { draw(); reportFps(); },
    onZoom: () => { draw(); reportFps(); },
  });

  function draw() {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
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

    let drawn = 0;
    for (const clip of data.clips) {
      if (clip.start + clip.duration < visStart || clip.start > visEnd) continue;
      const x = (clip.start - offset) * px;
      const width = clip.duration * px;
      const y = clip.track * (TRACK_HEIGHT + TRACK_GAP);
      ctx.fillStyle = clip.color;
      ctx.fillRect(x, y, Math.max(width, 1), TRACK_HEIGHT);
      if (width > 40) {
        ctx.fillStyle = 'rgba(0,0,0,0.65)';
        ctx.font = '11px system-ui, sans-serif';
        ctx.fillText(clip.label, x + 4, y + 16, Math.max(width - 8, 0));
      }
      drawn++;
    }
    onDrawCalls(drawn);

    if (playheadTimeRef.current != null) {
      ctx.fillStyle = '#ff3b3b';
      ctx.fillRect((playheadTimeRef.current - offset) * px, 0, 2, h);
    }
  }

  useEffect(() => {
    draw();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  useEffect(() => {
    if (!autoScrub) {
      playheadTimeRef.current = null;
      draw();
      return;
    }
    let raf: number;
    const loop = (t: number) => {
      playheadTimeRef.current = ((t / 1000) * SCRUB_SPEED) % data.duration;
      draw();
      reportFps();
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoScrub, data]);

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
      <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block' }} />
    </div>
  );
}
