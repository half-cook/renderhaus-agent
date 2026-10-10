"use client";

import { BookOpen, ChevronDown, ChevronRight, Files, Folder, FolderPlus, MessageSquare, PanelLeft, PanelRight, Plus, Search, Sparkles, Unplug, Upload, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchStudioConversations, type StudioConversation } from "@/lib/api";
import { useCanvasStore } from "@/lib/canvas/store";
import { AssetMedia } from "./AssetMedia";
import { AgentDock } from "./AgentDock";
import { BetaCreditCard } from "@/components/rh/BetaCreditCard";
import { safeCopy, workLabel } from "@/lib/rh/billing";
import { AgentReviewPanel } from "./AgentReviewPanel";
import styles from "./AgentWorkspace.module.css";

const STARTERS = [
  { name: "Plan a video", detail: "Turn a brief into a shot list", prompt: "Help me plan a video. Ask about the audience, story and length, then draft a shot list. Do not generate media yet." },
  { name: "Refine an edit", detail: "Pacing, structure and transitions", prompt: "Review the selected project media and suggest improvements to the edit, pacing and transitions. Present a plan before running tools." },
  { name: "Create variations", detail: "Explore a new visual direction", prompt: "Help me explore variations of the selected media. Ask what should stay consistent, then propose options and get approval before generation." },
];
type Section = "files" | "skills" | "connections" | "memory" | null;

export function AgentWorkspace({ busy, onBusyChange }: { busy: boolean; onBusyChange: (busy: boolean) => void }) {
  const open = useCanvasStore((s) => s.agentOpen);
  const projects = useCanvasStore((s) => s.projects);
  const projectId = useCanvasStore((s) => s.projectId);
  const conversations = useCanvasStore((s) => s.conversations);
  const conversationId = useCanvasStore((s) => s.conversationId);
  const nodes = useCanvasStore((s) => s.nodes);
  const providers = useCanvasStore((s) => s.providers);
  const status = useCanvasStore((s) => s.status);
  const loadError = useCanvasStore((s) => s.loadError);
  const [query, setQuery] = useState("");
  const [section, setSection] = useState<Section>(null);
  const [taskCache, setTaskCache] = useState<Record<string, StudioConversation[]>>({});
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [reviewOpen, setReviewOpen] = useState(true);
  const [suggestion, setSuggestion] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const clearSuggestion = useCallback(() => setSuggestion(null), []);
  useEffect(() => {
    // Keep task streams mounted, but stop playback in any panel just hidden.
    document.querySelectorAll<HTMLMediaElement>(".workspace video, .workspace audio").forEach((media) => {
      if (media.closest("[hidden]")) media.pause();
    });
  }, [open, section, reviewOpen]);
  useEffect(() => {
    const narrow = window.matchMedia("(max-width: 800px)");
    const adapt = () => { setSidebarOpen(!narrow.matches); setReviewOpen(!narrow.matches); };
    adapt();
    narrow.addEventListener("change", adapt);
    return () => narrow.removeEventListener("change", adapt);
  }, []);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void Promise.all(projects.filter((p) => p.id !== projectId).map(async (p) => [p.id, await fetchStudioConversations(p.id)] as const))
      .then((entries) => { if (!cancelled) setTaskCache(Object.fromEntries(entries)); })
      .catch(() => { if (!cancelled) setError("Some project tasks could not load. Open the project to retry."); });
    return () => { cancelled = true; };
  }, [open, projects.length, projectId]);

  const navigate = async (action: () => Promise<void | boolean>) => {
    if (busy) return;
    onBusyChange(true);
    setError(null);
    try { if (await action() === false) return; setSection(null); if (window.innerWidth <= 800) setSidebarOpen(false); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not complete the action."); }
    finally { onBusyChange(false); }
  };
  const chooseTask = (id: string, taskId?: string) => void navigate(async () => {
    if (id !== projectId) await useCanvasStore.getState().switchProject(id);
    if (useCanvasStore.getState().projectId !== id) return;
    if (taskId) await useCanvasStore.getState().switchAgentConversation(taskId);
  });
  const executions = useCanvasStore((s) => s.executions);
  const awaitingApproval = executions.some((execution) => execution.conversationId === conversationId && execution.status === "awaiting_approval");
  const mediaNodes = nodes.filter((node) => node.data.output);
  const memoryNodes = nodes.filter((node) => node.data.kind === "text");

  return <div className={`${styles.workspace} rh-agent-workspace ${sidebarOpen ? "" : styles.noSidebar} ${reviewOpen ? "" : styles.noReview}`} hidden={!open}>
    <div className={`${styles.toolbar} rh-agent-toolbar`}>
      <button type="button" aria-label="Toggle projects sidebar" aria-expanded={sidebarOpen} onClick={() => { setSidebarOpen(!sidebarOpen); if (window.innerWidth <= 800) setReviewOpen(false); }}><PanelLeft size={16} /></button>
      <span>Agent workspace</span>
      <button type="button" aria-label="Toggle review panel" aria-expanded={reviewOpen} onClick={() => { setReviewOpen(!reviewOpen); if (window.innerWidth <= 800) setSidebarOpen(false); }}><PanelRight size={16} /></button>
    </div>
    <aside className={`${styles.sidebar} rh-agent-sidebar`} aria-label="Projects and tasks" hidden={!sidebarOpen}>
      <button className={`${styles.newTask} rh-agent-new-task`} type="button" disabled={busy} onClick={() => void navigate(() => useCanvasStore.getState().createAgentConversation())}><Plus size={17} /> New task</button>
      <label className={`${styles.search} rh-agent-search`}><Search size={15} /><input aria-label="Search projects and tasks" placeholder="Search tasks" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
      <nav className={`${styles.resources} rh-agent-resources`} aria-label="Agent resources">
        {([ ["files", Files, "Files"], ["skills", Sparkles, "Skills"], ["connections", Unplug, "Connections"], ["memory", BookOpen, "Memory"] ] as const).map(([id, Icon, title]) =>
          <button key={id} type="button" aria-pressed={section === id} onClick={() => { setSection(section === id ? null : id); if (window.innerWidth <= 800) setSidebarOpen(false); }}><Icon size={16} />{title}{id === "files" ? <small>{mediaNodes.length}</small> : null}</button>)}
      </nav>
      <div className={`${styles.projectHeading} rh-agent-project-heading`}><span>Projects</span><button type="button" aria-label="New project" title="New project" disabled={busy} onClick={() => void navigate(() => useCanvasStore.getState().createProject())}><FolderPlus size={15} /></button></div>
      <div className={`${styles.projectList} rh-agent-project-list`}>
        {projects.map((project) => {
          const tasks = project.id === projectId ? conversations : taskCache[project.id] || [];
          const matching = tasks.filter((task) => task.title.toLowerCase().includes(query.toLowerCase()));
          if (query && !project.name.toLowerCase().includes(query.toLowerCase()) && matching.length === 0) return null;
          const expanded = project.id === projectId || Boolean(query);
          return <div key={project.id} className={`${styles.project} rh-agent-project`}>
            <button type="button" className={`${styles.projectButton} rh-agent-project-button`} aria-expanded={expanded} disabled={busy} onClick={() => chooseTask(project.id)}>
              {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}<Folder size={16} /><span>{project.name}</span>{project.id.startsWith("demo-") ? <span className="rh-chip rh-chip-mono">DEMO</span> : null}
            </button>
            {expanded ? <div className={`${styles.tasks} rh-agent-tasks`}>{matching.map((task) => <button type="button" key={task.id} disabled={busy} title={task.title} aria-current={task.id === conversationId && project.id === projectId ? "page" : undefined} onClick={() => chooseTask(project.id, task.id)}><MessageSquare size={13} /><span>{task.title}</span>{project.id === projectId && task.id === conversationId && awaitingApproval ? <i className="rh-pending-dot" role="img" aria-label="Waiting for your approval" /> : null}</button>)}
              {matching.length === 0 ? <p>{query ? "No matching tasks" : "No tasks yet"}</p> : null}
            </div> : null}
          </div>;
        })}
      </div>
      <BetaCreditCard />
      <div className={`${styles.sidebarFooter} rh-agent-sidebar-footer`}><span className={status?.agent ? styles.online : styles.offline} />{status?.agent ? "Agent connected" : "Agent unavailable"}<kbd>⌘ J</kbd></div>
    </aside>
    <main className={`${styles.conversation} rh-agent-conversation`} aria-label="Task workspace">
      {loadError || error ? <div className={`${styles.error} rh-agent-error`} role="alert">{error || loadError}</div> : null}
      {section ? <section className={`${styles.resourcePanel} rh-agent-resource-panel`} aria-label={`Project ${section}`}>
        <header><h2>{section[0].toUpperCase() + section.slice(1)}</h2><button type="button" aria-label="Back to conversation" onClick={() => setSection(null)}><X size={17} /></button></header>
        {section === "skills" ? <><p>Reusable starting points. Choose one to shape your next request.</p>{STARTERS.map((starter) => <button type="button" className={`${styles.starter} rh-agent-starter`} key={starter.name} disabled={busy} onClick={() => { setSuggestion(starter.prompt); setSection(null); }}><Sparkles size={19} /><span><strong>{starter.name}</strong><small>{starter.detail}</small></span><ChevronRight size={16} /></button>)}</> : null}
        {section === "connections" ? <><p>Tools available to your agent. Generation keeps your approval setting.</p>{providers.length === 0 ? <p>No tools loaded. Check the backend connection.</p> : providers.map((provider) => <details className={`${styles.connection} rh-agent-connection`} key={provider.id}><summary>{safeCopy(provider.name, "Studio tools")}<small>{provider.tools.length} tools · {status?.dry_run[provider.id] === true ? "Dry run" : status?.dry_run[provider.id] === false ? "Live" : "Available"}</small></summary>{provider.tools.map((tool) => <div key={tool.name}><strong>{workLabel(tool.name)}</strong><p>{safeCopy(tool.description, "")}</p></div>)}</details>)}</> : null}
        {section === "memory" ? <><p>Saved project notes and task history provide context. Add a note on the canvas and mention it with @ in a task.</p><div className={`${styles.memorySummary} rh-agent-memory-summary`}>{conversations.length} saved tasks · {mediaNodes.length} media files · {memoryNodes.length} notes</div>{memoryNodes.length ? memoryNodes.map((node) => <article className={`${styles.memory} rh-agent-memory`} key={node.id}><h3>{node.data.title}</h3><p>{String(node.data.config.text || node.data.config.prompt || "This note is empty.")}</p></article>) : <p>No project notes yet.</p>}</> : null}
        {section === "files" ? <><div className={`${styles.fileHeading} rh-agent-file-heading`}><p>Media placed in this project. Select a file to use it as agent context.</p><button type="button" disabled={busy} onClick={() => fileInput.current?.click()}><Upload size={15} /> Upload</button></div>
          <div className={`${styles.files} rh-agent-files`}>{mediaNodes.map((node) => <button type="button" key={node.id} onClick={() => { useCanvasStore.getState().onSelectionChange([node.id]); setSection(null); setReviewOpen(true); }}><AssetMedia asset={node.data.output} alt={node.data.title} muted /><strong>{node.data.output!.filename}</strong><small>{node.data.kind} · {node.data.title}</small></button>)}</div>{mediaNodes.length === 0 ? <p>No media placed yet. Upload a file or place an agent result on the canvas.</p> : null}</> : null}
      </section> : null}
      <input ref={fileInput} type="file" hidden accept="image/*,video/*,audio/*" onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ""; if (file) void navigate(() => useCanvasStore.getState().addUploadNode(file, { x: 80 + nodes.length * 40, y: 80 })); }} />
      <div className={`${styles.dockHost} rh-agent-dock-host`} hidden={section !== null}><AgentDock navigationBusy={busy} onBusyChange={onBusyChange} suggestion={suggestion} onSuggestionUsed={clearSuggestion} onAttach={() => fileInput.current?.click()} /></div>
    </main>
    <div className={`${styles.review} rh-agent-review`} hidden={!reviewOpen}><AgentReviewPanel /></div>
  </div>;
}
