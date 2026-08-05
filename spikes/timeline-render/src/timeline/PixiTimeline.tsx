import { useEffect, useRef } from 'react';
import { Application, Container, Graphics, Text, TextStyle } from 'pixi.js';
import type { RendererProps } from './types';
import { BASE_PX_PER_SEC, SCRUB_SPEED, TRACK_GAP, TRACK_HEIGHT } from './constants';
import { usePanZoom } from './usePanZoom';
import { useFpsReporter } from './useFps';

// Persistent scene graph on the GPU: one Graphics object per clip, created
// once. Pan/zoom are just container.x / container.scale.x writes — O(1)
// regardless of clip count. PIXI's ticker renders continuously by default
// (idiomatic usage), so its FPS number reflects sustained per-frame
// compositing cost with N display objects already resident on the GPU,
// which is a different (and more representative-of-playback) test than the
// interaction-triggered redraws used for the DOM/Canvas renderers.
//
// Caveat: clip label Text nodes are children of the same scaled container,
// so at extreme zoom they'd visually stretch/squish unless counter-scaled —
// not solved here since it's cosmetic, not a perf question. A real
// implementation would counter-scale labels or draw them in an unscaled layer.
export function PixiTimeline({ data, autoScrub, onFps, onDrawCalls }: RendererProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const worldRef = useRef<Container | null>(null);
  const autoScrubRef = useRef(autoScrub);
  autoScrubRef.current = autoScrub;
  const reportFps = useFpsReporter(onFps);

  const { offsetRef, pxRef, onPointerDown, onPointerMove, onPointerUp, onWheel } = usePanZoom({
    duration: data.duration,
    containerWidth: () => wrapRef.current?.clientWidth ?? 800,
    initialPx: BASE_PX_PER_SEC,
    onPan: applyTransform,
    onZoom: applyTransform,
  });

  function applyTransform(offset: number, px: number) {
    const world = worldRef.current;
    if (!world) return;
    world.scale.x = px / BASE_PX_PER_SEC;
    world.x = -offset * px;
  }

  useEffect(() => {
    let disposed = false;
    let appReady = false;
    const app = new Application();
    const style = new TextStyle({ fontSize: 11, fill: 0x1a1a1a, fontFamily: 'system-ui, sans-serif' });

    (async () => {
      const host = hostRef.current;
      if (!host) return;
      // app.init() is async; React StrictMode can run this effect's cleanup
      // before it resolves. Destroying a PIXI Application mid-init throws
      // (internal plugins like resizeTo aren't attached yet), so the two
      // teardown paths below are split: this one only runs once init has
      // actually finished, when destroy() is safe to call.
      await app.init({ resizeTo: host, antialias: true, background: 0xffffff });
      if (disposed) {
        app.destroy(true, { children: true });
        return;
      }
      appReady = true;
      host.appendChild(app.canvas);

      const world = new Container();
      app.stage.addChild(world);
      worldRef.current = world;
      applyTransform(offsetRef.current, pxRef.current);

      let drawn = 0;
      const showLabels = data.clips.length <= 800;
      for (const clip of data.clips) {
        const g = new Graphics()
          .rect(0, 0, Math.max(clip.duration * BASE_PX_PER_SEC, 1), TRACK_HEIGHT)
          .fill(clip.color);
        g.x = clip.start * BASE_PX_PER_SEC;
        g.y = clip.track * (TRACK_HEIGHT + TRACK_GAP);
        world.addChild(g);
        drawn++;
        if (showLabels) {
          const label = new Text({ text: clip.label, style });
          label.x = g.x + 4;
          label.y = g.y + 4;
          world.addChild(label);
        }
      }
      onDrawCalls(drawn);

      const playhead = new Graphics()
        .rect(0, 0, 2, data.trackCount * (TRACK_HEIGHT + TRACK_GAP))
        .fill(0xff3b3b);
      playhead.visible = false;
      app.stage.addChild(playhead);

      app.ticker.add(() => {
        if (autoScrubRef.current) {
          const time = ((performance.now() / 1000) * SCRUB_SPEED) % data.duration;
          playhead.visible = true;
          playhead.x = (time - offsetRef.current) * pxRef.current;
        } else {
          playhead.visible = false;
        }
        reportFps();
      });
    })();

    return () => {
      disposed = true;
      worldRef.current = null;
      // If init hasn't resolved yet, the async branch above handles destroy
      // once it does — calling it here too would double-destroy or hit the
      // not-yet-initialized-app crash.
      if (appReady) {
        app.destroy(true, { children: true });
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

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
      <div ref={hostRef} style={{ width: '100%', height: '100%' }} />
    </div>
  );
}
