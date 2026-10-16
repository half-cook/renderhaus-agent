const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const noop = () => {};
const settled = () => new Promise((resolve) => setImmediate(resolve));
const progress = (message = 'Working') => ({ jobId: 'fresh-run', status: 'running', message,
  toolEvents: [], progressEvents: [], approvals: [], autonomous: false });
const savedRun = (status) => ({ ...progress(), jobId: 'fresh-run', projectId: 'project', conversationId: 'conversation',
  prompt: 'Inspect my scene', assets: [], status });

function harness() {
  const slots = [];
  let index = 0;
  let effects = [];
  let refreshes = 0;
  let started = 0;
  let nextTimer = 0;
  let sendProgress;
  let finish;
  const timers = new Map();
  const state = { nodes: [], selectedNodeIds: [], executions: [], conversations: [{ id: 'conversation', title: 'Task' }],
    projectId: 'project', projectName: 'Project', conversationId: 'conversation', agentOpen: true, status: { agent: true },
    setAgentMessage: noop, refreshConversations: async () => { state.executions = [savedRun('completed')]; },
    refreshExecutions: async () => { refreshes++; state.executions = [savedRun('running')]; } };
  const react = {
    useState(initial) {
      const at = index++;
      if (!(at in slots)) slots[at] = typeof initial === 'function' ? initial() : initial;
      return [slots[at], (value) => { slots[at] = typeof value === 'function' ? value(slots[at]) : value; }];
    },
    useRef(initial) { const at = index++; return slots[at] ??= { current: initial }; },
    useMemo(factory) { index++; return factory(); },
    useEffect(effect, dependencies) {
      const at = index++;
      const previous = slots[at];
      if (!previous || dependencies.some((value, n) => value !== previous.dependencies[n])) {
        previous?.cleanup?.();
        effects.push(() => { slots[at] = { dependencies, cleanup: effect() }; });
      }
    },
  };
  const api = { AGENT_PROMPT_MAX_CHARS: 64000,
    submitAgentPrompt: (...args) => { sendProgress = args[6]; return new Promise((resolve) => { finish = resolve; }); } };
  const source = fs.readFileSync(path.join(__dirname, '../components/canvas/AgentDock.tsx'), 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const exported = {};
  new Function('require', 'exports', js)((name) => {
    if (name === 'react') return react;
    if (name === '@/lib/api') return api;
    if (name === '@/lib/canvas/store') return { useCanvasStore: (select) => select(state) };
    if (name === '@/lib/rh/changes-store') return { useChangesStore: (select) => select({}) };
    if (name === '@/lib/rh/credit-store') return { useCreditContext: (select) => select({ setPendingCap: noop, setHeld: noop }) };
    if (name === '@xyflow/react') return { useReactFlow: () => ({ screenToFlowPosition: (point) => point }) };
    if (name === 'react/jsx-runtime') return require(name);
    return new Proxy({}, { get: () => noop });
  }, exported);
  const find = (element, predicate) => {
    if (!element || typeof element !== 'object') return;
    if (predicate(element)) return element;
    for (const child of [element.props?.children].flat(Infinity)) {
      const result = find(child, predicate);
      if (result) return result;
    }
  };
  const props = { navigationBusy: false, onBusyChange: noop, suggestion: null, onSuggestionUsed: noop, onAttach: noop };
  return { state, timers, find,
    window: { localStorage: { getItem: () => null }, setInterval(callback, delay) {
      assert.equal(delay, 1000); started++; timers.set(++nextTimer, callback); return nextTimer;
    }, clearInterval(timer) { timers.delete(timer); } },
    render() { index = 0; effects = []; const element = exported.AgentDock(props); while (effects.length) effects.shift()(); return element; },
    progress: (next) => sendProgress(next), finish: (result) => finish(result),
    counts: () => ({ refreshes, started }),
    unmount() { for (const slot of slots) slot?.cleanup?.(); },
  };
}

test('fresh SSE jobs refresh shared executions immediately and keep one stable polling interval', async () => {
  const previousWindow = global.window;
  const ui = harness();
  global.window = ui.window;
  try {
    let tree = ui.render();
    assert.equal(ui.timers.size, 0);
    ui.find(tree, (element) => element.type === 'textarea').props.onChange({ target: { value: 'Inspect my scene' } });
    tree = ui.render();
    ui.find(tree, (element) => element.props?.['aria-label'] === 'Send to agent').props.onClick();
    ui.render();
    assert.equal(ui.timers.size, 0, 'no polling before the server accepts a job');
    ui.progress(progress());
    ui.render();
    assert.deepEqual(ui.counts(), { refreshes: 1, started: 1 }, 'known streamed job refreshes saved executions before terminal state');
    assert.equal(ui.state.executions[0].jobId, 'fresh-run', 'the header now receives the live job through its existing store');
    ui.progress(progress('A later streamed event'));
    ui.render();
    assert.deepEqual(ui.counts(), { refreshes: 1, started: 1 }, 'SSE events and persisted handoff do not restart the interval');
    [...ui.timers.values()][0]();
    assert.equal(ui.counts().refreshes, 2);
    ui.finish({ status: 'completed', message: 'Done', result: { executionId: 'fresh-run', toolEvents: [], assets: [] } });
    await settled();
    ui.render();
    assert.equal(ui.timers.size, 0, 'terminal cleanup stops the same existing interval');
  } finally { ui.unmount(); global.window = previousWindow; }
});

test('a restored active job uses the same refresh path and unmount clears it', () => {
  const previousWindow = global.window;
  const ui = harness();
  global.window = ui.window;
  try {
    ui.state.executions = [savedRun('running')];
    ui.render();
    assert.deepEqual(ui.counts(), { refreshes: 1, started: 1 });
    ui.render();
    assert.deepEqual(ui.counts(), { refreshes: 1, started: 1 });
    ui.unmount();
    assert.equal(ui.timers.size, 0);
  } finally { global.window = previousWindow; }
});
