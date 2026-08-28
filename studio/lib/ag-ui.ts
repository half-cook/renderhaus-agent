/**
 * Agent-User Interaction (AG-UI) Protocol client and event definitions for Renderhaus Studio.
 * Spec: https://docs.ag-ui.com/concepts/events
 */

export type AGUIEventType =
  | "RUN_STARTED"
  | "RUN_FINISHED"
  | "RUN_ERROR"
  | "STEP_STARTED"
  | "STEP_FINISHED"
  | "TEXT_MESSAGE_START"
  | "TEXT_MESSAGE_CONTENT"
  | "TEXT_MESSAGE_CHUNK"
  | "TEXT_MESSAGE_END"
  | "TOOL_CALL_START"
  | "TOOL_CALL_ARGS"
  | "TOOL_CALL_CHUNK"
  | "TOOL_CALL_END"
  | "TOOL_CALL_RESULT"
  | "STATE_SNAPSHOT"
  | "STATE_DELTA"
  | "MESSAGES_SNAPSHOT"
  | "CUSTOM"
  | "RAW";

export type BaseAGUIEvent = {
  type: AGUIEventType;
  timestamp?: number;
  rawEvent?: unknown;
  metadata?: Record<string, unknown>;
};

export type RunStartedEvent = BaseAGUIEvent & {
  type: "RUN_STARTED";
  threadId: string;
  runId: string;
  parentRunId?: string;
  input?: unknown;
};

export type StepStartedEvent = BaseAGUIEvent & {
  type: "STEP_STARTED";
  stepName: string;
};

export type StepFinishedEvent = BaseAGUIEvent & {
  type: "STEP_FINISHED";
  stepName: string;
};

export type TextMessageStartEvent = BaseAGUIEvent & {
  type: "TEXT_MESSAGE_START";
  messageId: string;
  role?: string;
};

export type TextMessageContentEvent = BaseAGUIEvent & {
  type: "TEXT_MESSAGE_CONTENT";
  messageId: string;
  delta: string;
};

export type TextMessageEndEvent = BaseAGUIEvent & {
  type: "TEXT_MESSAGE_END";
  messageId: string;
};

export type ToolCallStartEvent = BaseAGUIEvent & {
  type: "TOOL_CALL_START";
  toolCallId: string;
  toolCallName: string;
  parentMessageId?: string;
};

export type ToolCallArgsEvent = BaseAGUIEvent & {
  type: "TOOL_CALL_ARGS";
  toolCallId: string;
  delta: string;
};

export type ToolCallEndEvent = BaseAGUIEvent & {
  type: "TOOL_CALL_END";
  toolCallId: string;
};

export type ToolCallResultEvent = BaseAGUIEvent & {
  type: "TOOL_CALL_RESULT";
  messageId: string;
  toolCallId: string;
  content: string;
  role?: string;
};

export type StateSnapshotEvent = BaseAGUIEvent & {
  type: "STATE_SNAPSHOT";
  snapshot: Record<string, unknown>;
};

export type StateDeltaOp = {
  op: "add" | "remove" | "replace" | "move" | "copy" | "test";
  path: string;
  value?: unknown;
  from?: string;
};

export type StateDeltaEvent = BaseAGUIEvent & {
  type: "STATE_DELTA";
  delta: StateDeltaOp[];
};

export type CustomEvent = BaseAGUIEvent & {
  type: "CUSTOM";
  name: string;
  value: unknown;
};

export type RunFinishedEvent = BaseAGUIEvent & {
  type: "RUN_FINISHED";
  threadId: string;
  runId: string;
  outcome?: {
    type: "success" | "interrupt";
    result?: unknown;
    interrupts?: unknown[];
  };
};

export type RunErrorEvent = BaseAGUIEvent & {
  type: "RUN_ERROR";
  message: string;
  code?: string;
};

export type AGUIEvent =
  | RunStartedEvent
  | StepStartedEvent
  | StepFinishedEvent
  | TextMessageStartEvent
  | TextMessageContentEvent
  | TextMessageEndEvent
  | ToolCallStartEvent
  | ToolCallArgsEvent
  | ToolCallEndEvent
  | ToolCallResultEvent
  | StateSnapshotEvent
  | StateDeltaEvent
  | CustomEvent
  | RunFinishedEvent
  | RunErrorEvent;

/**
 * Parses an SSE stream of AG-UI protocol events.
 */
export async function parseAGUIEventStream(
  response: Response,
  onEvent: (event: AGUIEvent) => void,
): Promise<void> {
  if (!response.body) {
    throw new Error("Response body is empty.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() ?? "";

      let currentData = "";
      for (const line of lines) {
        if (line.startsWith("data:")) {
          const content = line.slice(5).trim();
          if (content) {
            currentData = currentData ? `${currentData}\n${content}` : content;
          }
        } else if (line.trim() === "" && currentData) {
          try {
            const parsed = JSON.parse(currentData) as AGUIEvent;
            if (parsed && typeof parsed === "object" && typeof parsed.type === "string") {
              onEvent(parsed);
            }
          } catch {
            // Ignore malformed chunks
          }
          currentData = "";
        }
      }
      if (currentData) {
        try {
          const parsed = JSON.parse(currentData) as AGUIEvent;
          if (parsed && typeof parsed === "object" && typeof parsed.type === "string") {
            onEvent(parsed);
          }
        } catch {
          // Incomplete chunk; keep in currentData
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
