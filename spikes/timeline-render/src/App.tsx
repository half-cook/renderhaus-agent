import { useMemo, useState } from 'react';
import { generateTimeline } from './timeline/data';
import { DomTimeline } from './timeline/DomTimeline';
import { CanvasTimeline } from './timeline/CanvasTimeline';
import { PixiTimeline } from './timeline/PixiTimeline';
import type { RendererProps } from './timeline/types';
import './App.css';

const TRACK_COUNT = 8;
const CLIP_COUNTS = [100, 500, 1000, 5000, 20000];
type Renderer = 'dom' | 'canvas' | 'pixi';

const RENDERERS: Record<Renderer, (props: RendererProps) => React.ReactElement> = {
  dom: DomTimeline,
  canvas: CanvasTimeline,
  pixi: PixiTimeline,
};

function App() {
  const [renderer, setRenderer] = useState<Renderer>('dom');
  const [clipCount, setClipCount] = useState(1000);
  const [autoScrub, setAutoScrub] = useState(false);
  const [fps, setFps] = useState<number | null>(null);
  const [drawCalls, setDrawCalls] = useState(0);

  const data = useMemo(() => generateTimeline(clipCount, TRACK_COUNT), [clipCount]);

  const handleSwitchRenderer = (r: Renderer) => {
    setRenderer(r);
    setFps(null);
  };

  const handleSwitchClipCount = (c: number) => {
    setClipCount(c);
    setFps(null);
  };

  const ActiveRenderer = RENDERERS[renderer];

  return (
    <div className="app">
      <header>
        <h1>warm-light — timeline render spike</h1>
        <p>
          Same synthetic timeline, three renderers: plain DOM, Canvas 2D, PixiJS/WebGL.
          Drag to pan, scroll to zoom, toggle auto-scrub to stress-test sustained frame rate.
        </p>
      </header>

      <div className="controls">
        <div className="control-group">
          <span className="control-label">Renderer</span>
          {(Object.keys(RENDERERS) as Renderer[]).map((r) => (
            <button
              key={r}
              className={renderer === r ? 'active' : ''}
              onClick={() => handleSwitchRenderer(r)}
            >
              {r.toUpperCase()}
            </button>
          ))}
        </div>

        <div className="control-group">
          <span className="control-label">Clip count</span>
          {CLIP_COUNTS.map((c) => (
            <button
              key={c}
              className={clipCount === c ? 'active' : ''}
              onClick={() => handleSwitchClipCount(c)}
            >
              {c.toLocaleString()}
            </button>
          ))}
        </div>

        <div className="control-group">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={autoScrub}
              onChange={(e) => setAutoScrub(e.target.checked)}
            />
            Auto-scrub (moving playhead)
          </label>
        </div>

        <div className="stats">
          <div>
            <strong>{fps ?? '—'}</strong>
            <span>FPS</span>
          </div>
          <div>
            <strong>{drawCalls.toLocaleString()}</strong>
            <span>clips drawn</span>
          </div>
          <div>
            <strong>{data.clips.length.toLocaleString()}</strong>
            <span>total clips</span>
          </div>
        </div>
      </div>

      <div className="stage">
        <ActiveRenderer
          key={renderer}
          data={data}
          autoScrub={autoScrub}
          onFps={setFps}
          onDrawCalls={setDrawCalls}
        />
      </div>

      <footer>
        <p>
          FPS is measured differently per renderer by design — see comments in each
          component under <code>src/timeline/</code>. This is a throwaway perf spike,
          not production code.
        </p>
      </footer>
    </div>
  );
}

export default App;
