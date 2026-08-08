"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import { useApiClient } from "@/lib/api/useApiClient";
import { ApiError, type Job, type Project } from "@/lib/api/types";
import {
  useGenerationStore,
  selectCurrentProject,
  type PanelKey,
} from "@/lib/generation/store";
import { useAddToTimeline } from "./useAddToTimeline";

const JOB_DRAG_TYPE = "text/plain";
const TIMELINE_MEDIA_TYPES = new Set(["video", "music"]);

// Create/list/open projects, "in this project"/"standalone" job sections,
// drag-drop from RecentHistoryStrip onto a project card. Per decision #1
// (Unified Timeline), artifact cards' only drop target is a project card --
// there's no separate timeline drop zone, "add to timeline" is the button
// built in the previous step.
//
// project.timeline (server-side) is kept as a snapshot, synced whenever
// membership changes (syncProjectTimeline below) -- not a second visible
// widget, but it has to actually be written for POST /.../merge to have
// anything to merge (design/MERGE_STATUS.md §5.1: this was the one piece
// that hadn't been wired up).
export function ProjectLibrary() {
  const api = useApiClient();
  const { isSignedIn } = useAuth();
  const projects = useGenerationStore((s) => s.projects);
  const setProjects = useGenerationStore((s) => s.setProjects);
  const upsertProject = useGenerationStore((s) => s.upsertProject);
  const upsertJob = useGenerationStore((s) => s.upsertJob);
  const currentProjectId = useGenerationStore((s) => s.currentProjectId);
  const setCurrentProject = useGenerationStore((s) => s.setCurrentProject);
  const currentProject = useGenerationStore(selectCurrentProject);
  const setActivePanel = useGenerationStore((s) => s.setActivePanel);
  const setActiveJob = useGenerationStore((s) => s.setActiveJob);

  const [projectJobs, setProjectJobs] = useState<Job[]>([]);
  const [standaloneJobs, setStandaloneJobs] = useState<Job[]>([]);
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [merging, setMerging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listProjects()
      .then((r) => setProjects(r.items))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fetch once on mount
  }, []);

  const refreshJobs = useCallback(async () => {
    const [projectResult, standaloneResult] = await Promise.all([
      currentProjectId
        ? api.listGenerations({ project_id: currentProjectId })
        : Promise.resolve({ items: [] as Job[] }),
      api.listGenerations({ unassigned: true }),
    ]);
    setProjectJobs(projectResult.items);
    setStandaloneJobs(standaloneResult.items);
  }, [api, currentProjectId]);

  useEffect(() => {
    // refreshJobs only calls setState after its awaits resolve (a genuine
    // async fetch, not a synchronous derivation) -- react-hooks/set-state-
    // in-effect can't see through that and flags it anyway.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refreshJobs().catch(() => {});
  }, [refreshJobs]);

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = title.trim();
    if (!trimmed) return;
    setCreating(true);
    setError(null);
    try {
      const project = await api.createProject({ title: trimmed });
      upsertProject(project);
      setCurrentProject(project.id);
      setTitle("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the project.");
    } finally {
      setCreating(false);
    }
  }

  async function openProject(project: Project) {
    setCurrentProject(project.id);
    try {
      const full = await api.getProject(project.id);
      upsertProject(full);
    } catch {
      // Keep the summary object already in state -- opening still works.
    }
  }

  // Writes the project's video/music artifacts to its server-side timeline
  // snapshot (PUT /api/projects/{id}/timeline). The backend fills in
  // asset_id/media_type/label/duration_seconds from each job record itself
  // (server/app.py's timeline handler doesn't trust those fields from the
  // client) -- {job_id} per item is all that's needed here. Images are
  // excluded: the backend silently drops them from the persisted timeline
  // anyway (video/music only), and they were never mergeable in the old UI.
  const syncProjectTimeline = useCallback(
    async (projectId: string, jobs: Job[]) => {
      const items = jobs
        .filter((job) => TIMELINE_MEDIA_TYPES.has(job.media_type))
        .map((job) => ({ job_id: job.id }));
      const project = await api.putProjectTimeline(projectId, items);
      upsertProject(project);
    },
    [api, upsertProject],
  );

  async function handleDropOnProject(projectId: string, jobId: string) {
    try {
      const { project } = await api.addProjectArtifact(projectId, jobId);
      upsertProject(project);
      const { items } = await api.listGenerations({ project_id: projectId });
      await syncProjectTimeline(projectId, items);
      await refreshJobs();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add that generation to the project.");
    }
  }

  async function handleMerge() {
    if (!currentProjectId) return;
    setMerging(true);
    setError(null);
    try {
      const { project, job } = await api.mergeProject(currentProjectId);
      upsertProject(project);
      upsertJob(job);
      setActiveJob(job.id);
      setActivePanel("generate" as PanelKey);
      await refreshJobs();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not merge the timeline clips.");
    } finally {
      setMerging(false);
    }
  }

  async function handleRemoveArtifact(jobId: string) {
    if (!currentProjectId) return;
    try {
      const { project } = await api.removeProjectArtifact(currentProjectId, jobId);
      upsertProject(project);
      await refreshJobs();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove that generation.");
    }
  }

  function openJob(jobId: string) {
    setActiveJob(jobId);
    setActivePanel("generate" as PanelKey);
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
      <form onSubmit={handleCreate} className="flex gap-1">
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="New project"
          className="min-w-0 flex-1 rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-xs text-neutral-200 placeholder:text-neutral-600 focus:border-neutral-600 focus:outline-none"
        />
        <button
          type="submit"
          disabled={creating || !title.trim()}
          className="rounded-md bg-neutral-800 px-2 py-1 text-xs text-neutral-200 hover:bg-neutral-700 disabled:opacity-50"
        >
          +
        </button>
      </form>

      {error && <p className="text-[11px] text-red-400">{error}</p>}

      <section className="flex flex-col gap-2">
        <p className="text-[11px] uppercase tracking-wide text-neutral-600">Projects</p>
        {projects.length === 0 && (
          <p className="text-xs text-neutral-600">
            {isSignedIn === false ? "Sign in to see your projects." : "No projects yet."}
          </p>
        )}
        {currentProjectId && (
          <button
            onClick={() => setCurrentProject(null)}
            className="text-left text-[11px] text-neutral-500 hover:text-neutral-300"
          >
            ← Leave project · back to standalone
          </button>
        )}
        <div className="flex flex-col gap-1">
          {projects.map((project) => (
            <div
              key={project.id}
              onClick={() => openProject(project)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                const jobId = event.dataTransfer.getData(JOB_DRAG_TYPE);
                if (jobId) void handleDropOnProject(project.id, jobId);
              }}
              className={`flex cursor-pointer flex-col gap-0.5 rounded-md border px-2 py-1.5 text-xs ${
                project.id === currentProjectId
                  ? "border-indigo-500 bg-indigo-950/40 text-neutral-100"
                  : "border-neutral-800 text-neutral-300 hover:bg-neutral-900"
              }`}
            >
              <span className="truncate font-medium">{project.title}</span>
              <span className="text-[10px] text-neutral-500">
                {project.artifact_count} · {project.timeline_count} on timeline
              </span>
            </div>
          ))}
        </div>
      </section>

      {currentProject && (
        <section className="flex flex-col gap-2">
          <p className="text-[11px] uppercase tracking-wide text-neutral-600">In this project</p>
          {projectJobs.length === 0 && (
            <p className="text-xs text-neutral-600">Drag a generation here, or add one below.</p>
          )}
          <div className="flex flex-col gap-1">
            {projectJobs.map((job) => (
              <ArtifactCard
                key={job.id}
                job={job}
                removable
                onOpen={() => openJob(job.id)}
                onRemove={() => handleRemoveArtifact(job.id)}
              />
            ))}
          </div>
          {projectJobs.filter((job) => job.media_type === "video" && job.status === "complete").length >=
            2 && (
            <button
              onClick={handleMerge}
              disabled={merging}
              className="rounded-md bg-neutral-800 py-1.5 text-xs text-neutral-200 hover:bg-neutral-700 disabled:opacity-50"
            >
              {merging ? "Merging…" : "Merge video clips"}
            </button>
          )}
        </section>
      )}

      <section className="flex flex-col gap-2">
        <p className="text-[11px] uppercase tracking-wide text-neutral-600">Standalone</p>
        {standaloneJobs.length === 0 && (
          <p className="text-xs text-neutral-600">
            {isSignedIn === false ? "Sign in to see your generations." : "Not in a project."}
          </p>
        )}
        <div className="flex flex-col gap-1">
          {standaloneJobs.map((job) => (
            <ArtifactCard
              key={job.id}
              job={job}
              assignable={Boolean(currentProjectId)}
              onOpen={() => openJob(job.id)}
              onAssign={
                currentProjectId ? () => handleDropOnProject(currentProjectId, job.id) : undefined
              }
            />
          ))}
        </div>
      </section>
    </div>
  );
}

function ArtifactCard({
  job,
  removable,
  assignable,
  onOpen,
  onRemove,
  onAssign,
}: {
  job: Job;
  removable?: boolean;
  assignable?: boolean;
  onOpen: () => void;
  onRemove?: () => void;
  onAssign?: () => void;
}) {
  const addToTimeline = useAddToTimeline();
  const title = job.prompt.split(/\s+/).slice(0, 3).join(" ") || job.id;
  const isReady = job.status === "complete";
  const draggable = isReady;

  return (
    <div
      draggable={draggable}
      onDragStart={(event) => {
        if (!draggable) return;
        event.dataTransfer.setData(JOB_DRAG_TYPE, job.id);
      }}
      className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-xs text-neutral-300 hover:bg-neutral-900"
    >
      <button onClick={onOpen} className="min-w-0 flex-1 truncate text-left">
        <span className="truncate">{title}</span>
        <span className="ml-2 text-[10px] text-neutral-600">
          {job.media_type} · {job.status === "complete" ? "Ready" : job.status === "failed" ? "Failed" : job.status}
        </span>
      </button>
      <div className="flex shrink-0 gap-1">
        {isReady && job.media_type !== "image" && (
          <button
            onClick={() => void addToTimeline(job)}
            className="rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] hover:bg-neutral-700"
          >
            Add to timeline
          </button>
        )}
        {isReady && assignable && job.media_type === "image" && onAssign && (
          <button
            onClick={onAssign}
            className="rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] hover:bg-neutral-700"
          >
            Add to project
          </button>
        )}
        {removable && onRemove && (
          <button
            onClick={onRemove}
            className="rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-400 hover:bg-neutral-700"
          >
            Remove
          </button>
        )}
      </div>
    </div>
  );
}
