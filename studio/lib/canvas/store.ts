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
  createStudioConversation,
  createStudioProject,
  fetchOptions,
  fetchStatus,
  fetchStudioCanvas,
  fetchStudioConversations,
  fetchStudioExecutions,
  fetchStudioProjects,
  fetchTools,
  saveStudioCanvas,
  updateStudioConversation,
  uploadStudioFile,
  type StudioCanvasDocument,
  type StudioExecution,
  type StudioConversation,
} from "@/lib/api";
import type { FieldOptions, ProviderCatalog, StudioAsset, StudioStatus } from "@/lib/types";
import {
  edgeAlreadyOccupiesHandle,
  isCompatibleConnection,
  type CanvasEdge,
  type CanvasNode,
} from "./connection-validation";
import { pollCreativeNode, runCreativeNode } from "./graph-execution";
import { approvedSequence, isSceneKind, SCENE_CARD_GAP, SCENE_CARD_WIDTH } from "./story";
import { defaultToolForRail, toolById, toolForAgentArtifact } from "./tool-registry";
import {
  schemaFor,
  type AgentToolEvent,
  type CanvasNodeData,
  type CreativeNodeKind,
  type JobStatus,
  type ProjectRecord,
  type RailTool,
  type ToolDefinition,
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
  asciiPanelOpen: boolean;
  agentOpen: boolean;
  advancedOpen: boolean;
  connectionHint: string | null;
  agentMessage: string | null;
  providers: ProviderCatalog[];
  fieldOptions: FieldOptions;
  status: StudioStatus | null;
  executions: StudioExecution[];
  conversations: StudioConversation[];
  conversationId: string | null;
  loadError: string | null;
  hydrated: boolean;
  past: Snapshot[];
  future: Snapshot[];
  hydrate: () => Promise<void>;
  loadCatalog: () => Promise<void>;
  refreshExecutions: () => Promise<void>;
  refreshConversations: () => Promise<void>;
  createAgentConversation: () => Promise<void>;
  switchAgentConversation: (id: string) => Promise<void>;
  renameAgentConversation: (id: string, title: string) => Promise<void>;
  archiveAgentConversation: (id: string) => Promise<void>;
  setProjectName: (name: string) => void;
  switchProject: (id: string) => Promise<void>;
  createProject: () => Promise<void>;
  setActiveTool: (tool: RailTool) => void;
  setInspectorOpen: (open: boolean) => void;
  setAsciiPanelOpen: (open: boolean) => void;
  setAgentOpen: (open: boolean) => void;
  arrangeSequence: () => void;
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
  placeAgentAsset: (input: {
    asset: StudioAsset;
    position: { x: number; y: number };
    title?: string;
    executionId?: string;
    prompt?: string;
    toolEvent?: AgentToolEvent;
  }) => string;
  addUploadNode: (file: File, position: { x: number; y: number }) => Promise<void>;
  updateNodeData: (id: string, patch: Partial<CanvasNode["data"]>) => void;
  updateNodeConfig: (id: string, name: string, value: unknown) => void;
  duplicateSelected: () => void;
  deleteSelected: () => void;
  connectImageToVideo: (imageNodeId: string) => void;
  addToStoryboard: (mediaNodeId: string) => void;
  cycleVariant: (id: string, direction: 1 | -1) => void;
  focusNode: (id: string) => void;
  runNode: (id: string) => Promise<void>;
  undo: () => void;
  redo: () => void;
  pushHistory: () => void;
  persist: () => Promise<void>;
  setAgentMessage: (message: string | null) => void;
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

function configForAgentArtifact(
  tool: ToolDefinition | undefined,
  event: AgentToolEvent | undefined,
  fallbackPrompt: string | undefined,
  providers: ProviderCatalog[],
): Record<string, unknown> | undefined {
  if (!tool) return undefined;
  const schema = schemaFor(providers, tool.providerId, tool.toolName);
  const allowedFields = new Set(
    Object.keys(schema?.inputSchema.properties || {}).length
      ? Object.keys(schema?.inputSchema.properties || {})
      : tool.primaryFields,
  );
  const config = Object.fromEntries(
    Object.entries(event?.arguments || {}).filter(
      ([name, value]) => allowedFields.has(name) && value !== undefined && value !== null,
    ),
  );
  const promptField = tool.id === "voice.generate" ? "text" : "prompt";
  if (!String(config[promptField] || "").trim() && fallbackPrompt?.trim()) {
    config[promptField] = fallbackPrompt.trim();
  }
  return config;
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
  return migrateAgentPresentationToDock(graph);
}

function needsAgentPresentationMigration(document: StudioCanvasDocument): boolean {
  return document.nodes.some((node) => {
    if (!node || typeof node !== "object") return false;
    const data = (node as { data?: CanvasNodeData }).data;
    if (!data) return false;
    if (data.kind === "agentResult" || data.kind === "agentRun") return true;
    if (data.agentRunId && data.output && !data.toolId) return true;
    const agentOutput = Boolean(data.agentRun || data.agentRunId || data.agentRole);
    return (
      data.agentRole === "final" ||
      Boolean(data.agentRun?.finalNodeId && !data.agentRun.primaryNodeId) ||
      (agentOutput && typeof data.title === "string" && data.title.startsWith("Final · "))
    );
  });
}

function migrateAgentPresentationToDock(graph: PersistedGraph): PersistedGraph {
  const removedIds = new Set(
    graph.nodes
      .filter((node) => node.data.kind === "agentResult" || node.data.kind === "agentRun")
      .map((node) => node.id),
  );
  let changed = removedIds.size > 0;
  const nodes = graph.nodes.filter((node) => !removedIds.has(node.id)).map((node) => {
    const data = node.data;
    const legacyPrimaryNodeId = data.agentRun?.finalNodeId;
    const shouldMigrateRun = Boolean(legacyPrimaryNodeId && !data.agentRun?.primaryNodeId);
    const shouldMigrateRole = data.agentRole === "final";
    const shouldMigrateTitle =
      Boolean(data.agentRun || data.agentRunId || data.agentRole) && data.title.startsWith("Final · ");
    const shouldNormalizeArtifact = Boolean(data.agentRunId && data.output && !data.toolId);
    if (
      !shouldMigrateRun &&
      !shouldMigrateRole &&
      !shouldMigrateTitle &&
      !shouldNormalizeArtifact
    ) return node;
    changed = true;
    const migratedRun =
      shouldMigrateRun && data.agentRun && legacyPrimaryNodeId
        ? { ...data.agentRun, primaryNodeId: legacyPrimaryNodeId, finalNodeId: undefined }
        : undefined;
    const artifactTool = shouldNormalizeArtifact && data.output
      ? toolForAgentArtifact(data.output.kind)
      : undefined;
    return {
      ...node,
      data: {
        ...data,
        ...(migratedRun ? { agentRun: migratedRun } : {}),
        ...(shouldMigrateRole ? { agentRole: "primary" as const } : {}),
        ...(shouldMigrateTitle ? { title: `Result · ${data.title.slice("Final · ".length)}` } : {}),
        ...(artifactTool
          ? {
              toolId: artifactTool.id,
              providerId: artifactTool.providerId,
              toolName: artifactTool.toolName,
              config: { ...defaultsFor(artifactTool, {}), ...data.config },
            }
          : {}),
      },
    };
  });
  return changed
    ? {
        ...graph,
        nodes,
        edges: graph.edges.filter(
          (edge) => !removedIds.has(edge.source) && !removedIds.has(edge.target),
        ),
      }
    : graph;
}

function makeNode(input: {
  kind: CreativeNodeKind;
  position: { x: number; y: number };
  toolId?: string;
  title?: string;
  config?: Record<string, unknown>;
  output?: StudioAsset;
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
      config: tool
        ? { ...defaultsFor(tool, input.fieldOptions), ...(input.config || {}) }
        : input.config || {},
      output: input.output,
      variants: input.output ? [input.output] : [],
      status: input.output ? "completed" : "idle",
    },
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
  asciiPanelOpen: false,
  agentOpen: false,
  advancedOpen: false,
  connectionHint: null,
  agentMessage: null,
  providers: [],
  fieldOptions: {},
  status: null,
  executions: [],
  conversations: [],
  conversationId: null,
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
      // The dashboard links to a specific project via ?project=<id> (e.g.
      // opening a card, or right after creating a new one) -- honor that
      // over the legacy-migration guess below when it matches a real project.
      const requestedId =
        typeof window !== "undefined"
          ? new URLSearchParams(window.location.search).get("project")
          : null;
      const project =
        (requestedId && projects.find((candidate) => candidate.id === requestedId)) ||
        projects.find((candidate) => candidate.id === legacyProjects[0]?.id) ||
        projects[0];
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
      window.setTimeout(() => void get().refreshConversations(), 0);
    } catch (error) {
      const project = legacyProjects[0] || { id: "untitled", name: "Untitled" };
      const localGraph = readGraph(project.id);
      const graph = localGraph ? migrateAgentPresentationToDock(localGraph) : null;
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

  refreshExecutions: async () => {
    try {
      const { projectId, conversationId } = get();
      const executions = conversationId
        ? await fetchStudioExecutions(projectId, conversationId)
        : [];
      if (get().projectId !== projectId || get().conversationId !== conversationId) return;
      set({ executions, loadError: null });
    } catch (error) {
      set({ loadError: error instanceof Error ? error.message : "Could not load agent jobs." });
    }
  },

  refreshConversations: async () => {
    try {
      const projectId = get().projectId;
      const conversations = await fetchStudioConversations(projectId);
      const current = conversations.find((item) => item.id === get().conversationId);
      const conversationId = current?.id || conversations[0]?.id || null;
      const executions = conversationId
        ? await fetchStudioExecutions(projectId, conversationId)
        : [];
      if (get().projectId !== projectId) return;
      set({ conversations, conversationId, executions, loadError: null });
    } catch (error) {
      set({
        loadError: error instanceof Error ? error.message : "Could not load agent conversations.",
      });
    }
  },

  createAgentConversation: async () => {
    try {
      const conversation = await createStudioConversation(get().projectId);
      set({
        conversations: [conversation, ...get().conversations],
        conversationId: conversation.id,
        executions: [],
        agentMessage: null,
      });
    } catch (error) {
      set({ loadError: error instanceof Error ? error.message : "Could not create conversation." });
    }
  },

  switchAgentConversation: async (id) => {
    if (id === get().conversationId) return;
    set({ conversationId: id, executions: [], agentMessage: null });
    await get().refreshExecutions();
  },

  renameAgentConversation: async (id, title) => {
    try {
      const conversation = await updateStudioConversation(id, { title });
      set({
        conversations: get().conversations.map((item) =>
          item.id === id ? conversation : item,
        ),
      });
    } catch (error) {
      set({ loadError: error instanceof Error ? error.message : "Could not rename conversation." });
    }
  },

  archiveAgentConversation: async (id) => {
    try {
      await updateStudioConversation(id, { status: "archived" });
      set({ conversations: get().conversations.filter((item) => item.id !== id) });
      await get().refreshConversations();
    } catch (error) {
      set({ loadError: error instanceof Error ? error.message : "Could not archive conversation." });
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
        conversations: [],
        conversationId: null,
        executions: [],
        past: [],
        future: [],
        loadError: null,
      });
      window.setTimeout(() => void get().refreshConversations(), 0);
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
        conversations: [],
        conversationId: null,
        executions: [],
        past: [],
        future: [],
        loadError: null,
      });
      window.setTimeout(() => void get().refreshConversations(), 0);
    } catch (error) {
      set({ loadError: error instanceof Error ? error.message : "Could not create project." });
    }
  },

  setActiveTool: (tool) =>
    set(
      tool === "agent"
        ? { activeTool: tool, agentOpen: true, inspectorOpen: false }
        : tool === "ascii"
          ? { activeTool: tool, asciiPanelOpen: true }
          : { activeTool: tool },
    ),
  setInspectorOpen: (open) =>
    set((state) =>
      open
        ? {
            inspectorOpen: true,
            agentOpen: false,
            activeTool: state.activeTool === "agent" ? "select" : state.activeTool,
          }
        : { inspectorOpen: false },
    ),
  setAsciiPanelOpen: (open) => set({ asciiPanelOpen: open }),
  setAgentOpen: (open) =>
    set((state) =>
      open
        ? { agentOpen: true, inspectorOpen: false, activeTool: "agent" }
        : {
            agentOpen: false,
            activeTool: state.activeTool === "agent" ? "select" : state.activeTool,
          },
    ),
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
  setAgentMessage: (message) => set({ agentMessage: message }),

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
      ...(selectionChanged
        ? { inspectorOpen: !get().agentOpen && nextSelected.length === 1 }
        : {}),
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
      inspectorOpen: !get().agentOpen && ids.length === 1,
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
      inspectorOpen: !get().agentOpen,
    });
    get().persist();
    return node.id;
  },

  placeAgentAsset: ({ asset, position, title, executionId, prompt, toolEvent }) => {
    get().pushHistory();
    const tool = toolForAgentArtifact(asset.kind, toolEvent);
    const node = makeNode({
      kind: asset.kind,
      position,
      title,
      toolId: tool?.id,
      config: configForAgentArtifact(tool, toolEvent, prompt, get().providers),
      output: asset,
      fieldOptions: get().fieldOptions,
    });
    node.selected = true;
    if (executionId) {
      node.data.agentRunId = executionId;
      node.data.agentRole = "artifact";
    }
    set({
      nodes: [...get().nodes.map((item) => ({ ...item, selected: false })), node],
      selectedNodeIds: [node.id],
      inspectorOpen: true,
      agentOpen: false,
      activeTool: "select",
    });
    get().persist();
    return node.id;
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
      data: structuredClone(node.data),
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
