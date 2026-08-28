"use client";

import { useReactFlow } from "@xyflow/react";
import { AtSign, ChevronDown, LoaderCircle, Paperclip, Send } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { submitAgentPrompt } from "@/lib/api";
import { useCanvasStore } from "@/lib/canvas/store";

export function AgentComposer() {
  const nodes = useCanvasStore((state) => state.nodes);
  const projectId = useCanvasStore((state) => state.projectId);
  const selectedNodeIds = useCanvasStore((state) => state.selectedNodeIds);
  const composerMessage = useCanvasStore((state) => state.composerMessage);
  const composerOpen = useCanvasStore((state) => state.composerOpen);
  const setComposerMessage = useCanvasStore((state) => state.setComposerMessage);
  const setComposerOpen = useCanvasStore((state) => state.setComposerOpen);
  const setActiveTool = useCanvasStore((state) => state.setActiveTool);
  const addAgentResult = useCanvasStore((state) => state.addAgentResult);
  const refreshExecutions = useCanvasStore((state) => state.refreshExecutions);
  const status = useCanvasStore((state) => state.status);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const { screenToFlowPosition } = useReactFlow();
  const mentions = useMemo(
    () => nodes.filter((node) => value.includes(`@${node.data.title.replaceAll(" ", "")}`)),
    [nodes, value],
  );

  useEffect(() => {
    if (composerOpen) {
      inputRef.current?.focus();
    }
  }, [composerOpen]);

  const submit = async () => {
    const prompt = value.trim();
    if (!prompt || busy) {
      return;
    }
    setBusy(true);
    setComposerMessage(null);
    const refs = mentions.map((node) => node.id);
    const ids = refs.length > 0 ? refs : selectedNodeIds;
    const referencedNodes = nodes.filter((node) => ids.includes(node.id));
    const contexts = referencedNodes.map((node) => {
      const promptValue = ["prompt", "text", "script", "lyrics"]
        .map((key) => node.data.config[key])
        .find((item): item is string => typeof item === "string" && item.trim().length > 0);
      return {
        id: node.id,
        title: node.data.title,
        kind: node.data.kind,
        prompt: promptValue || node.data.agentResult?.markdown || "",
        ...(node.data.output
          ? {
              asset_id: node.data.output.assetId,
              version_id: node.data.output.versionId,
            }
          : {}),
      };
    });
    try {
      const result = await submitAgentPrompt(
        prompt,
        projectId,
        ids,
        contexts,
        setComposerMessage,
        (_delta, fullText) => {
          setComposerMessage(`Streaming response (${fullText.length} chars)...`);
        },
      );
      setComposerMessage(result.message);
      const completedResult = result.result;
      if (completedResult) {
        const position = referencedNodes.length
          ? {
              x: Math.max(...referencedNodes.map((node) => node.position.x)) + 440,
              y: Math.min(...referencedNodes.map((node) => node.position.y)),
            }
          : (() => {
              const pane = document.querySelector(".react-flow");
              const rect = pane?.getBoundingClientRect();
              const center = screenToFlowPosition({
                x: (rect?.left || 0) + (rect?.width || 800) / 2,
                y: (rect?.top || 0) + (rect?.height || 600) / 2,
              });
              return { x: center.x - 210, y: center.y - 180 };
            })();
        addAgentResult(completedResult, position);
        setValue("");
      }
    } catch (error) {
      setComposerMessage(error instanceof Error ? error.message : "The agent could not run.");
    } finally {
      await refreshExecutions();
      setBusy(false);
    }
  };

  if (!composerOpen) {
    return (
      <div className="composer collapsed" id="agent-composer">
        <button
          className="composer-open-btn"
          type="button"
          onClick={() => {
            setComposerOpen(true);
            setActiveTool("agent");
          }}
        >
          Ask the agent
        </button>
      </div>
    );
  }

  return (
    <div className="composer" id="agent-composer">
      <div className="composer-row">
        <button
          className="icon-btn"
          type="button"
          disabled
          aria-label="Attachments are not connected yet"
          title="Attachments are not connected yet"
        >
          <Paperclip size={16} />
        </button>
        <textarea
          ref={inputRef}
          value={value}
          placeholder="Describe a change, or @ a node"
          rows={2}
          onFocus={() => setActiveTool("agent")}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void submit();
            }
          }}
        />
        <button
          className="icon-btn"
          type="button"
          aria-label="Mention a node"
          title="Mention a node"
          onClick={() => setValue((current) => `${current}@`)}
        >
          <AtSign size={16} />
        </button>
        <button
          className="send-btn"
          type="button"
          aria-label={busy ? "Agent is working" : "Send to agent"}
          disabled={busy || !status?.agent}
          onClick={() => {
            void submit();
          }}
        >
          {busy ? <LoaderCircle className="spin" size={14} /> : <Send size={14} />}
        </button>
      </div>
      {nodes.length > 0 && value.includes("@") ? (
        <div className="mention-list">
          {nodes.slice(0, 6).map((node) => (
            <button
              key={node.id}
              type="button"
              onClick={() => setValue((current) => `${current.replace(/@$/, "")}@${node.data.title.replaceAll(" ", "")} `)}
            >
              {node.data.title}
            </button>
          ))}
        </div>
      ) : null}
      <div className="composer-meta">
        <span>{busy ? "Choosing tools and building the result" : status?.agent ? "OpenAI agent ready" : "OpenAI agent unavailable"}</span>
        {composerMessage ? <span className="composer-status">{composerMessage}</span> : null}
        <button
          className="composer-collapse"
          type="button"
          aria-label="Collapse agent"
          onClick={() => setComposerOpen(false)}
        >
          <ChevronDown size={14} />
        </button>
      </div>
    </div>
  );
}
