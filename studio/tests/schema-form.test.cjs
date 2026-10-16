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
    require: (name) => name.startsWith("@/") ? load(name.slice(2) + ".ts") : name.startsWith(".") ? load(path.relative(root, path.resolve(path.dirname(filename), name + ".ts"))) : require(name),
  }, { filename });
  return module.exports;
}
const { SchemaForm } = load("components/forms/SchemaForm.tsx");
const { RadioGroup } = require("radix-ui");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function elements(tree) {
  if (Array.isArray(tree)) return tree.flatMap(elements);
  if (!tree || typeof tree !== "object") return [];
  return [tree, ...elements(tree.props?.children)];
}

test("ratio choices have their own accessible labels outside an implicit field label", () => {
  const props = {
    schema: { type: "object", properties: { aspect_ratio: { type: "string", enum: ["1:1", "16:9", "9:16"] } } },
    values: { aspect_ratio: "1:1" }, onChange() {},
  };
  const html = renderToStaticMarkup(React.createElement(SchemaForm, props));
  assert.match(html, /role="radiogroup"[^>]*aria-label="Aspect ratio"/);
  assert.match(html, /role="radio"[^>]*aria-checked="true"[^>]*>1:1<\/button>/);
  assert.equal(html.includes("<label"), false, "a group label must not replace the first choice's name");
});

test("keyboard radio selection preserves numeric field values", () => {
  const changes = [];
  const tree = elements(SchemaForm({
    schema: { type: "object", properties: { duration_seconds: { type: "number", enum: [4, 5.5, 8] } } },
    values: { duration_seconds: 4 }, onChange: (name, value) => changes.push([name, value]),
  }));
  const group = tree.find((element) => element.type === RadioGroup.Root);
  assert.ok(group, "use the installed radio group's keyboard and focus behavior");
  group.props.onValueChange("5.5");
  assert.deepEqual(changes, [["duration_seconds", 5.5]]);
});

for (const [field, type, value, label] of [
  ["reference_image_urls", "string", "https://example.invalid/frame.png", "Additional image references"],
  ["reference_video_durations", "number", 5.25, "reference video durations"],
  ["reference_video_fps", "number", 24, "reference video fps"],
]) {
  test(`reference form edits ${field} as a typed array`, () => {
    const values = {};
    const render = () => elements(SchemaForm({
      schema: { type: "object", properties: { [field]: { type: "array", items: { type } } } },
      values, onChange: (name, next) => { values[name] = next; },
    }));
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
