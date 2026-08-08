import { create } from "zustand";
import type {
  AspectRatio,
  Config,
  Job,
  MediaType,
  Production,
  Project,
} from "@/lib/api/types";

// Kept fully separate from lib/timeline/store.ts. That store has one clean
// invariant -- an undo-tracked document plus playback transport -- and
// generation/project/production state is neither undoable nor playback
// transport. The only integration point between the two stores is one
// directional call, useTimelineStore.getState().runCommand(addClipCommand(...)),
// made *from* this feature *into* the timeline store (see
// components/generation/useAddToTimeline.ts) -- the same imperative
// cross-module dispatch pattern lib/timeline/import.ts already establishes,
// not a reason to merge the stores.
//
// This store is pure client state + a normalized cache -- it does not
// fetch. Components call useApiClient()/usePoll() and write results in via
// upsertJob/upsertProduction/upsertProject.

export type PanelKey = "generate" | "library" | "production" | "captions" | "text" | "settings";

const RECENT_JOBS_LIMIT = 8;

interface GenerationState {
  // Composer
  mediaType: MediaType | "production";
  prompt: string;
  aspectRatio: AspectRatio;
  durationSeconds: number;
  referenceAssetId: string | null;
  referenceFileName: string | null;
  setMediaType: (mediaType: MediaType | "production") => void;
  setPrompt: (prompt: string) => void;
  setAspectRatio: (aspectRatio: AspectRatio) => void;
  setDurationSeconds: (durationSeconds: number) => void;
  setReferenceAsset: (assetId: string, fileName: string) => void;
  clearReference: () => void;

  // Config (GET /api/config), fetched once on mount by whatever panel needs it
  config: Config | null;
  setConfig: (config: Config) => void;

  // Active workspace
  activeJobId: string | null;
  activeProductionId: string | null;
  setActiveJob: (jobId: string | null) => void;
  setActiveProduction: (productionId: string | null) => void;

  // Normalized caches -- polling and mutation responses write here
  jobs: Record<string, Job>;
  productions: Record<string, Production>;
  recentJobIds: string[];
  upsertJob: (job: Job) => void;
  upsertProduction: (production: Production) => void;

  // Project library
  projects: Project[];
  currentProjectId: string | null;
  setProjects: (projects: Project[]) => void;
  upsertProject: (project: Project) => void;
  setCurrentProject: (projectId: string | null) => void;

  // Which IconRail panel is open -- lifted out of IconRail's local
  // useState so EditorShell can render panel content next to it.
  activePanel: PanelKey;
  setActivePanel: (panel: PanelKey) => void;
}

export const useGenerationStore = create<GenerationState>((set) => ({
  mediaType: "video",
  prompt: "",
  aspectRatio: "16:9",
  durationSeconds: 10,
  referenceAssetId: null,
  referenceFileName: null,
  setMediaType: (mediaType) => set({ mediaType }),
  setPrompt: (prompt) => set({ prompt }),
  setAspectRatio: (aspectRatio) => set({ aspectRatio }),
  setDurationSeconds: (durationSeconds) => set({ durationSeconds }),
  setReferenceAsset: (referenceAssetId, referenceFileName) =>
    set({ referenceAssetId, referenceFileName }),
  clearReference: () => set({ referenceAssetId: null, referenceFileName: null }),

  config: null,
  setConfig: (config) => set({ config }),

  activeJobId: null,
  activeProductionId: null,
  setActiveJob: (activeJobId) => set({ activeJobId }),
  setActiveProduction: (activeProductionId) => set({ activeProductionId }),

  jobs: {},
  productions: {},
  recentJobIds: [],
  upsertJob: (job) =>
    set((state) => {
      const recentJobIds = [job.id, ...state.recentJobIds.filter((id) => id !== job.id)].slice(
        0,
        RECENT_JOBS_LIMIT,
      );
      return { jobs: { ...state.jobs, [job.id]: job }, recentJobIds };
    }),
  upsertProduction: (production) =>
    set((state) => ({ productions: { ...state.productions, [production.id]: production } })),

  projects: [],
  currentProjectId: null,
  setProjects: (projects) => set({ projects }),
  upsertProject: (project) =>
    set((state) => {
      const existingIndex = state.projects.findIndex((p) => p.id === project.id);
      const projects =
        existingIndex === -1
          ? [project, ...state.projects]
          : state.projects.map((p) => (p.id === project.id ? project : p));
      return { projects };
    }),
  setCurrentProject: (currentProjectId) => set({ currentProjectId }),

  activePanel: "generate",
  setActivePanel: (activePanel) => set({ activePanel }),
}));

// Convenience selector helpers (not store actions) -- narrow reads for
// common lookups, matching the "always select a narrow slice" convention.
export function selectActiveJob(state: GenerationState): Job | null {
  return state.activeJobId ? state.jobs[state.activeJobId] ?? null : null;
}

export function selectActiveProduction(state: GenerationState): Production | null {
  return state.activeProductionId ? state.productions[state.activeProductionId] ?? null : null;
}

export function selectCurrentProject(state: GenerationState): Project | null {
  return state.currentProjectId
    ? state.projects.find((p) => p.id === state.currentProjectId) ?? null
    : null;
}
