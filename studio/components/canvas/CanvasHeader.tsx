"use client";

import { ChevronDown, Ellipsis, Redo2, Share2, Undo2 } from "lucide-react";
import { useRef, useState } from "react";
import { queueSize, useCanvasStore } from "@/lib/canvas/store";

export function CanvasHeader() {
  const projectName = useCanvasStore((state) => state.projectName);
  const projects = useCanvasStore((state) => state.projects);
  const projectId = useCanvasStore((state) => state.projectId);
  const status = useCanvasStore((state) => state.status);
  const loadError = useCanvasStore((state) => state.loadError);
  const nodes = useCanvasStore((state) => state.nodes);
  const past = useCanvasStore((state) => state.past);
  const future = useCanvasStore((state) => state.future);
  const setProjectName = useCanvasStore((state) => state.setProjectName);
  const switchProject = useCanvasStore((state) => state.switchProject);
  const createProject = useCanvasStore((state) => state.createProject);
  const undo = useCanvasStore((state) => state.undo);
  const redo = useCanvasStore((state) => state.redo);
  const persist = useCanvasStore((state) => state.persist);
  const [menu, setMenu] = useState<"project" | "status" | "more" | null>(null);
  const fileRef = useRef<HTMLAnchorElement>(null);
  const queued = queueSize(nodes);

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
  };

  return (
    <header className="chrome-header">
      <div className="header-left">
        <div className="wordmark">Renderhaus</div>
        <input
          className="project-name"
          value={projectName}
          aria-label="Project name"
          onChange={(event) => setProjectName(event.target.value)}
        />
        <div className="header-menu-wrap">
          <button
            className="icon-btn"
            type="button"
            aria-label="Switch project"
            onClick={() => setMenu(menu === "project" ? null : "project")}
          >
            <ChevronDown size={16} />
          </button>
          {menu === "project" ? (
            <div className="popover">
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
              <button type="button" onClick={() => { createProject(); setMenu(null); }}>
                New project
              </button>
            </div>
          ) : null}
        </div>
      </div>
      <div className="header-right">
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
            onClick={() => setMenu(menu === "status" ? null : "status")}
          >
            {queued > 0 ? `${queued} running` : "Queue idle"}
          </button>
          {menu === "status" ? (
            <div className="popover status-pop">
              {loadError ? <p>{loadError}. Is the API running?</p> : <p>Connected to local tools.</p>}
              {status
                ? Object.entries(status.dry_run).map(([id, dry]) => (
                    <p key={id}>
                      {id}: {dry ? "dry run" : "live"}
                    </p>
                  ))
                : null}
            </div>
          ) : null}
        </div>
        <button className="text-btn" type="button" disabled title="Sharing is not available locally">
          <Share2 size={14} />
          Share
        </button>
        <button className="text-btn" type="button" onClick={exportGraph}>
          Export
        </button>
        <div className="header-menu-wrap">
          <button className="icon-btn" type="button" aria-label="More" onClick={() => setMenu(menu === "more" ? null : "more")}>
            <Ellipsis size={16} />
          </button>
          {menu === "more" ? (
            <div className="popover">
              <button type="button" onClick={() => { useCanvasStore.getState().duplicateSelected(); setMenu(null); }}>
                Duplicate
              </button>
              <button type="button" onClick={() => { useCanvasStore.getState().deleteSelected(); setMenu(null); }}>
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
