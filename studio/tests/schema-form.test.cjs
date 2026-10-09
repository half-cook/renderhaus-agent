const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const ts = require("typescript");

const root = path.resolve(__dirname, "..");
function load(relative) {
  const filename = path.join(root, relative);
  const output = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2021 },
  }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(output, {
    module, exports: module.exports,
    require: (name) => name.startsWith("@/") ? load(name.slice(2) + ".ts") : require(name),
  }, { filename });
  return module.exports;
}
const { SchemaForm } = load("components/forms/SchemaForm.tsx");

function elements(tree) {
  if (Array.isArray(tree)) return tree.flatMap(elements);
  if (!tree || typeof tree !== "object") return [];
  return [tree, ...elements(tree.props?.children)];
}

for (const [field, type, value] of [
  ["reference_image_urls", "string", "https://example.invalid/frame.png"],
  ["reference_video_durations", "number", 5.25],
  ["reference_video_fps", "number", 24],
]) {
  test(`reference form edits ${field} as a typed array`, () => {
    const values = {};
    const render = () => elements(SchemaForm({
      schema: { type: "object", properties: { [field]: { type: "array", items: { type } } } },
      values, onChange: (name, next) => { values[name] = next; },
    }));
    const label = field.replaceAll("_", " ");
    const add = render().find((element) => element.type === "button" && element.props["aria-label"] === `Add ${label}`);
    assert.ok(add, "array editor offers an add control");
    add.props.onClick();
    const input = render().find((element) => element.type === "input" && element.props["aria-label"] === `${label} 1`);
    assert.ok(input, "array entry can be edited");
    input.props.onChange({ target: { value: String(value) } });
    assert.ok(Array.isArray(values[field]));
    assert.equal(values[field][0], value);
    const remove = render().find((element) => element.type === "button" && element.props["aria-label"] === `Remove ${label} 1`);
    remove.props.onClick();
    assert.equal(values[field].length, 0);
  });
}
