"use client";

import { useId, useState } from "react";
import type { AgentQuestionRequest, QuestionAnswer } from "@/lib/api";

export function QuestionCard({ question, active, busy, onAnswer }: {
  question: AgentQuestionRequest;
  active: boolean;
  busy: boolean;
  onAnswer: (answer: QuestionAnswer) => void;
}) {
  const fieldId = useId();
  const [text, setText] = useState("");
  if (question.decision || !active) {
    const answer = question.answer;
    const answerText = answer?.kind === "choice"
      ? question.options.find((option) => option.id === answer.option_id)?.label
      : answer?.text;
    return <details className="agent-approval-record">
      <summary>{question.decision ? "Answered" : "Closed"} · {question.question}</summary>
      {answerText ? <p>{answerText}</p> : null}
    </details>;
  }
  return <article className="agent-approval" aria-labelledby={`${fieldId}-title`} aria-busy={busy}>
    <header><span>Your answer is needed</span></header>
    <strong id={`${fieldId}-title`}>{question.question}</strong>
    {question.options.length ? <div role="group" aria-label="Choose an answer" style={{ display: "grid", gap: 8, marginTop: 12 }}>
      {question.options.map((option) => <button key={option.id} type="button" className="rh-btn"
        style={{ height: "auto", whiteSpace: "normal", textAlign: "left", display: "grid", gap: 4, padding: 12 }}
        disabled={busy} onClick={() => onAnswer({ kind: "choice", option_id: option.id })}>
        <span>{option.label}</span>
        {option.description ? <span className="rh-fg3 rh-small">{option.description}</span> : null}
      </button>)}
    </div> : null}
    {question.allowFreeText ? <form style={{ display: "grid", gap: 8, marginTop: 12 }} onSubmit={(event) => {
      event.preventDefault();
      if (text.trim() && !busy) onAnswer({ kind: "text", text: text.trim() });
    }}>
      <label htmlFor={fieldId}>{question.options.length ? "Or write your answer" : "Your answer"}</label>
      <textarea id={fieldId} value={text} onChange={(event) => setText(event.target.value)}
        maxLength={2000} rows={3} disabled={busy} required
        style={{ width: "100%", resize: "vertical", padding: 10, color: "inherit", background: "transparent", border: "1px solid var(--line)", borderRadius: 6 }} />
      <button type="submit" className="rh-btn rh-btn-primary" disabled={busy || !text.trim()}>
        {busy ? "Saving answer…" : "Send answer"}
      </button>
    </form> : null}
  </article>;
}
