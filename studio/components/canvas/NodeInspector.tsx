"use client";

import { ChevronDown, ChevronRight, PanelRightClose, PanelRightOpen } from "lucide-react";
import { SchemaForm } from "@/components/forms/SchemaForm";
import { PRIMARY_FIELD_ORDER } from "@/lib/canvas/field-labels";
import { schemaFor } from "@/lib/canvas/types";
import { selectedNode, useCanvasStore } from "@/lib/canvas/store";
import { toolById } from "@/lib/canvas/tool-registry";

export function NodeInspector() {
  const nodes = useCanvasStore((state) => state.nodes);
  const selectedNodeIds = useCanvasStore((state) => state.selectedNodeIds);
  const providers = useCanvasStore((state) => state.providers);
  const fieldOptions = useCanvasStore((state) => state.fieldOptions);
  const inspectorOpen = useCanvasStore((state) => state.inspectorOpen);
  const advancedOpen = useCanvasStore((state) => state.advancedOpen);
  const edges = useCanvasStore((state) => state.edges);
  const setInspectorOpen = useCanvasStore((state) => state.setInspectorOpen);
  const toggleAdvanced = useCanvasStore((state) => state.toggleAdvanced);
  const updateNodeConfig = useCanvasStore((state) => state.updateNodeConfig);
  const updateNodeData = useCanvasStore((state) => state.updateNodeData);
  const runNode = useCanvasStore((state) => state.runNode);
  const node = selectedNode(nodes, selectedNodeIds);

  if (!inspectorOpen) {
    return (
      <button className="inspector-toggle" type="button" aria-label="Open inspector" onClick={() => setInspectorOpen(true)}>
        <PanelRightOpen size={16} />
      </button>
    );
  }

  if (!node) {
    return (
      <aside className="inspector">
        <header className="inspector-head">
          <h2>Inspector</h2>
          <button className="icon-btn" type="button" aria-label="Close inspector" onClick={() => setInspectorOpen(false)}>
            <PanelRightClose size={16} />
          </button>
        </header>
        <p className="inspector-empty">Select a node to edit its settings.</p>
      </aside>
    );
  }

  const tool = toolById(node.data.toolId);
  const schema = schemaFor(providers, node.data.providerId, node.data.toolName);
  const connectedFields = edges
    .filter((edge) => edge.target === node.id)
    .map((edge) => edge.data?.targetField)
    .filter((field): field is string => Boolean(field));
  const primary = (tool?.primaryFields || PRIMARY_FIELD_ORDER).filter(
    (field) => schema?.inputSchema.properties?.[field] && !connectedFields.includes(field),
  );
  const advanced = Object.keys(schema?.inputSchema.properties || {}).filter(
    (field) => !primary.includes(field) && !connectedFields.includes(field),
  );

  return (
    <aside className="inspector">
      <header className="inspector-head">
        <h2>{node.data.title}</h2>
        <button className="icon-btn" type="button" aria-label="Close inspector" onClick={() => setInspectorOpen(false)}>
          <PanelRightClose size={16} />
        </button>
      </header>
      <label className="field">
        <span>Title</span>
        <input value={node.data.title} onChange={(event) => updateNodeData(node.id, { title: event.target.value })} />
      </label>
      {connectedFields.length > 0 ? (
        <p className="inspector-note">Some inputs come from connected nodes.</p>
      ) : null}
      {node.data.kind === "text" ? (
        <label className="field">
          <span>Prompt</span>
          <textarea
            value={String(node.data.config.prompt ?? "")}
            onChange={(event) => updateNodeConfig(node.id, "prompt", event.target.value)}
          />
        </label>
      ) : null}
      {schema ? (
        <>
          <SchemaForm
            schema={schema.inputSchema}
            values={node.data.config}
            options={node.data.providerId ? fieldOptions[node.data.providerId] : undefined}
            onlyFields={primary}
            hiddenFields={connectedFields}
            onChange={(name, value) => updateNodeConfig(node.id, name, value)}
          />
          {advanced.length > 0 ? (
            <section className="advanced">
              <button className="advanced-toggle" type="button" onClick={toggleAdvanced}>
                {advancedOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                Advanced
              </button>
              {advancedOpen ? (
                <SchemaForm
                  schema={schema.inputSchema}
                  values={node.data.config}
                  options={node.data.providerId ? fieldOptions[node.data.providerId] : undefined}
                  onlyFields={advanced}
                  hiddenFields={connectedFields}
                  onChange={(name, value) => updateNodeConfig(node.id, name, value)}
                />
              ) : null}
            </section>
          ) : null}
        </>
      ) : null}
      {node.data.toolId ? (
        <button
          className="generate-lg"
          type="button"
          disabled={node.data.status === "running" || node.data.status === "queued"}
          onClick={() => {
            void runNode(node.id);
          }}
        >
          {node.data.output ? "Regenerate" : "Generate"}
        </button>
      ) : null}
      {node.data.error ? <p className="node-error">{node.data.error}</p> : null}
    </aside>
  );
}
