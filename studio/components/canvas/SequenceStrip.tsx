"use client";

import { useReactFlow } from "@xyflow/react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { approvedSequence } from "@/lib/canvas/story";
import { useCanvasStore } from "@/lib/canvas/store";
import { AssetMedia } from "./AssetMedia";

export function SequenceStrip() {
  const nodes = useCanvasStore((state) => state.nodes);
  const selectedNodeIds = useCanvasStore((state) => state.selectedNodeIds);
  const focusNode = useCanvasStore((state) => state.focusNode);
  const moveInSequence = useCanvasStore((state) => state.moveInSequence);
  const arrangeSequence = useCanvasStore((state) => state.arrangeSequence);
  const { setCenter } = useReactFlow();
  const sequence = approvedSequence(nodes);

  return (
    <section className="sequence-strip" aria-label="Approved sequence">
      <header className="sequence-strip-head">
        <h2>Sequence</h2>
        <span>{sequence.length === 0 ? "None approved" : `${sequence.length} approved`}</span>
      </header>
      <ol className="sequence-strip-list">
        {sequence.length === 0 ? (
          <li className="sequence-empty">Approve a scene to lock it into playback order.</li>
        ) : (
          sequence.map((node, index) => {
            const selected = selectedNodeIds.length === 1 && selectedNodeIds[0] === node.id;
            return (
              <li key={node.id} className={selected ? "selected" : ""}>
                <button
                  className="sequence-shot"
                  type="button"
                  aria-current={selected ? "true" : undefined}
                  onClick={() => {
                    focusNode(node.id);
                    void setCenter(node.position.x + 190, node.position.y + 120, { zoom: 0.9, duration: 200 });
                  }}
                >
                  {node.data.output ? (
                    <AssetMedia asset={node.data.output} className="sequence-shot-media" alt="" muted />
                  ) : (
                    <span className="sequence-shot-empty" />
                  )}
                  <span>
                    {index + 1}. {node.data.title}
                  </span>
                </button>
                <div className="sequence-reorder">
                  <button
                    className="icon-btn"
                    type="button"
                    aria-label={`Move ${node.data.title} earlier`}
                    disabled={index === 0}
                    onClick={() => moveInSequence(node.id, -1)}
                  >
                    <ChevronLeft size={14} />
                  </button>
                  <button
                    className="icon-btn"
                    type="button"
                    aria-label={`Move ${node.data.title} later`}
                    disabled={index === sequence.length - 1}
                    onClick={() => moveInSequence(node.id, 1)}
                  >
                    <ChevronRight size={14} />
                  </button>
                </div>
              </li>
            );
          })
        )}
      </ol>
      <button
        className="text-btn"
        type="button"
        aria-label="Arrange sequence"
        disabled={sequence.length === 0}
        title={
          sequence.length === 0
            ? "Approve a scene to arrange the sequence"
            : "Arrange approved scenes left to right"
        }
        onClick={arrangeSequence}
      >
        Arrange
      </button>
    </section>
  );
}
