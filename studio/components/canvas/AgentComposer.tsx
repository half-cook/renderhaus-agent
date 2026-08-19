"use client";

import { AtSign, ChevronDown, Paperclip, Send, Square } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { submitAgentPrompt } from "@/lib/api";
import { useCanvasStore } from "@/lib/canvas/store";

export function AgentComposer() {
  const nodes = useCanvasStore((state) => state.nodes);
  const selectedNodeIds = useCanvasStore((state) => state.selectedNodeIds);
  const composerMessage = useCanvasStore((state) => state.composerMessage);
  const composerOpen = useCanvasStore((state) => state.composerOpen);
  const setComposerMessage = useCanvasStore((state) => state.setComposerMessage);
  const setComposerOpen = useCanvasStore((state) => state.setComposerOpen);
  const setActiveTool = useCanvasStore((state) => state.setActiveTool);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
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
    const result = await submitAgentPrompt(prompt, refs.length > 0 ? refs : selectedNodeIds);
    setComposerMessage(result.message);
    setBusy(false);
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
        <button className="icon-btn" type="button" disabled title="Attachments are not connected yet">
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
        <button className="icon-btn" type="button" title="Mention a node" onClick={() => setValue((current) => `${current}@`)}>
          <AtSign size={16} />
        </button>
        <button
          className="send-btn"
          type="button"
          aria-label={busy ? "Stop" : "Send"}
          onClick={() => {
            void submit();
          }}
        >
          {busy ? <Square size={14} /> : <Send size={14} />}
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
        <span>{busy ? "Sending" : "Agent is not connected yet"}</span>
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
