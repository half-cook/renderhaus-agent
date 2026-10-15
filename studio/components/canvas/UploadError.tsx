"use client";

export function UploadError({ message, onDismiss, onRetry, progress }: {
  message: string | null;
  onDismiss: () => void;
  onRetry?: (() => void) | null;
  progress?: { filename: string; loaded: number; total: number } | null;
}) {
  if (!message && progress) {
    const pct = progress.total ? Math.floor((progress.loaded / progress.total) * 100) : 0;
    return (
      <div className="upload-error connection-hint" role="status" data-shot="upload-progress">
        <p>Uploading {progress.filename} · {pct}%</p>
      </div>
    );
  }
  if (!message) return null;
  return (
    <div className="upload-error connection-hint" role="alert">
      <p className="agent-response-error">{message}</p>
      {onRetry ? <button type="button" onClick={onRetry}>Try again</button> : null}
      <button type="button" onClick={onDismiss} aria-label="Dismiss upload error">Dismiss</button>
    </div>
  );
}
