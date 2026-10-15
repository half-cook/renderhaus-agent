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
import { SpendLedger } from "@/components/rh/RunBilling";
import { spendSummary } from "@/lib/rh/approval-model";
import { TimelineMini } from "@/components/timeline/TimelineMini";
import { ChangesPanel } from "@/components/changes/ChangesPanel";
import { useChangesReview } from "@/components/changes/ChangesReview";
import { useChangesStore } from "@/lib/rh/changes-store";

function FileIcon({ kind }: { kind: StudioAsset["kind"] }) {
  const Icon = kind === "video" ? FileVideo : kind === "audio" ? FileAudio : FileImage;
  return <Icon size={15} aria-hidden="true" />;
}

function Diff({ lines }: { lines: DiffLine[] }) {
  return <div className={`${styles.diff} rh-review-diff`} aria-label="Edit comparison">
    {lines.map((line) => <div key={`${line.id}-${line.change}`} className={`${styles.diffLine} ${styles[line.change]}`}>
      <span title="Previous line">{line.before ?? ""}</span>
      <span title="Current line">{line.after ?? ""}</span>
      <span title={line.change}>{line.change === "added" ? "+" : line.change === "removed" ? "−" : " "}</span>
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
  return <span className={`${styles.thumbnail} rh-review-thumbnail`}>
    {asset && asset.kind !== "audio"
      ? <AssetMedia key={`${asset.versionId}-${start ?? 1}`} asset={asset} alt={asset.filename} className={`${styles.thumbnailMedia} rh-review-thumbnail-media`} muted preload="metadata" startTime={start ?? 1} />
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
    <div className={`${styles.segmentLine} rh-review-segment-line`}>
      <time aria-label="Previous time">{change !== "added" && before ? timecode(before.start) : ""}</time>
      <time aria-label="Current time">{change !== "removed" && after ? timecode(after.start) : ""}</time>
      <span className={`${styles.sign} rh-review-sign`} aria-label={change}>{change === "added" ? "+" : change === "removed" ? "−" : ""}</span>
      <button className={`${styles.segmentContent} rh-review-segment-content`} type="button" disabled={!canPreview} onClick={() => onPreview(row)} aria-label={`Preview ${change === "context" ? "" : `${change} `}${label} at ${timecode(segment.start)}`}>
        <Thumbnail asset={thumbnailAsset} kind={segment.kind} start={thumbnailTime} />
        <span className={`${styles.segmentText} rh-review-segment-text`}>
          <span className={`${styles.segmentTitle} rh-review-segment-title`}><small>{segment.track}</small><strong title={label}>{label}</strong><Play size={11} aria-hidden="true" /></span>
          <span className={`${styles.segmentMeta} rh-review-segment-meta`}>
            <span className={changedFields.includes("duration") && change !== "context" ? styles.changedValue : ""}>{segment.duration === undefined ? "Duration unknown" : `${segment.duration}s`}</span>
            <span> · </span><span className={`${styles.range} rh-review-range`}>{timecode(segment.start)}–{timecode(segment.end)}</span>
          </span>
          {segment.kind !== "text" ? <span className={`${styles.sourceName} ${changedFields.includes("source") && change !== "context" ? styles.changedValue : ""}`} title={segment.source}>{segment.source}</span> : null}
        </span>
      </button>
    </div>
    {change !== "removed" && keys.length > 0 ? <details className={`${styles.properties} rh-review-properties`}>
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
  return <div className={`${styles.timelineDiff} rh-review-timeline-diff`} aria-label="Timeline edit comparison">
    <div className={`${styles.diffHead} rh-review-diff-head`}><span>Old</span><span>New</span><span /><span>Timeline segments</span></div>
    {groups.map((group, index) => {
      const before = range(group.rows.filter((row) => row.change !== "added").map((row) => row.before));
      const after = range(group.rows.filter((row) => row.change !== "removed").map((row) => row.after));
      if (group.context && group.rows.length > 4) return <div key={index}>
        {renderRows(group.rows.slice(0, 1))}
        <details className={`${styles.contextFold} rh-review-context-fold`}>
          <summary><ChevronDown size={13} />{group.rows.length - 2} {hasPrevious ? "unchanged" : "more"} segments</summary>
          {renderRows(group.rows.slice(1, -1))}
        </details>
        {renderRows(group.rows.slice(-1))}
      </div>;
      return <div key={index}>
        {!group.context ? <div className={`${styles.hunk} rh-review-hunk`}><span>@@ {before === after ? after : `${before} → ${after}`} @@</span><span>{group.rows.some((row) => row.before && row.after) ? "Edited segments" : group.rows[0].change === "added" ? "Added segments" : "Removed segments"}</span></div> : null}
        {renderRows(group.rows)}
      </div>;
    })}
    {hasPrevious && rows.every((row) => row.change === "context") ? <p className={`${styles.baselineNote} rh-review-baseline-note`}>No segment changes between these saved plans.</p> : null}
  </div>;
}

function Viewer({ label, files, value, onChange, empty, startTime }: {
  label: string; files: ReviewFile[]; value: string;
  onChange: (value: string) => void; empty: string; startTime?: number;
}) {
  const asset = files.find((file) => file.asset.versionId === value)?.asset;
  return <section className={`${styles.viewer} rh-review-viewer`} aria-label={`${label} viewer`}>
    <header><span>{label}</span>{asset ? <AssetDownloadLink asset={asset} className={`${styles.iconButton} rh-review-icon-button`} ariaLabel={`Download ${label.toLowerCase()}`}><Download size={14} /></AssetDownloadLink> : null}</header>
    <label className={`${styles.selector} rh-review-selector`}>
      <span className={`${styles.srOnly} rh-review-sr-only`}>{label} media</span>
      <select value={asset?.versionId || ""} onChange={(event) => onChange(event.target.value)}>
        <option value="">Choose media</option>
        {files.map((file) => <option key={file.asset.versionId} value={file.asset.versionId}>{file.asset.filename} · {file.asset.versionId.slice(0, 8)}{file.currentTask ? " · This task" : ""}</option>)}
      </select>
    </label>
    <div className={`${styles.screen} rh-review-screen`} data-kind={asset?.kind}>
      {asset ? <AssetMedia key={`${asset.versionId}-${startTime ?? 0}`} asset={asset} alt={`${label}: ${asset.filename}`} className={`${styles.media} rh-review-media`} controls startTime={startTime} /> : <div className={`${styles.viewerEmpty} rh-review-viewer-empty`}><Film size={22} /><p>{empty}</p></div>}
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
  const [legacyTab, setLegacyTab] = useState<"changes" | "preview" | "timeline">(() => useCanvasStore.getState().executions.some((execution) => execution.approvals.length || execution.receipt || execution.pausedCap) ? "preview" : "changes");
  const changesDocument = useChangesStore((state) => state.document);
  const changesTab = useChangesStore((state) => state.tab);
  const selectedN = useChangesStore((state) => state.selectedN);
  const changesBusy = useChangesStore((state) => state.busy);
  const changesError = useChangesStore((state) => state.error);
  const changesReview = useChangesReview();
  const tab = changesDocument ? changesTab : legacyTab;
  const setTab = (value: "changes" | "preview" | "timeline") => changesDocument ? useChangesStore.getState().setTab(value) : setLegacyTab(value);
  const spend = useMemo(() => spendSummary(executions), [executions]);
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
    return <section className={`${styles.fileGroup} rh-review-file-group`} aria-label={title}>
      <h3>{title}<span>{items.length}</span></h3>
      {items.map((file) => <details className={`${styles.file} rh-review-file`} key={file.asset.versionId}>
        <summary><ChevronDown size={12} className={`${styles.chevron} rh-review-chevron`} /><FileIcon kind={file.asset.kind} /><span title={file.asset.filename}>{file.title || file.asset.filename}</span><small className={file.currentTask ? styles.created : ""}>{file.currentTask ? "Created" : file.origin}</small></summary>
        <div className={`${styles.fileDetails} rh-review-file-details`}>
          <Thumbnail asset={file.asset} />
          <div><p>{file.asset.filename}</p>
          <span>{file.asset.kind.toUpperCase()} · Version {file.asset.versionId.slice(0, 8)}</span>
          <button type="button" onClick={() => preview(file)}><Play size={13} />Open in preview</button>
          </div>
        </div>
      </details>)}
    </section>;
  }

  return <aside className={`${styles.panel} rh-review-panel`} aria-label="Agent review" data-has-changes={!!changesDocument}>
    <div className={`${styles.tabs} rh-review-tabs`} role="tablist" aria-label="Review mode">
      {(changesDocument ? ["preview", "changes", "timeline"] as const : ["changes", "preview", "timeline"] as const).map((value) => <button
        type="button" key={value} id={`${id}-${value}`} role="tab" aria-selected={tab === value}
        aria-controls={`${id}-panel`} tabIndex={tab === value ? 0 : -1}
        onClick={() => setTab(value)} onKeyDown={(event) => {
          const order = changesDocument ? ["preview", "changes", "timeline"] as const : ["changes", "preview", "timeline"] as const;
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const at = order.indexOf(tab);
          const next = event.key === "Home" ? order[0] : event.key === "End" ? order[2] : order[(at + (event.key === "ArrowRight" ? 1 : 2)) % 3]!;
          setTab(next); document.getElementById(`${id}-${next}`)?.focus();
        }}>
        {value === "changes" ? <GitCompareArrows size={15} /> : value === "preview" ? <Play size={15} /> : <Film size={15} />}
        {value === "changes" ? "Changes" : value === "preview" ? "Preview" : "Timeline"}
        {value === "changes" && changesDocument ? <span className="rh-change-count">{changesDocument.changes.length}</span> : null}
      </button>)}
    </div>
    <div className={`${styles.content} rh-review-content`} id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${tab}`}>
      {!changesDocument && changesError ? <div className="rh-change-notice" role="alert"><p>{changesError}</p><button type="button" className="rh-btn rh-btn-sm" disabled={changesBusy} onClick={() => void useChangesStore.getState().load(projectId)}>Reload changes</button></div> : null}
      {tab === "changes" && changesDocument ? <ChangesPanel document={changesDocument} selectedN={selectedN ?? 0} busy={changesBusy} error={changesError} rowProps={changesReview.rowProps}
        onAcceptFree={() => void useChangesStore.getState().acceptFree()} onRejectAll={() => void useChangesStore.getState().rejectAll()} onRestore={async () => { await useChangesStore.getState().restore(); return !useChangesStore.getState().error; }} /> : tab === "changes" ? <>
        <div className={`${styles.heading} rh-review-heading`}><div><h2>Changes</h2><p>{timeline ? "Saved edit plans and task media." : "Media created in this task."}</p></div><span className={`${styles.count} rh-review-count`}>{files.filter((file) => file.currentTask).length} created</span></div>
        {timeline ? <>
          {timeline.comparisons.length ? <label className={`${styles.comparisonSelector} rh-review-comparison-selector`}>Compare with
            <select value={timeline.previousPlanId || ""} onChange={(event) => setPreviousPlanId(event.target.value || null)}>
              <option value="">No comparison · current plan</option>
              {timeline.comparisons.map((plan) => <option key={plan.id} value={plan.id}>{plan.label}</option>)}
            </select>
          </label> : null}
          <details className={`${styles.timelineFile} rh-review-timeline-file`} open key={`${conversationId}-${timeline.currentLabel}`}>
            <summary className={`${styles.timelineTitle} rh-review-timeline-title`}><ChevronDown size={13} /><FileVideo size={15} /><strong>{timeline.outputFilename || timeline.title}</strong>
              {timeline.hasPrevious ? <span className={`${styles.diffTotals} rh-review-diff-totals`}><b>+{timeline.rows.filter((row) => row.change === "added").length}</b><b>−{timeline.rows.filter((row) => row.change === "removed").length}</b></span> : <small>{timeline.comparisons.length ? "Current plan" : "First version"}</small>}
            </summary>
            <div className={`${styles.planSummary} rh-review-plan-summary`}>
              <span>{timeline.hasPrevious ? `${timeline.previousLabel} → ${timeline.currentLabel}` : timeline.currentLabel}</span>
              <span className={["failed", "error", "rejected", "cancelled", "canceled"].includes(timeline.requestStatus.toLowerCase()) || ["failed", "error"].includes(timeline.status) ? styles.failedStatus : ""}>Run {timeline.status.replaceAll("_", " ")}{["failed", "error", "rejected", "cancelled", "canceled"].includes(timeline.requestStatus.toLowerCase()) ? ` · Request ${timeline.requestStatus}` : ""}</span>
            </div>
            {!timeline.hasPrevious ? <p className={`${styles.baselineNote} rh-review-baseline-note`}>{timeline.comparisons.length ? "Current saved plan. Choose an earlier plan to compare." : "First saved edit plan. No earlier plan to compare."}</p> : null}
            <TimelineDiff rows={timeline.rows} hasPrevious={timeline.hasPrevious} outputAsset={timeline.outputAsset} previousOutputAsset={timeline.previousOutputAsset} onPreview={previewSegment} />
            {timeline.metadata.length ? <details className={`${styles.planSettings} rh-review-plan-settings`}><summary>Project settings{timeline.metadata.some((line) => line.change !== "context") ? " · changed" : ""}</summary><Diff lines={timeline.metadata} /></details> : null}
            {timeline.outputAsset ? <button type="button" className={`${styles.openOutput} rh-review-open-output`} onClick={() => { setResultId(timeline.outputAsset!.versionId); setResultTime(undefined); showPreview(); }}><Play size={12} />Open rendered video</button> : <p className={`${styles.baselineNote} rh-review-baseline-note`}>Saved instructions · no rendered video linked to this plan.</p>}
          </details>
        </> : null}
        {sequence.length ? <details className={`${styles.editSection} rh-review-edit-section`} open={!timeline}>
          <summary className={`${styles.sectionTitle} rh-review-section-title`}><Rows3 size={14} /><h3>Approved sequence</h3></summary>
          <p className={`${styles.note} rh-review-note`}>{previous ? "Current canvas compared with its last undo snapshot." : "Current canvas sequence. No earlier snapshot to compare."}</p>
          <Diff lines={sequence} />
        </details> : null}
        {fileList(taskFiles, "Created in this task")}
        {projectFiles.length ? <details className={`${styles.projectMedia} rh-review-project-media`}><summary>Project media <span>{projectFiles.length}</span></summary>{fileList(projectFiles, "Existing media")}</details> : null}
        {!files.length && !sequence.length && !timeline ? <div className={`${styles.empty} rh-review-empty`}><GitCompareArrows size={28} /><h3>Your media, ready to review</h3><p>Upload a source or ask the agent to create something. Files appear here, with edit plans shown as numbered changes.</p></div> : null}
      </> : tab === "timeline" ? <TimelineMini /> : <>
        <div className={`${styles.viewers} rh-review-viewers`}>
          <Viewer label="Preview" files={files} value={result || source} startTime={resultTime} onChange={(value) => { setResultId(value); setResultTime(undefined); }} empty="Select media to preview." />
          <details className="rh-review-compare"><summary>Compare with source</summary><Viewer label="Source / current" files={files} value={source} startTime={sourceTime} onChange={(value) => { setSourceId(value); setSourceTime(undefined); }} empty="Select a canvas clip or choose source media." /></details>
        </div>
      </>}
      {spend && (!changesDocument || tab !== "changes") ? <div className="rh-spend-dock"><SpendLedger rows={spend.rows} totalLabel={spend.totalLabel} totalCents={spend.totalCents} /></div> : null}
    </div>
    {changesReview.dialogs}
  </aside>;
}
