"use client";

export function UploadError({ message, onDismiss }: { message: string | null; onDismiss: () => void }) {
  if (!message) return null;
  return (
    <div className="upload-error connection-hint" role="alert">
      <p className="agent-response-error">{message}</p>
      <button type="button" onClick={onDismiss} aria-label="Dismiss upload error">Dismiss</button>
    </div>
  );
}
