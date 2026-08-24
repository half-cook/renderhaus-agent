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
import {
  createStudioProject,
  fetchOptions,
  fetchStatus,
  fetchStudioCanvas,
  fetchStudioExecutions,
  fetchStudioProjects,
  fetchTools,
  saveStudioCanvas,
  uploadStudioFile,
  type StudioCanvasDocument,
  type StudioExecution,
} from "@/lib/api";
import type { FieldOptions, ProviderCatalog, StudioAsset, StudioStatus } from "@/lib/types";
import {
  edgeAlreadyOccupiesHandle,
  isCompatibleConnection,
  type CanvasEdge,
  type CanvasNode,
} from "./connection-validation";
import { pollCreativeNode, runCreativeNode } from "./graph-execution";
import {
  approvedSequence,
  compactStoryOrders,
  isSceneKind,
  nextStoryOrder,
  SCENE_CARD_GAP,
  SCENE_CARD_WIDTH,
} from "./story";
import { defaultToolForRail, toolById } from "./tool-registry";
import type {
  AgentRunData,
  AgentResultData,
  AgentToolEvent,
  CanvasNodeData,
  CreativeNodeKind,
  JobStatus,
  ProjectRecord,
  RailTool,
  ToolDefinition,
} from "./types";

const PROJECTS_KEY = "renderhaus.studio.projects";
const GRAPH_KEY = (id: string) => `renderhaus.studio.graph.${id}`;
const MIGRATED_KEY = "renderhaus.studio.server-migration.v2";
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
  composerOpen: boolean;
  advancedOpen: boolean;
  connectionHint: string | null;
  composerMessage: string | null;
  providers: ProviderCatalog[];
  fieldOptions: FieldOptions;
  status: StudioStatus | null;
  executions: StudioExecution[];
  loadError: string | null;
  hydrated: boolean;
  past: Snapshot[];
  future: Snapshot[];
  hydrate: () => Promise<void>;
  loadCatalog: () => Promise<void>;
  refreshExecutions: () => Promise<void>;
  setProjectName: (name: string) => void;
  switchProject: (id: string) => Promise<void>;
  createProject: () => Promise<void>;
  setActiveTool: (tool: RailTool) => void;
  setInspectorOpen: (open: boolean) => void;
  setComposerOpen: (open: boolean) => void;
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
  addAgentResult: (result: AgentResultData, position: { x: number; y: number }) => string;
  toggleAgentRun: (id: string) => void;
  addUploadNode: (file: File, position: { x: number; y: number }) => Promise<void>;
  updateNodeData: (id: string, patch: Partial<CanvasNode["data"]>) => void;
  updateNodeConfig: (id: string, name: string, value: unknown) => void;
  duplicateSelected: () => void;
  deleteSelected: () => void;
  connectImageToVideo: (imageNodeId: string) => void;
  addToStoryboard: (mediaNodeId: string) => void;
  setApproved: (id: string, approved: boolean) => void;
  cycleVariant: (id: string, direction: 1 | -1) => void;
  moveInSequence: (id: string, direction: 1 | -1) => void;
  arrangeSequence: () => void;
  startSequence: (origin: { x: number; y: number }) => void;
  focusNode: (id: string) => void;
  runNode: (id: string) => Promise<void>;
  undo: () => void;
  redo: () => void;
  pushHistory: () => void;
  persist: () => Promise<void>;
  setComposerMessage: (message: string | null) => void;
};

const pollTimers = new Map<string, number>();
let persistQueue: Promise<void> = Promise.resolve();
let viewportPersistTimer: number | null = null;
let persistedRevision = 0;

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
  if (args.model === undefined && catalog.model && catalog.model.length > 0) {
    args.model = catalog.model[0];
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

function documentFromGraph(graph: PersistedGraph): StudioCanvasDocument {
  return {
    schemaVersion: 2,
    projectName: graph.projectName,
    nodes: graph.nodes,
    edges: graph.edges,
    viewport: graph.viewport,
  };
}

function graphFromDocument(document: StudioCanvasDocument): PersistedGraph {
  const graph = {
    projectName: document.projectName || "Untitled",
    nodes: document.nodes as CanvasNode[],
    edges: document.edges as CanvasEdge[],
    viewport: document.viewport || { x: 80, y: 80, zoom: 1 },
  };
  return migrateLegacyAgentPresentation(expandLegacyAgentResults(graph));
}

function needsAgentPresentationMigration(document: StudioCanvasDocument): boolean {
  return document.nodes.some((node) => {
    if (!node || typeof node !== "object") return false;
    const data = (node as { data?: CanvasNodeData }).data;
    if (!data) return false;
    if (data.kind === "agentResult") return true;
    const agentOutput = Boolean(data.agentRun || data.agentRunId || data.agentRole);
    return (
      data.agentRole === "final" ||
      Boolean(data.agentRun?.finalNodeId && !data.agentRun.primaryNodeId) ||
      (agentOutput && typeof data.title === "string" && data.title.startsWith("Final · "))
    );
  });
}

function migrateLegacyAgentPresentation(graph: PersistedGraph): PersistedGraph {
  let changed = false;
  const nodes = graph.nodes.map((node) => {
    const data = node.data;
    const legacyPrimaryNodeId = data.agentRun?.finalNodeId;
    const shouldMigrateRun = Boolean(legacyPrimaryNodeId && !data.agentRun?.primaryNodeId);
    const shouldMigrateRole = data.agentRole === "final";
    const shouldMigrateTitle =
      Boolean(data.agentRun || data.agentRunId || data.agentRole) && data.title.startsWith("Final · ");
    if (!shouldMigrateRun && !shouldMigrateRole && !shouldMigrateTitle) return node;
    changed = true;
    const migratedRun =
      shouldMigrateRun && data.agentRun && legacyPrimaryNodeId
        ? { ...data.agentRun, primaryNodeId: legacyPrimaryNodeId, finalNodeId: undefined }
        : undefined;
    return {
      ...node,
      data: {
        ...data,
        ...(migratedRun ? { agentRun: migratedRun } : {}),
        ...(shouldMigrateRole ? { agentRole: "primary" as const } : {}),
        ...(shouldMigrateTitle ? { title: `Result · ${data.title.slice("Final · ".length)}` } : {}),
      },
    };
  });
  return changed ? { ...graph, nodes } : graph;
}

function makeNode(input: {
  kind: CreativeNodeKind;
  position: { x: number; y: number };
  toolId?: string;
  title?: string;
  config?: Record<string, unknown>;
  output?: StudioAsset;
  agentResult?: AgentResultData;
  agentRun?: AgentRunData;
  fieldOptions: FieldOptions;
}): CanvasNode {
  const tool = toolById(input.toolId);
  const id = uid();
  return {
    id,
    type: input.kind,
    position: input.position,
    selected: false,
    data: {
      kind: input.kind,
      title: input.title || (isSceneKind(input.kind) ? "Scene" : tool?.displayName || input.kind),
      toolId: tool?.id,
      providerId: tool?.providerId,
      toolName: tool?.toolName,
      config: input.config || (tool ? defaultsFor(tool, input.fieldOptions) : {}),
      output: input.output,
      variants: input.output ? [input.output] : [],
      agentResult: input.agentResult,
      agentRun: input.agentRun,
      status: input.output || input.agentResult || input.agentRun ? "completed" : "idle",
      approved: false,
    },
  };
}

type AgentAsset = { asset: StudioAsset; event?: AgentToolEvent };

function assetsForAgentRun(result: AgentResultData): AgentAsset[] {
  const assets = new Map<string, AgentAsset>();
  for (const event of result.toolEvents) {
    for (const asset of event.assets) {
      assets.set(asset.versionId, { asset, event });
    }
  }
  for (const asset of result.assets) {
    if (!assets.has(asset.versionId)) assets.set(asset.versionId, { asset });
  }
  return [...assets.values()];
}

function labelForAgentAsset(asset: StudioAsset, event: AgentToolEvent | undefined, index: number): string {
  const base = event?.label || `${asset.kind[0]?.toUpperCase() || "A"}${asset.kind.slice(1)}`;
  return `${base} ${index + 1}`;
}

function createAgentRunCluster(
  result: AgentResultData,
  position: { x: number; y: number },
  fieldOptions: FieldOptions,
): { nodes: CanvasNode[]; primaryNodeId?: string } {
  const runId = result.executionId || uid();
  const assets = assetsForAgentRun(result);
  const primaryAsset = result.primaryAsset || assets.at(-1)?.asset;
  const artifacts = assets.filter((item) => item.asset.versionId !== primaryAsset?.versionId);
  const artifactNodes = artifacts.map(({ asset, event }, index) => {
    const node = makeNode({
      kind: asset.kind,
      position: {
        x: position.x + Math.floor(index / 3) * 440,
        y: position.y + (index % 3) * 260,
      },
      title: labelForAgentAsset(asset, event, index),
      output: asset,
      fieldOptions,
    });
    node.data.agentRunId = runId;
    node.data.agentRole = "artifact";
    return node;
  });
  const primaryX = position.x + Math.max(1, Math.ceil(artifacts.length / 3)) * 440 + 40;
  const primaryNode = primaryAsset
    ? makeNode({
        kind: primaryAsset.kind,
        position: { x: primaryX, y: position.y + 120 },
        title: `Result · ${result.title}`,
        output: primaryAsset,
        fieldOptions,
      })
    : undefined;
  if (primaryNode) {
    primaryNode.data.agentRunId = runId;
    primaryNode.data.agentRole = "primary";
    primaryNode.selected = true;
  }
  const runNode = makeNode({
    kind: "agentRun",
    position: { x: primaryX, y: position.y + 430 },
    title: `Agent run · ${result.title}`,
    agentRun: {
      ...result,
      executionId: result.executionId || runId,
      artifactNodeIds: artifactNodes.map((node) => node.id),
      ...(primaryNode ? { primaryNodeId: primaryNode.id } : {}),
      collapsed: true,
    },
    fieldOptions,
  });
  return {
    nodes: [...artifactNodes, ...(primaryNode ? [primaryNode] : []), runNode],
    primaryNodeId: primaryNode?.id,
  };
}

function expandLegacyAgentResults(graph: PersistedGraph): PersistedGraph {
  const legacy = graph.nodes.filter((node) => node.data.kind === "agentResult" && node.data.agentResult);
  if (legacy.length === 0) return graph;
  const legacyIds = new Set(legacy.map((node) => node.id));
  const created = legacy.flatMap((node) =>
    createAgentRunCluster(node.data.agentResult as AgentResultData, node.position, {}).nodes,
  );
  return {
    ...graph,
    nodes: [...graph.nodes.filter((node) => !legacyIds.has(node.id)), ...created],
    edges: graph.edges.filter((edge) => !legacyIds.has(edge.source) && !legacyIds.has(edge.target)),
  };
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
  inspectorOpen: false,
  composerOpen: false,
  advancedOpen: false,
  connectionHint: null,
  composerMessage: null,
  providers: [],
  fieldOptions: {},
  status: null,
  executions: [],
  loadError: null,
  hydrated: false,
  past: [],
  future: [],

  hydrate: async () => {
    const legacyProjects = readProjects();
    try {
      let projects = await fetchStudioProjects();
      const migrated =
        typeof window !== "undefined" && window.localStorage.getItem(MIGRATED_KEY) === "true";
      if (!migrated) {
        for (const legacy of legacyProjects) {
          if (!projects.some((project) => project.id === legacy.id)) {
            await createStudioProject(legacy.name, legacy.id);
          }
          const legacyGraph = readGraph(legacy.id);
          if (legacyGraph) {
            const remote = await fetchStudioCanvas(legacy.id);
            if (remote.document.nodes.length === 0 && legacyGraph.nodes.length > 0) {
              await saveStudioCanvas(legacy.id, documentFromGraph(legacyGraph));
            }
          }
        }
        window.localStorage.setItem(MIGRATED_KEY, "true");
        projects = await fetchStudioProjects();
      }
      const project =
        projects.find((candidate) => candidate.id === legacyProjects[0]?.id) || projects[0];
      const snapshot = await fetchStudioCanvas(project.id);
      persistedRevision = snapshot.revision;
      const graph = graphFromDocument(snapshot.document);
      const migratedAgentPresentation = needsAgentPresentationMigration(snapshot.document);
      set({
        projects,
        projectId: project.id,
        projectName: graph.projectName || project.name,
        nodes: graph.nodes,
        edges: graph.edges,
        viewport: graph.viewport,
        hydrated: true,
        loadError: null,
        past: [],
        future: [],
      });
      if (migratedAgentPresentation) {
        window.setTimeout(() => void get().persist(), 0);
      }
    } catch (error) {
      const project = legacyProjects[0] || { id: "untitled", name: "Untitled" };
      const graph = readGraph(project.id);
      set({
        projects: legacyProjects,
        projectId: project.id,
        projectName: graph?.projectName || project.name,
        nodes: graph?.nodes || [],
        edges: graph?.edges || [],
        viewport: graph?.viewport || { x: 80, y: 80, zoom: 1 },
        hydrated: true,
        loadError:
          error instanceof Error ? error.message : "Could not load the server canvas.",
        past: [],
        future: [],
      });
    }
  },

  persist: async () => {
    const { projectId, projectName, nodes, edges, viewport, projects } = get();
    const nextProjects = projects.map((item) =>
      item.id === projectId ? { ...item, name: projectName } : item,
    );
    set({ projects: nextProjects });
    const document = documentFromGraph({ projectName, nodes, edges, viewport });
    const save = async () => {
      const snapshot = await saveStudioCanvas(
        projectId,
        document,
        persistedRevision || undefined,
      );
      persistedRevision = snapshot.revision;
    };
    persistQueue = persistQueue.then(save, save);
    try {
      await persistQueue;
      if (get().loadError?.startsWith("Canvas save failed:")) {
        set({ loadError: null });
      }
    } catch (error) {
      set({
        loadError: `Canvas save failed: ${
          error instanceof Error ? error.message : "unknown error"
        }`,
      });
    }
  },

  loadCatalog: async () => {
    try {
      const [providers, status, fieldOptions, executions] = await Promise.all([
        fetchTools(),
        fetchStatus(),
        fetchOptions().catch(() => ({})),
        fetchStudioExecutions().catch(() => []),
      ]);
      set({ providers, status, fieldOptions, executions, loadError: null });
    } catch (error) {
      set({ loadError: error instanceof Error ? error.message : "Could not load tools." });
    }
  },

  refreshExecutions: async () => {
    try {
      set({ executions: await fetchStudioExecutions(), loadError: null });
    } catch (error) {
      set({ loadError: error instanceof Error ? error.message : "Could not load agent jobs." });
    }
  },

  setProjectName: (name) => {
    set({ projectName: name || "Untitled" });
    get().persist();
  },

  switchProject: async (id) => {
    await get().persist();
    try {
      const snapshot = await fetchStudioCanvas(id);
      persistedRevision = snapshot.revision;
      const graph = graphFromDocument(snapshot.document);
      const migratedAgentPresentation = needsAgentPresentationMigration(snapshot.document);
      const project = get().projects.find((item) => item.id === id);
      set({
        projectId: id,
        projectName: graph.projectName || project?.name || "Untitled",
        nodes: graph.nodes,
        edges: graph.edges,
        viewport: graph.viewport,
        selectedNodeIds: [],
        past: [],
        future: [],
        loadError: null,
      });
      if (migratedAgentPresentation) {
        window.setTimeout(() => void get().persist(), 0);
      }
    } catch (error) {
      set({ loadError: error instanceof Error ? error.message : "Could not switch project." });
    }
  },

  createProject: async () => {
    await get().persist();
    try {
      const record = await createStudioProject("Untitled");
      persistedRevision = 1;
      set({
        projects: [record, ...get().projects],
        projectId: record.id,
        projectName: "Untitled",
        nodes: [],
        edges: [],
        viewport: { x: 80, y: 80, zoom: 1 },
        selectedNodeIds: [],
        past: [],
        future: [],
        loadError: null,
      });
    } catch (error) {
      set({ loadError: error instanceof Error ? error.message : "Could not create project." });
    }
  },

  setActiveTool: (tool) =>
    set(tool === "agent" ? { activeTool: tool, composerOpen: true } : { activeTool: tool }),
  setInspectorOpen: (open) => set({ inspectorOpen: open }),
  setComposerOpen: (open) => set({ composerOpen: open }),
  toggleAdvanced: () => set({ advancedOpen: !get().advancedOpen }),
  setViewport: (viewport) => {
    const current = get().viewport;
    if (current.x === viewport.x && current.y === viewport.y && current.zoom === viewport.zoom) {
      return;
    }
    set({ viewport });
    if (viewportPersistTimer !== null) {
      window.clearTimeout(viewportPersistTimer);
    }
    viewportPersistTimer = window.setTimeout(() => {
      viewportPersistTimer = null;
      void get().persist();
    }, 350);
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
    const nextSelected = next.filter((node) => node.selected).map((node) => node.id);
    const prevSelected = get().selectedNodeIds;
    const selectionChanged =
      prevSelected.length !== nextSelected.length || prevSelected.some((id, index) => id !== nextSelected[index]);
    set({
      nodes: next,
      selectedNodeIds: selectionChanged ? nextSelected : prevSelected,
      ...(selectionChanged ? { inspectorOpen: nextSelected.length === 1 } : {}),
    });
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

  onSelectionChange: (ids) => {
    const prev = get().selectedNodeIds;
    if (prev.length === ids.length && prev.every((id, index) => id === ids[index])) {
      return;
    }
    set({
      selectedNodeIds: ids,
      inspectorOpen: ids.length === 1,
    });
  },

  addCreativeNode: ({ kind, position, toolId, title, config, output }) => {
    get().pushHistory();
    const node = makeNode({
      kind,
      position,
      toolId,
      title,
      config,
      output,
      fieldOptions: get().fieldOptions,
    });
    node.selected = true;
    set({
      nodes: [...get().nodes.map((item) => ({ ...item, selected: false })), node],
      selectedNodeIds: [node.id],
      inspectorOpen: true,
    });
    get().persist();
    return node.id;
  },

  addAgentResult: (result, position) => {
    get().pushHistory();
    const cluster = createAgentRunCluster(result, position, get().fieldOptions);
    const selectedNodeId = cluster.primaryNodeId || cluster.nodes[cluster.nodes.length - 1]?.id;
    set({
      nodes: [
        ...get().nodes.map((item) => ({ ...item, selected: false })),
        ...cluster.nodes,
      ],
      selectedNodeIds: selectedNodeId ? [selectedNodeId] : [],
      inspectorOpen: false,
    });
    get().persist();
    return selectedNodeId || "";
  },

  toggleAgentRun: (id) => {
    const node = get().nodes.find((item) => item.id === id);
    if (!node?.data.agentRun) return;
    get().updateNodeData(id, {
      agentRun: { ...node.data.agentRun, collapsed: !node.data.agentRun.collapsed },
    });
  },

  addUploadNode: async (file, position) => {
    const uploaded = await uploadStudioFile(file, get().projectId);
    const kind = uploaded.kind;
    get().addCreativeNode({
      kind,
      position,
      title: uploaded.filename.replace(/\.[^.]+$/, ""),
      output: uploaded,
      config: {},
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
      data: { ...structuredClone(node.data), approved: false, storyOrder: undefined },
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
      nodes: compactStoryOrders(get().nodes.filter((node) => !ids.has(node.id))),
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

  setApproved: (id, approved) => {
    const node = get().nodes.find((item) => item.id === id);
    if (!node || !isSceneKind(node.data.kind)) {
      return;
    }
    get().pushHistory();
    const storyOrder = approved ? nextStoryOrder(get().nodes) : undefined;
    const next = get().nodes.map((item) =>
      item.id === id ? { ...item, data: { ...item.data, approved, storyOrder } } : item,
    );
    set({ nodes: compactStoryOrders(next) });
    get().persist();
  },

  cycleVariant: (id, direction) => {
    const node = get().nodes.find((item) => item.id === id);
    const variants = node?.data.variants || [];
    if (!node || variants.length < 2) {
      return;
    }
    const current = Math.max(
      0,
      variants.findIndex((item) => item.versionId === node.data.output?.versionId),
    );
    const next = (current + direction + variants.length) % variants.length;
    get().updateNodeData(id, { output: variants[next] });
  },

  moveInSequence: (id, direction) => {
    const sequence = approvedSequence(get().nodes);
    const index = sequence.findIndex((item) => item.id === id);
    const swapWith = sequence[index + direction];
    if (index < 0 || !swapWith) {
      return;
    }
    get().pushHistory();
    const currentOrder = sequence[index]?.data.storyOrder ?? index + 1;
    const otherOrder = swapWith.data.storyOrder ?? index + direction + 1;
    const next = get().nodes.map((node) => {
      if (node.id === id) {
        return { ...node, data: { ...node.data, storyOrder: otherOrder } };
      }
      if (node.id === swapWith.id) {
        return { ...node, data: { ...node.data, storyOrder: currentOrder } };
      }
      return node;
    });
    set({ nodes: compactStoryOrders(next) });
    get().persist();
  },

  arrangeSequence: () => {
    const sequence = approvedSequence(get().nodes);
    if (sequence.length === 0) {
      return;
    }
    get().pushHistory();
    const originY = sequence[0]?.position.y ?? 80;
    const placed = new Map(
      sequence.map((node, index) => [
        node.id,
        { x: 80 + index * (SCENE_CARD_WIDTH + SCENE_CARD_GAP), y: originY },
      ]),
    );
    set({
      nodes: get().nodes.map((node) => {
        const position = placed.get(node.id);
        return position ? { ...node, position } : node;
      }),
    });
    get().persist();
  },

  startSequence: (origin) => {
    get().pushHistory();
    const created = [0, 1, 2].map((index) => {
      const node = makeNode({
        kind: "image",
        position: { x: origin.x + index * (SCENE_CARD_WIDTH + SCENE_CARD_GAP), y: origin.y },
        toolId: "image.generate",
        title: `Scene ${index + 1}`,
        fieldOptions: get().fieldOptions,
      });
      return node;
    });
    const last = created[created.length - 1];
    if (last) {
      last.selected = true;
    }
    set({
      nodes: [...get().nodes.map((node) => ({ ...node, selected: false })), ...created],
      selectedNodeIds: last ? [last.id] : [],
      inspectorOpen: Boolean(last),
    });
    get().persist();
  },

  focusNode: (id) => {
    if (!get().nodes.some((node) => node.id === id)) {
      return;
    }
    set({
      nodes: get().nodes.map((node) => ({ ...node, selected: node.id === id })),
      selectedNodeIds: [id],
      inspectorOpen: true,
    });
  },

  runNode: async (id) => {
    const node = get().nodes.find((item) => item.id === id);
    if (!node) {
      return;
    }
    get().updateNodeData(id, { status: "running", error: undefined });
    try {
      const patch = await runCreativeNode(node, get().nodes, get().edges, get().projectId);
      get().updateNodeData(id, patch);
      if (patch.status === "queued" && patch.jobId) {
        const tick = async () => {
          const current = get().nodes.find((item) => item.id === id);
          if (!current) {
            return;
          }
          try {
            const next = await pollCreativeNode(current, get().projectId);
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
