"use client";

import { FileVideo, Pause, RotateCw, X } from "lucide-react";

/** Upload progress row for the resumable chunked upload (spec 4.12.5, mockup 50). Never shows a price: uploading spends no credit. */
export type UploadRowState =
  | { kind: "uploading"; name: string; confirmedBytes: number; totalBytes: number; secondsLeft?: number }
  | { kind: "resuming"; name: string; confirmedBytes: number; totalBytes: number; chunk: number; chunks: number }
  | { kind: "failed"; name: string; confirmedBytes: number; totalBytes: number }
  | { kind: "waiting"; name: string; totalBytes: number }
  | { kind: "done"; name: string; totalBytes: number };

export function formatBytes(bytes: number): string {
  const gb = bytes / 1e9;
  if (gb >= 0.1) return `${gb.toFixed(gb >= 10 ? 1 : 2).replace(/\.?0+$/, (m) => (m.startsWith(".") ? "" : m))} GB`;
  return `${Math.max(1, Math.round(bytes / 1e6))} MB`;
}

function gb(bytes: number): string {
  return `${(bytes / 1e9).toFixed(2)} GB`;
}

export function UploadRow({ state, onPause, onCancel, onRetry }: { state: UploadRowState; onPause?: () => void; onCancel?: () => void; onRetry?: () => void }) {
  const confirmed = "confirmedBytes" in state ? state.confirmedBytes : state.kind === "done" ? state.totalBytes : 0;
  const pct = state.totalBytes ? Math.min(100, Math.floor((confirmed / state.totalBytes) * 100)) : 0;
  const status = state.kind === "uploading" ? `${pct}%` : state.kind === "resuming" ? "Resuming…" : state.kind === "failed" ? "Upload failed" : state.kind === "waiting" ? "Waiting" : "Uploaded";
  const detail = state.kind === "uploading"
    ? `${formatBytes(state.confirmedBytes)} of ${formatBytes(state.totalBytes)}${state.secondsLeft != null ? ` · ${Math.max(1, Math.round(state.secondsLeft / 60))} min left` : ""}`
    : state.kind === "resuming" ? `Connection dropped. Picking up from ${gb(state.confirmedBytes)} of ${formatBytes(state.totalBytes)}, chunk ${state.chunk} of ${state.chunks}`
    : state.kind === "failed" ? `Stopped at ${gb(state.confirmedBytes)} of ${formatBytes(state.totalBytes)}. Retry continues from there, nothing is lost.`
    : state.kind === "waiting" ? `${formatBytes(state.totalBytes)} · starts when the current file finishes`
    : formatBytes(state.totalBytes);
  return (
    <div className="rh-upload-row" data-state={state.kind} role="group" aria-label={`${state.name}: ${status}`}>
      <FileVideo size={18} aria-hidden="true" className="rh-fg3" />
      <div className="rh-upload-main">
        <div className="rh-upload-top"><span className="rh-upload-name">{state.name}</span><span className="rh-upload-status" aria-live="polite">{status}</span></div>
        <div className="rh-upload-bar" data-state={state.kind}><b style={{ width: `${state.kind === "waiting" ? 0 : pct}%` }} /></div>
        <div className="rh-upload-detail rh-mono">{detail}</div>
      </div>
      <div className="rh-upload-actions">
        {state.kind === "uploading" ? <><button type="button" className="rh-btn rh-btn-quiet rh-btn-sm" aria-label="Pause upload" onClick={onPause}><Pause size={14} /></button><button type="button" className="rh-btn rh-btn-quiet rh-btn-sm" aria-label="Cancel upload" onClick={onCancel}><X size={14} /></button></> : null}
        {state.kind === "resuming" || state.kind === "waiting" ? <button type="button" className="rh-btn rh-btn-quiet rh-btn-sm" aria-label="Cancel upload" onClick={onCancel}><X size={14} /></button> : null}
        {state.kind === "failed" ? <button type="button" className="rh-btn rh-btn-sm" onClick={onRetry}><RotateCw size={13} aria-hidden="true" />Retry</button> : null}
      </div>
    </div>
  );
}
