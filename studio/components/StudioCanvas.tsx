"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ToolNodeCard } from "./ToolNodeCard";
import { fetchOptions, fetchStatus, fetchTools, invokeTool } from "@/lib/api";
import type { FieldOptions, ProviderCatalog, StudioStatus, ToolNode, ToolSchema, Viewport } from "@/lib/types";

function uid(): string {
  return crypto.randomUUID();
}

const PREFERRED_DEFAULTS: Record<string, Record<string, string | number>> = {
  seedance: {
    duration_seconds: 5,
    aspect_ratio: "16:9",
    resolution: "720p",
  },
  seedream: {
    aspect_ratio: "1:1",
    size: "2K",
    response_format: "url",
  },
  mureka: {
    model: "auto",
  },
  gemini_tts: {
    voice: "Zephyr",
    output_format: "wav",
  },
};

function defaultsFor(
  tool: ToolSchema,
  providerId: string,
  fieldOptions: FieldOptions,
): Record<string, unknown> {
  const args: Record<string, unknown> = {};
  const properties = tool.inputSchema.properties || {};
  const required = new Set(tool.inputSchema.required || []);
  const catalog = fieldOptions[providerId] || {};
  const preferred = PREFERRED_DEFAULTS[providerId] || {};
  for (const [name, field] of Object.entries(properties)) {
    if (field.type === "boolean") {
      args[name] = false;
      continue;
    }
    const choices = catalog[name] || field.enum || [];
    if (choices.length === 0) {
      continue;
    }
    const wanted = preferred[name];
    if (wanted !== undefined && choices.some((choice) => String(choice) === String(wanted))) {
      args[name] = wanted;
    } else if (required.has(name)) {
      args[name] = choices[0];
    }
  }
  return args;
}

export function StudioCanvas() {
  const [providers, setProviders] = useState<ProviderCatalog[]>([]);
  const [fieldOptions, setFieldOptions] = useState<FieldOptions>({});
  const [status, setStatus] = useState<StudioStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [nodes, setNodes] = useState<ToolNode[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [viewport, setViewport] = useState<Viewport>({ x: 80, y: 80, zoom: 1 });
  const [panning, setPanning] = useState(false);
  const [menu, setMenu] = useState<{
    x: number;
    y: number;
    worldX: number;
    worldY: number;
    providerId?: string;
  } | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const dragOrigin = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);
  const nodeOrigin = useRef<Record<string, { x: number; y: number }>>({});

  useEffect(() => {
    Promise.all([fetchTools(), fetchStatus()])
      .then(([nextProviders, nextStatus]) => {
        setProviders(nextProviders);
        setStatus(nextStatus);
      })
      .catch((error: Error) => setLoadError(error.message));
    fetchOptions()
      .then(setFieldOptions)
      .catch(() => undefined);
  }, []);

  const liveFlags = useMemo(() => {
    if (!status) {
      return [];
    }
    return Object.entries(status.dry_run).map(([id, dry]) => ({ id, dry }));
  }, [status]);

  const screenToWorld = (clientX: number, clientY: number) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    const left = rect?.left ?? 0;
    const top = rect?.top ?? 0;
    return {
      x: (clientX - left - viewport.x) / viewport.zoom,
      y: (clientY - top - viewport.y) / viewport.zoom,
    };
  };

  const addNode = (provider: ProviderCatalog, tool: ToolSchema, worldX: number, worldY: number) => {
    const node: ToolNode = {
      id: uid(),
      providerId: provider.id,
      providerName: provider.name,
      tool,
      x: worldX + nodes.length * 36,
      y: worldY + nodes.length * 28,
      args: defaultsFor(tool, provider.id, fieldOptions),
      status: "idle",
      result: null,
      assets: [],
      error: null,
    };
    setNodes((current) => [...current, node]);
    setSelectedId(node.id);
    setMenu(null);
  };

  const runNode = async (node: ToolNode) => {
    setNodes((current) =>
      current.map((item) =>
        item.id === node.id ? { ...item, status: "running", error: null } : item,
      ),
    );
    try {
      const payload = await invokeTool(node.providerId, node.tool.name, node.args);
      setNodes((current) =>
        current.map((item) =>
          item.id === node.id
            ? { ...item, status: "ok", result: payload.result, assets: payload.assets, error: null }
            : item,
        ),
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "invoke failed";
      setNodes((current) =>
        current.map((item) =>
          item.id === node.id ? { ...item, status: "error", error: message } : item,
        ),
      );
    }
  };

  return (
    <div className="app">
      <div
        ref={canvasRef}
        className={panning ? "canvas panning" : "canvas"}
        onPointerDown={(event) => {
          if (event.button !== 0) {
            return;
          }
          if ((event.target as HTMLElement).closest(".node, .menu, .topbar, .toolbar, .zoombar")) {
            return;
          }
          setMenu(null);
          setSelectedId(null);
          setPanning(true);
          dragOrigin.current = { x: event.clientX, y: event.clientY, vx: viewport.x, vy: viewport.y };
        }}
        onPointerMove={(event) => {
          if (!dragOrigin.current) {
            return;
          }
          setViewport((current) => ({
            ...current,
            x: dragOrigin.current!.vx + (event.clientX - dragOrigin.current!.x),
            y: dragOrigin.current!.vy + (event.clientY - dragOrigin.current!.y),
          }));
        }}
        onPointerUp={() => {
          dragOrigin.current = null;
          setPanning(false);
        }}
        onWheel={(event) => {
          event.preventDefault();
          const factor = event.deltaY > 0 ? 0.92 : 1.08;
          const nextZoom = Math.min(2.2, Math.max(0.35, viewport.zoom * factor));
          const rect = canvasRef.current?.getBoundingClientRect();
          const px = event.clientX - (rect?.left ?? 0);
          const py = event.clientY - (rect?.top ?? 0);
          const worldX = (px - viewport.x) / viewport.zoom;
          const worldY = (py - viewport.y) / viewport.zoom;
          setViewport({
            zoom: nextZoom,
            x: px - worldX * nextZoom,
            y: py - worldY * nextZoom,
          });
        }}
        onDoubleClick={(event) => {
          if ((event.target as HTMLElement).closest(".node, .menu")) {
            return;
          }
          const world = screenToWorld(event.clientX, event.clientY);
          setMenu({ x: event.clientX, y: event.clientY, worldX: world.x, worldY: world.y });
        }}
        onContextMenu={(event) => {
          event.preventDefault();
          const world = screenToWorld(event.clientX, event.clientY);
          setMenu({ x: event.clientX, y: event.clientY, worldX: world.x, worldY: world.y });
        }}
      >
        <div
          className="canvas-world"
          style={{ transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})` }}
        >
          {nodes.map((node) => (
            <ToolNodeCard
              key={node.id}
              node={node}
              selected={node.id === selectedId}
              options={fieldOptions[node.providerId]}
              onSelect={() => {
                setSelectedId(node.id);
                nodeOrigin.current[node.id] = { x: node.x, y: node.y };
              }}
              onMove={(dx, dy) => {
                const origin = nodeOrigin.current[node.id] || { x: node.x, y: node.y };
                setNodes((current) =>
                  current.map((item) =>
                    item.id === node.id
                      ? {
                          ...item,
                          x: origin.x + dx / viewport.zoom,
                          y: origin.y + dy / viewport.zoom,
                        }
                      : item,
                  ),
                );
              }}
              onChange={(name, value) => {
                setNodes((current) =>
                  current.map((item) =>
                    item.id === node.id ? { ...item, args: { ...item.args, [name]: value } } : item,
                  ),
                );
              }}
              onRun={() => {
                void runNode(node);
              }}
              onDelete={() => setNodes((current) => current.filter((item) => item.id !== node.id))}
            />
          ))}
        </div>
        {nodes.length === 0 ? (
          <div className="empty">
            <div>
              <h1>Double-click to add a tool</h1>
              <p>Each node is one MCP function. Fill the parameters, then run it locally.</p>
            </div>
          </div>
        ) : null}
      </div>

      <header className="topbar">
        <div className="brand">Renderhaus studio</div>
        <div className="hint">local tools, no agent</div>
        <div className="pills">
          {liveFlags.map((flag) => (
            <span key={flag.id} className={flag.dry ? "pill" : "pill live"}>
              {flag.id} {flag.dry ? "dry-run" : "live"}
            </span>
          ))}
        </div>
      </header>

      <nav className="toolbar" aria-label="Add tools">
        {providers.map((provider) => (
          <button
            key={provider.id}
            className="tool-btn"
            title={`Add ${provider.name} tool`}
            type="button"
            onClick={(event) => {
              const world = screenToWorld(event.clientX + 80, event.clientY);
              setMenu({
                x: 72,
                y: Math.max(24, event.clientY - 40),
                worldX: world.x,
                worldY: world.y,
                providerId: provider.id,
              });
            }}
          >
            {provider.name}
          </button>
        ))}
      </nav>

      <div className="zoombar">
        <button type="button" onClick={() => setViewport((current) => ({ ...current, zoom: Math.max(0.35, current.zoom - 0.1) }))}>
          -
        </button>
        {Math.round(viewport.zoom * 100)}%
        <button type="button" onClick={() => setViewport((current) => ({ ...current, zoom: Math.min(2.2, current.zoom + 0.1) }))}>
          +
        </button>
      </div>

      {menu ? (
        <div className="menu" style={{ left: menu.x, top: menu.y }}>
          {loadError ? <p className="status error">{loadError}. Is make web running?</p> : null}
          {(menu.providerId
            ? providers.filter((provider) => provider.id === menu.providerId)
            : providers
          ).map((provider) => (
            <section key={provider.id}>
              <h2>{provider.name}</h2>
              {provider.tools.map((tool) => (
                <button
                  key={tool.name}
                  type="button"
                  onClick={() => addNode(provider, tool, menu.worldX, menu.worldY)}
                >
                  {tool.name}
                  <span className="desc">{tool.description}</span>
                </button>
              ))}
            </section>
          ))}
        </div>
      ) : null}
    </div>
  );
}
