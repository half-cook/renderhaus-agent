const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const cache = new Map();

module.exports = function load(file) {
  const target = path.resolve(root, file);
  if (cache.has(target)) return cache.get(target);
  const exported = {};
  cache.set(target, exported);
  const source = fs.readFileSync(target, 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  new Function('require', 'exports', js)((name) => {
    if (name.startsWith('@/') || name.startsWith('.')) {
      const local = name.startsWith('@/') ? path.join(root, name.slice(2)) : path.resolve(path.dirname(target), name);
      return load(fs.existsSync(local) ? local : `${local}.ts`);
    }
    return require(name);
  }, exported);
  return exported;
};
