const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const load = require('./load-ts.cjs');
const timeline = load('lib/rh/timeline.ts');
const story = load('lib/canvas/story.ts');

const clip = (id, trimIn, trimOut) => ({ id, order: 1, title: id, sourceSeconds: 10, trimIn, trimOut });
const clips = [clip('a', 2, 5), clip('b', 1, 3)];
const asset = { assetId: 'a', versionId: 'a', kind: 'video', filename: 'a.mp4', mimeType: 'video/mp4' };
const settled = () => new Promise((resolve) => setImmediate(resolve));

function video() {
  return { readyState: 1, duration: 10, currentTime: 0, paused: true, seeking: false, ended: false, plays: 0, pauses: 0,
    play() { this.plays++; this.paused = false; return Promise.resolve(); },
    pause() { this.pauses++; this.paused = true; },
  };
}

test('global timeline positions map to trimmed sources and cross cut boundaries', () => {
  assert.equal(timeline.timelinePosition([], 0), undefined);
  assert.equal(timeline.timelinePosition(clips, -1).sourceTime, 2);
  assert.equal(timeline.timelinePosition(clips, 2).sourceTime, 4);
  assert.deepEqual(timeline.timelinePosition(clips, 3), { clip: clips[1], timelineStart: 3, sourceTime: 1 });
  assert.equal(timeline.timelinePosition(clips, 100).sourceTime, 3);
});

test('native playback waits for metadata, seeks, plays, pauses, and never rewinds media-clock updates', async () => {
  const media = video();
  media.readyState = 0;
  assert.equal(timeline.syncTimelineVideo(media, 2, true), undefined);
  assert.equal(media.plays, 0);
  media.readyState = 1;
  await timeline.syncTimelineVideo(media, 2, true);
  assert.equal(media.currentTime, 2);
  assert.equal(media.plays, 1);
  media.currentTime = 2.13;
  timeline.syncTimelineVideo(media, 2.1, true, false);
  assert.equal(media.currentTime, 2.13, 'reported clock does not seek backward after rendering');
  timeline.syncTimelineVideo(media, 4, false);
  assert.equal(media.paused, true);
  assert.equal(media.currentTime, 4);
});

function harness(file, mocks) {
  const slots = [];
  const setters = [];
  let index = 0;
  let effects = [];
  const react = {
    useState(initial) {
      const slot = index++;
      if (!(slot in slots)) slots[slot] = typeof initial === 'function' ? initial() : initial;
      setters[slot] ??= (value) => { slots[slot] = typeof value === 'function' ? value(slots[slot]) : value; };
      return [slots[slot], setters[slot]];
    },
    useRef(initial) { const slot = index++; return slots[slot] ??= { current: initial }; },
    useMemo(factory) { index++; return factory(); },
    useCallback(callback, dependencies) {
      const slot = index++;
      if (!slots[slot] || dependencies.some((value, n) => value !== slots[slot].dependencies[n])) {
        slots[slot] = { callback, dependencies };
      }
      return slots[slot].callback;
    },
    useEffect(effect, dependencies) {
      const slot = index++;
      const previous = slots[slot];
      if (!previous || dependencies.some((value, n) => value !== previous.dependencies[n])) {
        previous?.cleanup?.();
        effects.push(() => { slots[slot] = { dependencies, cleanup: effect() }; });
      }
    },
  };
  const modules = new Map();
  const compile = (file) => {
    if (modules.has(file)) return modules.get(file);
    const source = fs.readFileSync(file, 'utf8');
    const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    const exported = {};
    modules.set(file, exported);
    new Function('require', 'exports', js)((name) => {
      if (name === 'react') return react;
      if (mocks[name]) return mocks[name];
      if (name.startsWith('.') || name.startsWith('@/')) {
        const local = name.startsWith('@/') ? path.join(__dirname, '..', name.slice(2)) : path.resolve(path.dirname(file), name);
        return compile(fs.existsSync(`${local}.ts`) ? `${local}.ts` : `${local}.tsx`);
      }
      return require(name);
    }, exported);
    return exported;
  };
  const exported = compile(path.join(__dirname, '..', file));
  return (name, ...args) => {
    index = 0; effects = [];
    const element = exported[name](...args);
    return { element, effects: () => { while (effects.length) effects.shift()(); } };
  };
}

function find(element, predicate) {
  if (!element || typeof element !== 'object') return;
  if (predicate(element)) return element;
  for (const child of [element.props?.children].flat(Infinity)) {
    const result = find(child, predicate);
    if (result) return result;
  }
}

test('selecting a shot uses the same rounded cut boundary as the media clock', () => {
  const sourceClips = [clip('one', 0, 0.1), clip('two', 0, 0.7), clip('three', 0, 1)];
  const render = harness('components/timeline/Timeline.tsx', {
    'lucide-react': {}, '@/lib/rh/timeline': timeline,
    '@/components/canvas/AssetMedia': {}, '@/lib/canvas/store': {},
  });
  render('useTransport', sourceClips).element.select('three');
  const transport = render('useTransport', sourceClips).element;
  assert.equal(transport.playhead, 0.8);
  assert.equal(transport.selected.id, 'three');
});

test('AssetMedia exposes loading, fetch/native errors and an explicit retry that restores video callbacks', () => {
  let status = 'loading';
  let attempt;
  let failures = 0;
  const render = harness('components/canvas/AssetMedia.tsx', { '@/lib/assets': {
    useStudioAssetPlayback: (_, nextAttempt) => { attempt = nextAttempt; return status === 'ready' ? { status, url: '/clip.mp4' } : { status, message: 'Saved preview unavailable' }; },
  } });
  const props = { asset, alt: 'Shot', videoRef: { current: null }, onTimeUpdate: () => {}, onEnded: () => {}, onPlaybackError: () => { failures++; } };
  let view = render('AssetMedia', props); view.effects();
  assert.equal(view.element.props['aria-label'], 'Loading Shot');
  status = 'error';
  view = render('AssetMedia', props); view.effects();
  assert.equal(view.element.props.role, 'alert');
  assert.equal(failures, 1);
  find(view.element, (element) => element.type === 'button').props.onClick();
  status = 'ready';
  view = render('AssetMedia', props); view.effects();
  assert.equal(attempt, 1);
  assert.equal(view.element.type, 'video');
  assert.equal(view.element.props.ref, props.videoRef);
  assert.equal(view.element.props.onTimeUpdate, props.onTimeUpdate);
  view.element.props.onError({ currentTarget: video() });
  view = render('AssetMedia', props); view.effects();
  assert.equal(view.element.props.role, 'alert');
  find(view.element, (element) => element.type === 'button').props.onClick();
  view = render('AssetMedia', props); view.effects();
  assert.equal(view.element.type, 'video');
  assert.equal(attempt, 2);
});

test('full Timeline binds Play, seek, trim end and rejected playback to actual media', async () => {
  const realWindow = global.window;
  const realFrame = global.requestAnimationFrame;
  const realCancel = global.cancelAnimationFrame;
  global.window = { addEventListener() {}, removeEventListener() {} };
  global.requestAnimationFrame = () => 1;
  global.cancelAnimationFrame = () => {};
  try {
    let playhead = 0;
    let playing = false;
    const AssetMedia = () => null;
    const model = { clips, mediaFor: () => asset };
    const nodes = clips.map((item) => ({ id: item.id, data: { kind: 'video', title: item.id, output: asset, config: { aspect_ratio: '16:9' } } }));
    const transport = {
      setPlaying: (value) => { playing = value; },
      setPlayhead: (value) => { playhead = typeof value === 'function' ? value(playhead) : value; },
    };
    const render = harness('components/timeline/TimelineView.tsx', {
      'lucide-react': {}, '@/components/canvas/AssetMedia': { AssetMedia },
      '@/lib/canvas/store': { useCanvasStore: (selector) => selector({ nodes }) },
      '@/lib/canvas/story': story, '@/lib/rh/timeline': timeline,
      './Timeline': { useTimelineModel: () => model, useTransport: () => {
        return { ...transport, playhead, playing, total: 5, selected: timeline.timelinePosition(clips, playhead)?.clip };
      } },
    });
    const media = video();
    const draw = () => {
      const view = render('TimelineView');
      const element = find(view.element, (candidate) => candidate.type === AssetMedia);
      element.props.videoRef(media);
      view.effects();
      return { view, element };
    };
    draw();
    assert.equal(media.currentTime, 2, 'preview starts at trim in');
    playing = true;
    let { element } = draw();
    await settled();
    assert.equal(media.paused, false);
    media.currentTime = 3;
    element.props.onTimeUpdate();
    assert.equal(playhead, 1, 'source time maps back to edit clock');
    playhead = 2;
    ({ element } = draw());
    assert.equal(media.currentTime, 4, 'ruler seek changes actual video');
    media.currentTime = 5;
    element.props.onTimeUpdate();
    assert.equal(playhead, 3, 'trim out advances to the next clip');
    assert.equal(media.paused, true);
    assert.equal(playing, true, 'sequence continues on the next source');
    ({ element } = draw());
    assert.equal(media.currentTime, 1, 'next source begins at its own trim in');
    media.currentTime = 3;
    element.props.onEnded();
    assert.equal(playhead, 5);
    assert.equal(playing, false, 'last source finishes the transport');
    playhead = 0;
    media.paused = true;
    media.play = () => Promise.reject(new Error('Playback not allowed'));
    playing = true;
    draw();
    await settled();
    assert.equal(playing, false);
    const { view } = draw();
    assert.ok(find(view.element, (candidate) => candidate.props?.role === 'alert'), 'rejected play becomes visible');
  } finally {
    global.window = realWindow;
    global.requestAnimationFrame = realFrame;
    global.cancelAnimationFrame = realCancel;
  }
});

test('canvas dock plays a visible source and pauses when its containing canvas hides', async () => {
  const realWindow = global.window;
  const realFrame = global.requestAnimationFrame;
  const realCancel = global.cancelAnimationFrame;
  global.window = { addEventListener() {}, removeEventListener() {} };
  global.requestAnimationFrame = () => 1;
  global.cancelAnimationFrame = () => {};
  try {
    const AssetMedia = () => null;
    const state = { timelineDockOpen: true, nodes: [{ id: 'a', position: { x: 0, y: 0 }, data: {
      kind: 'video', title: 'Dock shot', output: asset, config: { duration_seconds: 5, trim_in_seconds: 2 },
    } }] };
    const render = harness('components/timeline/Timeline.tsx', {
      'lucide-react': {}, '@/lib/rh/timeline': timeline,
      '@/components/canvas/AssetMedia': { AssetMedia },
      '@/lib/canvas/store': { useCanvasStore: (selector) => selector(state) },
    });
    const media = video();
    const draw = (active = true) => {
      const view = render('TimelineDock', { active });
      const source = find(view.element, (element) => element.type === AssetMedia);
      source.props.videoRef(media);
      view.effects();
      return { view, source, bar: find(view.element, (element) => element.type?.name === 'TransportBar') };
    };
    let current = draw();
    assert.equal(media.currentTime, 2);
    current.bar.props.transport.setPlaying(true);
    current = draw();
    await settled();
    assert.equal(media.paused, false);
    media.currentTime = 3;
    current.source.props.onTimeUpdate();
    current = draw();
    assert.equal(current.bar.props.transport.playhead, 1);
    current = draw(false);
    assert.equal(media.paused, true, 'navigation away from the canvas pauses its source');
    current = draw(false);
    assert.equal(current.bar.props.transport.playing, false);
    const pauses = media.pauses;
    current.source.props.videoRef(null);
    assert.equal(media.pauses, pauses + 1, 'detaching or unmounting explicitly pauses media');
  } finally {
    global.window = realWindow;
    global.requestAnimationFrame = realFrame;
    global.cancelAnimationFrame = realCancel;
  }
});

test('Changes timeline uses actual playback and a paused ruler seek selects the matching source', async () => {
  const realWindow = global.window;
  const realFrame = global.requestAnimationFrame;
  const realCancel = global.cancelAnimationFrame;
  global.window = { addEventListener() {}, removeEventListener() {} };
  global.requestAnimationFrame = () => 1;
  global.cancelAnimationFrame = () => {};
  try {
    let playhead = 0;
    let playing = false;
    const changes = load('lib/rh/changes.ts');
    const cut = { id: 'cut', order: ['a', 'b'], slots: [{ slotId: 'a', takeId: 'take-a', inMs: 2000, outMs: 5000 },
      { slotId: 'b', takeId: 'take-b', inMs: 1000, outMs: 3000 }] };
    const document = { currentCut: cut, changes: [], takes: clips.map((item, index) => ({
      id: `take-${item.id}`, slotId: item.id, mediaKind: 'video', mediaRef: `/${item.id}.mp4`, durationMs: 10000, costCents: 0, n: index + 1,
    })) };
    const transport = {
      setPlaying: (value) => { playing = value; },
      setPlayhead: (value) => { playhead = typeof value === 'function' ? value(playhead) : value; },
      select() {},
    };
    const render = harness('components/changes/ChangesTimeline.tsx', {
      'lucide-react': {}, '@/lib/rh/timeline': timeline, '@/lib/rh/money': { formatCents: () => '' },
      '@/lib/rh/changes': { ...changes, withChangesCut: () => cut },
      '@/components/timeline/Timeline': { useTransport: () => ({ ...transport, playhead, playing, total: 5,
        selectedId: timeline.timelinePosition(clips, playhead).clip.id, selected: timeline.timelinePosition(clips, playhead).clip }) },
    });
    const props = { document, selectedN: 0, actions: { trim() {}, reorder() {}, remove() {} } };
    const media = video();
    const draw = () => {
      const view = render('ChangesTimeline', props);
      const source = find(view.element, (element) => element.type === 'video');
      source.props.ref(media);
      view.effects();
      return { view, source };
    };
    let current = draw();
    assert.equal(media.currentTime, 2);
    playing = true;
    current = draw();
    await settled();
    assert.equal(media.paused, false);
    playing = false;
    playhead = 3.5;
    current = draw();
    assert.equal(current.source.props.src, '/b.mp4');
    assert.equal(media.currentTime, 1.5);
    current.source.props.onError();
    current = draw();
    const alert = find(current.view.element, (element) => element.props?.role === 'alert');
    assert.ok(alert, 'media failure is visible');
    const before = current.source.key;
    find(alert, (element) => element.type === 'button').props.onClick();
    current = draw();
    assert.notEqual(current.source.key, before, 'explicit retry remounts and reloads the selected source');
    const previousSource = current.source.key;
    document.takes[1].mediaRef = '/b-refreshed.mp4';
    current = draw();
    assert.notEqual(current.source.key, previousSource, 'a refreshed URL cannot retain the old source element');
  } finally {
    global.window = realWindow;
    global.requestAnimationFrame = realFrame;
    global.cancelAnimationFrame = realCancel;
  }
});

test('an alternative take stops at its real end instead of inventing time or mutating the cut', () => {
  const realFrame = global.requestAnimationFrame;
  const realCancel = global.cancelAnimationFrame;
  global.requestAnimationFrame = () => 1;
  global.cancelAnimationFrame = () => {};
  try {
    const sourceClips = [clip('alternative', 0, 5)];
    const before = structuredClone(sourceClips);
    let playhead = 0;
    let playing = true;
    const transport = {
      setPlaying: (value) => { playing = value; },
      setPlayhead: (value) => { playhead = typeof value === 'function' ? value(playhead) : value; },
    };
    const render = harness('components/timeline/useTimelinePlayback.ts', { '@/lib/rh/timeline': timeline });
    const media = video();
    media.duration = 2;
    const draw = () => {
      const view = render('useTimelinePlayback', sourceClips, { ...transport, playhead, playing, total: 5 },
        { sourceKey: 'alternative', active: true, stopAtSourceEnd: true });
      view.element.mediaProps.videoRef(media);
      view.effects();
      return view.element;
    };
    let playback = draw();
    media.currentTime = 2;
    media.ended = true;
    playback.mediaProps.onEnded();
    assert.equal(playhead, 2);
    assert.equal(playing, false);
    playback = draw();
    assert.equal(playback.endedEarly, true);
    assert.deepEqual(sourceClips, before);
    playing = true;
    draw();
    assert.equal(playhead, 0, 'replay returns to this take start');
    playback = draw();
    assert.equal(media.currentTime, 0, 'the next render seeks instead of repeatedly rewinding the clock');
    assert.equal(media.paused, false);
    media.ended = false;
    sourceClips[0].trimIn = 3;
    playback = draw();
    playback = draw();
    assert.match(playback.error, /too short/);
    assert.equal(playing, false);
  } finally {
    global.requestAnimationFrame = realFrame;
    global.cancelAnimationFrame = realCancel;
  }
});
