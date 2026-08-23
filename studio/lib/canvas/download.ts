import type { AgentResultData } from "./types";

export function agentResultDownloadUrl(result: AgentResultData): string {
  return `data:${result.mimeType},${encodeURIComponent(result.markdown)}`;
}

export function agentResultDownloadFilename(result: AgentResultData): string {
  return result.primaryAsset?.filename || result.filename;
}
