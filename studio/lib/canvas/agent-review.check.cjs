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
const { reviewFiles, diffReviewLines, sequenceReviewLines, timelineSegments, diffTimelineSegments, latestTimelineReview } = load(path.join(__dirname, "agent-review.ts"));
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

const lines = timelineSegments(event(4).arguments, [source]);
assert.match(lines.at(-1).source, /source\.mp4/);
assert.equal(lines.at(-1).duration, 4);
const review = latestTimelineReview([run(2, [event(6)]), run(1, [event(4)])], [source]);
assert.equal(review.hasPrevious, true);
assert.deepEqual(review.rows.map((line) => line.change), ["removed", "added"]);
assert.equal(latestTimelineReview([run(1, [event(4, "failed")])], []).requestStatus, "failed", "Failed render instructions retain their failure status independently of the run");
const completed = latestTimelineReview([run(1, [event(4, "queued")])], [generated]);
assert.equal(completed.status, "completed", "A completed run must not be labeled with the stale queued submission status");
assert.match(completed.currentLabel, /run completed/);
assert.doesNotMatch(completed.currentLabel, /queued/);
assert.equal(completed.outputFilename, "result.mp4", "Timeline file header uses the same execution primary output");
assert.equal(latestTimelineReview([run(1, [event(4, "queued")], "failed")], []).status, "failed", "Saved media must not upgrade a failed run to completed");
assert.equal(latestTimelineReview([run(1)], []), undefined);
assert.equal(timelineSegments({ visuals: [null, false, "bad"] }, []).length, 0);
assert.doesNotMatch(timelineSegments({ visuals: [{ url: "https://media.example/movie.mp4?secret=token#secret", duration_seconds: 2 }] }, [])[0].source, /secret|token|https/);

const clip = (name, duration = 4, extra = {}) => ({ kind: "video", url: `https://media.example/${name}.mp4`, duration_seconds: duration, ...extra });
const segments = (visuals, extra = {}) => timelineSegments({ visuals, ...extra }, [source, generated]);
const changes = (old, next) => diffTimelineSegments(old, next);
const changeTypes = (rows) => rows.map((row) => row.change);
const oldCut = segments([clip("A"), clip("B")]);
const inserted = segments([clip("X", 2, {start_seconds:0}), clip("A",4,{start_seconds:2}), clip("B",4,{start_seconds:6})]);
assert.deepEqual(changeTypes(changes(oldCut, inserted)), ["added", "context", "context"], "An insertion and its explicit ripple do not replace every subsequent clip");
assert.deepEqual(changeTypes(changes(oldCut, segments([clip("A",3),clip("B")]))), ["removed","added","context"], "A trim pairs old/new without cascading through implicit starts");
assert.deepEqual(changes(oldCut,segments([clip("A",3),clip("B")]))[0].changedFields,["duration"]);
const duplicateBefore = segments([clip("A",3),clip("A",7),clip("B",2)]);
const duplicateAfter = segments([clip("A",1),clip("A",3),clip("A",7),clip("B",2)]);
assert.equal(new Set(duplicateAfter.map((s)=>s.id)).size,4,"Duplicate sources retain unique occurrence IDs");
assert.deepEqual(changeTypes(changes(duplicateBefore,duplicateAfter)),["added","context","context","context"],"LCS prefers unchanged repeated source uses");
assert.deepEqual(changeTypes(changes(segments([clip("A"),clip("X",2),clip("B")]),oldCut)),["context","removed","context"],"Deletion stays in its hunk rather than at top of file");
const replacement = changes(segments([clip("A"),clip("X"),clip("B")]),segments([clip("A"),clip("Y"),clip("B")]));
assert.deepEqual(changeTypes(replacement),["context","removed","added","context"]);
assert.equal(replacement[1].after,replacement[2].after,"Replacement counterparts carry both versions");
const mixedBefore=segments(Array.from({length:8},(_,i)=>clip(`old-shot-${i}`,8.75)),{audio_tracks:[clip("old-score",70)]});
const mixedAfter=segments([clip("new-shot",30)],{audio_tracks:[clip("new-score",30)],text_overlays:[{text:"After the flash",duration_seconds:5}]});
const mixedDiff=changes(mixedBefore,mixedAfter);
const mediaLane=(segment)=>["audio","text"].includes(segment.kind)?segment.kind:segment.track;
assert.equal(mixedDiff.filter((row)=>row.before&&row.after).every((row)=>mediaLane(row.before)===mediaLane(row.after)),true,"An unmatched mixed-media hunk must never replace a shot with audio or text");
assert.equal(mixedDiff.filter((row)=>row.change==="removed"&&!row.after).length,7,"Remaining old shots are deletions, not fabricated media replacements");
assert.equal(mixedDiff.at(-1).change,"added");
assert.equal(mixedDiff.at(-1).segment.kind,"text");
assert.equal(mixedDiff.at(-1).before,undefined,"New title is an addition");
const audioPair=mixedDiff.findIndex((row)=>row.change==="removed"&&row.before?.kind==="audio");
assert.equal(mixedDiff[audioPair+1].change,"added");
assert.equal(mixedDiff[audioPair+1].segment.kind,"audio","Audio replacement remains adjacent");
assert.deepEqual(mixedDiff.filter((row)=>row.change!=="added").map((row)=>row.before.id),mixedBefore.map((segment)=>segment.id),"Old media order is preserved");
assert.deepEqual(mixedDiff.filter((row)=>row.change!=="removed").map((row)=>row.after.id),mixedAfter.map((segment)=>segment.id),"New media order is preserved");
const trackReplacement=changes(segments([clip("old-main"),clip("old-overlay",4,{track:1})]),segments([clip("new-overlay",4,{track:1}),clip("new-main",4,{kind:"image"})]));
assert.equal(trackReplacement.every((row)=>row.before.track===row.after.track),true,"Fallback visual replacements stay on their own track");
assert.equal(trackReplacement[1].segment.kind,"image","Image/video replacement on the same visual track is valid");
const stableChange=changes(segments([clip("A",4,{id:"stable-shot"})]),segments([clip("B",4,{id:"stable-shot"})]));
assert.deepEqual(stableChange[0].changedFields,["source"]);
assert.deepEqual(changeTypes(changes(segments([clip("A"),clip("B")]),segments([clip("B"),clip("A")]))),["removed","context","added"],"Reorders retain matches and show moved occurrences as removal/addition");
assert.deepEqual(changeTypes(changes(oldCut,segments([clip("A",4,{volume:1,source_in_seconds:0,fit:"cover",motion:"none",playback_rate:1}),clip("B")]))),["context","context"],"Recorded defaults and explicit equivalent defaults compare equal");
const trimmed=segments([{...clip("source"),url:"renderhaus-asset://upload-1",source_in_seconds:1.25}])[0];
assert.equal(trimmed.asset,source);
assert.equal(trimmed.sourceStart,1.25);
assert.equal(trimmed.source,"source.mp4 [upload-1]","The UI sees a filename, not a transport handle");
const nextSource={...source,versionId:"upload-2"};
const nextVersion=timelineSegments({visuals:[{...clip("source"),url:"renderhaus-asset://upload-2",source_in_seconds:1.25}]},[nextSource]);
assert.deepEqual(changes([trimmed],nextVersion)[0].changedFields,["source"],"Same-filename asset version updates still diff");
const layered=segments([clip("A",4),clip("B",2,{track:1}),clip("C",3,{track:0}),clip("D",1,{track:1,start_seconds:0.5})]);
assert.deepEqual(layered.map((s)=>[s.track,s.start,s.end]),[["V1",0,4],["V2",0,2],["V1",4,7],["V2",0.5,1.5]],"Starts append on their own tracks and preserve explicit overlap");
const missing=segments([clip("A",undefined,{duration_seconds:undefined,transition:"fade"}),clip("B")]);
assert.equal(missing[0].duration,undefined);
assert.equal(missing[0].end,undefined);
assert.equal(missing[0].properties.fade_in_seconds,"Unknown");
assert.equal(missing[1].start,undefined,"Unknown preceding end must not invent a next start");
assert.equal(segments([clip("A",4,{start_seconds:"bad"})])[0].start,undefined);
const fades=segments([clip("A",6,{transition:"fade"}),clip("B",4)],{audio_tracks:[clip("audio",20,{start_seconds:2})],text_overlays:[{text:"Caption",start_seconds:9,duration_seconds:8,fade_in_seconds:0}]});
assert.equal(fades[1].start,6,"Transitions do not invent overlap");
assert.equal(fades[2].duration,8,"Audio ends at visual end");
assert.equal(fades[3].duration,1,"Visible title ends at visual end");
assert.equal(fades[3].properties.fade_in_seconds,"0.2","Renderer treats explicit zero title fade as its default");
const providerDefaults=segments([clip("A",4,{scale:6,playback_rate:9,opacity:2,rotation_degrees:500})],{audio_tracks:[clip("audio",8,{volume:1.5})],text_overlays:[{text:"  Caption  ",start_seconds:3.9,duration_seconds:8,font_size:64.9}]});
assert.equal(providerDefaults[0].properties.scale,"4");
assert.equal(providerDefaults[0].properties.playback_rate,"4");
assert.equal(providerDefaults[0].properties.opacity,"1");
assert.equal(providerDefaults[0].properties.rotation_degrees,"360");
assert.equal(providerDefaults[1].properties.volume,"1.5","Audio gain is not clamped by the provider");
assert.equal(providerDefaults[2].properties.fade_in_seconds,"0.2","Title fades use requested duration before visible clipping");
assert.equal(providerDefaults[2].properties.font_size,"64");
assert.equal(providerDefaults[2].label,"Caption");
assert.deepEqual(changeTypes(changes(segments([clip("A")],{audio_tracks:[clip("music",4)]}),segments([clip("A")],{audio_tracks:[clip("voice",4),clip("music",4)]}))),["context","added","context"],"Automatically renumbered audio tracks do not cascade into changed sources");
assert.doesNotMatch(JSON.stringify(segments([clip("A",4,{url:"https://name:password@media.example/A.mp4?secret=token#private"})])),/password|secret|token|private/,"Structured source data also strips URL credentials and signatures");
assert.deepEqual(changeTypes(diffTimelineSegments(undefined,oldCut)),["context","context"]);

const captioned = segments([clip("talk", 4)], {
  text_overlays: [{text: "Speaker", start_seconds: 0, duration_seconds: 4}],
  subtitles: [{text: "HELLO", start_seconds: 1.25, duration_seconds: 0.4}],
});
assert.deepEqual(captioned.map((segment) => segment.track), ["V1", "T1", "S1"], "Subtitles have a separate final review track");
assert.equal(captioned.at(-1).start, 1.25, "Subtitle review uses output timing");
assert.equal(captioned.at(-1).properties.fade_in_seconds, "0", "Short subtitles have no implicit title fade");
const editorialBefore = segments([clip("talk", 4)]);
const editorialAfter = segments([clip("talk", 4, {grade: "warm", audio_fade_in_seconds: 0.03, audio_fade_out_seconds: 0.03})]);
assert.deepEqual(changes(editorialBefore, editorialAfter)[0].changedFields.sort(), ["audio_fade_in_seconds", "audio_fade_out_seconds", "grade"], "Grade and dialogue fades remain reviewable");
assert.equal(editorialAfter[0].properties.fade_in_seconds, "0", "Audio fades do not add picture fades");
assert.deepEqual(changeTypes(changes(editorialBefore, segments([clip("talk", 4, {grade: "none", audio_fade_in_seconds: 0, audio_fade_out_seconds: 0})]))), ["context"], "Explicit editorial defaults compare equal");

const namedEvent=(title,status="queued",extra={})=>({...event(4,status),id:`event-${title}`,arguments:{...event(4).arguments,title},...extra});
const output=(id,version)=>({...generated,assetId:id,versionId:version});
const namedRun=(n,title,primary=undefined,status="completed",toolStatus="queued")=>({...run(n,[namedEvent(title,toolStatus)],status),jobId:`run-${n}`,primaryAsset:primary,assets:primary?[primary]:[]});
const unrelated=latestTimelineReview([namedRun(1,"Different"),namedRun(2,"Current")],[]);
assert.equal(unrelated.hasPrevious,false,"Unrelated titles must not be silently compared");
const histories=[namedRun(1,"Cut"),namedRun(2,"Other"),namedRun(3,"Cut",undefined,"failed","rejected"),namedRun(4,"Cut")];
const compared=latestTimelineReview(histories,[]);
assert.equal(compared.previousPlanId,"run-1:event-Cut","Auto selection skips unrelated/rejected plans");
assert.equal(compared.comparisons.length,3);
assert.match(compared.comparisons.find((p)=>p.id==="run-3:event-Cut").label,/rejected/);
assert.equal(latestTimelineReview(histories,[],"run-2:event-Other").comparisonBasis,"selected","Explicit comparison may choose an unrelated saved plan without asserting ancestry");
assert.equal(latestTimelineReview(histories,[],null).hasPrevious,false);
assert.equal(latestTimelineReview(histories,[],"missing").hasPrevious,false,"Invalid selection cannot silently change the baseline");
const logical=latestTimelineReview([namedRun(1,"Original",output("logical","v1")),namedRun(2,"New title",output("different","v2")),namedRun(3,"New title",output("logical","v3"))],[]);
assert.equal(logical.previousPlanId,"run-1:event-Original","Reliable logical output identity takes precedence over title");
assert.equal(logical.metadata.some((line)=>line.change==="removed"&&line.text==="title: Original"),true);
assert.equal(logical.outputAsset.versionId,"v3");
const multi={...run(1,[namedEvent("First"),namedEvent("Last")]),jobId:"multi"};
assert.equal(latestTimelineReview([multi],[]).outputAsset,undefined,"Execution primary alone cannot identify which of multiple plans created it");
multi.toolEvents[1].providerJobId="render-last";
multi.toolEvents.push({name:"Remotion___get_render_progress",providerJobId:"render-last",assets:[generated],arguments:{},status:"completed"});
assert.equal(latestTimelineReview([multi],[]).outputAsset,generated,"Matching provider render ID establishes output association");
const sourcePrimary={...run(1,[namedEvent("Failed","failed"),{name:"Seedance___generate",assets:[generated],arguments:{},status:"completed"}]),jobId:"partial"};
assert.equal(latestTimelineReview([sourcePrimary],[]).outputAsset,undefined,"A generated source is not the output of a failed render");
console.log("Unified video diff checks passed: media-lane replacements, identity and duplicate alignment, adjacent hunks, ripple timing, normalized defaults, unknown timing, source trim, baseline selection, output provenance, statuses, and URL redaction.");
