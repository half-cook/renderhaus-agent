"use client";

import { AtSign, Paperclip, Send, Square } from "lucide-react";
import { useMemo, useState } from "react";
import { submitAgentPrompt } from "@/lib/api";
import { useCanvasStore } from "@/lib/canvas/store";

export function AgentComposer() {
  const nodes = useCanvasStore((state) => state.nodes);
  const selectedNodeIds = useCanvasStore((state) => state.selectedNodeIds);
  const composerMessage = useCanvasStore((state) => state.composerMessage);
  const setComposerMessage = useCanvasStore((state) => state.setComposerMessage);
  const setActiveTool = useCanvasStore((state) => state.setActiveTool);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const mentions = useMemo(
    () => nodes.filter((node) => value.includes(`@${node.data.title.replaceAll(" ", "")}`)),
    [nodes, value],
  );

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

  return (
    <div className="composer" id="agent-composer">
      <div className="composer-row">
        <button className="icon-btn" type="button" disabled title="Attachments are not connected yet">
          <Paperclip size={16} />
        </button>
        <textarea
          value={value}
          placeholder="Describe what you want to create or change… Use @ to mention a node"
          rows={1}
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
        <span>{busy ? "Sending" : "Agent"}</span>
        {composerMessage ? <span className="composer-status">{composerMessage}</span> : null}
      </div>
    </div>
  );
}
