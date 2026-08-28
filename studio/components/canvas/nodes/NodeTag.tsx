"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useStore } from "@xyflow/react";
import { statusLabel } from "@/lib/canvas/store";
import type { JobStatus } from "@/lib/canvas/types";

const selectZoom = (state: { transform: [number, number, number] }) => state.transform[2];

function showStatus(status: JobStatus): boolean {
  switch (status) {
    case "queued":
    case "running":
    case "failed":
      return true;
    case "idle":
    case "completed":
      return false;
    default: {
      const exhaustive: never = status;
      return exhaustive;
    }
  }
}

type Props = {
  title: string;
  status: JobStatus;
  selected?: boolean;
  badge?: string;
  onRename: (title: string) => void;
};

export function NodeTag({ title, status, selected, badge, onRename }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  const inputRef = useRef<HTMLInputElement>(null);
  const zoom = useStore(selectZoom);

  useEffect(() => {
    setDraft(title);
  }, [title]);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  const commit = () => {
    const next = draft.trim();
    onRename(next || title);
    setDraft(next || title);
    setEditing(false);
  };

  const cancel = () => {
    setDraft(title);
    setEditing(false);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      commit();
    }
    if (event.key === "Escape") {
      event.preventDefault();
      cancel();
    }
  };

  const showBadge = Boolean(badge) && badge?.trim().toLowerCase() !== title.trim().toLowerCase();

  return (
    <div
      className={`node-tag ${selected ? "selected" : ""}`}
      style={{ transform: `scale(${1 / zoom})`, transformOrigin: "left bottom" }}
    >
      {showBadge ? <span className="node-tag-badge">{badge}</span> : null}
      {editing ? (
        <input
          ref={inputRef}
          className="nodrag nopan nowheel node-tag-input"
          value={draft}
          aria-label="Node title"
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={onKeyDown}
        />
      ) : (
        <button
          className="node-tag-name"
          type="button"
          title="Double click to rename"
          onDoubleClick={(event) => {
            event.stopPropagation();
            setEditing(true);
          }}
        >
          {title || "Untitled"}
        </button>
      )}
      {showStatus(status) ? <span className={`node-status ${status}`}>{statusLabel(status)}</span> : null}
    </div>
  );
}
