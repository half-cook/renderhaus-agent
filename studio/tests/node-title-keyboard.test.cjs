const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function harness() {
  const values = [];
  let cursor = 0;
  const renamed = [];
  const exported = {};
  const source = fs.readFileSync(path.join(__dirname, '../components/canvas/nodes/NodeTag.tsx'), 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  new Function('require', 'exports', js)((name) => {
    if (name === 'react') return {
      useState(initial) {
        const index = cursor++;
        if (!(index in values)) values[index] = initial;
        return [values[index], (value) => { values[index] = value; }];
      },
      useEffect() {}, useRef: () => ({ current: null }),
    };
    if (name === '@xyflow/react') return { useStore: () => 1 };
    if (name === '@/lib/canvas/store') return { statusLabel: (status) => status };
    return require(name);
  }, exported);
  return {
    renamed,
    render() {
      cursor = 0;
      const element = exported.NodeTag({ title: 'Scene one', status: 'idle', onRename: (title) => renamed.push(title) });
      return element.props.children.find((child) => child?.type === 'button' || child?.type === 'input');
    },
  };
}

for (const key of ['Enter', ' ']) test(`${JSON.stringify(key)} opens the title editor without bubbling a canvas shortcut`, () => {
  const ui = harness();
  let prevented = 0, stopped = 0;
  ui.render().props.onKeyDown({ key, preventDefault: () => prevented++, stopPropagation: () => stopped++ });
  assert.equal(ui.render().type, 'input');
  assert.equal(prevented, 1);
  assert.equal(stopped, 1);
});

test('unrelated keys leave the title as a button', () => {
  const ui = harness();
  ui.render().props.onKeyDown({ key: 'ArrowRight', preventDefault: assert.fail, stopPropagation: assert.fail });
  assert.equal(ui.render().type, 'button');
});

test('keyboard rename commits with Enter and discards a later draft with Escape', () => {
  const ui = harness();
  const key = (value) => ({ key: value, preventDefault() {}, stopPropagation() {} });
  ui.render().props.onKeyDown(key('Enter'));
  ui.render().props.onChange({ target: { value: '  Updated scene  ' } });
  ui.render().props.onKeyDown(key('Enter'));
  assert.deepEqual(ui.renamed, ['Updated scene']);
  ui.render().props.onKeyDown(key(' '));
  ui.render().props.onChange({ target: { value: 'Discard me' } });
  ui.render().props.onKeyDown(key('Escape'));
  assert.equal(ui.render().type, 'button');
  assert.deepEqual(ui.renamed, ['Updated scene']);
});
