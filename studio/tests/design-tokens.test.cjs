const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const postcss = require('postcss');

const studio = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(studio, 'app/globals.css'), 'utf8');
const css = postcss.parse(source);
const tokenRule = (selector) => css.nodes.find((node) => node.type === 'rule' && node.selector === selector);
const tokens = (rule) => rule.nodes.filter((node) => node.type === 'decl' && node.prop.startsWith('--')).map((node) => node.prop).sort();

test('the declared cascade puts xyflow below legacy and utilities above legacy', () => {
  const order = css.nodes.find((node) => node.type === 'atrule' && node.name === 'layer' && !node.nodes);
  assert.ok(order, 'explicit layer order is required');
  assert.equal(order.params, 'theme, base, xyflow, legacy, components, utilities');
  const tailwind = css.nodes.find((node) => node.type === 'atrule' && node.name === 'import' && node.params.includes('tailwindcss'));
  assert.ok(css.nodes.indexOf(order) < css.nodes.indexOf(tailwind));
  assert.ok(css.nodes.some((node) => node.name === 'import' && /@xyflow\/react\/dist\/style\.css.*layer\(xyflow\)/.test(node.params)));
  assert.ok(!fs.readFileSync(path.join(studio, 'components/canvas/CanvasShell.tsx'), 'utf8').includes('import "@xyflow/react/dist/style.css"'));
});

test('global style rules stay inside legacy except theme tokens and utility definitions', () => {
  for (const node of css.nodes) {
    if (node.type === 'comment') continue;
    if (node.type === 'rule') {
      assert.ok([':root', ':root[data-theme="light"]', '[data-surface="beta"]'].includes(node.selector), `unlayered rule: ${node.selector}`);
      assert.ok(node.nodes.every((child) => child.type === 'comment' || (child.type === 'decl' && (child.prop.startsWith('--') || child.prop === 'color-scheme'))));
      continue;
    }
    assert.equal(node.type, 'atrule');
    assert.ok(['import', 'theme', 'layer', 'utility'].includes(node.name), `unexpected top-level @${node.name}`);
    if (node.name === 'layer' && node.nodes) assert.equal(node.params, 'legacy');
  }
  const legacy = css.nodes.find((node) => node.name === 'layer' && node.params === 'legacy' && node.nodes);
  assert.ok(legacy?.nodes.some((node) => node.type === 'rule' && node.selector.includes('body')));
  legacy.walkAtRules('import', () => assert.fail('imports must remain at top level'));
});

test('the Tailwind radius and shadow scales are removed with only a named pill exception', () => {
  const theme = css.nodes.filter((node) => node.name === 'theme').flatMap((node) => node.nodes).filter((node) => node.type === 'decl');
  assert.ok(theme.some((node) => node.prop === '--radius-*' && node.value === 'initial'));
  assert.ok(theme.some((node) => node.prop === '--shadow-*' && node.value === 'initial'));
  assert.deepEqual(theme.filter((node) => node.prop.startsWith('--radius-') && node.prop !== '--radius-*').map((node) => [node.prop, node.value]), [['--radius-pill', '9999px']]);
});

test('the opt-in dark beta surface defines every root token without changing the root palette', () => {
  const root = tokenRule(':root');
  const beta = tokenRule('[data-surface="beta"]');
  assert.ok(beta, 'beta surface must be opt-in');
  assert.deepEqual(tokens(beta), tokens(root));
  assert.ok(beta.nodes.some((node) => node.prop === 'color-scheme' && node.value === 'dark'));
  assert.equal(root.nodes.find((node) => node.prop === '--bg').value, 'var(--color-neutral-950)');
  assert.equal(root.nodes.find((node) => node.prop === '--ease').value, 'cubic-bezier(0.32, 0.72, 0, 1)');
});

test('compiled Tailwind removes rounded-lg and shadow-md, emits pill and semantic utilities in the winning layer', async () => {
  const tailwind = require('@tailwindcss/postcss');
  const fixture = source.replace('@import "tailwindcss";', '@import "tailwindcss" source(none);') + '\n@source inline("rounded-lg rounded-pill shadow-md bg-background duration-base ease-studio");\n';
  const result = await postcss([tailwind({ base: studio, optimize: false })]).process(fixture, { from: path.join(studio, 'app/globals.css') });
  const compiled = postcss.parse(result.css);
  const find = (selector) => { let found; compiled.walkRules(selector, (rule) => { found = rule; }); return found; };
  assert.equal(find('.rounded-lg'), undefined);
  assert.equal(find('.shadow-md'), undefined);
  assert.ok(find('.rounded-pill').nodes.some((node) => node.prop === 'border-radius' && /9999px|var\(--radius-pill\)/.test(node.value)));
  assert.ok(find('.bg-background').nodes.some((node) => node.prop === 'background-color' && node.value === 'var(--bg)'));
  assert.ok(find('.duration-base'));
  assert.ok(find('.ease-studio').nodes.some((node) => node.value === 'var(--ease)'));
  assert.equal(find('.bg-background').parent.params, 'utilities');
  const order = compiled.nodes.find((node) => node.name === 'layer' && !node.nodes && node.params.includes('legacy')).params.split(',').map((name) => name.trim());
  assert.ok(order.indexOf('legacy') < order.indexOf('utilities'));
});
