import type { AgentResultData } from "./types";

export function agentResultDownloadUrl(result: AgentResultData): string {
  return `data:${result.mimeType},${encodeURIComponent(result.markdown)}`;
}
