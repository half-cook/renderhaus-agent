"use client";

import { ChevronDown, Ellipsis, Redo2, Share2, Undo2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { LogoMark } from "@/components/Logo";
import { queueSize, useCanvasStore } from "@/lib/canvas/store";
import { approvedSequence } from "@/lib/canvas/story";
import type { StudioAsset } from "@/lib/types";
import { AccountBalance } from "./AccountBalance";
import { AssetDownloadLink } from "./AssetMedia";
import { ThemeToggle } from "./ThemeToggle";

function executionStatusClass(status: string): string {
  if (["error", "failed", "cancelled", "canceled"].includes(status)) return "failed";
  if (["queued", "running", "pending"].includes(status)) return "running";
  return "completed";
}

function ExecutionDownload({ asset }: { asset?: StudioAsset }) {
  if (!asset) return null;
  return (
    <AssetDownloadLink asset={asset} ariaLabel={`Download ${asset.filename}`}>
      Result
    </AssetDownloadLink>
  );
}

export function CanvasHeader() {
  const projectName = useCanvasStore((state) => state.projectName);
  const projects = useCanvasStore((state) => state.projects);
  const projectId = useCanvasStore((state) => state.projectId);
  const status = useCanvasStore((state) => state.status);
  const loadError = useCanvasStore((state) => state.loadError);
  const nodes = useCanvasStore((state) => state.nodes);
  const executions = useCanvasStore((state) => state.executions);
  const refreshExecutions = useCanvasStore((state) => state.refreshExecutions);
  const selectedNodeIds = useCanvasStore((state) => state.selectedNodeIds);
  const past = useCanvasStore((state) => state.past);
  const future = useCanvasStore((state) => state.future);
  const setProjectName = useCanvasStore((state) => state.setProjectName);
  const switchProject = useCanvasStore((state) => state.switchProject);
  const createProject = useCanvasStore((state) => state.createProject);
  const undo = useCanvasStore((state) => state.undo);
  const redo = useCanvasStore((state) => state.redo);
  const persist = useCanvasStore((state) => state.persist);
  const duplicateSelected = useCanvasStore((state) => state.duplicateSelected);
  const deleteSelected = useCanvasStore((state) => state.deleteSelected);
  const arrangeSequence = useCanvasStore((state) => state.arrangeSequence);
  const [menu, setMenu] = useState<"project" | "status" | "share" | "more" | null>(null);
  const [exported, setExported] = useState(false);
  const fileRef = useRef<HTMLAnchorElement>(null);
  const headerRef = useRef<HTMLElement>(null);
  const queued = queueSize(nodes);
  const hasSelection = selectedNodeIds.length > 0;
  const hasSequence = approvedSequence(nodes).length > 0;

  useEffect(() => {
    if (!menu) {
      return;
    }
    const onPointerDown = (event: PointerEvent) => {
      if (headerRef.current && !headerRef.current.contains(event.target as Node)) {
        setMenu(null);
      }
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, [menu]);

  const exportGraph = () => {
    persist();
    const blob = new Blob(
      [JSON.stringify({ projectName, nodes, edges: useCanvasStore.getState().edges }, null, 2)],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob);
    const link = fileRef.current;
    if (!link) {
      return;
    }
    link.href = url;
    link.download = `${projectName.replaceAll(" ", "-").toLowerCase() || "renderhaus"}.json`;
    link.click();
    URL.revokeObjectURL(url);
    setExported(true);
    window.setTimeout(() => setExported(false), 2000);
  };

  return (
    <header className="chrome-header" ref={headerRef}>
      <div className="header-left">
        <div className="wordmark">
          <LogoMark size={16} />
          Renderhaus
        </div>
        <div className="header-menu-wrap">
          <button
            className="project-switcher"
            type="button"
            aria-haspopup="listbox"
            aria-expanded={menu === "project"}
            onClick={() => setMenu(menu === "project" ? null : "project")}
          >
            <span className="project-name-display">{projectName || "Untitled"}</span>
            <ChevronDown size={16} />
          </button>
          {menu === "project" ? (
            <div className="popover project-pop">
              <label className="field">
                <span>Project name</span>
                <input
                  value={projectName}
                  aria-label="Project name"
                  onChange={(event) => setProjectName(event.target.value)}
                  onClick={(event) => event.stopPropagation()}
                />
              </label>
              {projects.map((project) => (
                <button
                  key={project.id}
                  type="button"
                  className={project.id === projectId ? "active" : ""}
                  onClick={() => {
                    switchProject(project.id);
                    setMenu(null);
                  }}
                >
                  {project.name}
                </button>
              ))}
              <button
                type="button"
                onClick={() => {
                  createProject();
                  setMenu(null);
                }}
              >
                New project
              </button>
            </div>
          ) : null}
        </div>
      </div>
      <div className="header-right">
        <AccountBalance refreshKey={queued} />
        <ThemeToggle />
        <button className="icon-btn" type="button" aria-label="Undo" disabled={past.length === 0} onClick={undo}>
          <Undo2 size={16} />
        </button>
        <button className="icon-btn" type="button" aria-label="Redo" disabled={future.length === 0} onClick={redo}>
          <Redo2 size={16} />
        </button>
        <div className="header-menu-wrap">
          <button
            className="queue-chip"
            type="button"
            aria-expanded={menu === "status"}
            onClick={() => {
              const opening = menu !== "status";
              setMenu(opening ? "status" : null);
              if (opening) {
                void refreshExecutions();
              }
            }}
          >
            {queued > 0 ? `${queued} running` : "Queue idle"}
          </button>
          {menu === "status" ? (
            <div className="popover status-pop">
              {loadError ? <p>{loadError}. Is the API running?</p> : <p>Connected to local tools.</p>}
              {status
                ? Object.entries(status.dry_run).map(([id, dry]) => (
                    <p key={id}>
                      {id.replaceAll("_", " ")}: {dry ? "dry run" : "live"}
                    </p>
                  ))
                : null}
              {executions.length > 0 ? (
                <div className="execution-list" aria-label="Recent agent jobs">
                  <strong>Recent agent jobs</strong>
                  {executions.slice(0, 5).map((execution) => (
                    <div className="execution-item" key={execution.jobId}>
                      <span
                        className={`agent-tool-status ${executionStatusClass(execution.status)}`}
                        aria-hidden="true"
                      />
                      <span>
                        <b>{execution.title || execution.status}</b>
                        <small>{execution.message}</small>
                      </span>
                      <ExecutionDownload asset={execution.primaryAsset} />
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="header-menu-wrap">
          <button
            className="text-btn"
            type="button"
            aria-expanded={menu === "share"}
            onClick={() => setMenu(menu === "share" ? null : "share")}
          >
            <Share2 size={14} />
            Share
          </button>
          {menu === "share" ? (
            <div className="popover status-pop">
              <p>Share is unavailable in the local studio. Cloud sharing is not connected yet.</p>
            </div>
          ) : null}
        </div>
        <button className="text-btn" type="button" aria-live="polite" onClick={exportGraph}>
          {exported ? "Exported" : "Export"}
        </button>
        <div className="header-menu-wrap">
          <button
            className="icon-btn"
            type="button"
            aria-label="More"
            aria-expanded={menu === "more"}
            onClick={() => setMenu(menu === "more" ? null : "more")}
          >
            <Ellipsis size={16} />
          </button>
          {menu === "more" ? (
            <div className="popover">
              <button
                type="button"
                disabled={!hasSequence}
                title={hasSequence ? "Arrange approved scenes left to right" : "Approve a scene to arrange the sequence"}
                onClick={() => {
                  arrangeSequence();
                  setMenu(null);
                }}
              >
                Arrange sequence
              </button>
              <button
                type="button"
                disabled={!hasSelection}
                title={hasSelection ? "Duplicate selected nodes" : "Select a node to duplicate"}
                onClick={() => {
                  duplicateSelected();
                  setMenu(null);
                }}
              >
                Duplicate
              </button>
              <button
                type="button"
                disabled={!hasSelection}
                title={hasSelection ? "Delete selected nodes" : "Select a node to delete"}
                onClick={() => {
                  deleteSelected();
                  setMenu(null);
                }}
              >
                Delete selected
              </button>
            </div>
          ) : null}
        </div>
      </div>
      <a ref={fileRef} hidden />
    </header>
  );
}
