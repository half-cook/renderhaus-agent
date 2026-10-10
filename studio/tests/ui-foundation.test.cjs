const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const ts = require('typescript');

const studio = path.resolve(__dirname, '..');
const pkg = JSON.parse(fs.readFileSync(path.join(studio, 'package.json'), 'utf8'));
const files = ['dialog', 'popover', 'tooltip', 'tabs', 'dropdown-menu', 'sonner'];

test('the stack pins compatible Next, React and Tailwind without competing UI frameworks', () => {
  const all = { ...pkg.dependencies, ...pkg.devDependencies };
  for (const name of Object.keys(all)) assert.ok(!/^(framer-motion|cmdk|vaul|next-themes|storybook|@storybook\/|react-aria|@react-aria\/|@base-ui)/.test(name), `forbidden direct dependency: ${name}`);
  assert.match(pkg.dependencies.next, /^15\.5\.\d+$/);
  assert.match(pkg.dependencies.react, /^19\.2\.\d+$/);
  assert.equal(pkg.dependencies['react-dom'], pkg.dependencies.react);
  assert.match(pkg.devDependencies.tailwindcss, /^4\.3\.\d+$/);
  assert.equal(pkg.devDependencies['@tailwindcss/postcss'], pkg.devDependencies.tailwindcss);
  for (const name of ['radix-ui', 'class-variance-authority', 'clsx', 'tailwind-merge', 'sonner', 'motion']) assert.match(pkg.dependencies[name] ?? '', /^\d+\.\d+\.\d+$/, name);
  for (const name of ['@playwright/test', '@axe-core/playwright', 'pixelmatch', 'pngjs']) {
    assert.match(pkg.devDependencies[name] ?? '', /^\d+\.\d+\.\d+$/, name);
    assert.ok(!pkg.dependencies[name]);
  }
});

test('the six copy-in UI files stay square, flat, semantic and limited to their approved imports', () => {
  const ui = path.join(studio, 'components/ui');
  assert.ok(fs.existsSync(ui), 'copy-in components are required');
  assert.deepEqual(fs.readdirSync(ui).sort(), files.map((name) => `${name}.tsx`).sort());
  for (const file of fs.readdirSync(ui)) {
    const source = fs.readFileSync(path.join(ui, file), 'utf8');
    assert.match(source, /data-slot=/, file);
    assert.doesNotMatch(source, /\bdark:|\brounded-(?:sm|md|lg|xl|2xl|3xl|full)\b|\bshadow-/, file);
    assert.doesNotMatch(source, /\b(?:bg|text|border)-(?:black|white|amber|slate|neutral|stone)(?:\b|-)|\b(?:focus|hover|data-\[[^\]]+\]):bg-accent/, file);
    const parsed = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    for (const node of parsed.statements.filter(ts.isImportDeclaration)) {
      const module = node.moduleSpecifier.text;
      if (module === 'react' && node.importClause?.isTypeOnly) continue;
      if (file === 'sonner.tsx' && module === 'sonner') continue;
      assert.ok(['radix-ui', 'lucide-react', '@/lib/cn'].includes(module), `${file}: ${module}`);
    }
  }
});

test('cn merges conflicting Tailwind classes and Motion stays lean and unmounted', () => {
  const source = fs.readFileSync(path.join(studio, 'lib/cn.ts'), 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true } }).outputText;
  const exported = {};
  new Function('require', 'exports', js)(require, exported);
  assert.equal(exported.cn('px-2', false, ['px-4', { 'text-muted': true }]), 'px-4 text-muted');
  const provider = fs.readFileSync(path.join(studio, 'components/motion/provider.tsx'), 'utf8');
  assert.match(provider, /LazyMotion/);
  assert.match(provider, /features=\{domAnimation\}/);
  assert.match(provider, /reducedMotion="user"/);
  assert.match(provider, /export \{ m \} from "motion\/react"/);
  const layout = fs.readFileSync(path.join(studio, 'app/layout.tsx'), 'utf8');
  assert.doesNotMatch(layout, /components\/(ui|motion)/, 'foundation must not add route JS yet');
});
