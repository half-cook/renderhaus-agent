import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type EdgeChange,
  type NodeChange,
  type Viewport,
} from "@xyflow/react";
import { create } from "zustand";
import { fetchOptions, fetchStatus, fetchTools, uploadStudioFile } from "@/lib/api";
import type { FieldOptions, ProviderCatalog, StudioAsset, StudioStatus } from "@/lib/types";
import {
  edgeAlreadyOccupiesHandle,
  isCompatibleConnection,
  type CanvasEdge,
  type CanvasNode,
} from "./connection-validation";
import { pollCreativeNode, runCreativeNode } from "./graph-execution";
import { defaultToolForRail, toolById } from "./tool-registry";
import type { CreativeNodeKind, JobStatus, ProjectRecord, RailTool, ToolDefinition } from "./types";

const PROJECTS_KEY = "renderhaus.studio.projects";
const GRAPH_KEY = (id: string) => `renderhaus.studio.graph.${id}`;
const HISTORY_LIMIT = 50;

const PREFERRED: Record<string, Record<string, string | number>> = {
  seedance: { duration_seconds: 5, aspect_ratio: "16:9", resolution: "720p" },
  seedream: { aspect_ratio: "1:1", size: "2K", response_format: "url" },
  mureka: { model: "auto" },
  fish_audio: { voice: "Energetic Male", output_format: "mp3", model: "s2.1-pro-free" },
};

type PersistedGraph = {
  projectName: string;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  viewport: Viewport;
};

type Snapshot = { nodes: CanvasNode[]; edges: CanvasEdge[] };

type CanvasStore = {
  projectId: string;
  projectName: string;
  projects: ProjectRecord[];
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  viewport: Viewport;
  selectedNodeIds: string[];
  activeTool: RailTool;
  inspectorOpen: boolean;
  advancedOpen: boolean;
  connectionHint: string | null;
  composerMessage: string | null;
  providers: ProviderCatalog[];
  fieldOptions: FieldOptions;
  status: StudioStatus | null;
  loadError: string | null;
  hydrated: boolean;
  past: Snapshot[];
  future: Snapshot[];
  hydrate: () => void;
  loadCatalog: () => Promise<void>;
  setProjectName: (name: string) => void;
  switchProject: (id: string) => void;
  createProject: () => void;
  setActiveTool: (tool: RailTool) => void;
  setInspectorOpen: (open: boolean) => void;
  toggleAdvanced: () => void;
  setViewport: (viewport: Viewport) => void;
  onNodesChange: (changes: NodeChange<CanvasNode>[]) => void;
  onEdgesChange: (changes: EdgeChange<CanvasEdge>[]) => void;
  onConnect: (connection: Connection) => void;
  onSelectionChange: (ids: string[]) => void;
  addCreativeNode: (input: {
    kind: CreativeNodeKind;
    position: { x: number; y: number };
    toolId?: string;
    title?: string;
    config?: Record<string, unknown>;
    output?: StudioAsset;
  }) => string;
  addUploadNode: (file: File, position: { x: number; y: number }) => Promise<void>;
  updateNodeData: (id: string, patch: Partial<CanvasNode["data"]>) => void;
  updateNodeConfig: (id: string, name: string, value: unknown) => void;
  duplicateSelected: () => void;
  deleteSelected: () => void;
  connectImageToVideo: (imageNodeId: string) => void;
  addToStoryboard: (mediaNodeId: string) => void;
  runNode: (id: string) => Promise<void>;
  undo: () => void;
  redo: () => void;
  pushHistory: () => void;
  persist: () => void;
  setComposerMessage: (message: string | null) => void;
};

const pollTimers = new Map<string, number>();

function uid(): string {
  return crypto.randomUUID();
}

function cloneGraph(nodes: CanvasNode[], edges: CanvasEdge[]): Snapshot {
  return {
    nodes: structuredClone(nodes),
    edges: structuredClone(edges),
  };
}

function defaultsFor(tool: ToolDefinition, fieldOptions: FieldOptions): Record<string, unknown> {
  const preferred = PREFERRED[tool.providerId] || {};
  const catalog = fieldOptions[tool.providerId] || {};
  const args: Record<string, unknown> = {};
  for (const [name, value] of Object.entries(preferred)) {
    const choices = catalog[name];
    if (!choices || choices.some((choice) => String(choice) === String(value))) {
      args[name] = value;
    }
  }
  return args;
}

function readProjects(): ProjectRecord[] {
  if (typeof window === "undefined") {
    return [];
  }
  try {
    const raw = window.localStorage.getItem(PROJECTS_KEY);
    const parsed = raw ? (JSON.parse(raw) as ProjectRecord[]) : [];
    if (Array.isArray(parsed) && parsed.length > 0) {
      return parsed;
    }
  } catch {
    return [{ id: "untitled", name: "Untitled" }];
  }
  return [{ id: "untitled", name: "Untitled" }];
}

function readGraph(projectId: string): PersistedGraph | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(GRAPH_KEY(projectId));
    return raw ? (JSON.parse(raw) as PersistedGraph) : null;
  } catch {
    return null;
  }
}

function runningCount(nodes: CanvasNode[]): number {
  return nodes.filter((node) => node.data.status === "running" || node.data.status === "queued").length;
}

export const useCanvasStore = create<CanvasStore>((set, get) => ({
  projectId: "untitled",
  projectName: "Untitled",
  projects: [{ id: "untitled", name: "Untitled" }],
  nodes: [],
  edges: [],
  viewport: { x: 80, y: 80, zoom: 1 },
  selectedNodeIds: [],
  activeTool: "select",
  inspectorOpen: true,
  advancedOpen: false,
  connectionHint: null,
  composerMessage: null,
  providers: [],
  fieldOptions: {},
  status: null,
  loadError: null,
  hydrated: false,
  past: [],
  future: [],

  hydrate: () => {
    const projects = readProjects();
    const project = projects[0];
    const graph = readGraph(project.id);
    set({
      projects,
      projectId: project.id,
      projectName: graph?.projectName || project.name,
      nodes: graph?.nodes || [],
      edges: graph?.edges || [],
      viewport: graph?.viewport || { x: 80, y: 80, zoom: 1 },
      hydrated: true,
      past: [],
      future: [],
    });
  },

  persist: () => {
    if (typeof window === "undefined") {
      return;
    }
    const { projectId, projectName, nodes, edges, viewport, projects } = get();
    const nextProjects = projects.map((item) =>
      item.id === projectId ? { ...item, name: projectName } : item,
    );
    window.localStorage.setItem(PROJECTS_KEY, JSON.stringify(nextProjects));
    window.localStorage.setItem(
      GRAPH_KEY(projectId),
      JSON.stringify({ projectName, nodes, edges, viewport } satisfies PersistedGraph),
    );
    set({ projects: nextProjects });
  },

  loadCatalog: async () => {
    try {
      const [providers, status, fieldOptions] = await Promise.all([
        fetchTools(),
        fetchStatus(),
        fetchOptions().catch(() => ({})),
      ]);
      set({ providers, status, fieldOptions, loadError: null });
    } catch (error) {
      set({ loadError: error instanceof Error ? error.message : "Could not load tools." });
    }
  },

  setProjectName: (name) => {
    set({ projectName: name || "Untitled" });
    get().persist();
  },

  switchProject: (id) => {
    get().persist();
    const graph = readGraph(id);
    const project = get().projects.find((item) => item.id === id);
    set({
      projectId: id,
      projectName: graph?.projectName || project?.name || "Untitled",
      nodes: graph?.nodes || [],
      edges: graph?.edges || [],
      viewport: graph?.viewport || { x: 80, y: 80, zoom: 1 },
      selectedNodeIds: [],
      past: [],
      future: [],
    });
  },

  createProject: () => {
    get().persist();
    const id = uid();
    const record = { id, name: "Untitled" };
    set({
      projects: [...get().projects, record],
      projectId: id,
      projectName: "Untitled",
      nodes: [],
      edges: [],
      viewport: { x: 80, y: 80, zoom: 1 },
      selectedNodeIds: [],
      past: [],
      future: [],
    });
    get().persist();
  },

  setActiveTool: (tool) => set({ activeTool: tool }),
  setInspectorOpen: (open) => set({ inspectorOpen: open }),
  toggleAdvanced: () => set({ advancedOpen: !get().advancedOpen }),
  setViewport: (viewport) => {
    set({ viewport });
    get().persist();
  },
  setComposerMessage: (message) => set({ composerMessage: message }),

  pushHistory: () => {
    const { nodes, edges, past } = get();
    const nextPast = [...past, cloneGraph(nodes, edges)].slice(-HISTORY_LIMIT);
    set({ past: nextPast, future: [] });
  },

  onNodesChange: (changes) => {
    if (changes.some((change) => change.type === "remove" || change.type === "add")) {
      get().pushHistory();
    }
    const next = applyNodeChanges(changes, get().nodes);
    const selectedNodeIds = next.filter((node) => node.selected).map((node) => node.id);
    set({ nodes: next, selectedNodeIds });
    const structural = changes.some((change) => change.type === "remove" || change.type === "add");
    if (structural) {
      get().persist();
    }
  },

  onEdgesChange: (changes) => {
    if (changes.some((change) => change.type === "remove" || change.type === "add")) {
      get().pushHistory();
    }
    set({ edges: applyEdgeChanges(changes, get().edges) });
    const structural = changes.some((change) => change.type === "remove" || change.type === "add");
    if (structural) {
      get().persist();
    }
  },

  onConnect: (connection) => {
    const check = isCompatibleConnection(connection, get().nodes);
    if (!check.ok) {
      set({ connectionHint: check.reason });
      window.setTimeout(() => set({ connectionHint: null }), 2400);
      return;
    }
    get().pushHistory();
    let edges = get().edges;
    if (edgeAlreadyOccupiesHandle(edges, connection)) {
      edges = edges.filter(
        (edge) =>
          !(edge.target === connection.target && (edge.targetHandle || "") === (connection.targetHandle || "")),
      );
    }
    set({
      edges: addEdge(
        {
          ...connection,
          data: { dataType: check.dataType, targetField: check.targetField },
        },
        edges,
      ),
      connectionHint: null,
    });
    get().persist();
  },

  onSelectionChange: (ids) => set({ selectedNodeIds: ids }),

  addCreativeNode: ({ kind, position, toolId, title, config, output }) => {
    get().pushHistory();
    const tool = toolById(toolId);
    const id = uid();
    const node: CanvasNode = {
      id,
      type: kind,
      position,
      selected: true,
      data: {
        kind,
        title: title || tool?.displayName || kind,
        toolId: tool?.id,
        providerId: tool?.providerId,
        toolName: tool?.toolName,
        config: config || (tool ? defaultsFor(tool, get().fieldOptions) : {}),
        output,
        variants: output ? [output] : [],
        status: output ? "completed" : "idle",
      },
    };
    set({
      nodes: [...get().nodes.map((item) => ({ ...item, selected: false })), node],
      selectedNodeIds: [id],
      inspectorOpen: true,
    });
    get().persist();
    return id;
  },

  addUploadNode: async (file, position) => {
    const uploaded = await uploadStudioFile(file);
    const kind = uploaded.kind;
    get().addCreativeNode({
      kind,
      position,
      title: uploaded.filename.replace(/\.[^.]+$/, ""),
      output: { kind, url: uploaded.url },
      config: { path: uploaded.path },
    });
  },

  updateNodeData: (id, patch) => {
    set({
      nodes: get().nodes.map((node) =>
        node.id === id ? { ...node, data: { ...node.data, ...patch } } : node,
      ),
    });
    get().persist();
  },

  updateNodeConfig: (id, name, value) => {
    set({
      nodes: get().nodes.map((node) =>
        node.id === id
          ? { ...node, data: { ...node.data, config: { ...node.data.config, [name]: value } } }
          : node,
      ),
    });
    get().persist();
  },

  duplicateSelected: () => {
    const selected = get().nodes.filter((node) => get().selectedNodeIds.includes(node.id));
    if (selected.length === 0) {
      return;
    }
    get().pushHistory();
    const created = selected.map((node) => ({
      ...structuredClone(node),
      id: uid(),
      position: { x: node.position.x + 40, y: node.position.y + 40 },
      selected: true,
    }));
    set({
      nodes: [
        ...get().nodes.map((node) => ({ ...node, selected: false })),
        ...created,
      ],
      selectedNodeIds: created.map((node) => node.id),
    });
    get().persist();
  },

  deleteSelected: () => {
    const ids = new Set(get().selectedNodeIds);
    if (ids.size === 0) {
      return;
    }
    get().pushHistory();
    set({
      nodes: get().nodes.filter((node) => !ids.has(node.id)),
      edges: get().edges.filter((edge) => !ids.has(edge.source) && !ids.has(edge.target)),
      selectedNodeIds: [],
    });
    get().persist();
  },

  connectImageToVideo: (imageNodeId) => {
    const source = get().nodes.find((node) => node.id === imageNodeId);
    if (!source) {
      return;
    }
    const tool = defaultToolForRail("video");
    const fromImage = toolById("video.fromImage") || tool;
    const id = get().addCreativeNode({
      kind: "video",
      position: { x: source.position.x + 440, y: source.position.y },
      toolId: fromImage?.id,
      title: "Image to video",
    });
    get().onConnect({
      source: imageNodeId,
      target: id,
      sourceHandle: "image",
      targetHandle: "image",
    });
  },

  addToStoryboard: (mediaNodeId) => {
    const source = get().nodes.find((node) => node.id === mediaNodeId);
    let board = get().nodes.find((node) => node.data.kind === "storyboard");
    if (!board) {
      const id = get().addCreativeNode({
        kind: "storyboard",
        position: {
          x: (source?.position.x || 0) + 440,
          y: source?.position.y || 80,
        },
        title: "Storyboard",
      });
      board = get().nodes.find((node) => node.id === id);
    }
    if (!board || !source) {
      return;
    }
    const handle = source.data.kind === "video" ? "video" : "image";
    get().onConnect({
      source: mediaNodeId,
      target: board.id,
      sourceHandle: handle,
      targetHandle: handle,
    });
  },

  runNode: async (id) => {
    const node = get().nodes.find((item) => item.id === id);
    if (!node) {
      return;
    }
    get().updateNodeData(id, { status: "running", error: undefined });
    try {
      const patch = await runCreativeNode(node, get().nodes, get().edges);
      get().updateNodeData(id, patch);
      if (patch.status === "queued" && patch.jobId) {
        const tick = async () => {
          const current = get().nodes.find((item) => item.id === id);
          if (!current) {
            return;
          }
          try {
            const next = await pollCreativeNode(current);
            if (!next) {
              return;
            }
            get().updateNodeData(id, next);
            if (next.status === "running" || next.status === "queued") {
              const timer = window.setTimeout(() => {
                void tick();
              }, 2500);
              pollTimers.set(id, timer);
            } else {
              pollTimers.delete(id);
            }
          } catch (error) {
            get().updateNodeData(id, {
              status: "failed",
              error: error instanceof Error ? error.message : "Polling failed.",
            });
            pollTimers.delete(id);
          }
        };
        void tick();
      }
    } catch (error) {
      get().updateNodeData(id, {
        status: "failed",
        error: error instanceof Error ? error.message : "Generation failed.",
      });
    }
  },

  undo: () => {
    const { past, nodes, edges, future } = get();
    const previous = past[past.length - 1];
    if (!previous) {
      return;
    }
    set({
      nodes: previous.nodes,
      edges: previous.edges,
      past: past.slice(0, -1),
      future: [...future, cloneGraph(nodes, edges)],
      selectedNodeIds: [],
    });
    get().persist();
  },

  redo: () => {
    const { future, nodes, edges, past } = get();
    const next = future[future.length - 1];
    if (!next) {
      return;
    }
    set({
      nodes: next.nodes,
      edges: next.edges,
      future: future.slice(0, -1),
      past: [...past, cloneGraph(nodes, edges)],
      selectedNodeIds: [],
    });
    get().persist();
  },
}));

export function queueSize(nodes: CanvasNode[]): number {
  return runningCount(nodes);
}

export function selectedNode(nodes: CanvasNode[], ids: string[]): CanvasNode | undefined {
  if (ids.length !== 1) {
    return undefined;
  }
  return nodes.find((node) => node.id === ids[0]);
}

export function statusLabel(status: JobStatus): string {
  switch (status) {
    case "idle":
      return "Ready";
    case "queued":
      return "Queued";
    case "running":
      return "Running";
    case "completed":
      return "Done";
    case "failed":
      return "Failed";
    default: {
      const exhaustive: never = status;
      return exhaustive;
    }
  }
}
