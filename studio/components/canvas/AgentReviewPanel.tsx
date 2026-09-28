"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { ChevronDown, Download, FileAudio, FileImage, FileVideo, Film, GitCompareArrows, Play, Rows3, Type } from "lucide-react";
import { useCanvasStore } from "@/lib/canvas/store";
import {
  diffReviewLines, latestTimelineReview, reviewFiles, sequenceReviewLines,
  type DiffLine, type ReviewFile, type TimelineDiffRow, type TimelineSegment,
} from "@/lib/canvas/agent-review";
import type { StudioAsset } from "@/lib/types";
import { AssetDownloadLink, AssetMedia } from "./AssetMedia";
import styles from "./AgentReviewPanel.module.css";

function FileIcon({ kind }: { kind: StudioAsset["kind"] }) {
  const Icon = kind === "video" ? FileVideo : kind === "audio" ? FileAudio : FileImage;
  return <Icon size={15} aria-hidden="true" />;
}

function Diff({ lines }: { lines: DiffLine[] }) {
  return <div className={styles.diff} aria-label="Edit comparison">
    {lines.map((line) => <div key={`${line.id}-${line.change}`} className={`${styles.diffLine} ${styles[line.change]}`}>
      <span aria-label="Previous line">{line.before ?? ""}</span>
      <span aria-label="Current line">{line.after ?? ""}</span>
      <span aria-label={line.change}>{line.change === "added" ? "+" : line.change === "removed" ? "−" : " "}</span>
      <code>{line.text}</code>
    </div>)}
  </div>;
}

function timecode(value: number | undefined) {
  if (value === undefined || !Number.isFinite(value)) return "—";
  const seconds = Math.round(Math.max(0, value) * 100) / 100;
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${(seconds % 60).toFixed(seconds % 1 ? 2 : 0).padStart(seconds % 1 ? 5 : 2, "0")}`;
}

function fieldName(key: string) {
  return ({ source: "Source", start: "Timeline start", duration: "Duration", label: "Content", track: "Track", kind: "Media type" } as Record<string, string>)[key]
    || key.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function fieldValue(segment: TimelineSegment, key: string) {
  if (key === "start") return timecode(segment.start);
  if (key === "duration") return segment.duration === undefined ? "Unknown" : `${segment.duration}s`;
  if (key === "source" || key === "label" || key === "track" || key === "kind") return segment[key];
  return segment.properties[key] ?? "Not set";
}

function Thumbnail({ asset, kind, start }: { asset?: StudioAsset; kind?: TimelineSegment["kind"]; start?: number }) {
  return <span className={styles.thumbnail}>
    {asset && asset.kind !== "audio"
      ? <AssetMedia key={`${asset.versionId}-${start ?? 1}`} asset={asset} alt={asset.filename} className={styles.thumbnailMedia} muted preload="metadata" startTime={start ?? 1} />
      : kind === "text" ? <Type size={19} aria-hidden="true" /> : <FileIcon kind={asset?.kind || (kind === "audio" ? "audio" : "video")} />}
  </span>;
}

function SegmentRow({ row, onPreview, outputAsset, previousOutputAsset }: { row: TimelineDiffRow; onPreview: (row: TimelineDiffRow) => void; outputAsset?: StudioAsset; previousOutputAsset?: StudioAsset }) {
  const { segment, before, after, change, changedFields } = row;
  const label = segment.kind === "text" ? segment.label : `${segment.kind === "audio" ? "Audio" : "Shot"} ${String(segment.kind === "audio" ? segment.track.slice(1) : segment.ordinal).padStart(2, "0")}`;
  const keys = change === "context" ? Object.keys(segment.properties) : changedFields;
  const canPreview = Boolean(segment.asset || (outputAsset && after?.start !== undefined));
  const renderedAsset = change === "removed" ? previousOutputAsset : outputAsset;
  const thumbnailAsset = segment.asset || (segment.kind !== "audio" && segment.kind !== "text" && segment.start !== undefined ? renderedAsset : undefined);
  const sampleOffset = Math.min(1, (segment.duration || 0) / 2);
  const thumbnailTime = segment.asset ? (segment.sourceStart ?? 0) + sampleOffset : segment.start === undefined ? undefined : segment.start + sampleOffset;
  return <div className={`${styles.segment} ${styles[change]}`}>
    <div className={styles.segmentLine}>
      <time aria-label="Previous time">{change !== "added" && before ? timecode(before.start) : ""}</time>
      <time aria-label="Current time">{change !== "removed" && after ? timecode(after.start) : ""}</time>
      <span className={styles.sign} aria-label={change}>{change === "added" ? "+" : change === "removed" ? "−" : ""}</span>
      <button className={styles.segmentContent} type="button" disabled={!canPreview} onClick={() => onPreview(row)} aria-label={`Preview ${change === "context" ? "" : `${change} `}${label} at ${timecode(segment.start)}`}>
        <Thumbnail asset={thumbnailAsset} kind={segment.kind} start={thumbnailTime} />
        <span className={styles.segmentText}>
          <span className={styles.segmentTitle}><small>{segment.track}</small><strong title={label}>{label}</strong><Play size={11} aria-hidden="true" /></span>
          <span className={styles.segmentMeta}>
            <span className={changedFields.includes("duration") && change !== "context" ? styles.changedValue : ""}>{segment.duration === undefined ? "Duration unknown" : `${segment.duration}s`}</span>
            <span> · </span><span className={styles.range}>{timecode(segment.start)}–{timecode(segment.end)}</span>
          </span>
          {segment.kind !== "text" ? <span className={`${styles.sourceName} ${changedFields.includes("source") && change !== "context" ? styles.changedValue : ""}`} title={segment.source}>{segment.source}</span> : null}
        </span>
      </button>
    </div>
    {change !== "removed" && keys.length > 0 ? <details className={styles.properties}>
      <summary>{change === "context" ? "Clip settings" : `${keys.length} changed ${keys.length === 1 ? "property" : "properties"}`}</summary>
      <dl>{keys.map((key) => <div key={key}><dt>{fieldName(key)}</dt><dd>
        {change !== "context" && before ? <><del>{fieldValue(before, key)}</del><span aria-hidden="true"> → </span></> : null}
        <span>{fieldValue(segment, key)}</span>
      </dd></div>)}</dl>
    </details> : null}
  </div>;
}

function TimelineDiff({ rows, hasPrevious, outputAsset, previousOutputAsset, onPreview }: {
  rows: TimelineDiffRow[]; hasPrevious: boolean; outputAsset?: StudioAsset; previousOutputAsset?: StudioAsset; onPreview: (row: TimelineDiffRow) => void;
}) {
  const groups: { context: boolean; rows: TimelineDiffRow[] }[] = [];
  for (const row of rows) {
    const context = row.change === "context";
    if (groups.at(-1)?.context === context) groups.at(-1)!.rows.push(row);
    else groups.push({ context, rows: [row] });
  }
  function range(items: (TimelineSegment | undefined)[]) {
    const timed = items.filter((item): item is TimelineSegment => Boolean(item && item.start !== undefined && item.end !== undefined));
    return timed.length ? `${timecode(Math.min(...timed.map((item) => item.start!)))}–${timecode(Math.max(...timed.map((item) => item.end!)))}` : "—";
  }
  const renderRows = (items: TimelineDiffRow[]) => items.map((row) => <SegmentRow key={row.id} row={row} onPreview={onPreview} outputAsset={outputAsset} previousOutputAsset={previousOutputAsset} />);
  return <div className={styles.timelineDiff} aria-label="Timeline edit comparison">
    <div className={styles.diffHead}><span>Old</span><span>New</span><span /><span>Timeline segments</span></div>
    {groups.map((group, index) => {
      const before = range(group.rows.filter((row) => row.change !== "added").map((row) => row.before));
      const after = range(group.rows.filter((row) => row.change !== "removed").map((row) => row.after));
      if (group.context && group.rows.length > 4) return <div key={index}>
        {renderRows(group.rows.slice(0, 1))}
        <details className={styles.contextFold}>
          <summary><ChevronDown size={13} />{group.rows.length - 2} {hasPrevious ? "unchanged" : "more"} segments</summary>
          {renderRows(group.rows.slice(1, -1))}
        </details>
        {renderRows(group.rows.slice(-1))}
      </div>;
      return <div key={index}>
        {!group.context ? <div className={styles.hunk}><span>@@ {before === after ? after : `${before} → ${after}`} @@</span><span>{group.rows.some((row) => row.before && row.after) ? "Edited segments" : group.rows[0].change === "added" ? "Added segments" : "Removed segments"}</span></div> : null}
        {renderRows(group.rows)}
      </div>;
    })}
    {hasPrevious && rows.every((row) => row.change === "context") ? <p className={styles.baselineNote}>No segment changes between these saved plans.</p> : null}
  </div>;
}

function Viewer({ label, files, value, onChange, empty, startTime }: {
  label: string; files: ReviewFile[]; value: string;
  onChange: (value: string) => void; empty: string; startTime?: number;
}) {
  const asset = files.find((file) => file.asset.versionId === value)?.asset;
  return <section className={styles.viewer} aria-label={`${label} viewer`}>
    <header><span>{label}</span>{asset ? <AssetDownloadLink asset={asset} className={styles.iconButton} ariaLabel={`Download ${label.toLowerCase()}`}><Download size={14} /></AssetDownloadLink> : null}</header>
    <label className={styles.selector}>
      <span className={styles.srOnly}>{label} media</span>
      <select value={asset?.versionId || ""} onChange={(event) => onChange(event.target.value)}>
        <option value="">Choose media</option>
        {files.map((file) => <option key={file.asset.versionId} value={file.asset.versionId}>{file.asset.filename} · {file.asset.versionId.slice(0, 8)}{file.currentTask ? " · This task" : ""}</option>)}
      </select>
    </label>
    <div className={styles.screen}>
      {asset ? <AssetMedia key={`${asset.versionId}-${startTime ?? 0}`} asset={asset} alt={`${label}: ${asset.filename}`} className={styles.media} controls startTime={startTime} /> : <div className={styles.viewerEmpty}><Film size={22} /><p>{empty}</p></div>}
    </div>
    <footer>{asset ? `${asset.kind.toUpperCase()} · ${asset.filename}` : "No media selected"}</footer>
  </section>;
}

export function AgentReviewPanel() {
  const nodes = useCanvasStore((state) => state.nodes);
  const executions = useCanvasStore((state) => state.executions);
  const past = useCanvasStore((state) => state.past);
  const selectedNodeIds = useCanvasStore((state) => state.selectedNodeIds);
  const conversationId = useCanvasStore((state) => state.conversationId);
  const projectId = useCanvasStore((state) => state.projectId);
  const [tab, setTab] = useState<"changes" | "preview">("changes");
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [resultId, setResultId] = useState<string | null>(null);
  const [sourceTime, setSourceTime] = useState<number>();
  const [resultTime, setResultTime] = useState<number>();
  const [previousPlanId, setPreviousPlanId] = useState<string | null>();
  const id = useId();
  const files = useMemo(() => reviewFiles(nodes, executions), [nodes, executions]);
  const assets = useMemo(() => files.map((file) => file.asset), [files]);
  const timeline = useMemo(() => latestTimelineReview(executions, assets, previousPlanId), [executions, assets, previousPlanId]);
  const previous = past.at(-1);
  const sequence = useMemo(() => diffReviewLines(
    previous ? sequenceReviewLines(previous.nodes) : undefined,
    sequenceReviewLines(nodes),
  ), [previous, nodes]);
  const selectedAsset = nodes.find((node) => selectedNodeIds.includes(node.id) && node.data.output)?.data.output;
  const latestOutput = [...executions].sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0))
    .find((execution) => execution.primaryAsset || execution.assets.length);
  const defaultResult = latestOutput?.primaryAsset || latestOutput?.assets.find((asset) => asset.kind === "video") || latestOutput?.assets[0];
  const defaultSource = selectedAsset || files.find((file) => !file.currentTask)?.asset;

  useEffect(() => { setSourceId(null); setResultId(null); setSourceTime(undefined); setResultTime(undefined); setPreviousPlanId(undefined); }, [projectId, conversationId]);
  useEffect(() => { if (selectedAsset) { setSourceId(selectedAsset.versionId); setSourceTime(undefined); } }, [selectedAsset?.versionId]);

  const source = sourceId === null ? defaultSource?.versionId || "" : files.some((file) => file.asset.versionId === sourceId) ? sourceId : "";
  const result = resultId === null ? defaultResult?.versionId || "" : files.some((file) => file.asset.versionId === resultId) ? resultId : "";
  const taskFiles = files.filter((file) => file.currentTask && file.asset.versionId !== timeline?.outputAsset?.versionId);
  const projectFiles = files.filter((file) => !file.currentTask);

  function showPreview() {
    setTab("preview");
    document.getElementById(`${id}-preview`)?.focus();
  }

  function preview(file: ReviewFile) {
    if (file.currentTask) { setResultId(file.asset.versionId); setResultTime(undefined); }
    else { setSourceId(file.asset.versionId); setSourceTime(undefined); }
    showPreview();
  }

  function previewSegment(row: TimelineDiffRow) {
    const clip = row.segment;
    setSourceId(clip.asset?.versionId || "");
    setSourceTime(clip.sourceStart);
    setResultId(row.after ? timeline?.outputAsset?.versionId || "" : "");
    setResultTime(row.after?.start);
    showPreview();
  }

  function fileList(items: ReviewFile[], title: string) {
    if (!items.length) return null;
    return <section className={styles.fileGroup} aria-label={title}>
      <h3>{title}<span>{items.length}</span></h3>
      {items.map((file) => <details className={styles.file} key={file.asset.versionId}>
        <summary><ChevronDown size={12} className={styles.chevron} /><FileIcon kind={file.asset.kind} /><span title={file.asset.filename}>{file.title || file.asset.filename}</span><small className={file.currentTask ? styles.created : ""}>{file.currentTask ? "Created" : file.origin}</small></summary>
        <div className={styles.fileDetails}>
          <Thumbnail asset={file.asset} />
          <div><p>{file.asset.filename}</p>
          <span>{file.asset.kind.toUpperCase()} · Version {file.asset.versionId.slice(0, 8)}</span>
          <button type="button" onClick={() => preview(file)}><Play size={13} />Open in preview</button>
          </div>
        </div>
      </details>)}
    </section>;
  }

  return <aside className={styles.panel} aria-label="Agent review">
    <div className={styles.tabs} role="tablist" aria-label="Review mode">
      {(["changes", "preview"] as const).map((value) => <button
        type="button" key={value} id={`${id}-${value}`} role="tab" aria-selected={tab === value}
        aria-controls={`${id}-panel`} tabIndex={tab === value ? 0 : -1}
        onClick={() => setTab(value)} onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const next = event.key === "Home" ? "changes" : event.key === "End" ? "preview" : tab === "changes" ? "preview" : "changes";
          setTab(next); document.getElementById(`${id}-${next}`)?.focus();
        }}>
        {value === "changes" ? <GitCompareArrows size={15} /> : <Play size={15} />}
        {value === "changes" ? "Changes" : "Preview"}
      </button>)}
    </div>
    <div className={styles.content} id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${tab}`}>
      {tab === "changes" ? <>
        <div className={styles.heading}><div><h2>Changes</h2><p>{timeline ? "Saved edit plans and task media." : "Media created in this task."}</p></div><span className={styles.count}>{files.filter((file) => file.currentTask).length} created</span></div>
        {timeline ? <>
          {timeline.comparisons.length ? <label className={styles.comparisonSelector}>Compare with
            <select value={timeline.previousPlanId || ""} onChange={(event) => setPreviousPlanId(event.target.value || null)}>
              <option value="">No comparison · current plan</option>
              {timeline.comparisons.map((plan) => <option key={plan.id} value={plan.id}>{plan.label}</option>)}
            </select>
          </label> : null}
          <details className={styles.timelineFile} open key={`${conversationId}-${timeline.currentLabel}`}>
            <summary className={styles.timelineTitle}><ChevronDown size={13} /><FileVideo size={15} /><strong>{timeline.outputFilename || timeline.title}</strong>
              {timeline.hasPrevious ? <span className={styles.diffTotals}><b>+{timeline.rows.filter((row) => row.change === "added").length}</b><b>−{timeline.rows.filter((row) => row.change === "removed").length}</b></span> : <small>{timeline.comparisons.length ? "Current plan" : "First version"}</small>}
            </summary>
            <div className={styles.planSummary}>
              <span>{timeline.hasPrevious ? `${timeline.previousLabel} → ${timeline.currentLabel}` : timeline.currentLabel}</span>
              <span className={["failed", "error", "rejected", "cancelled", "canceled"].includes(timeline.requestStatus.toLowerCase()) || ["failed", "error"].includes(timeline.status) ? styles.failedStatus : ""}>Run {timeline.status.replaceAll("_", " ")}{["failed", "error", "rejected", "cancelled", "canceled"].includes(timeline.requestStatus.toLowerCase()) ? ` · Request ${timeline.requestStatus}` : ""}</span>
            </div>
            {!timeline.hasPrevious ? <p className={styles.baselineNote}>{timeline.comparisons.length ? "Current saved plan. Choose an earlier plan to compare." : "First saved edit plan. No earlier plan to compare."}</p> : null}
            <TimelineDiff rows={timeline.rows} hasPrevious={timeline.hasPrevious} outputAsset={timeline.outputAsset} previousOutputAsset={timeline.previousOutputAsset} onPreview={previewSegment} />
            {timeline.metadata.length ? <details className={styles.planSettings}><summary>Project settings{timeline.metadata.some((line) => line.change !== "context") ? " · changed" : ""}</summary><Diff lines={timeline.metadata} /></details> : null}
            {timeline.outputAsset ? <button type="button" className={styles.openOutput} onClick={() => { setResultId(timeline.outputAsset!.versionId); setResultTime(undefined); showPreview(); }}><Play size={12} />Open rendered video</button> : <p className={styles.baselineNote}>Saved instructions · no rendered video linked to this plan.</p>}
          </details>
        </> : null}
        {sequence.length ? <details className={styles.editSection} open={!timeline}>
          <summary className={styles.sectionTitle}><Rows3 size={14} /><h3>Approved sequence</h3></summary>
          <p className={styles.note}>{previous ? "Current canvas compared with its last undo snapshot." : "Current canvas sequence. No earlier snapshot to compare."}</p>
          <Diff lines={sequence} />
        </details> : null}
        {fileList(taskFiles, "Created in this task")}
        {projectFiles.length ? <details className={styles.projectMedia}><summary>Project media <span>{projectFiles.length}</span></summary>{fileList(projectFiles, "Existing media")}</details> : null}
        {!files.length && !sequence.length && !timeline ? <div className={styles.empty}><GitCompareArrows size={28} /><h3>Your media, ready to review</h3><p>Upload a source or ask the agent to create something. Files appear here, with edit plans shown as numbered changes.</p></div> : null}
      </> : <>
        <div className={styles.heading}><div><h2>Source & result</h2><p>Compare your current media with a created version.</p></div></div>
        <div className={styles.viewers}>
          <Viewer label="Source / current" files={files} value={source} startTime={sourceTime} onChange={(value) => { setSourceId(value); setSourceTime(undefined); }} empty="Select a canvas clip or choose source media." />
          <Viewer label="Created result" files={files} value={result} startTime={resultTime} onChange={(value) => { setResultId(value); setResultTime(undefined); }} empty="No rendered result linked to this selection. Choose media to compare." />
        </div>
        <p className={styles.note}>Each viewer has independent playback controls. Choose any two versions to compare.</p>
      </>}
    </div>
  </aside>;
}
