import type { AgentPendingRequest, AgentQuestionRequest, QuestionAnswer } from "@/lib/api";
import { formatCents } from "./money";

/**
 * Launch fallback for agent pauses.
 *
 * The designed pause screens (mockups 30-40: question card, checking-its-work,
 * check and retry cost lines) are not built yet. Until they ship, every pause is
 * shown as a plain chat message: the question, each option with its estimated
 * price, and a reply box. Set NEXT_PUBLIC_RH_PAUSE_CARDS=true to use the cards.
 */
export function pauseCardsEnabled(env: Record<string, string | undefined> = readEnv()): boolean {
  return (env.NEXT_PUBLIC_RH_PAUSE_CARDS || "").trim().toLowerCase() === "true";
}

function readEnv(): Record<string, string | undefined> {
  // Next inlines NEXT_PUBLIC_* at build time only for this literal access.
  return { NEXT_PUBLIC_RH_PAUSE_CARDS: process.env.NEXT_PUBLIC_RH_PAUSE_CARDS };
}

export type PauseChatOption = { id: string; letter: string; label: string; description: string; price: string };

export type PauseChatModel = {
  callId: string;
  text: string;
  options: PauseChatOption[];
  allowFreeText: boolean;
  placeholder: string;
  footnote: string;
};

const LETTERS = "ABCDEF";

export function questionChatModel(question: AgentQuestionRequest): PauseChatModel {
  const options = question.options.map((option, index) => ({
    id: option.id,
    letter: LETTERS[index] ?? String(index + 1),
    label: option.label,
    description: option.description,
    price: typeof option.estimateCents === "number" ? `est. ${formatCents(option.estimateCents)}` : "",
  }));
  const placeholder = options.length
    ? question.allowFreeText ? `Reply ${options.map((o) => o.letter).join(", ")} or describe what you want` : `Reply ${options.map((o) => o.letter).join(" or ")}`
    : "Type your answer";
  return {
    callId: question.callId,
    text: question.question,
    options,
    allowFreeText: question.allowFreeText || options.length === 0,
    placeholder,
    footnote: "Answering only costs a few cents of planning. Any paid step still asks for your approval first.",
  };
}

/** Maps a typed reply to an answer: "A", "b", "1", "option A" pick an option; anything else is free text. */
export function replyToAnswer(model: PauseChatModel, reply: string): QuestionAnswer | { error: string } {
  const text = reply.trim();
  if (!text) return { error: "Type a reply first." };
  const pick = /^(?:option\s+)?([a-f]|[1-6])[.)]?$/i.exec(text);
  if (pick && model.options.length) {
    const token = pick[1].toUpperCase();
    const option = /\d/.test(token) ? model.options[Number(token) - 1] : model.options.find((o) => o.letter === token);
    if (option) return { kind: "choice", option_id: option.id };
  }
  const named = model.options.find((o) => o.label.trim().toLowerCase() === text.toLowerCase());
  if (named) return { kind: "choice", option_id: named.id };
  if (!model.allowFreeText) return { error: `Reply with ${model.options.map((o) => o.letter).join(" or ")}.` };
  return { kind: "text", text: text.slice(0, 2000) };
}

export function answeredLine(question: AgentQuestionRequest): string {
  const answer = question.answer;
  if (!answer) return question.decision ? "Answered" : "Closed";
  if (answer.kind === "choice") {
    const option = question.options.find((o) => o.id === answer.option_id);
    return `You picked ${option?.label ?? "an option"}${typeof option?.estimateCents === "number" ? ` · est. ${formatCents(option.estimateCents)}` : ""}`;
  }
  return `You replied: ${answer.text}`;
}

/**
 * A run that waits on something the chat cannot show would leave the person stuck.
 * Returns the plain message to show in that case, or null when every pending request is visible.
 */
export function stuckPauseMessage(status: string, pending: AgentPendingRequest[], pausedCap: boolean): string | null {
  if (status !== "awaiting_approval" || pausedCap) return null;
  if (pending.some((item) => !item.decision)) return null;
  return "I'm waiting on a step I can't show here yet. Stop the run to keep your progress and release the held credit, then ask me again.";
}
