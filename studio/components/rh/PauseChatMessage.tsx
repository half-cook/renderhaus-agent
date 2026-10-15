"use client";

import { useId, useState } from "react";
import type { AgentQuestionRequest, QuestionAnswer } from "@/lib/api";
import { answeredLine, questionChatModel, replyToAnswer } from "@/lib/rh/pause-fallback";

/** Plain chat rendering of an agent question (launch fallback for mockups 30-31). */
export function PauseChatMessage({ question, active, busy, onAnswer }: {
  question: AgentQuestionRequest;
  active: boolean;
  busy: boolean;
  onAnswer: (answer: QuestionAnswer) => void;
}) {
  const fieldId = useId();
  const [reply, setReply] = useState("");
  const [error, setError] = useState("");
  if (question.decision || !active) {
    return <p className="agent-response-summary rh-fg3">{question.question} — {answeredLine(question)}</p>;
  }
  const model = questionChatModel(question);
  const send = (answer: QuestionAnswer) => {
    setError("");
    onAnswer(answer);
  };
  return <div className="agent-response-summary" role="group" aria-labelledby={`${fieldId}-q`}>
    <p id={`${fieldId}-q`}>{model.text}</p>
    {model.options.length ? <ol style={{ listStyle: "none", padding: 0, margin: "8px 0", display: "grid", gap: 6 }}>
      {model.options.map((option) => <li key={option.id}>
        <button type="button" className="rh-btn" disabled={busy} onClick={() => send({ kind: "choice", option_id: option.id })}
          style={{ height: "auto", whiteSpace: "normal", textAlign: "left", width: "100%", padding: 10 }}>
          <strong>{option.letter}. {option.label}</strong>{option.price ? <span className="rh-money"> · {option.price}</span> : null}
          {option.description ? <span className="rh-fg3 rh-small" style={{ display: "block" }}>{option.description}</span> : null}
        </button>
      </li>)}
    </ol> : null}
    <form style={{ display: "flex", gap: 8 }} onSubmit={(event) => {
      event.preventDefault();
      if (busy) return;
      const answer = replyToAnswer(model, reply);
      if ("error" in answer) setError(answer.error);
      else send(answer);
    }}>
      <label htmlFor={fieldId} className="sr-only">Your reply</label>
      <input id={fieldId} value={reply} onChange={(event) => setReply(event.target.value)} maxLength={2000}
        placeholder={model.placeholder} disabled={busy} autoComplete="off"
        style={{ flex: 1, padding: 8, color: "inherit", background: "transparent", border: "1px solid var(--line)" }} />
      <button type="submit" className="rh-btn rh-btn-primary" disabled={busy || !reply.trim()}>{busy ? "Sending…" : "Reply"}</button>
    </form>
    {error ? <p role="alert" className="rh-small">{error}</p> : null}
    <p className="rh-fg3 rh-small">{model.footnote}</p>
  </div>;
}
