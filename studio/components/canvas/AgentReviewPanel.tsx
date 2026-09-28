"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { Download, FileAudio, FileImage, FileVideo, Film, GitCompareArrows, Play, Rows3 } from "lucide-react";
import { useCanvasStore } from "@/lib/canvas/store";
import {
  diffReviewLines, latestTimelineReview, reviewFiles, sequenceReviewLines,
  type DiffLine, type ReviewFile,
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

function Viewer({ label, files, value, onChange, empty }: {
  label: string; files: ReviewFile[]; value: string;
  onChange: (value: string) => void; empty: string;
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
      {asset ? <AssetMedia key={asset.versionId} asset={asset} alt={`${label}: ${asset.filename}`} className={styles.media} controls /> : <div className={styles.viewerEmpty}><Film size={22} /><p>{empty}</p></div>}
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
  const [sourceId, setSourceId] = useState("");
  const [resultId, setResultId] = useState("");
  const id = useId();
  const files = useMemo(() => reviewFiles(nodes, executions), [nodes, executions]);
  const assets = useMemo(() => files.map((file) => file.asset), [files]);
  const timeline = useMemo(() => latestTimelineReview(executions, assets), [executions, assets]);
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

  useEffect(() => { setSourceId(""); setResultId(""); }, [projectId, conversationId]);
  useEffect(() => { if (selectedAsset) setSourceId(selectedAsset.versionId); }, [selectedAsset?.versionId]);

  const source = files.some((file) => file.asset.versionId === sourceId) ? sourceId : defaultSource?.versionId || "";
  const result = files.some((file) => file.asset.versionId === resultId) ? resultId : defaultResult?.versionId || "";
  const taskFiles = files.filter((file) => file.currentTask);
  const projectFiles = files.filter((file) => !file.currentTask);

  function preview(file: ReviewFile) {
    if (file.currentTask) setResultId(file.asset.versionId);
    else setSourceId(file.asset.versionId);
    setTab("preview");
  }

  function fileList(items: ReviewFile[], title: string) {
    if (!items.length) return null;
    return <section className={styles.fileGroup} aria-label={title}>
      <h3>{title}<span>{items.length}</span></h3>
      {items.map((file) => <details className={styles.file} key={file.asset.versionId}>
        <summary><FileIcon kind={file.asset.kind} /><span title={file.asset.filename}>{file.asset.filename}</span><small className={file.currentTask ? styles.created : ""}>{file.currentTask ? "Created" : file.origin}</small></summary>
        <div className={styles.fileDetails}>
          <p>{file.title || file.asset.filename}</p>
          <span>{file.asset.kind.toUpperCase()} · Version {file.asset.versionId.slice(0, 8)}</span>
          <button type="button" onClick={() => preview(file)}><Play size={13} />Open in preview</button>
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
        <div className={styles.heading}><div><h2>Review your work</h2><p>Media files and the edits that shape them.</p></div><span className={styles.count}>{files.length} files</span></div>
        {timeline ? <section className={styles.editSection}>
          <div className={styles.sectionTitle}><FileVideo size={14} /><h3>{timeline.outputFilename || timeline.title}</h3></div>
          <p className={styles.note}>{timeline.outputFilename ? `${timeline.title} · ` : ""}Run {timeline.status.replaceAll("_", " ")} · saved edit plan{["failed", "error", "rejected", "cancelled", "canceled"].includes(timeline.requestStatus.toLowerCase()) ? ` · Render request ${timeline.requestStatus}` : ""}</p>
          <p className={styles.note}>{timeline.hasPrevious ? "Latest recorded edit plan compared with the previous plan in this task." : "First recorded edit plan in this task. No earlier plan to compare."}</p>
          <Diff lines={timeline.lines} />
        </section> : null}
        {sequence.length ? <details className={styles.editSection} open={!timeline}>
          <summary className={styles.sectionTitle}><Rows3 size={14} /><h3>Approved sequence</h3></summary>
          <p className={styles.note}>{previous ? "Current canvas compared with its last undo snapshot." : "Current canvas sequence. No earlier snapshot to compare."}</p>
          <Diff lines={sequence} />
        </details> : null}
        {fileList(taskFiles, "Created in this task")}
        {fileList(projectFiles, "Project media")}
        {!files.length && !sequence.length && !timeline ? <div className={styles.empty}><GitCompareArrows size={28} /><h3>Your media, ready to review</h3><p>Upload a source or ask the agent to create something. Files appear here, with edit plans shown as numbered changes.</p></div> : null}
      </> : <>
        <div className={styles.heading}><div><h2>Source & result</h2><p>Compare your current media with a created version.</p></div></div>
        <div className={styles.viewers}>
          <Viewer label="Source / current" files={files} value={source} onChange={setSourceId} empty="Select a canvas clip or choose source media." />
          <Viewer label="Created result" files={files} value={result} onChange={setResultId} empty="Completed task media will appear here." />
        </div>
        <p className={styles.note}>Each viewer has independent playback controls. Choose any two versions to compare.</p>
      </>}
    </div>
  </aside>;
}
