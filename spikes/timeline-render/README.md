# Timeline render spike

Throwaway app comparing three ways to render a multi-track timeline: plain
DOM (`src/timeline/DomTimeline.tsx`), Canvas 2D (`CanvasTimeline.tsx`), and
PixiJS/WebGL (`PixiTimeline.tsx`). Same synthetic data, same pan/zoom
interaction, same FPS reporter — see the comment at the top of each renderer
for exactly how it's implemented and why.

```
npm install
npm run dev
```

Pick a renderer, pick a clip count, drag to pan, scroll to zoom, toggle
**Auto-scrub** to force a continuously moving playhead (the sustained-load
test — this is what the FPS number reflects; it's meaningless while idle).

## Findings (2026-07-21)

Measured in a headless Chromium container, so treat absolute FPS numbers as
indicative, not authoritative — but the *shape* of the result (flat vs.
degrading as clip count grows) is the thing that matters for the decision,
and that should hold on real hardware.

| Renderer | 1,000 clips, auto-scrub | 20,000 clips, auto-scrub |
|---|---|---|
| DOM (unvirtualized, one div per clip) | 60 fps | 46 fps |
| Canvas 2D (viewport-culled redraw) | 60 fps | 60 fps |
| PixiJS (persistent GPU scene graph) | 60 fps | 60 fps |

- **DOM** degrades measurably at 20k clips even though pan is a cheap
  compositor-only transform — the cost is just having 20k live elements in
  the tree. A naive React-DOM timeline is fine at MVP scale (hundreds of
  clips) but is the renderer most likely to need real work (virtualization)
  once tracks/captions/keyframes add up on a longer edit.
- **Canvas 2D** stays flat because it culls to the visible time range every
  frame — draw calls per frame are bounded by *visible* clips (~50-60 here),
  not total clips. Simple mental model, no extra dependency.
- **PixiJS** stays flat because clips are persistent GPU-resident objects;
  pan/zoom are just container transform writes, O(1) regardless of clip
  count. Also gives non-uniform x/y scaling for free (zoom stretches width,
  not clip height) — a real ergonomic win over DOM/Canvas, which would need
  to counter-scale by hand.

**Recommendation:** build the real timeline on Canvas 2D. It already scales
fine with basic viewport culling, has no extra dependency, and is a smaller
lifecycle/complexity surface than Pixi (see the bug below). Keep PixiJS in
reserve as the upgrade path if a later feature genuinely needs GPU
compositing (waveform rendering, heavier caption animation, non-uniform
zoom without hand-rolled counter-scaling).

## Bug found and fixed during testing

Switching to the Pixi renderer crashed the page (`this._cancelResize is not
a function`) under React `StrictMode`. Root cause: `Application.init()` is
async, and StrictMode's mount→cleanup→mount dev-mode double-invoke can run
the effect cleanup *before* `init()` resolves — destroying a PixiJS
`Application` mid-init throws because internal plugins (like `resizeTo`)
aren't attached yet. Fixed by gating the destroy call on an `appReady` flag
set only after `init()` resolves; the still-pending-init case is handled by
the async function's own post-init `disposed` check instead. See the
comments around `useEffect` in `PixiTimeline.tsx`.

This is exactly the kind of lifecycle subtlety a production Pixi
integration needs to get right — worth remembering as a real data point
against Pixi's complexity cost, not just a test-harness fluke.
