// Run: node studio/lib/canvas/agent-review.check.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

// Use the installed compiler; the pure review helpers need no browser or test framework.
function load(file) {
  const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  new Function("require", "exports", output)((name) => load(path.resolve(path.dirname(file), `${name}.ts`)), exports);
  return exports;
}
const { reviewFiles, diffReviewLines, sequenceReviewLines, timelineReviewLines, latestTimelineReview } = load(path.join(__dirname, "agent-review.ts"));
const source = { versionId: "upload-1", assetId: "a", filename: "source.mp4", kind: "video" };
const generated = { versionId: "generated-1", assetId: "b", filename: "result.mp4", kind: "video" };
const node = { id: "scene-1", data: { kind: "video", title: "Opening", config: { duration_seconds: 4 }, output: source, variants: [source], approved: true, storyOrder: 0 } };
const event = (duration, status = "completed") => ({ name: "Remotion___render_timeline", status, assets: [], arguments: { title: "Cut", visuals: [{ kind: "video", url: "renderhaus-asset://upload-1", start_seconds: 0, duration_seconds: duration }] } });
const run = (createdAt, events = [], status = "completed") => ({ createdAt, status, assets: [generated], toolEvents: events, primaryAsset: generated });

const files = reviewFiles([node], [run(1)]);
assert.equal(files.length, 2, "Deduplicate current output and its variant");
assert.equal(files.find((file) => file.asset === source).origin, "Uploaded");
assert.equal(files.find((file) => file.asset === generated).currentTask, true);
assert.equal(reviewFiles([node], [])[0].currentTask, false, "Project media is not attributed to the selected task");
assert.deepEqual(diffReviewLines(undefined, sequenceReviewLines([node])).map((line) => line.change), ["context"], "No baseline must not invent an addition");
const changed = { ...node, data: { ...node.data, config: { duration_seconds: 6 } } };
assert.deepEqual(diffReviewLines(sequenceReviewLines([node]), sequenceReviewLines([changed])).map((line) => line.change), ["removed", "added"]);
assert.equal(diffReviewLines(sequenceReviewLines([node]), [])[0].change, "removed");
assert.equal(sequenceReviewLines([{ ...node, data: { ...node.data, approved: false } }]).length, 0);

const lines = timelineReviewLines(event(4).arguments, [source]);
assert.match(lines.at(-1).text, /source\.mp4/);
assert.match(lines.at(-1).text, /duration seconds: 4/);
const review = latestTimelineReview([run(2, [event(6)]), run(1, [event(4)])], [source]);
assert.equal(review.hasPrevious, true);
assert.deepEqual(review.lines.map((line) => line.change), ["context", "removed", "added"]);
assert.equal(latestTimelineReview([run(1, [event(4, "failed")])], []).requestStatus, "failed", "Failed render instructions retain their failure status independently of the run");
const completed = latestTimelineReview([run(1, [event(4, "queued")])], [generated]);
assert.equal(completed.status, "completed", "A completed run must not be labeled with the stale queued submission status");
assert.equal(completed.outputFilename, "result.mp4", "Timeline file header uses the same execution primary output");
assert.equal(latestTimelineReview([run(1, [event(4, "queued")], "failed")], []).status, "failed", "Saved media must not upgrade a failed run to completed");
assert.equal(latestTimelineReview([run(1)], []), undefined);
assert.equal(timelineReviewLines({ visuals: [null, false, "bad"] }, []).length, 0);
assert.doesNotMatch(timelineReviewLines({ visuals: [{ url: "https://media.example/movie.mp4?secret=token#secret", duration_seconds: 2 }] }, [])[0].text, /secret|token|https/);
console.log("Agent review checks passed: uploads, task outputs, real sequence deltas, completed-run status, output filename, failure status, and URL redaction.");
