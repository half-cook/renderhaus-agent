"use client";

import { SignOutButton } from "@clerk/nextjs";
import { ChevronDown, Ellipsis, Film, LayoutGrid, PanelBottom, Redo2, Share2, Sparkles, Undo2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ExportSheet } from "@/components/rh/ExportSheet";
import { Avatar } from "@/components/rh/AppNav";
import { fetchAccount } from "@/lib/api";
import { useClerkConfigured } from "@/components/StudioAuth";
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

export function CanvasHeader({ navigationBusy, onBusyChange }: {
  navigationBusy: boolean;
  onBusyChange: (busy: boolean) => void;
}) {
  const agentOpen = useCanvasStore((state) => state.agentOpen);
  const timelineOpen = useCanvasStore((state) => state.timelineOpen);
  const setWorkspaceView = useCanvasStore((state) => state.setWorkspaceView);
  const timelineDockOpen = useCanvasStore((state) => state.timelineDockOpen);
  const setTimelineDockOpen = useCanvasStore((state) => state.setTimelineDockOpen);
  const [accountName, setAccountName] = useState("");
  useEffect(() => {
    let cancelled = false;
    void fetchAccount().then((account) => { if (!cancelled && account.display_name) setAccountName(account.display_name); }).catch(() => undefined);
    return () => { cancelled = true; };
  }, []);
  const clerkConfigured = useClerkConfigured();
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
  const duplicateSelected = useCanvasStore((state) => state.duplicateSelected);
  const deleteSelected = useCanvasStore((state) => state.deleteSelected);
  const arrangeSequence = useCanvasStore((state) => state.arrangeSequence);
  const [menu, setMenu] = useState<"project" | "status" | "share" | "more" | null>(null);
  const headerRef = useRef<HTMLElement>(null);
  const navigating = useRef(false);
  const queued =
    queueSize(nodes) +
    executions.filter(
      (execution) =>
        execution.projectId === projectId &&
        ["queued", "running", "pending"].includes(execution.status.toLowerCase()),
    ).length;
  const hasSelection = selectedNodeIds.length > 0;
  const hasSequence = approvedSequence(nodes).length > 0;

  const navigate = async (action: () => Promise<void>) => {
    if (navigationBusy || navigating.current) return;
    navigating.current = true;
    onBusyChange(true);
    setMenu(null);
    try { await action(); }
    finally { navigating.current = false; onBusyChange(false); }
  };

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


  return (
    <header className="chrome-header rh-canvas-header" ref={headerRef}>
      <div className="header-left">
        <Link href="/home" className="rh-brand" aria-label="Renderhaus home">
          <span className="rh-mark" aria-hidden="true" />
          <span className="rh-wordmark">Renderhaus</span>
        </Link>
        <div className="header-menu-wrap">
          <button
            className="project-switcher"
            type="button"
            aria-haspopup="listbox"
            disabled={navigationBusy}
            aria-expanded={menu === "project"}
            onClick={() => setMenu(menu === "project" ? null : "project")}
          >
            <span className="project-name-display">{projectName || "Untitled"}</span>
            {projectId.startsWith("demo-") ? <span className="rh-chip rh-chip-mono">DEMO</span> : null}
            <ChevronDown size={16} />
          </button>
          {menu === "project" ? (
            <div className="popover project-pop">
              <label className="field">
                <span>Project name</span>
                <input
                  value={projectName}
                  aria-label="Project name"
                  disabled={navigationBusy}
                  onChange={(event) => setProjectName(event.target.value)}
                  onClick={(event) => event.stopPropagation()}
                />
              </label>
              {projects.map((project) => (
                <button
                  key={project.id}
                  type="button"
                  disabled={navigationBusy}
                  className={project.id === projectId ? "active" : ""}
                  onClick={() => void navigate(() => switchProject(project.id))}
                >
                  {project.name}
                </button>
              ))}
              <button
                type="button"
                disabled={navigationBusy}
                onClick={() => void navigate(createProject)}
              >
                New project
              </button>
            </div>
          ) : null}
        </div>
      </div>
      <nav className="workspace-tabs" aria-label="Workspace">
        <button type="button" aria-pressed={!agentOpen && !timelineOpen} onClick={() => setWorkspaceView("canvas")}><LayoutGrid size={14} aria-hidden="true" />Canvas</button>
        <button type="button" aria-pressed={agentOpen} onClick={() => setWorkspaceView("agent")}><Sparkles size={14} aria-hidden="true" />Agent</button>
        <button type="button" aria-pressed={timelineOpen} onClick={() => setWorkspaceView("timeline")}><Film size={14} aria-hidden="true" />Timeline</button>
      </nav>
      <div className="header-right">
        <button className="icon-btn" type="button" aria-label="Undo" disabled={past.length === 0} onClick={undo}>
          <Undo2 size={16} />
        </button>
        <button className="icon-btn" type="button" aria-label="Redo" disabled={future.length === 0} onClick={redo}>
          <Redo2 size={16} />
        </button>
        <button className="icon-btn" type="button" aria-label="Timeline dock" aria-pressed={timelineDockOpen} onClick={() => setTimelineDockOpen(!timelineDockOpen)}>
          <PanelBottom size={16} />
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
            <span className={`rh-dot ${queued > 0 ? "rh-dot-run" : "rh-dot-ok"}`} aria-hidden="true" />{queued > 0 ? `${queued} running` : "Queue idle"}
          </button>
          {menu === "status" ? (
            <div className="popover status-pop">
              {loadError ? <p>{loadError}. Is the API running?</p> : <p>Connected to local tools.</p>}
              {status
                ? Object.entries(status.dry_run).map(([id, dry]) => (
                    <p key={id}>
                      Studio tools: {dry ? "dry run" : "live"}
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
        <ExportSheet />
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
        <AccountBalance refreshKey={queued} />
        <ThemeToggle />
        {clerkConfigured ? (
          <SignOutButton redirectUrl="/">
            <button className="rh-avatar-btn" type="button" aria-label="Sign out"><Avatar name={accountName} /></button>
          </SignOutButton>
        ) : <Avatar name={accountName} />}
      </div>
    </header>
  );
}
