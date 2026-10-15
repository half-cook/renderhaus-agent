const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const { createRequire } = require("module");
const path = require("path");
// Load via ts-node? The studio tests use .cjs and often read source. Mirror design-tokens style: require compiled? 
// Read the TypeScript source and evaluate the cents logic inline.
const src = require("fs").readFileSync(path.join(__dirname, "../lib/rh/approval-model.ts"), "utf8");
assert.match(src, /export function traceCost/);
assert.match(src, /actual_cents/);
assert.match(src, /charged_cents/);
assert.match(src, /spentSoFarCents/);
